"""M8 tenant-isolation executor over the real local product composition.

The fixed cases remain immutable inputs.  Each supported case is selected by
its complete canonical digest, then observed through the API -> Worker ->
LangGraph product root with the production runtime identity validator.  The
external Provider and Gateway transports stay deterministic and offline.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .canonical import (
    canonical_digest,
    load_json_strict,
    sha256_file,
    stable_json_bytes,
)
from .execution import CaseExecutionResult, ExecutionState
from .m7_product import M7EnterpriseKnowledgeExecutor

M8_IDENTITY_EXECUTOR_ID = "flowpilot.m8.identity-tenancy"
M8_IDENTITY_EXECUTOR_VERSION = "1.0.0"
M8_SUPPORTED_CASE_COUNT = 6

_SUPPORTED_ASSERTIONS = frozenset(
    {
        "assert.task.terminal_status.v1",
        "assert.tenant.cross_access_zero.v1",
        "assert.audit.complete.v1",
        "assert.tool.write_count.v1",
    }
)
_PRODUCT_SCENARIO_BY_CASE_SCENARIO = {
    "cross_tenant_read": "cross_tenant_knowledge_denied",
    "cross_tenant_write": "cross_tenant_knowledge_denied",
    "cross_tenant_knowledge": "cross_tenant_knowledge_denied",
    "retrieval_scope_leak": "cross_tenant_knowledge_denied",
    "foreign_ref_ignored": "password_reset_policy",
    "cross_tenant_impersonation": "cross_tenant_knowledge_denied",
}


class M8IdentityTenancyExecutor:
    """Execute the six immutable tenant-isolation cases fail closed."""

    executor_id = M8_IDENTITY_EXECUTOR_ID
    executor_version = M8_IDENTITY_EXECUTOR_VERSION

    def __init__(self, repository_root: Path) -> None:
        self._root = repository_root.resolve()
        self._case_pins = self._load_case_pins()
        self._product = M7EnterpriseKnowledgeExecutor(self._root)

    @property
    def supported_case_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._case_pins))

    def registration(self) -> dict[str, Any]:
        return {
            "schema": "flowpilot.m8-executor-registration.v1",
            "executor_id": self.executor_id,
            "executor_version": self.executor_version,
            "match_policy": "exact_case_digest",
            "product_boundary": "API->Worker->LangGraph->GatewayClientPort",
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
            return canonical_digest(dict(case)) == self._case_pins[case_id]
        except (TypeError, ValueError):
            return False

    def execute(
        self,
        case: Mapping[str, Any],
        evidence_root: Path,
    ) -> CaseExecutionResult:
        if not self.supports(case):
            raise ValueError("case does not match an immutable M8 identity pin")
        case_value = dict(case)
        case_scenario = _scenario(case_value)
        product_scenario = _PRODUCT_SCENARIO_BY_CASE_SCENARIO[case_scenario]
        observation = asyncio.run(
            self._product.observe_product_scenario(
                case_value,
                scenario=product_scenario,
            )
        )
        assertions = self._assertions(case_value, observation)
        event_types = tuple(str(item) for item in observation["event_types"])
        event_sequences = tuple(int(item) for item in observation["event_sequences"])
        evidence = {
            "schema": "flowpilot.m8-identity-tenancy-observation.v1",
            "case_id": case_value["case_id"],
            "case_input_digest": canonical_digest(case_value),
            "executor_id": self.executor_id,
            "executor_version": self.executor_version,
            "case_scenario": case_scenario,
            "product_probe_profile": product_scenario,
            "product_boundary": "API->Worker->LangGraph->GatewayClientPort",
            "transport_profile": "offline-synthetic",
            "terminal_status": observation["terminal_status"],
            "failure_code": observation["failure_code"],
            "cross_tenant_read_success_count": observation[
                "cross_tenant_success_count"
            ],
            "cross_tenant_write_success_count": observation["tool_write_count"],
            "tool_write_count": observation["tool_write_count"],
            "logical_tool_calls": observation["logical_tool_calls"],
            "logical_model_calls": observation["logical_model_calls"],
            "event_types": list(event_types),
            "event_sequences": list(event_sequences),
            "security_context_validation_count": observation[
                "security_context_validation_count"
            ],
            "restart_replay_model_delta": observation[
                "restart_replay_model_delta"
            ],
            "restart_replay_tool_delta": observation["restart_replay_tool_delta"],
            "provider_session_exposure_count": observation[
                "provider_session_exposure_count"
            ],
            "request_content_durable_exposure_count": observation[
                "request_content_durable_exposure_count"
            ],
            "live_legs": {
                "keycloak_to_api": "ENV_BLOCKED_NOT_RUN",
                "postgresql_rls_connection_reuse": "ENV_BLOCKED_NOT_RUN",
            },
            "assertion_results": dict(sorted(assertions.items())),
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
        results: dict[str, bool] = {}
        raw_assertions = case.get("deterministic_assertions")
        if not isinstance(raw_assertions, list):
            raise ValueError("M8 case assertions must be a list")
        event_types = tuple(observation["event_types"])
        event_sequences = tuple(observation["event_sequences"])
        audit_complete = (
            len(event_types) == 2
            and event_types[0] == "task.created.v1"
            and event_types[1]
            in {"task.completed.v1", "task.failed.v1"}
            and event_sequences == (1, 2)
        )
        for raw in raw_assertions:
            if not isinstance(raw, dict):
                raise ValueError("M8 assertion must be an object")
            assertion_id = raw.get("assertion_id")
            parameters = raw.get("parameters")
            if not isinstance(assertion_id, str) or not isinstance(parameters, dict):
                raise ValueError("M8 assertion identity and parameters are required")
            if assertion_id == "assert.task.terminal_status.v1":
                results[assertion_id] = (
                    observation["terminal_status"] == parameters.get("expected")
                )
            elif assertion_id == "assert.tenant.cross_access_zero.v1":
                results[assertion_id] = (
                    observation["cross_tenant_success_count"] == 0
                    and observation["tool_write_count"] == 0
                )
            elif assertion_id == "assert.audit.complete.v1":
                results[assertion_id] = audit_complete
            elif assertion_id == "assert.tool.write_count.v1":
                maximum = parameters.get("maximum")
                results[assertion_id] = (
                    isinstance(maximum, int)
                    and not isinstance(maximum, bool)
                    and observation["tool_write_count"] <= maximum
                )
            else:
                results[assertion_id] = False
        return results

    def _load_case_pins(self) -> dict[str, str]:
        pins: dict[str, str] = {}
        scenarios: set[str] = set()
        pattern = "m6-incremental-*/cases/safety_fault/*.json"
        for path in sorted((self._root / "evals" / "datasets").glob(pattern)):
            value = load_json_strict(path)
            if (
                not isinstance(value, dict)
                or value.get("category") != "tenant_isolation"
            ):
                continue
            case_id = value.get("case_id")
            scenario = _scenario(value)
            assertions = {
                item.get("assertion_id")
                for item in value.get("deterministic_assertions", [])
                if isinstance(item, dict)
            }
            if (
                not isinstance(case_id, str)
                or case_id in pins
                or scenario not in _PRODUCT_SCENARIO_BY_CASE_SCENARIO
                or assertions != _SUPPORTED_ASSERTIONS
            ):
                raise ValueError("M8 identity case registry is not uniquely supported")
            pins[case_id] = canonical_digest(value)
            scenarios.add(scenario)
        if (
            len(pins) != M8_SUPPORTED_CASE_COUNT
            or scenarios != set(_PRODUCT_SCENARIO_BY_CASE_SCENARIO)
        ):
            raise ValueError("M8 executor must pin exactly six tenant scenarios")
        return pins


def _scenario(case: Mapping[str, Any]) -> str:
    tags = case.get("tags")
    if not isinstance(tags, list):
        raise ValueError("M8 case tags must be a list")
    scenarios = [
        item.removeprefix("scenario:")
        for item in tags
        if isinstance(item, str) and item.startswith("scenario:")
    ]
    if len(scenarios) != 1:
        raise ValueError("M8 case must declare exactly one scenario tag")
    return scenarios[0]


__all__ = [
    "M8IdentityTenancyExecutor",
    "M8_IDENTITY_EXECUTOR_ID",
    "M8_IDENTITY_EXECUTOR_VERSION",
    "M8_SUPPORTED_CASE_COUNT",
]
