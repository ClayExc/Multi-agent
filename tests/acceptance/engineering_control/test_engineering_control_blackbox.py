"""Independent public-CLI acceptance for WP-093."""

from __future__ import annotations

from pathlib import Path

from tests.acceptance.engineering_control.blackbox import (
    build_proof,
    canonical_json,
    run_cache_cases,
    run_efficiency_and_path_case,
    run_expansion_case,
    run_mutation_matrix,
    run_report_cases,
    sha256_bytes,
)


def _assert_passed(cases: list[dict[str, object]]) -> None:
    assert cases
    assert len({str(case["case_id"]) for case in cases}) == len(cases)
    assert all(case["status"] == "PASSED" for case in cases)


def test_mutation_matrix_has_zero_missed_selection(tmp_path: Path) -> None:
    _assert_passed(run_mutation_matrix(tmp_path))


def test_map_capsule_efficiency_and_path_noise(tmp_path: Path) -> None:
    _assert_passed(run_efficiency_and_path_case(tmp_path))


def test_manual_scope_expansion_is_preserved(tmp_path: Path) -> None:
    _assert_passed(run_expansion_case(tmp_path))


def test_evidence_cache_fails_closed(tmp_path: Path) -> None:
    _assert_passed(run_cache_cases(tmp_path))


def test_attempt_report_separates_actual_and_estimated(tmp_path: Path) -> None:
    _assert_passed(run_report_cases(tmp_path))


def test_proof_is_derived_from_unique_raw_cases(tmp_path: Path) -> None:
    proof = build_proof(tmp_path)
    claimed = proof["proof_sha256"]
    payload = {key: value for key, value in proof.items() if key != "proof_sha256"}
    assert claimed == sha256_bytes(canonical_json(payload))
    assert proof["all_declared_cases"] == proof["passed"]
    assert proof["failed"] == 0
    assert proof["skipped"] == 0
    assert proof["gate"] == "PASS"
