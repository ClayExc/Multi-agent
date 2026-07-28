"""Read-only validation of the rc2 contract and offline evaluation fixtures."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlsplit

from .canonical import (
    canonical_digest,
    load_json_strict,
    portable_bytes_error,
    sha256_file,
)
from .safety import find_unsafe_evidence


CONTRACT_CONTENT_FIELDS = (
    "$schema",
    "contract_set_id",
    "version",
    "digest_profile",
    "owner",
    "published_on",
    "supersedes",
    "required_reviewers",
    "freeze_requirements",
    "schemas",
    "artifacts",
    "release_dependencies",
)
SAFETY_GATE_DOMAINS = {"approval", "observability", "security", "tenant", "tool"}
TERMINAL_STATUSES = {"COMPLETED", "CANCELLED", "ESCALATED", "FAILED"}
FEATURE_ID_PATTERN = re.compile(r"^FP-[A-Z]+-[0-9]{3}$")
CASE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
REQUIRED_REVIEWERS = [
    "S2-RUNTIME",
    "S3-PLATFORM",
    "S4-QUALITY",
    "S5-CORE",
    "S6-DATA",
]
FIXED_SUITE_QUOTAS = {
    "functional": {
        "knowledge_qa_citation": 24,
        "clarification": 16,
        "business_read": 16,
        "ticket_write_verification": 16,
        "approval_recovery": 16,
        "parallel_composite": 16,
        "long_context_handoff": 16,
    },
    "safety_fault": {
        "tenant_isolation": 6,
        "rbac_abac_sod": 6,
        "prompt_injection_malicious_mcp": 6,
        "approval_replay_tamper_duplicate_write": 6,
        "dependency_failure_unknown": 6,
        "secret_dlp_audit": 6,
    },
}
CASE_REQUIRED_FIELDS = {
    "case_id",
    "suite",
    "category",
    "feature_ids",
    "dataset_ref",
    "registry_ref",
    "fixture_bundle_ref",
    "tenant_fixture",
    "input",
    "expected",
    "deterministic_assertions",
    "tags",
}
CASE_ALLOWED_FIELDS = CASE_REQUIRED_FIELDS | {
    "principal_fixture",
    "fault_injection",
    "judge_rubrics",
}


@dataclass(frozen=True, slots=True)
class ValidationFinding:
    code: str
    path: str
    message: str


class OfflineRepositoryValidator:
    """Validate immutable contract inputs without application dependencies."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.contracts = self.root / "contracts"
        self.schema_dir = self.contracts / "jsonschema"
        self.contract_set_path = self.contracts / "contract-set.v1.json"
        self.traceability_path = (
            self.root / "docs" / "acceptance" / "traceability.v1.json"
        )
        self.registry_path = (
            self.contracts / "registries" / "evaluation-registry.v1.json"
        )
        self.dataset_path = (
            self.contracts
            / "registries"
            / "evaluation-dataset-manifest.v1.json"
        )
        self.fixture_path = (
            self.contracts
            / "registries"
            / "evaluation-fixture-manifest.v1.json"
        )

    def validate_repository(self) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []
        required = (
            self.contract_set_path,
            self.traceability_path,
            self.registry_path,
            self.dataset_path,
            self.fixture_path,
        )
        for path in required:
            if not path.is_file():
                findings.append(self._finding("REFERENCE_MISSING", path, "file missing"))
        if findings:
            return findings

        try:
            manifest = load_json_strict(self.contract_set_path)
            traceability = load_json_strict(self.traceability_path)
            registry = load_json_strict(self.registry_path)
            dataset = load_json_strict(self.dataset_path)
            fixtures = load_json_strict(self.fixture_path)
        except (OSError, UnicodeError, ValueError) as exc:
            return [
                ValidationFinding(
                    "JSON_INVALID",
                    ".",
                    str(exc),
                )
            ]

        findings.extend(self._validate_contract_set(manifest))
        findings.extend(self._validate_schema_catalog(manifest))
        findings.extend(self._validate_traceability(traceability))
        findings.extend(
            self._validate_evaluation_manifests(
                manifest,
                registry,
                dataset,
                fixtures,
            )
        )
        return sorted(findings, key=lambda item: (item.path, item.code, item.message))

    def validate_evaluation_cases(
        self,
        cases: Iterable[dict[str, Any]],
    ) -> list[ValidationFinding]:
        traceability = load_json_strict(self.traceability_path)
        registry = load_json_strict(self.registry_path)
        dataset = load_json_strict(self.dataset_path)
        fixtures = load_json_strict(self.fixture_path)
        feature_ids = {item["feature_id"] for item in traceability["features"]}
        assertion_by_id = {
            item["assertion_id"]: item for item in registry["deterministic_assertions"]
        }
        rubric_by_id = {
            item["rubric_id"]: item for item in registry["judge_rubrics"]
        }
        suite_policies = registry["suite_policies"]
        tenant_ids = {
            item["tenant_fixture_id"] for item in fixtures["tenant_fixtures"]
        }
        principal_ids = {
            item["principal_fixture_id"] for item in fixtures["principal_fixtures"]
        }
        expected_refs = {
            "dataset_ref": (
                dataset["dataset_id"],
                dataset["version"],
                sha256_file(self.dataset_path),
            ),
            "registry_ref": (
                registry["registry_id"],
                registry["version"],
                sha256_file(self.registry_path),
            ),
            "fixture_bundle_ref": (
                fixtures["fixture_id"],
                fixtures["version"],
                sha256_file(self.fixture_path),
            ),
        }
        findings: list[ValidationFinding] = []
        seen: set[str] = set()
        for index, case in enumerate(cases):
            case_path = f"cases[{index}]"
            case_id = case.get("case_id")
            if not isinstance(case_id, str) or not case_id:
                findings.append(
                    ValidationFinding("CASE_ID_INVALID", case_path, "case_id missing")
                )
                continue
            if case_id in seen:
                findings.append(
                    ValidationFinding(
                        "CASE_ID_DUPLICATE",
                        case_path,
                        f"duplicate case_id: {case_id}",
                    )
                )
            seen.add(case_id)
            findings.extend(
                self._validate_evaluation_case(
                    case,
                    case_path,
                    feature_ids,
                    assertion_by_id,
                    rubric_by_id,
                    suite_policies,
                    tenant_ids,
                    principal_ids,
                    expected_refs,
                    registry["status"],
                )
            )
        return sorted(findings, key=lambda item: (item.path, item.code, item.message))

    def _validate_contract_set(self, manifest: dict[str, Any]) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []
        source_paths: list[Path] = [self.contract_set_path]
        projection = {field: manifest.get(field) for field in CONTRACT_CONTENT_FIELDS}
        try:
            actual_digest = canonical_digest(projection)
        except ValueError as exc:
            findings.append(
                self._finding("CONTENT_DIGEST_INVALID", self.contract_set_path, str(exc))
            )
        else:
            if manifest.get("content_digest") != actual_digest:
                findings.append(
                    self._finding(
                        "CONTENT_DIGEST_MISMATCH",
                        self.contract_set_path,
                        f"expected {actual_digest}",
                    )
                )

        seen_names: set[str] = set()
        seen_ids: set[str] = set()
        seen_paths: set[str] = set()
        for entry in manifest.get("schemas", []):
            source_paths.append(self.contracts / entry["path"])
            for value, seen, label in (
                (entry["name"], seen_names, "schema name"),
                (entry["id"], seen_ids, "schema id"),
                (entry["path"], seen_paths, "schema path"),
            ):
                if value in seen:
                    findings.append(
                        self._finding(
                            "CONTRACT_ENTRY_DUPLICATE",
                            self.contract_set_path,
                            f"duplicate {label}: {value}",
                        )
                    )
                seen.add(value)
            findings.extend(self._validate_hash_entry(entry, self.contracts))

        artifact_names: set[str] = set()
        for entry in manifest.get("artifacts", []):
            if entry["name"] in artifact_names:
                findings.append(
                    self._finding(
                        "CONTRACT_ENTRY_DUPLICATE",
                        self.contract_set_path,
                        f"duplicate artifact name: {entry['name']}",
                    )
                )
            artifact_names.add(entry["name"])
            path = (self.contracts / entry["path"]).resolve()
            source_paths.append(path)
            findings.extend(self._validate_hash_entry(entry, self.contracts))

        for path in source_paths:
            if not path.is_file():
                continue
            portable_error = portable_bytes_error(path)
            if portable_error:
                findings.append(self._finding("BYTES_NOT_PORTABLE", path, portable_error))

        required_reviewers = manifest.get("required_reviewers", [])
        review_roles = [item.get("role") for item in manifest.get("reviews", [])]
        if required_reviewers != REQUIRED_REVIEWERS:
            findings.append(
                self._finding(
                    "REQUIRED_REVIEWERS_INVALID",
                    self.contract_set_path,
                    "required_reviewers must be S2 through S6",
                )
            )
        if review_roles != required_reviewers:
            findings.append(
                self._finding(
                    "REVIEWER_SET_MISMATCH",
                    self.contract_set_path,
                    "review slots must exactly match required_reviewers",
                )
            )
        for review in manifest.get("reviews", []):
            if review.get("decision") == "PENDING":
                continue
            if review.get("reviewed_content_digest") != manifest.get("content_digest"):
                findings.append(
                    self._finding(
                        "REVIEW_DIGEST_MISMATCH",
                        self.contract_set_path,
                        f"review digest mismatch: {review.get('role')}",
                    )
                )
            evidence_ref = review.get("evidence_ref")
            if not isinstance(evidence_ref, str):
                findings.append(
                    self._finding(
                        "REVIEW_EVIDENCE_MISSING",
                        self.contract_set_path,
                        f"review evidence missing: {review.get('role')}",
                    )
                )
                continue
            evidence_path = (self.root / evidence_ref).resolve()
            if not self._inside_root(evidence_path) or not evidence_path.is_file():
                findings.append(
                    self._finding(
                        "REVIEW_EVIDENCE_MISSING",
                        evidence_path,
                        f"review evidence missing: {review.get('role')}",
                    )
                )
            elif sha256_file(evidence_path) != review.get("evidence_sha256"):
                findings.append(
                    self._finding(
                        "REVIEW_EVIDENCE_HASH_MISMATCH",
                        evidence_path,
                        f"review evidence hash mismatch: {review.get('role')}",
                    )
                )
        if manifest.get("status") == "frozen":
            if any(
                review.get("decision") != "ACCEPT"
                for review in manifest.get("reviews", [])
            ):
                findings.append(
                    self._finding(
                        "FROZEN_REVIEW_GATE_INVALID",
                        self.contract_set_path,
                        "frozen contract-set requires five ACCEPT reviews",
                    )
                )
            if any(
                dependency.get("status") != "frozen"
                for dependency in manifest.get("release_dependencies", {}).values()
            ):
                findings.append(
                    self._finding(
                        "FROZEN_DEPENDENCY_GATE_INVALID",
                        self.contract_set_path,
                        "frozen contract-set requires frozen release dependencies",
                    )
                )
        return findings

    def _validate_hash_entry(
        self,
        entry: dict[str, Any],
        base: Path,
    ) -> list[ValidationFinding]:
        path = (base / entry["path"]).resolve()
        if not self._inside_root(path) or not path.is_file():
            return [self._finding("REFERENCE_MISSING", path, "manifest target missing")]
        actual = sha256_file(path)
        if actual != entry.get("sha256"):
            return [
                self._finding(
                    "HASH_MISMATCH",
                    path,
                    f"expected {entry.get('sha256')}, got {actual}",
                )
            ]
        return []

    def _validate_schema_catalog(
        self,
        manifest: dict[str, Any],
    ) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []
        schema_files = sorted(self.schema_dir.glob("*.json"))
        listed = {
            (self.contracts / entry["path"]).resolve()
            for entry in manifest.get("schemas", [])
        }
        if set(schema_files) != listed:
            findings.append(
                self._finding(
                    "SCHEMA_CATALOG_MISMATCH",
                    self.schema_dir,
                    "contract-set schemas differ from contracts/jsonschema",
                )
            )
        documents: dict[Path, dict[str, Any]] = {}
        ids: dict[str, Path] = {}
        for path in schema_files:
            try:
                document = load_json_strict(path)
            except (OSError, UnicodeError, ValueError) as exc:
                findings.append(self._finding("SCHEMA_JSON_INVALID", path, str(exc)))
                continue
            documents[path.resolve()] = document
            if document.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
                findings.append(
                    self._finding(
                        "SCHEMA_DIALECT_INVALID",
                        path,
                        "schema must declare Draft 2020-12",
                    )
                )
            schema_id = document.get("$id")
            if not isinstance(schema_id, str):
                findings.append(
                    self._finding("SCHEMA_ID_MISSING", path, "$id must be a string")
                )
            elif schema_id in ids:
                findings.append(
                    self._finding(
                        "SCHEMA_ID_DUPLICATE",
                        path,
                        f"duplicate $id: {schema_id}",
                    )
                )
            else:
                ids[schema_id] = path.resolve()

        for path, document in documents.items():
            for pointer, reference in self._walk_refs(document):
                target_path, fragment = self._resolve_schema_ref(path, reference, ids)
                if target_path is None or target_path not in documents:
                    findings.append(
                        self._finding(
                            "SCHEMA_REF_UNRESOLVED",
                            path,
                            f"{pointer}: {reference}",
                        )
                    )
                    continue
                if fragment and not self._json_pointer_exists(
                    documents[target_path],
                    fragment,
                ):
                    findings.append(
                        self._finding(
                            "SCHEMA_REF_FRAGMENT_UNRESOLVED",
                            path,
                            f"{pointer}: {reference}",
                        )
                    )
        return findings

    def _validate_traceability(
        self,
        traceability: dict[str, Any],
    ) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []
        feature_ids: set[str] = set()
        test_ids: set[str] = set()
        evidence_ids: set[str] = set()
        for index, feature in enumerate(traceability.get("features", [])):
            path = f"traceability.features[{index}]"
            feature_id = feature.get("feature_id", "")
            if not FEATURE_ID_PATTERN.fullmatch(feature_id):
                findings.append(
                    ValidationFinding(
                        "FEATURE_ID_INVALID",
                        path,
                        f"invalid feature_id: {feature_id}",
                    )
                )
            elif feature_id in feature_ids:
                findings.append(
                    ValidationFinding(
                        "FEATURE_ID_DUPLICATE",
                        path,
                        f"duplicate feature_id: {feature_id}",
                    )
                )
            feature_ids.add(feature_id)
            if feature.get("implementation_owner") == feature.get("verification_owner"):
                findings.append(
                    ValidationFinding(
                        "VERIFICATION_NOT_INDEPENDENT",
                        path,
                        "implementation_owner and verification_owner must differ",
                    )
                )
            parent_segment = feature_id.lower()
            declared_tests: set[str] = set()
            declared_evidence: set[str] = set()
            for test in feature.get("tests", []):
                test_id = test.get("test_id", "")
                declared_tests.add(test_id)
                if parent_segment not in test_id:
                    findings.append(
                        ValidationFinding(
                            "TEST_PARENT_MISMATCH",
                            path,
                            f"test_id does not contain {parent_segment}: {test_id}",
                        )
                    )
                if test_id in test_ids:
                    findings.append(
                        ValidationFinding(
                            "TEST_ID_DUPLICATE",
                            path,
                            f"duplicate test_id: {test_id}",
                        )
                    )
                test_ids.add(test_id)
            for evidence in feature.get("evidence", []):
                evidence_id = evidence.get("evidence_id", "")
                declared_evidence.add(evidence_id)
                if parent_segment not in evidence_id:
                    findings.append(
                        ValidationFinding(
                            "EVIDENCE_PARENT_MISMATCH",
                            path,
                            f"evidence_id does not contain {parent_segment}: {evidence_id}",
                        )
                    )
                if evidence_id in evidence_ids:
                    findings.append(
                        ValidationFinding(
                            "EVIDENCE_ID_DUPLICATE",
                            path,
                            f"duplicate evidence_id: {evidence_id}",
                        )
                    )
                evidence_ids.add(evidence_id)

            refs = feature.get("valid_evidence_refs", [])
            if feature.get("status") in {"VERIFIED", "RELEASED"} and not refs:
                findings.append(
                    ValidationFinding(
                        "VERIFIED_EVIDENCE_MISSING",
                        path,
                        "VERIFIED/RELEASED feature requires evidence",
                    )
                )
            for evidence_ref in refs:
                findings.extend(
                    self._validate_evidence_ref(
                        evidence_ref,
                        feature,
                        path,
                        declared_tests,
                        declared_evidence,
                    )
                )
        return findings

    def _validate_evidence_ref(
        self,
        evidence_ref: dict[str, Any],
        feature: dict[str, Any],
        path: str,
        declared_tests: set[str],
        declared_evidence: set[str],
    ) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []
        if evidence_ref.get("test_id") not in declared_tests:
            findings.append(
                ValidationFinding(
                    "EVIDENCE_TEST_UNDECLARED",
                    path,
                    f"undeclared test_id: {evidence_ref.get('test_id')}",
                )
            )
        if evidence_ref.get("evidence_id") not in declared_evidence:
            findings.append(
                ValidationFinding(
                    "EVIDENCE_ID_UNDECLARED",
                    path,
                    f"undeclared evidence_id: {evidence_ref.get('evidence_id')}",
                )
            )
        if evidence_ref.get("verifier_role") != feature.get("verification_owner"):
            findings.append(
                ValidationFinding(
                    "EVIDENCE_VERIFIER_INVALID",
                    path,
                    "verifier_role must equal verification_owner",
                )
            )
        artifact = (self.root / evidence_ref.get("artifact_path", "")).resolve()
        if not self._inside_root(artifact) or not artifact.is_file():
            findings.append(
                ValidationFinding(
                    "EVIDENCE_ARTIFACT_MISSING",
                    path,
                    f"artifact missing: {evidence_ref.get('artifact_path')}",
                )
            )
        elif sha256_file(artifact) != evidence_ref.get("artifact_hash"):
            findings.append(
                ValidationFinding(
                    "EVIDENCE_ARTIFACT_HASH_MISMATCH",
                    path,
                    f"artifact hash mismatch: {evidence_ref.get('artifact_path')}",
                )
            )
        return findings

    def _validate_evaluation_manifests(
        self,
        contract_set: dict[str, Any],
        registry: dict[str, Any],
        dataset: dict[str, Any],
        fixtures: dict[str, Any],
    ) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []
        dependency_sources = {
            "evaluation_registry": (self.registry_path, registry),
            "evaluation_dataset": (self.dataset_path, dataset),
            "evaluation_fixtures": (self.fixture_path, fixtures),
            "traceability": (
                self.traceability_path,
                load_json_strict(self.traceability_path),
            ),
        }
        for name, (path, instance) in dependency_sources.items():
            dependency = contract_set["release_dependencies"].get(name)
            if dependency is None:
                findings.append(
                    self._finding(
                        "RELEASE_DEPENDENCY_MISSING",
                        self.contract_set_path,
                        name,
                    )
                )
                continue
            if (
                dependency.get("sha256") != sha256_file(path)
                or dependency.get("version") != instance.get("version")
                or dependency.get("status") != instance.get("status")
            ):
                findings.append(
                    self._finding(
                        "RELEASE_DEPENDENCY_MISMATCH",
                        self.contract_set_path,
                        name,
                    )
                )

        findings.extend(self._duplicates(registry, fixtures, dataset))
        for suite_name, policy in registry.get("suite_policies", {}).items():
            if sum(policy["category_counts"].values()) != policy["expected_case_count"]:
                findings.append(
                    self._finding(
                        "SUITE_QUOTA_MISMATCH",
                        self.registry_path,
                        suite_name,
                    )
                )
            fixed_quota = FIXED_SUITE_QUOTAS.get(suite_name)
            if fixed_quota is not None and (
                policy["category_counts"] != fixed_quota
                or policy["expected_case_count"] != sum(fixed_quota.values())
            ):
                findings.append(
                    self._finding(
                        "FIXED_SUITE_QUOTA_INVALID",
                        self.registry_path,
                        f"{suite_name} quota differs from the M0 baseline",
                    )
                )
            denominator = policy["denominator_policy"]
            expected = {
                "denominator": "all_declared_cases",
                "passed": "success",
                "failed": "failure",
                "skipped": "failure",
                "quarantined": "failure",
            }
            if denominator != expected:
                findings.append(
                    self._finding(
                        "DENOMINATOR_POLICY_INVALID",
                        self.registry_path,
                        suite_name,
                    )
                )

        if dataset.get("status") == "frozen" and not dataset.get("cases"):
            findings.append(
                self._finding(
                    "FROZEN_DATASET_EMPTY",
                    self.dataset_path,
                    "frozen dataset cannot be empty",
                )
            )
        dataset_cases: list[dict[str, Any]] = []
        for case_ref in dataset.get("cases", []):
            case_path = (self.root / case_ref["path"]).resolve()
            if not self._inside_root(case_path) or not case_path.is_file():
                findings.append(
                    self._finding(
                        "DATASET_CASE_MISSING",
                        case_path,
                        case_ref["case_id"],
                    )
                )
                continue
            if sha256_file(case_path) != case_ref["sha256"]:
                findings.append(
                    self._finding(
                        "DATASET_CASE_HASH_MISMATCH",
                        case_path,
                        case_ref["case_id"],
                    )
                )
                continue
            try:
                case_instance = load_json_strict(case_path)
            except (OSError, UnicodeError, ValueError) as exc:
                findings.append(
                    self._finding("DATASET_CASE_JSON_INVALID", case_path, str(exc))
                )
                continue
            if (
                case_instance.get("case_id") != case_ref["case_id"]
                or case_instance.get("suite") != case_ref["suite"]
                or case_instance.get("category") != case_ref["category"]
            ):
                findings.append(
                    self._finding(
                        "DATASET_CASE_BINDING_MISMATCH",
                        case_path,
                        case_ref["case_id"],
                    )
                )
            dataset_cases.append(case_instance)
        if dataset_cases:
            findings.extend(self.validate_evaluation_cases(dataset_cases))
        if dataset.get("status") == "frozen":
            observed: dict[str, dict[str, int]] = {}
            for case in dataset_cases:
                suite_counts = observed.setdefault(case["suite"], {})
                suite_counts[case["category"]] = (
                    suite_counts.get(case["category"], 0) + 1
                )
            for suite_name, quota in FIXED_SUITE_QUOTAS.items():
                if observed.get(suite_name, {}) != quota:
                    findings.append(
                        self._finding(
                            "FROZEN_DATASET_QUOTA_MISMATCH",
                            self.dataset_path,
                            suite_name,
                        )
                    )
        if registry.get("status") == "frozen":
            for rubric in registry.get("judge_rubrics", []):
                if rubric.get("gate_domain") != "semantic_only":
                    findings.append(
                        self._finding(
                            "JUDGE_DOMAIN_INVALID",
                            self.registry_path,
                            rubric.get("rubric_id", ""),
                        )
                    )
                prompt_ref = rubric.get("prompt_ref")
                prompt_hash = rubric.get("prompt_hash")
                if not prompt_ref or not prompt_hash:
                    findings.append(
                        self._finding(
                            "FROZEN_JUDGE_PROMPT_MISSING",
                            self.registry_path,
                            rubric.get("rubric_id", ""),
                        )
                    )
                else:
                    prompt_path = (self.root / prompt_ref).resolve()
                    if (
                        not self._inside_root(prompt_path)
                        or not prompt_path.is_file()
                        or sha256_file(prompt_path) != prompt_hash
                    ):
                        findings.append(
                            self._finding(
                                "FROZEN_JUDGE_PROMPT_INVALID",
                                prompt_path,
                                rubric.get("rubric_id", ""),
                            )
                        )
        return findings

    def _duplicates(
        self,
        registry: dict[str, Any],
        fixtures: dict[str, Any],
        dataset: dict[str, Any],
    ) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []
        groups = (
            (
                self.registry_path,
                "assertion_id",
                [item["assertion_id"] for item in registry["deterministic_assertions"]],
            ),
            (
                self.registry_path,
                "implementation_key",
                [
                    item["implementation_key"]
                    for item in registry["deterministic_assertions"]
                ],
            ),
            (
                self.registry_path,
                "rubric_id",
                [item["rubric_id"] for item in registry["judge_rubrics"]],
            ),
            (
                self.fixture_path,
                "tenant_fixture_id",
                [
                    item["tenant_fixture_id"]
                    for item in fixtures["tenant_fixtures"]
                ],
            ),
            (
                self.fixture_path,
                "principal_fixture_id",
                [
                    item["principal_fixture_id"]
                    for item in fixtures["principal_fixtures"]
                ],
            ),
            (
                self.dataset_path,
                "case_id",
                [item["case_id"] for item in dataset["cases"]],
            ),
        )
        for path, label, values in groups:
            if len(values) != len(set(values)):
                findings.append(
                    self._finding(
                        "IDENTIFIER_DUPLICATE",
                        path,
                        f"duplicate {label}",
                    )
                )
        all_categories = [
            category
            for categories in registry["categories"].values()
            for category in categories
        ]
        if len(all_categories) != len(set(all_categories)):
            findings.append(
                self._finding(
                    "CATEGORY_DUPLICATE",
                    self.registry_path,
                    "category appears in more than one suite",
                )
            )
        return findings

    def _validate_evaluation_case(
        self,
        case: dict[str, Any],
        path: str,
        feature_ids: set[str],
        assertion_by_id: dict[str, dict[str, Any]],
        rubric_by_id: dict[str, dict[str, Any]],
        suite_policies: dict[str, dict[str, Any]],
        tenant_ids: set[str],
        principal_ids: set[str],
        expected_refs: dict[str, tuple[str, str, str]],
        registry_status: str,
    ) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []
        missing_fields = CASE_REQUIRED_FIELDS - set(case)
        extra_fields = set(case) - CASE_ALLOWED_FIELDS
        if missing_fields:
            findings.append(
                ValidationFinding(
                    "CASE_FIELDS_MISSING",
                    path,
                    f"missing fields: {sorted(missing_fields)}",
                )
            )
        if extra_fields:
            findings.append(
                ValidationFinding(
                    "CASE_FIELDS_UNKNOWN",
                    path,
                    f"unknown fields: {sorted(extra_fields)}",
                )
            )
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not CASE_ID_PATTERN.fullmatch(case_id):
            findings.append(
                ValidationFinding(
                    "CASE_ID_INVALID",
                    path,
                    f"invalid case_id: {case_id}",
                )
            )
        suite = case.get("suite")
        category = case.get("category")
        if suite not in suite_policies:
            findings.append(
                ValidationFinding("SUITE_UNKNOWN", path, f"unknown suite: {suite}")
            )
            return findings
        policy = suite_policies[suite]
        if category not in policy["category_counts"]:
            findings.append(
                ValidationFinding(
                    "CATEGORY_UNKNOWN",
                    path,
                    f"category {category!r} is not registered for {suite}",
                )
            )
        case_feature_ids = case.get("feature_ids", [])
        if (
            not isinstance(case_feature_ids, list)
            or not case_feature_ids
            or len(case_feature_ids) != len(set(case_feature_ids))
        ):
            findings.append(
                ValidationFinding(
                    "FEATURE_IDS_INVALID",
                    path,
                    "feature_ids must be a non-empty unique list",
                )
            )
            case_feature_ids = []
        unknown_features = set(case_feature_ids) - feature_ids
        if unknown_features:
            findings.append(
                ValidationFinding(
                    "FEATURE_UNKNOWN",
                    path,
                    f"unknown feature IDs: {sorted(unknown_features)}",
                )
            )
        if case.get("tenant_fixture") not in tenant_ids:
            findings.append(
                ValidationFinding(
                    "TENANT_FIXTURE_UNKNOWN",
                    path,
                    f"unknown tenant fixture: {case.get('tenant_fixture')}",
                )
            )
        principal = case.get("principal_fixture")
        if principal is not None and principal not in principal_ids:
            findings.append(
                ValidationFinding(
                    "PRINCIPAL_FIXTURE_UNKNOWN",
                    path,
                    f"unknown principal fixture: {principal}",
                )
            )
        ref_fields = {
            "dataset_ref": ("dataset_id", "dataset_version", "dataset_hash"),
            "registry_ref": ("registry_id", "registry_version", "registry_hash"),
            "fixture_bundle_ref": ("fixture_id", "fixture_version", "fixture_hash"),
        }
        for key, expected in expected_refs.items():
            ref = case.get(key, {})
            actual = (
                tuple(ref.get(field) for field in ref_fields[key])
                if isinstance(ref, dict)
                else ()
            )
            if actual != expected:
                findings.append(
                    ValidationFinding(
                        "CASE_REFERENCE_MISMATCH",
                        path,
                        f"{key} must bind the current ID, version and hash",
                    )
                )

        assertions = case.get("deterministic_assertions", [])
        if not isinstance(assertions, list) or not assertions:
            findings.append(
                ValidationFinding(
                    "ASSERTIONS_INVALID",
                    path,
                    "deterministic_assertions must be a non-empty list",
                )
            )
            assertions = []
        assertion_ids: list[str] = []
        assertion_domains: set[str] = set()
        for assertion in assertions:
            assertion_id = assertion.get("assertion_id")
            assertion_ids.append(assertion_id)
            registered = assertion_by_id.get(assertion_id)
            if registered is None:
                findings.append(
                    ValidationFinding(
                        "ASSERTION_UNKNOWN",
                        path,
                        f"unknown assertion: {assertion_id}",
                    )
                )
                continue
            assertion_domains.add(registered["gate_domain"])
            if suite not in registered["allowed_suites"]:
                findings.append(
                    ValidationFinding(
                        "ASSERTION_SUITE_INVALID",
                        path,
                        f"{assertion_id} is not allowed for {suite}",
                    )
                )
            parameter_errors = _simple_schema_errors(
                assertion.get("parameters"),
                registered["parameters_schema"],
                f"{path}.{assertion_id}.parameters",
            )
            findings.extend(
                ValidationFinding("ASSERTION_PARAMETERS_INVALID", location, message)
                for location, message in parameter_errors
            )
        if len(assertion_ids) != len(set(assertion_ids)):
            findings.append(
                ValidationFinding(
                    "ASSERTION_DUPLICATE",
                    path,
                    "deterministic assertion IDs must be unique",
                )
            )
        required_assertions = set(
            policy["required_assertions_by_category"].get(category, [])
        )
        missing = required_assertions - set(assertion_ids)
        if missing:
            findings.append(
                ValidationFinding(
                    "ASSERTION_REQUIRED_MISSING",
                    path,
                    f"missing required assertions: {sorted(missing)}",
                )
            )
        if suite == "safety_fault" and not assertion_domains.intersection(
            SAFETY_GATE_DOMAINS
        ):
            findings.append(
                ValidationFinding(
                    "SAFETY_GATE_MISSING",
                    path,
                    "safety case requires a deterministic safety gate domain",
                )
            )

        expected = case.get("expected", {})
        allowed_tools = set(expected.get("allowed_tools", []))
        forbidden_tools = set(expected.get("forbidden_tools", []))
        overlap = allowed_tools.intersection(forbidden_tools)
        if overlap:
            findings.append(
                ValidationFinding(
                    "TOOL_SET_OVERLAP",
                    path,
                    f"tools cannot be both allowed and forbidden: {sorted(overlap)}",
                )
            )
        terminal = expected.get("terminal_status")
        if terminal is not None and terminal not in TERMINAL_STATUSES:
            findings.append(
                ValidationFinding(
                    "TERMINAL_STATUS_INVALID",
                    path,
                    f"invalid terminal status: {terminal}",
                )
            )
        terminal_assertions = [
            item
            for item in assertions
            if item.get("assertion_id") == "assert.task.terminal_status.v1"
        ]
        if terminal_assertions and terminal_assertions[0]["parameters"].get(
            "expected"
        ) != terminal:
            findings.append(
                ValidationFinding(
                    "TERMINAL_ASSERTION_MISMATCH",
                    path,
                    "terminal assertion must match expected.terminal_status",
                )
            )

        rubric_refs = case.get("judge_rubrics", [])
        if not isinstance(rubric_refs, list):
            findings.append(
                ValidationFinding(
                    "RUBRICS_INVALID",
                    path,
                    "judge_rubrics must be a list",
                )
            )
            rubric_refs = []
        rubric_ids: list[str] = []
        for rubric_ref in rubric_refs:
            rubric_id = rubric_ref.get("rubric_id")
            rubric_ids.append(rubric_id)
            rubric = rubric_by_id.get(rubric_id)
            if rubric is None:
                findings.append(
                    ValidationFinding(
                        "RUBRIC_UNKNOWN",
                        path,
                        f"unknown judge rubric: {rubric_id}",
                    )
                )
                continue
            if rubric.get("gate_domain") != "semantic_only":
                findings.append(
                    ValidationFinding(
                        "JUDGE_DOMAIN_INVALID",
                        path,
                        f"{rubric_id} must be semantic_only",
                    )
                )
            if suite not in rubric.get("allowed_suites", []):
                findings.append(
                    ValidationFinding(
                        "RUBRIC_SUITE_INVALID",
                        path,
                        f"{rubric_id} is not allowed for {suite}",
                    )
                )
            if registry_status == "frozen" and (
                not rubric.get("prompt_ref") or not rubric.get("prompt_hash")
            ):
                findings.append(
                    ValidationFinding(
                        "FROZEN_JUDGE_PROMPT_MISSING",
                        path,
                        rubric_id,
                    )
                )
        if len(rubric_ids) != len(set(rubric_ids)):
            findings.append(
                ValidationFinding(
                    "RUBRIC_DUPLICATE",
                    path,
                    "judge rubric IDs must be unique",
                )
            )
        tags = case.get("tags", [])
        if not isinstance(tags, list) or len(tags) != len(set(tags)):
            findings.append(
                ValidationFinding(
                    "TAGS_INVALID",
                    path,
                    "tags must be a unique list",
                )
            )
        findings.extend(
            ValidationFinding("EVIDENCE_UNSAFE", location, message)
            for location, message in (
                (path, finding) for finding in find_unsafe_evidence(case)
            )
        )
        return findings

    def _walk_refs(
        self,
        value: Any,
        pointer: str = "#",
    ) -> Iterable[tuple[str, str]]:
        if isinstance(value, dict):
            for key, child in value.items():
                child_pointer = f"{pointer}/{key}"
                if key == "$ref" and isinstance(child, str):
                    yield child_pointer, child
                else:
                    yield from self._walk_refs(child, child_pointer)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from self._walk_refs(child, f"{pointer}/{index}")

    def _resolve_schema_ref(
        self,
        source_path: Path,
        reference: str,
        ids: dict[str, Path],
    ) -> tuple[Path | None, str]:
        if reference.startswith("#"):
            return source_path, reference[1:]
        parsed = urlsplit(reference)
        fragment = parsed.fragment
        if parsed.scheme in {"http", "https"}:
            base = reference.split("#", 1)[0]
            return ids.get(base), fragment
        target_text = unquote(reference.split("#", 1)[0])
        return (source_path.parent / target_text).resolve(), fragment

    def _json_pointer_exists(self, document: Any, fragment: str) -> bool:
        if fragment == "":
            return True
        if not fragment.startswith("/"):
            return False
        target = document
        try:
            for token in fragment[1:].split("/"):
                token = unquote(token).replace("~1", "/").replace("~0", "~")
                target = target[int(token)] if isinstance(target, list) else target[token]
        except (IndexError, KeyError, TypeError, ValueError):
            return False
        return True

    def _inside_root(self, path: Path) -> bool:
        return path == self.root or self.root in path.parents

    def _finding(self, code: str, path: Path, message: str) -> ValidationFinding:
        try:
            display = path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            display = str(path)
        return ValidationFinding(code, display, message)


def _simple_schema_errors(
    value: Any,
    schema: dict[str, Any],
    path: str,
) -> list[tuple[str, str]]:
    """Validate the small assertion-parameter schema vocabulary used by rc2."""

    errors: list[tuple[str, str]] = []
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(value, dict):
            return [(path, "expected object")]
        required = set(schema.get("required", []))
        missing = required - set(value)
        if missing:
            errors.append((path, f"missing required fields: {sorted(missing)}"))
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extras = set(value) - set(properties)
            if extras:
                errors.append((path, f"unexpected fields: {sorted(extras)}"))
        for key, child in value.items():
            if key in properties:
                errors.extend(
                    _simple_schema_errors(child, properties[key], f"{path}.{key}")
                )
    elif expected_type == "array":
        if not isinstance(value, list):
            return [(path, "expected array")]
        if schema.get("uniqueItems") and len({repr(item) for item in value}) != len(
            value
        ):
            errors.append((path, "array items must be unique"))
        minimum = schema.get("minItems")
        if minimum is not None and len(value) < minimum:
            errors.append((path, f"requires at least {minimum} items"))
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                errors.extend(
                    _simple_schema_errors(item, item_schema, f"{path}[{index}]")
                )
    elif expected_type == "string" and not isinstance(value, str):
        errors.append((path, "expected string"))
    elif expected_type == "integer" and (
        not isinstance(value, int) or isinstance(value, bool)
    ):
        errors.append((path, "expected integer"))
    if "enum" in schema and value not in schema["enum"]:
        errors.append((path, f"value must be one of {schema['enum']}"))
    if isinstance(value, int) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        if minimum is not None and value < minimum:
            errors.append((path, f"value must be at least {minimum}"))
    return errors
