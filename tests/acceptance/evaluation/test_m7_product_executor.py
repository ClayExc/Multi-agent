from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from packages.evaluation.canonical import load_json_strict
from packages.evaluation.execution import (
    CaseExecutionResult,
    CaseExecutorRegistry,
    ExecutionState,
    validate_completed_execution,
)
from packages.evaluation.m7_product import (
    M7_PRODUCT_EXECUTOR_ID,
    M7_PRODUCT_EXECUTOR_VERSION,
    M7_SUPPORTED_CASE_COUNT,
    M7EnterpriseKnowledgeExecutor,
    build_m7_executor_registry,
)
from scripts.acceptance.run_acceptance import collect_cases, verify_collection

ROOT = Path(__file__).resolve().parents[3]


def _cases() -> dict[str, dict[str, object]]:
    return {case["case_id"]: case for case in collect_cases()}


def test_fixed_denominator_has_one_executor_for_exactly_24_product_cases() -> None:
    cases = collect_cases()
    executor = M7EnterpriseKnowledgeExecutor(ROOT)

    assert len(cases) == 156
    assert verify_collection(cases) == []
    assert len(executor.supported_case_ids) == M7_SUPPORTED_CASE_COUNT == 24
    assert sum(executor.supports(case) for case in cases) == 24
    assert sum(case["suite"] == "functional" for case in cases) == 120
    assert sum(case["suite"] == "safety_fault" for case in cases) == 36
    registration = executor.registration()
    assert registration["supported_case_count"] == 24
    assert registration["match_policy"] == "exact_case_digest"
    assert len(registration["supported_cases"]) == 24


def test_supported_case_runs_real_product_and_binds_evidence(tmp_path: Path) -> None:
    case = _cases()["m6a.func.kq.001"]
    registry = build_m7_executor_registry(ROOT)

    result = registry.dispatch(case, tmp_path)
    evidence = load_json_strict(tmp_path / result.evidence_refs[0])

    assert result.state is ExecutionState.COMPLETED
    assert result.executor_id == M7_PRODUCT_EXECUTOR_ID
    assert result.executor_version == M7_PRODUCT_EXECUTOR_VERSION
    assert all(result.assertion_results.values())
    assert evidence["product_boundary"] == "API->Worker->LangGraph"
    assert evidence["logical_tool_calls"] == 1
    assert evidence["logical_model_calls"] == 1
    assert evidence["restart_replay_tool_delta"] == 0
    assert evidence["restart_replay_model_delta"] == 0
    assert evidence["cross_tenant_success_count"] == 0
    assert evidence["provider_session_exposure_count"] == 0
    assert evidence["request_content_durable_exposure_count"] == 0


@pytest.mark.parametrize(
    "case_id,expected_model_calls",
    [
        ("m6a.func.kq.013", 0),
        ("m6a.func.kq.014", 0),
        ("m6a.func.kq.015", 0),
        ("m6a.func.kq.024", 0),
    ],
)
def test_expected_product_failures_are_observed_not_skipped(
    tmp_path: Path,
    case_id: str,
    expected_model_calls: int,
) -> None:
    case = _cases()[case_id]

    result = build_m7_executor_registry(ROOT).dispatch(case, tmp_path)
    evidence = load_json_strict(tmp_path / result.evidence_refs[0])

    assert result.state is ExecutionState.COMPLETED
    assert all(result.assertion_results.values())
    assert evidence["terminal_status"] == "FAILED"
    assert evidence["result_ref_present"] is False
    assert evidence["citation_count"] == 0
    assert evidence["logical_model_calls"] == expected_model_calls
    assert evidence["restart_replay_tool_delta"] == 0
    assert evidence["restart_replay_model_delta"] == 0
    assert evidence["cross_tenant_success_count"] == 0


def test_unimplemented_category_is_explicit_failure_not_skip(tmp_path: Path) -> None:
    case = _cases()["m6b.func.br.001"]

    result = build_m7_executor_registry(ROOT).dispatch(case, tmp_path)

    assert result.state is ExecutionState.NOT_EXECUTED
    assert result.failure_code == "EXECUTOR_NOT_REGISTERED"
    assert result.evidence_refs == ()
    assert result.judge_scores == {}
    assert not any(result.assertion_results.values())


def test_case_identity_or_version_change_cannot_select_executor(
    tmp_path: Path,
) -> None:
    case = copy.deepcopy(_cases()["m6a.func.kq.001"])
    dataset_ref = case["dataset_ref"]
    assert isinstance(dataset_ref, dict)
    dataset_ref["dataset_version"] = "forged-version"

    result = build_m7_executor_registry(ROOT).dispatch(case, tmp_path)

    assert result.state is ExecutionState.NOT_EXECUTED
    assert result.failure_code == "EXECUTOR_NOT_REGISTERED"
    assert result.evidence_refs == ()


def test_missing_or_forged_product_evidence_fails_validation(
    tmp_path: Path,
) -> None:
    case = _cases()["m6a.func.kq.001"]
    evidence_root = tmp_path / "execution"
    executor = M7EnterpriseKnowledgeExecutor(ROOT)
    result = executor.execute(case, evidence_root)
    evidence = evidence_root / result.evidence_refs[0]

    evidence.write_text("{}\n", encoding="utf-8", newline="\n")
    forged = validate_completed_execution(case, result, evidence_root)
    evidence.unlink()
    missing = validate_completed_execution(case, result, evidence_root)

    assert "output digest does not bind the primary evidence artifact" in forged
    assert any("missing or empty" in finding for finding in missing)


def test_registry_executor_identity_must_be_unique() -> None:
    executor = M7EnterpriseKnowledgeExecutor(ROOT)

    class WrongVersionExecutor(M7EnterpriseKnowledgeExecutor):
        executor_version = "forged-version"

    with pytest.raises(ValueError, match="executor IDs must be unique"):
        CaseExecutorRegistry([executor, WrongVersionExecutor(ROOT)])


def test_selected_executor_wrong_result_version_fails_closed(tmp_path: Path) -> None:
    case = _cases()["m6a.func.kq.001"]

    class WrongResultVersionExecutor(M7EnterpriseKnowledgeExecutor):
        def execute(
            self,
            case: Mapping[str, Any],
            evidence_root: Path,
        ) -> CaseExecutionResult:
            valid = super().execute(case, evidence_root)
            return replace(valid, executor_version="forged-version")

    result = CaseExecutorRegistry([WrongResultVersionExecutor(ROOT)]).dispatch(
        case,
        tmp_path,
    )

    assert result.state is ExecutionState.FAILED
    assert result.failure_code == "EXECUTOR_IDENTITY_MISMATCH"
    assert result.evidence_refs == ()
