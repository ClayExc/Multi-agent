from __future__ import annotations

import copy
from pathlib import Path

from packages.evaluation.canonical import load_json_strict
from packages.evaluation.execution import CaseExecutorRegistry, ExecutionState
from packages.evaluation.m7_product import M7EnterpriseKnowledgeExecutor
from packages.evaluation.m8_identity import M8IdentityTenancyExecutor
from packages.evaluation.m9_governance import (
    M9_GOVERNANCE_EXECUTOR_ID,
    M9_GOVERNANCE_EXECUTOR_VERSION,
    M9_SUPPORTED_CASE_COUNT,
    M9GovernanceSecurityExecutor,
)
from scripts.acceptance.run_acceptance import collect_cases

ROOT = Path(__file__).resolve().parents[3]


def _cases() -> dict[str, dict[str, object]]:
    return {case["case_id"]: case for case in collect_cases()}


def test_m9_executor_has_unique_identity_and_exact_case_digests() -> None:
    cases = collect_cases()
    m7 = M7EnterpriseKnowledgeExecutor(ROOT)
    m8 = M8IdentityTenancyExecutor(ROOT)
    m9 = M9GovernanceSecurityExecutor(ROOT)

    assert len(m9.supported_case_ids) == M9_SUPPORTED_CASE_COUNT == 9
    assert sum(m9.supports(case) for case in cases) == M9_SUPPORTED_CASE_COUNT
    assert not set(m7.supported_case_ids) & set(m9.supported_case_ids)
    assert not set(m8.supported_case_ids) & set(m9.supported_case_ids)
    registration = m9.registration()
    assert registration["executor_id"] == M9_GOVERNANCE_EXECUTOR_ID
    assert registration["executor_version"] == M9_GOVERNANCE_EXECUTOR_VERSION
    assert registration["match_policy"] == "exact_case_digest"
    assert registration["supported_case_count"] == M9_SUPPORTED_CASE_COUNT
    assert len(registration["supported_cases"]) == M9_SUPPORTED_CASE_COUNT


def test_m9_connected_cases_use_deterministic_product_observations(
    tmp_path: Path,
) -> None:
    executor = M9GovernanceSecurityExecutor(ROOT)
    registry = CaseExecutorRegistry([executor])
    cases = _cases()

    for case_id in executor.supported_case_ids:
        result = registry.dispatch(cases[case_id], tmp_path)
        evidence = load_json_strict(tmp_path / result.evidence_refs[0])

        assert result.state is ExecutionState.COMPLETED, case_id
        assert result.failure_code is None, case_id
        assert result.judge_scores == {}, case_id
        assert all(result.assertion_results.values()), case_id
        assert evidence["dangerous_output_count"] == 0, case_id
        assert evidence["cross_tenant_success_count"] == 0, case_id
        assert evidence["audit_complete"] is True, case_id
        assert evidence["audit_event_count"] >= 1, case_id
        assert evidence["product_boundary"].startswith("McpGateway->"), case_id


def test_m9_pre_upstream_rejections_have_no_capability_ledger_or_write(
    tmp_path: Path,
) -> None:
    executor = M9GovernanceSecurityExecutor(ROOT)
    cases = _cases()
    case_ids = {
        "m6a.safe.art.001",
        "m6a.safe.art.002",
        "m6b.safe.art.004",
        "m6b.safe.art.005",
        "m6b.safe.dlp.002",
        "m6b.safe.dlp.003",
    }

    for case_id in sorted(case_ids):
        result = executor.execute(cases[case_id], tmp_path)
        evidence = load_json_strict(tmp_path / result.evidence_refs[0])
        assert evidence["upstream_invocation_count"] == 0, case_id
        assert evidence["tool_write_count"] == 0, case_id
        assert evidence["capability_issue_count"] == 0, case_id
        assert evidence["valid_ledger_record_count"] == 0, case_id


def test_m9_unconnected_cases_remain_explicit_failures(tmp_path: Path) -> None:
    cases = _cases()
    registry = CaseExecutorRegistry([M9GovernanceSecurityExecutor(ROOT)])

    for case_id in (
        "m6a.safe.pi.001",
        "m6b.safe.dlp.001",
        "m6c.safe.dlp.004",
        "m6a.safe.rbac.001",
    ):
        result = registry.dispatch(cases[case_id], tmp_path)
        assert result.state is ExecutionState.NOT_EXECUTED
        assert result.failure_code == "EXECUTOR_NOT_REGISTERED"
        assert not any(result.assertion_results.values())


def test_m9_digest_tamper_cannot_select_executor(tmp_path: Path) -> None:
    case = copy.deepcopy(_cases()["m6a.safe.art.001"])
    tags = case["tags"]
    assert isinstance(tags, list)
    tags.append("forged:executor-selection")

    result = CaseExecutorRegistry([M9GovernanceSecurityExecutor(ROOT)]).dispatch(
        case,
        tmp_path,
    )

    assert result.state is ExecutionState.NOT_EXECUTED
    assert result.failure_code == "EXECUTOR_NOT_REGISTERED"
    assert result.evidence_refs == ()


def test_wp108_proof_binds_registry_and_fixed_denominator() -> None:
    proof = load_json_strict(
        ROOT / "tests" / "acceptance" / "m9" / "evidence" / "WP-108-a1-PROOF.json"
    )
    registration = M9GovernanceSecurityExecutor(ROOT).registration()
    registered = proof["executor_registry"]["executors"]
    counts = proof["fixed_denominator"]

    assert registered[-1]["executor_id"] == registration["executor_id"]
    assert registered[-1]["executor_version"] == registration["executor_version"]
    assert registered[-1]["supported_cases"] == registration["supported_cases"]
    assert sum(item["supported_case_count"] for item in registered) == counts[
        "completed"
    ]
    assert counts["completed"] + counts["explicit_failed"] == 156
    assert counts["skipped"] == counts["quarantined"] == 0
    assert counts["gate"] == "fail"
    assert proof["release_claimed"] is False
