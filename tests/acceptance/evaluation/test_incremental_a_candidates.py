"""Acceptance tests for the M6 incremental-A candidate corpus (goal e1).

The corpus is a candidate-only local dataset (48 functional + 21 safety/fault)
validated against the released evaluation-registry without touching the frozen
contracts. Tests cover:

- registry validation of every candidate, both independently and collectively;
- binding completeness (Feature, Fixture, rule assertion, data source, safety
  classification) for every candidate;
- zero real credentials across cases and offline fixtures (FP-SEC-006);
- deterministic offline rebuild from in-repo sources only;
- local manifest hash integrity;
- contract schema conformance (evaluation-case.v1.schema.json);
- rejection of invalid references (failure path);
- TRACEABILITY.md candidate registration rows staying in sync with the corpus.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from packages.evaluation.canonical import load_json_strict, sha256_file
from packages.evaluation.incremental_a import (
    CASE_SPECS,
    DATA_SOURCE_BY_CATEGORY,
    EXPECTED_CATEGORY_COUNTS,
    FEATURE_BY_SUITE,
    GATE_DOMAIN_BY_CATEGORY,
    SECURITY_CLASS_BY_CATEGORY,
    dataset_dir,
    generate_cases,
    generated_matches_committed,
    load_cases,
)
from packages.evaluation.safety import find_unsafe_evidence
from packages.evaluation.validation import (
    SAFETY_GATE_DOMAINS,
    OfflineRepositoryValidator,
)

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def validator() -> OfflineRepositoryValidator:
    return OfflineRepositoryValidator(ROOT)


@pytest.fixture(scope="module")
def cases() -> list[dict]:
    return load_cases(ROOT)


# ---------------------------------------------------------------------------
# Normal path: counts, registry validation, independent runnability
# ---------------------------------------------------------------------------


def test_candidate_counts_match_incremental_a_quota(cases: list[dict]) -> None:
    counts: dict[str, dict[str, int]] = {}
    for case in cases:
        suite_counts = counts.setdefault(case["suite"], {})
        suite_counts[case["category"]] = suite_counts.get(case["category"], 0) + 1
    assert counts == EXPECTED_CATEGORY_COUNTS
    assert sum(sum(values.values()) for values in counts.values()) == 69
    assert len({case["case_id"] for case in cases}) == 69


def test_every_candidate_is_registry_valid(
    validator: OfflineRepositoryValidator, cases: list[dict]
) -> None:
    findings = validator.validate_evaluation_cases(cases)
    assert findings == []


def test_every_candidate_runs_independently(
    validator: OfflineRepositoryValidator, cases: list[dict]
) -> None:
    for case in cases:
        findings = validator.validate_evaluation_cases([case])
        assert findings == [], f"{case['case_id']} failed: {findings}"


def test_manifest_hashes_match_committed_files() -> None:
    manifest = load_json_strict(dataset_dir(ROOT) / "manifest.json")
    assert manifest["dataset_id"] == "flowpilot-m6-incremental-a-local"
    assert manifest["candidate_only"] is True
    assert manifest["case_count"] == 69
    for rel, expected_hash in manifest["files"].items():
        path = dataset_dir(ROOT) / rel
        assert path.is_file(), f"manifest entry missing: {rel}"
        assert sha256_file(path) == expected_hash, f"hash drift: {rel}"


def test_every_case_conforms_to_contract_schema(cases: list[dict]) -> None:
    schema_dir = ROOT / "contracts" / "jsonschema"
    case_schema = load_json_strict(schema_dir / "evaluation-case.v1.schema.json")
    task_schema = load_json_strict(schema_dir / "task.v1.schema.json")
    registry = Registry().with_resource(
        "https://flowpilot.local/schemas/task.v1.schema.json",
        Resource.from_contents(task_schema),
    )
    check = Draft202012Validator(case_schema, registry=registry)
    for case in cases:
        errors = sorted(check.iter_errors(case), key=lambda item: list(item.path))
        assert errors == [], f"{case['case_id']} schema errors: {errors}"


# ---------------------------------------------------------------------------
# Binding completeness: Feature / Fixture / rule assertion / data source /
# safety classification
# ---------------------------------------------------------------------------


def test_every_candidate_binds_feature_and_fixture(cases: list[dict]) -> None:
    traceability = load_json_strict(
        ROOT / "docs" / "acceptance" / "traceability.v1.json"
    )
    known_features = {item["feature_id"] for item in traceability["features"]}
    for case in cases:
        assert case["feature_ids"] == [FEATURE_BY_SUITE[case["suite"]]], case["case_id"]
        assert case["feature_ids"][0] in known_features, case["case_id"]
        assert case["tenant_fixture"] == "tenant-a", case["case_id"]
        assert case["principal_fixture"] == "principal-basic-user", case["case_id"]


def test_every_candidate_binds_data_source_tag(cases: list[dict]) -> None:
    card = (dataset_dir(ROOT) / "dataset-card.yaml").read_text(encoding="utf-8")
    for case in cases:
        expected = DATA_SOURCE_BY_CATEGORY[case["category"]]
        assert f"source:{expected}" in case["tags"], case["case_id"]
        assert expected in card, case["case_id"]


def test_safety_candidates_carry_safety_classification(cases: list[dict]) -> None:
    for case in cases:
        if case["suite"] != "safety_fault":
            continue
        security_class = SECURITY_CLASS_BY_CATEGORY[case["category"]]
        gate = GATE_DOMAIN_BY_CATEGORY[case["category"]]
        assert f"security-class:{security_class}" in case["tags"], case["case_id"]
        assert f"gate:{gate}" in case["tags"], case["case_id"]
        assert gate in SAFETY_GATE_DOMAINS, case["case_id"]


def test_functional_candidates_do_not_claim_safety_class(cases: list[dict]) -> None:
    for case in cases:
        if case["suite"] != "functional":
            continue
        assert not any(
            tag.startswith("security-class:") or tag.startswith("gate:")
            for tag in case["tags"]
        ), case["case_id"]


def test_safety_candidates_have_deterministic_safety_gate(
    cases: list[dict],
) -> None:
    registry = load_json_strict(
        ROOT / "contracts" / "registries" / "evaluation-registry.v1.json"
    )
    gate_by_assertion = {
        item["assertion_id"]: item["gate_domain"]
        for item in registry["deterministic_assertions"]
    }
    for case in cases:
        if case["suite"] != "safety_fault":
            continue
        domains = {
            gate_by_assertion[item["assertion_id"]]
            for item in case["deterministic_assertions"]
        }
        assert domains & SAFETY_GATE_DOMAINS, case["case_id"]
        assert GATE_DOMAIN_BY_CATEGORY[case["category"]] in domains, case["case_id"]


def test_every_candidate_binds_required_rule_assertions(
    validator: OfflineRepositoryValidator, cases: list[dict]
) -> None:
    registry = load_json_strict(
        ROOT / "contracts" / "registries" / "evaluation-registry.v1.json"
    )
    policy = registry["suite_policies"]
    for case in cases:
        required = set(
            policy[case["suite"]]["required_assertions_by_category"][case["category"]]
        )
        declared = {
            item["assertion_id"] for item in case["deterministic_assertions"]
        }
        assert required <= declared, case["case_id"]


def test_fault_profiles_are_resolvable_and_bound(cases: list[dict]) -> None:
    for case in cases:
        injection = case.get("fault_injection")
        if injection is None:
            continue
        profile_path = (
            ROOT / "evals" / "fixtures" / "fault-profiles"
            / f"{injection['profile_id']}.json"
        )
        assert profile_path.is_file(), case["case_id"]
        profile = load_json_strict(profile_path)
        assert profile["profile_id"] == injection["profile_id"], case["case_id"]
        assert profile["profile_version"] == injection["profile_version"], case[
            "case_id"
        ]
        assert sha256_file(profile_path) == injection["profile_hash"], case["case_id"]


# ---------------------------------------------------------------------------
# Security: zero real credentials (FP-SEC-006)
# ---------------------------------------------------------------------------


def _offline_fixture_paths() -> list[Path]:
    paths = [
        ROOT / "evals" / "fixtures" / "synthetic-knowledge-corpus.v1.json",
        ROOT / "evals" / "fixtures" / "synthetic-tenant-directory.v1.json",
        ROOT / "evals" / "fixtures" / "synthetic-ticket-store.v1.json",
        ROOT / "evals" / "fixtures" / "synthetic-approval-ledger.v1.json",
    ]
    paths.extend(
        path
        for path in (ROOT / "evals" / "fixtures" / "fault-profiles").glob("*.json")
    )
    return paths


def test_no_real_credentials_in_cases_or_fixtures(cases: list[dict]) -> None:
    for case in cases:
        findings = find_unsafe_evidence(case)
        assert findings == [], f"{case['case_id']}: {findings}"
    for path in _offline_fixture_paths():
        findings = find_unsafe_evidence(load_json_strict(path))
        assert findings == [], f"{path.name}: {findings}"


# ---------------------------------------------------------------------------
# Recovery: deterministic offline rebuild, no external service
# ---------------------------------------------------------------------------


def test_offline_rebuild_is_deterministic() -> None:
    ok, mismatches = generated_matches_committed(ROOT)
    assert ok, f"regenerated bytes differ: {mismatches}"
    regenerated = {case["case_id"] for case in generate_cases(ROOT)}
    assert regenerated == {spec.case_id for spec in CASE_SPECS}


# ---------------------------------------------------------------------------
# Failure path: invalid references are rejected by the registry validator
# ---------------------------------------------------------------------------


def test_invalid_feature_reference_is_rejected(
    validator: OfflineRepositoryValidator, cases: list[dict]
) -> None:
    broken = copy.deepcopy(cases[0])
    broken["feature_ids"] = ["FP-UNKNOWN-999"]
    findings = validator.validate_evaluation_cases([broken])
    assert "FEATURE_UNKNOWN" in {finding.code for finding in findings}


def test_invalid_fixture_reference_is_rejected(
    validator: OfflineRepositoryValidator, cases: list[dict]
) -> None:
    broken = copy.deepcopy(cases[0])
    broken["tenant_fixture"] = "tenant-does-not-exist"
    broken["principal_fixture"] = "principal-does-not-exist"
    findings = validator.validate_evaluation_cases([broken])
    codes = {finding.code for finding in findings}
    assert "TENANT_FIXTURE_UNKNOWN" in codes
    assert "PRINCIPAL_FIXTURE_UNKNOWN" in codes


def test_invalid_assertion_reference_is_rejected(
    validator: OfflineRepositoryValidator, cases: list[dict]
) -> None:
    broken = copy.deepcopy(cases[0])
    broken["deterministic_assertions"][0]["assertion_id"] = "assert.nonexistent.v1"
    findings = validator.validate_evaluation_cases([broken])
    assert "ASSERTION_UNKNOWN" in {finding.code for finding in findings}


def test_undecidable_assertion_parameters_are_rejected(
    validator: OfflineRepositoryValidator, cases: list[dict]
) -> None:
    broken = copy.deepcopy(
        next(case for case in cases if case["suite"] == "safety_fault")
    )
    broken["deterministic_assertions"] = [
        {"assertion_id": "assert.tool.write_count.v1", "parameters": {}}
    ]
    findings = validator.validate_evaluation_cases([broken])
    assert "ASSERTION_PARAMETERS_INVALID" in {
        finding.code for finding in findings
    }


def test_safety_case_without_safety_gate_is_rejected(
    validator: OfflineRepositoryValidator, cases: list[dict]
) -> None:
    broken = copy.deepcopy(
        next(case for case in cases if case["suite"] == "safety_fault")
    )
    broken["deterministic_assertions"] = [
        {
            "assertion_id": "assert.task.terminal_status.v1",
            "parameters": {"expected": "FAILED"},
        }
    ]
    findings = validator.validate_evaluation_cases([broken])
    assert "SAFETY_GATE_MISSING" in {finding.code for finding in findings}


def test_duplicate_case_id_is_rejected(
    validator: OfflineRepositoryValidator, cases: list[dict]
) -> None:
    findings = validator.validate_evaluation_cases([cases[0], copy.deepcopy(cases[0])])
    assert "CASE_ID_DUPLICATE" in {finding.code for finding in findings}


# ---------------------------------------------------------------------------
# TRACEABILITY candidate registration rows stay in sync
# ---------------------------------------------------------------------------


def test_traceability_registration_rows_cover_every_candidate(
    cases: list[dict],
) -> None:
    text = (ROOT / "docs" / "acceptance" / "TRACEABILITY.md").read_text(
        encoding="utf-8"
    )
    assert "M6 评测候选登记" in text
    for case in cases:
        assert case["case_id"] in text, f"{case['case_id']} missing from TRACEABILITY"
