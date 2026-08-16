from __future__ import annotations

import copy
from pathlib import Path

import pytest

from packages.evaluation.canonical import load_json_strict
from packages.evaluation.execution import CaseExecutorRegistry, ExecutionState
from packages.evaluation.m7_product import M7EnterpriseKnowledgeExecutor
from packages.evaluation.m8_identity import M8IdentityTenancyExecutor
from packages.evaluation.m9_governance import M9GovernanceSecurityExecutor
from packages.evaluation.m10_knowledge import (
    M10_KNOWLEDGE_EXECUTOR_ID,
    M10_KNOWLEDGE_EXECUTOR_VERSION,
    M10_SUPPORTED_CASE_COUNT,
    M10KnowledgeSecurityExecutor,
)
from scripts.acceptance.run_acceptance import (
    build_product_executors,
    collect_cases,
    executor_registration,
)
from tests.acceptance.m10.knowledge_acceptance_probe import (
    observe_knowledge_acceptance,
)

ROOT = Path(__file__).resolve().parents[3]


def _cases() -> dict[str, dict[str, object]]:
    return {case["case_id"]: case for case in collect_cases()}


@pytest.mark.asyncio
async def test_m10_product_matrix_fails_closed_and_is_deterministic() -> None:
    observation = await observe_knowledge_acceptance()

    assert observation.scenario == "injection_in_knowledge_doc"
    assert observation.terminal_status == "FAILED"
    assert observation.error_code == "PLATFORM_KNOWLEDGE_CONTENT_REJECTED"
    assert observation.tool_write_count == 0
    assert observation.audit_event_count == 1
    assert observation.security_event_count == 1
    assert observation.dangerous_output_count == 0
    assert observation.cross_tenant_success_count == 0
    assert observation.expired_candidate_read_count == 0
    assert observation.low_relevance_returned_count == 0
    assert observation.malicious_document_rejected is True
    assert observation.citation_drift_rejected is True
    assert observation.delete_returned_count == 0
    assert observation.rebuild_returned_count == 1
    assert observation.deterministic_order == tuple(
        sorted(observation.deterministic_order)
    )
    assert observation.audit_complete is True


def test_m10_executor_has_unique_identity_and_exact_case_digest() -> None:
    cases = collect_cases()
    m7 = M7EnterpriseKnowledgeExecutor(ROOT)
    m8 = M8IdentityTenancyExecutor(ROOT)
    m9 = M9GovernanceSecurityExecutor(ROOT)
    m10 = M10KnowledgeSecurityExecutor(ROOT)

    assert len(m10.supported_case_ids) == M10_SUPPORTED_CASE_COUNT == 1
    assert sum(m10.supports(case) for case in cases) == 1
    assert not set(m7.supported_case_ids) & set(m10.supported_case_ids)
    assert not set(m8.supported_case_ids) & set(m10.supported_case_ids)
    assert not set(m9.supported_case_ids) & set(m10.supported_case_ids)
    registration = m10.registration()
    assert registration["executor_id"] == M10_KNOWLEDGE_EXECUTOR_ID
    assert registration["executor_version"] == M10_KNOWLEDGE_EXECUTOR_VERSION
    assert registration["match_policy"] == "exact_case_digest"
    assert registration["supported_case_count"] == 1


def test_m10_fixed_case_uses_measured_product_evidence(tmp_path: Path) -> None:
    executor = M10KnowledgeSecurityExecutor(ROOT)
    case = _cases()[executor.supported_case_ids[0]]

    result = CaseExecutorRegistry([executor]).dispatch(case, tmp_path)
    evidence = load_json_strict(tmp_path / result.evidence_refs[0])

    assert result.state is ExecutionState.COMPLETED
    assert result.failure_code is None
    assert result.judge_scores == {}
    assert all(result.assertion_results.values())
    assert evidence["cross_tenant_success_count"] == 0
    assert evidence["expired_candidate_read_count"] == 0
    assert evidence["low_relevance_returned_count"] == 0
    assert evidence["malicious_document_rejected"] is True
    assert evidence["citation_drift_rejected"] is True
    assert evidence["delete_returned_count"] == 0
    assert evidence["rebuild_returned_count"] == 1
    assert evidence["audit_complete"] is True
    assert evidence["assertion_results"] == result.assertion_results


def test_m10_digest_tamper_and_unimplemented_cases_fail_explicitly(
    tmp_path: Path,
) -> None:
    executor = M10KnowledgeSecurityExecutor(ROOT)
    case = copy.deepcopy(_cases()[executor.supported_case_ids[0]])
    tags = case["tags"]
    assert isinstance(tags, list)
    tags.append("forged:executor-selection")

    registry = CaseExecutorRegistry([executor])
    tampered = registry.dispatch(case, tmp_path)
    unimplemented = registry.dispatch(_cases()["m6b.safe.dlp.001"], tmp_path)

    assert tampered.state is ExecutionState.NOT_EXECUTED
    assert tampered.failure_code == "EXECUTOR_NOT_REGISTERED"
    assert tampered.evidence_refs == ()
    assert unimplemented.state is ExecutionState.NOT_EXECUTED
    assert unimplemented.failure_code == "EXECUTOR_NOT_REGISTERED"
    assert not any(unimplemented.assertion_results.values())


def test_official_registry_keeps_one_unique_156_case_fact_source() -> None:
    registry, registered = build_product_executors()
    del registry
    serialized = executor_registration(registered)
    cases = collect_cases()
    matches = {
        str(case["case_id"]): sum(item.supports(case) for item in registered)
        for case in cases
    }

    assert len(cases) == 156
    assert serialized["executor_count"] == 4
    assert serialized["supported_case_count"] == 40
    assert serialized["executors"][-1]["executor_id"] == (
        M10_KNOWLEDGE_EXECUTOR_ID
    )
    assert set(matches.values()) <= {0, 1}
    assert sum(matches.values()) == 40
