from __future__ import annotations

import copy
from pathlib import Path

from packages.evaluation.canonical import load_json_strict
from packages.evaluation.execution import CaseExecutorRegistry, ExecutionState
from packages.evaluation.m7_product import M7EnterpriseKnowledgeExecutor
from packages.evaluation.m8_identity import (
    M8_IDENTITY_EXECUTOR_ID,
    M8_IDENTITY_EXECUTOR_VERSION,
    M8_SUPPORTED_CASE_COUNT,
    M8IdentityTenancyExecutor,
)
from packages.evaluation.reporting import CaseStatus
from packages.evaluation.validation import OfflineRepositoryValidator
from scripts.acceptance.run_acceptance import (
    build_product_executors,
    collect_cases,
    evaluate_case,
    executor_registration,
    verify_collection,
)

ROOT = Path(__file__).resolve().parents[3]


def _cases() -> dict[str, dict[str, object]]:
    return {case["case_id"]: case for case in collect_cases()}


def test_m8_executor_uniquely_pins_six_tenant_cases() -> None:
    cases = collect_cases()
    m7 = M7EnterpriseKnowledgeExecutor(ROOT)
    m8 = M8IdentityTenancyExecutor(ROOT)

    assert len(cases) == 156
    assert verify_collection(cases) == []
    assert len(m8.supported_case_ids) == M8_SUPPORTED_CASE_COUNT == 6
    assert sum(m8.supports(case) for case in cases) == 6
    assert not set(m7.supported_case_ids) & set(m8.supported_case_ids)
    registration = m8.registration()
    assert registration["executor_id"] == M8_IDENTITY_EXECUTOR_ID
    assert registration["executor_version"] == M8_IDENTITY_EXECUTOR_VERSION
    assert registration["match_policy"] == "exact_case_digest"
    assert registration["supported_case_count"] == 6


def test_all_m8_cases_run_product_with_deterministic_security_gates(
    tmp_path: Path,
) -> None:
    executor = M8IdentityTenancyExecutor(ROOT)
    registry = CaseExecutorRegistry([executor])

    for case_id in executor.supported_case_ids:
        result = registry.dispatch(_cases()[case_id], tmp_path)
        evidence = load_json_strict(tmp_path / result.evidence_refs[0])

        assert result.state is ExecutionState.COMPLETED
        assert result.failure_code is None
        assert result.judge_scores == {}
        assert all(result.assertion_results.values())
        assert evidence["security_context_validation_count"] > 0
        assert evidence["cross_tenant_read_success_count"] == 0
        assert evidence["cross_tenant_write_success_count"] == 0
        assert evidence["tool_write_count"] == 0
        assert evidence["event_sequences"] == [1, 2]
        assert evidence["restart_replay_model_delta"] == 0
        assert evidence["restart_replay_tool_delta"] == 0
        assert evidence["provider_session_exposure_count"] == 0
        assert evidence["request_content_durable_exposure_count"] == 0
        assert evidence["live_legs"] == {
            "keycloak_to_api": "ENV_BLOCKED_NOT_RUN",
            "postgresql_rls_connection_reuse": "ENV_BLOCKED_NOT_RUN",
        }


def test_m8_case_digest_or_version_tamper_cannot_select_executor(
    tmp_path: Path,
) -> None:
    case = copy.deepcopy(_cases()["m6a.safe.ten.001"])
    dataset_ref = case["dataset_ref"]
    assert isinstance(dataset_ref, dict)
    dataset_ref["dataset_version"] = "forged-version"

    result = CaseExecutorRegistry([M8IdentityTenancyExecutor(ROOT)]).dispatch(
        case,
        tmp_path,
    )

    assert result.state is ExecutionState.NOT_EXECUTED
    assert result.failure_code == "EXECUTOR_NOT_REGISTERED"
    assert result.evidence_refs == ()


def test_approval_cases_remain_explicitly_unimplemented(tmp_path: Path) -> None:
    registry = CaseExecutorRegistry(
        [M7EnterpriseKnowledgeExecutor(ROOT), M8IdentityTenancyExecutor(ROOT)]
    )
    case = _cases()["m6a.safe.rbac.001"]

    result = registry.dispatch(case, tmp_path)

    assert result.state is ExecutionState.NOT_EXECUTED
    assert result.failure_code == "EXECUTOR_NOT_REGISTERED"
    assert result.judge_scores == {}
    assert not any(result.assertion_results.values())


def test_official_fixed_denominator_measures_registered_product_cases(
    tmp_path: Path,
) -> None:
    cases = collect_cases()
    registry, executors = build_product_executors()
    validator = OfflineRepositoryValidator(ROOT)
    statuses: list[CaseStatus] = []
    execution_states: list[ExecutionState] = []

    for case in cases:
        result, execution, _findings, skip_reason = evaluate_case(
            validator,
            case,
            executors=registry,
            evidence_root=tmp_path,
            judge_calibrated=False,
        )
        statuses.append(result.status)
        execution_states.append(execution.state)
        assert skip_reason is None

    registration = executor_registration(executors)
    assert len(cases) == len(statuses) == len(execution_states) == 156
    assert statuses.count(CaseStatus.PASSED) == 30
    assert statuses.count(CaseStatus.FAILED) == 126
    assert statuses.count(CaseStatus.SKIPPED) == 0
    assert statuses.count(CaseStatus.QUARANTINED) == 0
    assert execution_states.count(ExecutionState.COMPLETED) == 30
    assert execution_states.count(ExecutionState.NOT_EXECUTED) == 126
    assert registration["supported_case_count"] == 30
    assert [item["executor_id"] for item in registration["executors"]] == [
        "flowpilot.m7.enterprise-knowledge",
        "flowpilot.m8.identity-tenancy",
    ]
