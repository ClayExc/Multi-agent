from __future__ import annotations

from pathlib import Path

import pytest

from packages.evaluation.reporting import (
    AssertionOutcome,
    CaseResult,
    CaseStatus,
    aggregate_results,
    generate_acceptance_bundle,
)


def _result(case_id: str, status: CaseStatus) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        suite="functional",
        category="knowledge_qa_citation",
        status=status,
        assertions=(
            AssertionOutcome(
                assertion_id="assert.citation.valid.v1",
                gate_domain="evaluation",
                passed=status
                in {
                    CaseStatus.PASSED,
                    CaseStatus.SKIPPED,
                    CaseStatus.QUARANTINED,
                },
            ),
        ),
        judge_scores={},
    )


def _metadata() -> dict[str, object]:
    return {
        "run_id": "acc_offline123",
        "started_at": "2026-07-28T12:00:00Z",
        "finished_at": "2026-07-28T12:00:01Z",
        "git_commit": "b5caaf2448c2860cfa67d8c5a39b9cda62eca809",
        "dirty_worktree": False,
        "contract_content_digest": (
            "sha256:0a82e7f58c4223362721c95a50e9a820"
            "d714e550e72eebc7a90ab01e283100fc"
        ),
        "dataset_versions": {},
        "dataset_hashes": {},
        "dataset_manifest_hash": "sha256:" + "a" * 64,
        "fixture_manifest_hash": "sha256:" + "b" * 64,
        "traceability_hash": "sha256:" + "c" * 64,
        "evaluation_registry_hash": "sha256:" + "d" * 64,
        "commands": ["python -m pytest tests/acceptance -q"],
    }


def test_zero_case_report_is_not_a_pass_or_a_success_rate() -> None:
    report = aggregate_results([], [])

    assert report.report_state == "empty"
    assert report.gate_result == "fail"
    assert report.success_rate is None
    assert report.denominator_policy == "all_declared_cases"


def test_failed_skipped_and_quarantined_all_count_as_failures() -> None:
    results = [
        _result("case-passed", CaseStatus.PASSED),
        _result("case-failed", CaseStatus.FAILED),
        _result("case-skipped", CaseStatus.SKIPPED),
        _result("case-quarantined", CaseStatus.QUARANTINED),
    ]

    report = aggregate_results([item.case_id for item in results], results)

    assert report.declared_case_count == 4
    assert report.passed == 1
    assert report.failure_count == 3
    assert report.success_rate == "0.250000"
    assert report.gate_result == "fail"


def test_missing_declared_result_is_rejected() -> None:
    with pytest.raises(ValueError, match="missing results"):
        aggregate_results(["case-one"], [])


def test_duplicate_result_is_rejected() -> None:
    result = _result("case-one", CaseStatus.PASSED)

    with pytest.raises(ValueError, match="result IDs must be unique"):
        aggregate_results(["case-one"], [result, result])


def test_bundle_generation_is_idempotent(tmp_path: Path) -> None:
    result = _result("case-one", CaseStatus.PASSED)
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_manifest = generate_acceptance_bundle(
        output_dir=first,
        metadata=_metadata(),
        declared_case_ids=["case-one"],
        results=[result],
    )
    second_manifest = generate_acceptance_bundle(
        output_dir=second,
        metadata=_metadata(),
        declared_case_ids=["case-one"],
        results=[result],
    )

    assert first_manifest == second_manifest
    for relative in (
        "manifest.json",
        "REPORT.md",
        "eval/aggregate.json",
        "eval/case-results.jsonl",
    ):
        assert (first / relative).read_bytes() == (second / relative).read_bytes()


def test_bundle_rejects_secret_like_evidence(tmp_path: Path) -> None:
    metadata = _metadata()
    metadata["models"] = {"unsafe": "Bearer " + "x" * 24}

    with pytest.raises(ValueError, match="secret-like material"):
        generate_acceptance_bundle(
            output_dir=tmp_path / "unsafe",
            metadata=metadata,
            declared_case_ids=[],
            results=[],
        )
