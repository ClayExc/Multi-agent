from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

from packages.evaluation.canonical import load_json_strict
from packages.evaluation.validation import OfflineRepositoryValidator

ROOT = Path(__file__).resolve().parents[3]
FUNCTIONAL_CASE = (
    ROOT / "evals" / "fixtures" / "minimal-functional-case.v1.json"
)
SAFETY_CASE = (
    ROOT / "evals" / "fixtures" / "minimal-safety-fault-case.v1.json"
)


def _copy_contract_inputs(tmp_path: Path) -> Path:
    target = tmp_path / "repository"
    shutil.copytree(ROOT / "contracts", target / "contracts")
    shutil.copytree(ROOT / "docs", target / "docs")
    return target


def test_current_contract_and_minimal_cases_are_valid() -> None:
    validator = OfflineRepositoryValidator(ROOT)

    repository_findings = validator.validate_repository()
    case_findings = validator.validate_evaluation_cases(
        [load_json_strict(FUNCTIONAL_CASE), load_json_strict(SAFETY_CASE)]
    )

    assert repository_findings == []
    assert case_findings == []


def test_contract_schema_hash_drift_is_detected(tmp_path: Path) -> None:
    repository = _copy_contract_inputs(tmp_path)
    schema = repository / "contracts" / "jsonschema" / "task.v1.schema.json"
    schema.write_text(schema.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    findings = OfflineRepositoryValidator(repository).validate_repository()

    assert "HASH_MISMATCH" in {finding.code for finding in findings}


def test_fixed_120_36_quotas_cannot_be_reduced(tmp_path: Path) -> None:
    repository = _copy_contract_inputs(tmp_path)
    registry_path = (
        repository
        / "contracts"
        / "registries"
        / "evaluation-registry.v1.json"
    )
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    functional = registry["suite_policies"]["functional"]
    functional["category_counts"]["knowledge_qa_citation"] = 23
    functional["expected_case_count"] = 119
    registry_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    findings = OfflineRepositoryValidator(repository).validate_repository()

    assert "FIXED_SUITE_QUOTA_INVALID" in {
        finding.code for finding in findings
    }


def test_five_required_reviewers_cannot_be_reduced(tmp_path: Path) -> None:
    repository = _copy_contract_inputs(tmp_path)
    manifest_path = repository / "contracts" / "contract-set.v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["required_reviewers"] = manifest["required_reviewers"][:-1]
    manifest["reviews"] = manifest["reviews"][:-1]
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    findings = OfflineRepositoryValidator(repository).validate_repository()

    assert "REQUIRED_REVIEWERS_INVALID" in {
        finding.code for finding in findings
    }


def test_unresolved_schema_reference_is_detected(tmp_path: Path) -> None:
    repository = _copy_contract_inputs(tmp_path)
    schema_path = (
        repository
        / "contracts"
        / "jsonschema"
        / "evaluation-case.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["properties"]["expected"]["properties"]["terminal_status"]["oneOf"][1][
        "$ref"
    ] = "./missing-task-schema.json#/$defs/terminalStatus"
    schema_path.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    findings = OfflineRepositoryValidator(repository).validate_repository()

    assert "SCHEMA_REF_UNRESOLVED" in {finding.code for finding in findings}


def test_unknown_feature_and_duplicate_case_are_detected() -> None:
    validator = OfflineRepositoryValidator(ROOT)
    case = load_json_strict(FUNCTIONAL_CASE)
    unknown = copy.deepcopy(case)
    unknown["feature_ids"] = ["FP-UNKNOWN-999"]

    findings = validator.validate_evaluation_cases([unknown, copy.deepcopy(unknown)])
    codes = {finding.code for finding in findings}

    assert "FEATURE_UNKNOWN" in codes
    assert "CASE_ID_DUPLICATE" in codes


def test_case_hash_binding_drift_is_detected() -> None:
    validator = OfflineRepositoryValidator(ROOT)
    case = load_json_strict(FUNCTIONAL_CASE)
    case["dataset_ref"]["dataset_hash"] = "sha256:" + "f" * 64

    findings = validator.validate_evaluation_cases([case])

    assert "CASE_REFERENCE_MISMATCH" in {
        finding.code for finding in findings
    }


def test_safety_case_without_deterministic_safety_gate_is_rejected() -> None:
    validator = OfflineRepositoryValidator(ROOT)
    case = load_json_strict(SAFETY_CASE)
    case["deterministic_assertions"] = [
        {
            "assertion_id": "assert.intent.matches.v1",
            "parameters": {"expected": "blocked"},
        }
    ]

    findings = validator.validate_evaluation_cases([case])
    codes = {finding.code for finding in findings}

    assert "SAFETY_GATE_MISSING" in codes
    assert "ASSERTION_REQUIRED_MISSING" in codes


def test_forged_feature_evidence_is_rejected(tmp_path: Path) -> None:
    repository = _copy_contract_inputs(tmp_path)
    trace_path = repository / "docs" / "acceptance" / "traceability.v1.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    feature = next(
        item for item in trace["features"] if item["feature_id"] == "FP-EVAL-003"
    )
    feature["status"] = "VERIFIED"
    feature["valid_evidence_refs"] = [
        {
            "evidence_id": "evidence.fp-eval-003.primary.v1",
            "test_id": "test.fp-eval-003.primary.v1",
            "artifact_path": "artifacts/acceptance/forged.json",
            "artifact_hash": "sha256:" + "0" * 64,
            "run_id": "acc_offline123",
            "produced_at": "2026-07-28T12:00:00Z",
            "verifier_role": "S4-QUALITY",
        }
    ]
    trace_path.write_text(
        json.dumps(trace, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    findings = OfflineRepositoryValidator(repository).validate_repository()
    codes = {finding.code for finding in findings}

    assert "EVIDENCE_VERIFIER_INVALID" in codes
    assert "EVIDENCE_ARTIFACT_MISSING" in codes
