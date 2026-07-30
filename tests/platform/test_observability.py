from __future__ import annotations

import pytest
from factories import SignalSink, TickingClock, make_fixture
from flowpilot_domain import ToolOperation
from flowpilot_mcp_gateway import (
    DEBUG_PROJECTION_KEYS,
    GatewayReason,
    LifecycleOutcome,
    LifecycleRecorder,
    LifecycleStage,
)
from flowpilot_security import assert_safe_projection


@pytest.mark.asyncio
async def test_unknown_lifecycle_reason_code_is_rejected() -> None:
    fixture = make_fixture()
    recorder = LifecycleRecorder(
        invocation=fixture.invocation,
        sink=SignalSink(),
        clock=TickingClock(),
    )

    with pytest.raises(ValueError, match="reason code"):
        await recorder.record(
            LifecycleStage.INGRESS,
            LifecycleOutcome.PASSED,
            "FREE_FORM_REASON",
        )


@pytest.mark.asyncio
async def test_debug_projection_is_a_closed_safe_whitelist() -> None:
    fixture = make_fixture(operation=ToolOperation.READ)

    execution = await fixture.gateway.execute(fixture.invocation)
    projection = dict(execution.debug_projection)

    assert set(projection) == DEBUG_PROJECTION_KEYS
    assert "security_context" not in projection
    assert "arguments" not in projection
    assert "capability" not in projection
    assert "messages" not in projection
    assert_safe_projection(projection)


@pytest.mark.asyncio
async def test_blocked_audit_and_security_events_are_bidirectionally_linked() -> None:
    fixture = make_fixture()
    fixture.policy_source.available = False

    execution = await fixture.gateway.execute(fixture.invocation)

    assert execution.result.error_code == "PLATFORM_POLICY_UNAVAILABLE"
    assert len(fixture.signals.audits) == 1
    assert len(fixture.signals.security) == 1
    audit = fixture.signals.audits[0]
    security = fixture.signals.security[0]
    assert audit.security_event_id == security.event_id
    assert security.audit_event_id == audit.event_id
    assert audit.trace_id == security.trace_id
    assert audit.correlation_id == security.correlation_id
    assert audit.tenant_id == security.tenant_id
    assert audit.to_mapping()["arguments_redacted"] == {"field_names": []}
    assert "security_context" not in security.to_mapping()


@pytest.mark.asyncio
async def test_unknown_timeline_contains_ledger_upstream_and_result() -> None:
    fixture = make_fixture()
    fixture.adapter.mode = "unknown_executed"

    execution = await fixture.gateway.execute(fixture.invocation)

    stages = [event.stage.value for event in execution.lifecycle]
    assert stages.index("ledger") < stages.index("upstream") < stages.index(
        "result"
    )
    assert execution.debug_projection["reason_code"] in {
        GatewayReason.UPSTREAM_OUTCOME_UNKNOWN.value,
        GatewayReason.RESULT_UNKNOWN.value,
    }
    assert execution.stage_metrics["result.unknown"] == 1
