"""Independent M9 security checks at the Gateway and signal boundaries."""

from __future__ import annotations

import copy
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from flowpilot_domain import ToolOperation
from flowpilot_policy import PolicyDecisionKind
from flowpilot_security import SecurityError, SecurityErrorCode
from flowpilot_tool_contracts import ToolResultStatus

from packages.evaluation.canonical import load_json_strict
from packages.observability.signals import validate_linked_security_pair
from tests.acceptance.m9.governance_security_probe import (
    observe_governance_security,
)
from tests.acceptance.platform_security.blackbox import NOW, make_blackbox

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("decision", "role_granted", "expected_code"),
    [
        (PolicyDecisionKind.DENY, True, "PLATFORM_POLICY_DENIED"),
        (
            PolicyDecisionKind.REQUIRE_APPROVAL,
            False,
            "PLATFORM_SEPARATION_OF_DUTIES",
        ),
    ],
)
async def test_policy_and_sod_reject_before_capability_ledger_and_upstream(
    decision: PolicyDecisionKind,
    role_granted: bool,
    expected_code: str,
) -> None:
    fixture = make_blackbox(decision_kind=decision)
    fixture.approvers.role_granted = role_granted

    execution = await fixture.gateway.execute(fixture.invocation)

    assert execution.result.status is ToolResultStatus.FAILED_FINAL
    assert execution.result.error_code == expected_code
    assert fixture.adapter.invocation_count == 0
    assert fixture.adapter.logical_write_count == 0
    assert fixture.dependencies.credentials.issue_count == 0
    assert await fixture.ledger_record(execution.result.execution_id) is None
    assert len(fixture.signals.audits) == 1
    assert len(fixture.signals.security_events) == 1


@pytest.mark.asyncio
async def test_missing_approval_cannot_be_bypassed() -> None:
    fixture = make_blackbox(
        decision_kind=PolicyDecisionKind.REQUIRE_APPROVAL
    )

    execution = await fixture.gateway.execute(
        fixture.request_for(approval_id=None)
    )

    assert execution.result.status is ToolResultStatus.FAILED_FINAL
    assert execution.result.error_code == "PLATFORM_APPROVAL_REQUIRED"
    assert fixture.adapter.invocation_count == 0
    assert fixture.adapter.logical_write_count == 0
    assert fixture.dependencies.credentials.issue_count == 0


@pytest.mark.asyncio
async def test_issued_capability_is_atomic_and_single_use() -> None:
    fixture = make_blackbox(operation=ToolOperation.READ)

    execution = await fixture.gateway.execute(fixture.invocation)

    assert execution.result.status is ToolResultStatus.VERIFIED
    broker = fixture.dependencies.credentials
    assert broker.issue_count == broker.consume_count == 1
    handles = tuple(broker._issued.values())
    assert len(handles) == 1
    with pytest.raises(SecurityError) as captured:
        await broker.consume(handle=handles[0], now=NOW + timedelta(seconds=1))
    assert captured.value.code is SecurityErrorCode.CAPABILITY_REPLAY
    assert fixture.adapter.invocation_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenario", "expected_code", "maximum_upstream", "maximum_write"),
    [
        ("direct_injection", "PLATFORM_PROMPT_INJECTION_BLOCKED", 0, 0),
        ("injection_in_tool_result", "PLATFORM_PROMPT_INJECTION_BLOCKED", 1, 0),
        ("dlp_pre_write_scan", "PLATFORM_DLP_BLOCKED", 0, 0),
        ("tool_result_secret", "PLATFORM_DLP_BLOCKED", 1, 0),
        ("mcp_forged_write_success", "PLATFORM_READBACK_MISMATCH", 1, 1),
    ],
)
async def test_content_and_malicious_mcp_fail_closed_without_projection(
    scenario: str,
    expected_code: str,
    maximum_upstream: int,
    maximum_write: int,
) -> None:
    observation = await observe_governance_security(scenario)

    assert observation.terminal_status == "FAILED"
    assert observation.error_code == expected_code
    assert observation.upstream_invocation_count <= maximum_upstream
    assert observation.tool_write_count <= maximum_write
    assert observation.dangerous_output_count == 0
    assert observation.cross_tenant_success_count == 0
    assert observation.audit_complete is True


def test_audit_security_cross_link_tamper_is_rejected() -> None:
    routing = load_json_strict(
        ROOT / "evals" / "fixtures" / "observability" / "signal-routing.v1.json"
    )
    cases = load_json_strict(ROOT / "contracts" / "conformance" / "rc2-cases.json")
    by_id = {item["case_id"]: item["instance"] for item in cases["cases"]}
    audit = by_id[routing["audit_case_id"]]
    security = by_id[routing["security_event_case_id"]]
    validate_linked_security_pair(audit, security)

    tampered: dict[str, Any] = copy.deepcopy(security)
    tampered["audit_event_id"] = "evt_wrong123"
    with pytest.raises(ValueError, match="does not match"):
        validate_linked_security_pair(audit, tampered)
