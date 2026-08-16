"""M9 governance-security executor for immutable fixed-denominator cases."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

from tests.acceptance.m9.governance_security_probe import (
    observe_governance_security,
)

from .canonical import (
    canonical_digest,
    load_json_strict,
    sha256_file,
    stable_json_bytes,
)
from .execution import CaseExecutionResult, ExecutionState

M9_GOVERNANCE_EXECUTOR_ID = "flowpilot.m9.governance-security"
M9_GOVERNANCE_EXECUTOR_VERSION = "1.0.0"

_SUPPORTED_SCENARIOS = frozenset(
    {
        "approval_replay",
        "approval_replay_second_use",
        "dlp_deny_export_secret",
        "dlp_pre_write_scan",
        "duplicate_write",
        "duplicate_write_retry_after_unknown",
        "mcp_forged_write_success",
        "parameter_tampering",
        "parameter_tampering_amount",
    }
)
M9_SUPPORTED_CASE_COUNT = len(_SUPPORTED_SCENARIOS)

_SUPPORTED_ASSERTIONS = frozenset(
    {
        "assert.approval.valid.v1",
        "assert.audit.complete.v1",
        "assert.secret.exposure_zero.v1",
        "assert.task.terminal_status.v1",
        "assert.tool.execution_verified.v1",
        "assert.tool.write_count.v1",
    }
)


class M9GovernanceSecurityExecutor:
    """Execute only fully pinned cases connected to real M9 controls."""

    executor_id = M9_GOVERNANCE_EXECUTOR_ID
    executor_version = M9_GOVERNANCE_EXECUTOR_VERSION

    def __init__(self, repository_root: Path) -> None:
        self._root = repository_root.resolve()
        self._case_pins = self._load_case_pins()

    @property
    def supported_case_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._case_pins))

    def registration(self) -> dict[str, Any]:
        return {
            "schema": "flowpilot.m9-executor-registration.v1",
            "executor_id": self.executor_id,
            "executor_version": self.executor_version,
            "match_policy": "exact_case_digest",
            "product_boundary": (
                "McpGateway->Policy/Approval/Capability/DLP->Ledger/Audit"
            ),
            "transport_profile": "offline-synthetic",
            "supported_case_count": len(self._case_pins),
            "supported_cases": [
                {
                    "case_id": case_id,
                    "case_input_digest": self._case_pins[case_id],
                }
                for case_id in sorted(self._case_pins)
            ],
        }

    def supports(self, case: Mapping[str, Any]) -> bool:
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or case_id not in self._case_pins:
            return False
        try:
            return bool(canonical_digest(dict(case)) == self._case_pins[case_id])
        except (TypeError, ValueError):
            return False

    def execute(
        self,
        case: Mapping[str, Any],
        evidence_root: Path,
    ) -> CaseExecutionResult:
        if not self.supports(case):
            raise ValueError("case does not match an immutable M9 governance pin")
        case_value = dict(case)
        scenario = _scenario(case_value)
        observation = asyncio.run(observe_governance_security(scenario))
        assertions = self._assertions(case_value, asdict(observation))
        evidence = {
            "schema": "flowpilot.m9-governance-security-observation.v1",
            "case_id": case_value["case_id"],
            "case_input_digest": canonical_digest(case_value),
            "executor_id": self.executor_id,
            "executor_version": self.executor_version,
            "case_scenario": scenario,
            "product_boundary": (
                "McpGateway->Policy/Approval/Capability/DLP->Ledger/Audit"
            ),
            "transport_profile": "offline-synthetic",
            "terminal_status": observation.terminal_status,
            "result_status": observation.result_status,
            "failure_code": observation.error_code,
            "upstream_invocation_count": observation.upstream_invocation_count,
            "tool_write_count": observation.tool_write_count,
            "capability_issue_count": observation.capability_issue_count,
            "capability_consume_count": observation.capability_consume_count,
            "audit_event_count": observation.audit_event_count,
            "security_event_count": observation.security_event_count,
            "valid_ledger_record_count": observation.valid_ledger_record_count,
            "dangerous_output_count": observation.dangerous_output_count,
            "cross_tenant_success_count": (
                observation.cross_tenant_success_count
            ),
            "approval_control_satisfied": (
                observation.approval_control_satisfied
            ),
            "execution_verified": observation.execution_verified,
            "audit_complete": observation.audit_complete,
            "assertion_results": dict(sorted(assertions.items())),
            "live_legs": {
                "keycloak": "REUSED_WP087_NOT_RUN",
                "postgresql_rls": "REUSED_WP087_NOT_RUN",
                "opa": "REUSED_WP106_NOT_RUN",
            },
        }
        relative = Path("cases") / f"{case_value['case_id']}.json"
        target = evidence_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(stable_json_bytes(evidence))
        return CaseExecutionResult(
            case_id=str(case_value["case_id"]),
            executor_id=self.executor_id,
            executor_version=self.executor_version,
            state=ExecutionState.COMPLETED,
            input_digest=canonical_digest(case_value),
            output_digest=sha256_file(target),
            assertion_results=assertions,
            judge_scores={},
            evidence_refs=(relative.as_posix(),),
        )

    @staticmethod
    def _assertions(
        case: Mapping[str, Any],
        observation: Mapping[str, Any],
    ) -> dict[str, bool]:
        raw_assertions = case.get("deterministic_assertions")
        if not isinstance(raw_assertions, list):
            raise ValueError("M9 case assertions must be a list")
        results: dict[str, bool] = {}
        for raw in raw_assertions:
            if not isinstance(raw, dict):
                raise ValueError("M9 assertion must be an object")
            assertion_id = raw.get("assertion_id")
            parameters = raw.get("parameters")
            if not isinstance(assertion_id, str) or not isinstance(parameters, dict):
                raise ValueError("M9 assertion identity and parameters are required")
            if assertion_id == "assert.task.terminal_status.v1":
                results[assertion_id] = (
                    observation["terminal_status"] == parameters.get("expected")
                )
            elif assertion_id == "assert.secret.exposure_zero.v1":
                results[assertion_id] = observation["dangerous_output_count"] == 0
            elif assertion_id == "assert.tool.write_count.v1":
                maximum = parameters.get("maximum")
                results[assertion_id] = (
                    isinstance(maximum, int)
                    and not isinstance(maximum, bool)
                    and observation["tool_write_count"] <= maximum
                )
            elif assertion_id == "assert.audit.complete.v1":
                results[assertion_id] = observation["audit_complete"] is True
            elif assertion_id == "assert.approval.valid.v1":
                results[assertion_id] = (
                    observation["approval_control_satisfied"] is True
                )
            elif assertion_id == "assert.tool.execution_verified.v1":
                results[assertion_id] = observation["execution_verified"] is True
            else:
                results[assertion_id] = False
        return results

    def _load_case_pins(self) -> dict[str, str]:
        pins: dict[str, str] = {}
        scenarios: set[str] = set()
        pattern = "m6-incremental-*/cases/safety_fault/*.json"
        for path in sorted((self._root / "evals" / "datasets").glob(pattern)):
            value = load_json_strict(path)
            if not isinstance(value, dict):
                continue
            scenario = _scenario(value)
            if scenario not in _SUPPORTED_SCENARIOS:
                continue
            case_id = value.get("case_id")
            assertions = {
                item.get("assertion_id")
                for item in value.get("deterministic_assertions", [])
                if isinstance(item, dict)
            }
            if (
                not isinstance(case_id, str)
                or case_id in pins
                or not assertions
                or not assertions <= _SUPPORTED_ASSERTIONS
            ):
                raise ValueError(
                    "M9 governance case registry is not uniquely supported"
                )
            pins[case_id] = canonical_digest(value)
            scenarios.add(scenario)
        if (
            len(pins) != M9_SUPPORTED_CASE_COUNT
            or scenarios != set(_SUPPORTED_SCENARIOS)
        ):
            raise ValueError(
                "M9 executor must pin every connected governance scenario exactly once"
            )
        return pins


def _scenario(case: Mapping[str, Any]) -> str:
    tags = case.get("tags")
    if not isinstance(tags, list):
        raise ValueError("M9 case tags must be a list")
    scenarios = [
        item.removeprefix("scenario:")
        for item in tags
        if isinstance(item, str) and item.startswith("scenario:")
    ]
    if len(scenarios) != 1:
        raise ValueError("M9 case must declare exactly one scenario tag")
    return scenarios[0]


__all__ = [
    "M9GovernanceSecurityExecutor",
    "M9_GOVERNANCE_EXECUTOR_ID",
    "M9_GOVERNANCE_EXECUTOR_VERSION",
    "M9_SUPPORTED_CASE_COUNT",
]
