"""FlowPilot M0 contract conformance gate.

Requires ``jsonschema>=4.23``. The script is intentionally independent from
application packages so every Codex session can validate the frozen boundary.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator, FormatChecker
    from referencing import Registry, Resource
except ImportError as exc:  # pragma: no cover - dependency bootstrap is external
    raise SystemExit(
        "jsonschema>=4.23 is required; the repository dependency is assigned "
        "to S5-CORE before make test-contract is enabled"
    ) from exc


ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"
SCHEMA_DIR = CONTRACTS / "jsonschema"


def load_json(path: Path) -> Any:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise AssertionError(f"duplicate JSON key in {path}: {key}")
            value[key] = item
        return value

    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_keys,
    )


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def rfc8785_canonical_bytes(value: Any) -> bytes:
    """Canonicalize the integer-only I-JSON profile used by contract fixtures.

    Production code must use a complete RFC 8785 implementation. The M0
    contract/audit profiles reject floats and unsafe integers so this compact
    gate is exact for every accepted conformance value rather than pretending
    Python's generic sort_keys encoding is JCS.
    """

    def encode(item: Any) -> str:
        if item is None:
            return "null"
        if item is True:
            return "true"
        if item is False:
            return "false"
        if isinstance(item, int):
            if not -(2**53 - 1) <= item <= 2**53 - 1:
                raise AssertionError("RFC 8785 fixture integer exceeds I-JSON range")
            return str(item)
        if isinstance(item, float):
            raise AssertionError(
                "FlowPilot digest fixtures reject floats; normalize them before hashing"
            )
        if isinstance(item, str):
            return json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        if isinstance(item, list):
            return "[" + ",".join(encode(child) for child in item) + "]"
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise AssertionError("RFC 8785 object keys must be strings")
            ordered_keys = sorted(
                item,
                key=lambda key: key.encode("utf-16-be", errors="strict"),
            )
            return (
                "{"
                + ",".join(
                    f"{encode(key)}:{encode(item[key])}" for key in ordered_keys
                )
                + "}"
            )
        raise AssertionError(f"unsupported RFC 8785 fixture type: {type(item)!r}")

    return encode(value).encode("utf-8", errors="strict")


def canonical_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(rfc8785_canonical_bytes(value)).hexdigest()


def audit_event_hash(event: dict[str, Any]) -> str:
    canonical_event = copy.deepcopy(event)
    del canonical_event["integrity"]["event_hash"]
    return canonical_digest(
        {
            "profile": "flowpilot.audit-chain.v1",
            "event": canonical_event,
        }
    )


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


def contract_content_digest(manifest: dict[str, Any]) -> str:
    return canonical_digest(
        {field: manifest[field] for field in CONTRACT_CONTENT_FIELDS}
    )


def require_portable_hash_source(path: Path) -> None:
    value = path.read_bytes()
    if value.startswith(b"\xef\xbb\xbf"):
        raise AssertionError(f"UTF-8 BOM is forbidden in hashed source: {path}")
    if b"\r" in value:
        raise AssertionError(f"hashed source must use LF line endings: {path}")


def require_unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise AssertionError(f"duplicate {label}")


def apply_json_pointer(document: Any, mutation: dict[str, Any]) -> None:
    pointer = mutation["json_pointer"]
    operation = mutation.get("operation", "replace")
    if not pointer.startswith("/"):
        raise AssertionError(f"invalid JSON Pointer: {pointer}")
    parts = [
        part.replace("~1", "/").replace("~0", "~")
        for part in pointer.removeprefix("/").split("/")
    ]
    target = document
    for part in parts[:-1]:
        target = target[int(part)] if isinstance(target, list) else target[part]
    last = parts[-1]
    if operation == "remove":
        if isinstance(target, list):
            target.pop(int(last))
        else:
            del target[last]
        return
    value = mutation["value"]
    if isinstance(target, list):
        if operation == "add" and last == "-":
            target.append(value)
        elif operation in {"add", "replace"}:
            target[int(last)] = value
        else:
            raise AssertionError(f"unsupported JSON Pointer operation: {operation}")
    else:
        if operation not in {"add", "replace"}:
            raise AssertionError(f"unsupported JSON Pointer operation: {operation}")
        target[last] = value


def main() -> int:
    manifest = load_json(CONTRACTS / "contract-set.v1.json")
    schema_paths = sorted(SCHEMA_DIR.glob("*.json"))
    schemas = {path.name: load_json(path) for path in schema_paths}

    registry = Registry()
    for path, schema in zip(schema_paths, schemas.values(), strict=True):
        Draft202012Validator.check_schema(schema)
        resource = Resource.from_contents(schema)
        registry = registry.with_resource(schema["$id"], resource)
        registry = registry.with_resource(path.resolve().as_uri(), resource)

    Draft202012Validator(
        schemas["contract-set.v1.schema.json"],
        registry=registry,
        format_checker=FormatChecker(),
    ).validate(manifest)
    expected_content_digest = contract_content_digest(manifest)
    if manifest["content_digest"] != expected_content_digest:
        raise AssertionError(
            f"contract-set content_digest mismatch: expected {expected_content_digest}"
        )
    require_portable_hash_source(CONTRACTS / "contract-set.v1.json")

    manifest_names = [entry["path"].split("/")[-1] for entry in manifest["schemas"]]
    require_unique(manifest_names, "schema manifest path")
    require_unique([entry["name"] for entry in manifest["schemas"]], "schema name")
    require_unique([entry["id"] for entry in manifest["schemas"]], "schema id")
    if set(manifest_names) != set(schemas):
        raise AssertionError("contract-set schemas differ from contracts/jsonschema")
    for entry in manifest["schemas"]:
        path = CONTRACTS / entry["path"]
        require_portable_hash_source(path)
        if entry["sha256"] != sha256(path):
            raise AssertionError(f"hash mismatch: {entry['name']}")
    artifact_names = [entry["name"] for entry in manifest["artifacts"]]
    require_unique(artifact_names, "artifact name")
    for entry in manifest["artifacts"]:
        path = (CONTRACTS / entry["path"]).resolve()
        require_portable_hash_source(path)
        if entry["sha256"] != sha256(path):
            raise AssertionError(f"artifact hash mismatch: {entry['name']}")
    for review in manifest["reviews"]:
        if review["decision"] == "PENDING":
            continue
        if review["reviewed_content_digest"] != manifest["content_digest"]:
            raise AssertionError(f"review digest mismatch: {review['role']}")
        evidence_path = (ROOT / review["evidence_ref"]).resolve()
        if not evidence_path.is_relative_to(ROOT) or not evidence_path.is_file():
            raise AssertionError(f"review evidence missing: {review['role']}")
        if review["evidence_sha256"] != sha256(evidence_path):
            raise AssertionError(f"review evidence hash mismatch: {review['role']}")
    if manifest["status"] == "frozen" and any(
        review["decision"] != "ACCEPT" for review in manifest["reviews"]
    ):
        raise AssertionError(
            "frozen contract-set requires all required reviewers to ACCEPT"
        )

    format_checker = FormatChecker()
    suite = load_json(CONTRACTS / "conformance" / "rc2-cases.json")
    case_ids = [case["case_id"] for case in suite["cases"]]
    require_unique(case_ids, "conformance case_id")
    positive = negative = 0
    for case in suite["cases"]:
        schema = schemas[case["schema"]]
        validator = Draft202012Validator(
            schema,
            registry=registry,
            format_checker=format_checker,
        )
        errors = sorted(validator.iter_errors(case["instance"]), key=str)
        actual_valid = not errors
        if actual_valid != case["expect_valid"]:
            detail = "valid unexpectedly" if actual_valid else errors[0].message
            raise AssertionError(f"{case['case_id']}: {detail}")
        positive += int(actual_valid)
        negative += int(not actual_valid)

    cases_by_id = {case["case_id"]: case for case in suite["cases"]}
    mutation_cases = suite.get("schema_mutation_cases", [])
    mutation_ids = [case["case_id"] for case in mutation_cases]
    mutation_positive = mutation_negative = 0
    for case in mutation_cases:
        base = cases_by_id[case["base_case_id"]]
        if not base["expect_valid"]:
            raise AssertionError(
                f"{case['case_id']}: mutation base must be an expected-valid case"
            )
        instance = copy.deepcopy(base["instance"])
        for mutation in case["mutations"]:
            apply_json_pointer(instance, mutation)
        validator = Draft202012Validator(
            schemas[base["schema"]],
            registry=registry,
            format_checker=format_checker,
        )
        actual_valid = not list(validator.iter_errors(instance))
        if actual_valid != case["expect_valid"]:
            raise AssertionError(f"{case['case_id']}: schema mutation expectation mismatch")
        mutation_positive += int(actual_valid)
        mutation_negative += int(not actual_valid)

    evaluation_registry = load_json(
        CONTRACTS / "registries" / "evaluation-registry.v1.json"
    )
    Draft202012Validator(
        schemas["evaluation-registry.v1.schema.json"],
        registry=registry,
        format_checker=format_checker,
    ).validate(evaluation_registry)
    evaluation_dataset = load_json(
        CONTRACTS / "registries" / "evaluation-dataset-manifest.v1.json"
    )
    Draft202012Validator(
        schemas["evaluation-dataset-manifest.v1.schema.json"],
        registry=registry,
        format_checker=format_checker,
    ).validate(evaluation_dataset)
    evaluation_fixtures = load_json(
        CONTRACTS / "registries" / "evaluation-fixture-manifest.v1.json"
    )
    Draft202012Validator(
        schemas["evaluation-fixture-manifest.v1.schema.json"],
        registry=registry,
        format_checker=format_checker,
    ).validate(evaluation_fixtures)
    assertion_ids = [
        item["assertion_id"] for item in evaluation_registry["deterministic_assertions"]
    ]
    rubric_ids = [item["rubric_id"] for item in evaluation_registry["judge_rubrics"]]
    require_unique(assertion_ids, "assertion_id")
    require_unique(rubric_ids, "rubric_id")
    assertion_registry = {
        item["assertion_id"]: item
        for item in evaluation_registry["deterministic_assertions"]
    }
    rubric_registry = {
        item["rubric_id"]: item for item in evaluation_registry["judge_rubrics"]
    }
    for item in assertion_registry.values():
        Draft202012Validator.check_schema(item["parameters_schema"])
    if any(item["gate_domain"] != "semantic_only" for item in evaluation_registry["judge_rubrics"]):
        raise AssertionError("Judge rubric escaped semantic_only boundary")
    all_categories = [
        category
        for categories in evaluation_registry["categories"].values()
        for category in categories
    ]
    require_unique(all_categories, "evaluation category")

    traceability = load_json(ROOT / "docs" / "acceptance" / "traceability.v1.json")
    Draft202012Validator(
        schemas["feature-traceability.v1.schema.json"],
        registry=registry,
        format_checker=format_checker,
    ).validate(traceability)
    dependency_sources = {
        "evaluation_registry": (
            CONTRACTS / "registries" / "evaluation-registry.v1.json",
            evaluation_registry,
        ),
        "evaluation_dataset": (
            CONTRACTS / "registries" / "evaluation-dataset-manifest.v1.json",
            evaluation_dataset,
        ),
        "evaluation_fixtures": (
            CONTRACTS / "registries" / "evaluation-fixture-manifest.v1.json",
            evaluation_fixtures,
        ),
        "traceability": (
            ROOT / "docs" / "acceptance" / "traceability.v1.json",
            traceability,
        ),
    }
    artifact_by_path = {
        (CONTRACTS / item["path"]).resolve(): item for item in manifest["artifacts"]
    }
    for dependency_name, (source_path, source_instance) in dependency_sources.items():
        dependency = manifest["release_dependencies"][dependency_name]
        declared_path = (CONTRACTS / dependency["path"]).resolve()
        resolved_source = source_path.resolve()
        if declared_path != resolved_source:
            raise AssertionError(f"release dependency path mismatch: {dependency_name}")
        if (
            dependency["version"] != source_instance["version"]
            or dependency["status"] != source_instance["status"]
            or dependency["sha256"] != sha256(resolved_source)
        ):
            raise AssertionError(
                f"release dependency metadata mismatch: {dependency_name}"
            )
        artifact_entry = artifact_by_path.get(resolved_source)
        if artifact_entry is None or artifact_entry["sha256"] != dependency["sha256"]:
            raise AssertionError(
                f"release dependency missing from artifacts: {dependency_name}"
            )
        if manifest["status"] == "frozen" and source_instance["status"] != "frozen":
            raise AssertionError(
                f"frozen contract-set has non-frozen dependency: {dependency_name}"
            )
    feature_ids = [item["feature_id"] for item in traceability["features"]]
    test_ids = [
        test["test_id"] for feature in traceability["features"] for test in feature["tests"]
    ]
    evidence_ids = [
        evidence["evidence_id"]
        for feature in traceability["features"]
        for evidence in feature["evidence"]
    ]
    require_unique(feature_ids, "feature_id")
    require_unique(test_ids, "test_id")
    require_unique(evidence_ids, "evidence_id")

    def duplicate_values(values: list[str]) -> bool:
        return len(values) != len(set(values))

    classification_rank = {
        "public": 0,
        "internal": 1,
        "confidential": 2,
        "restricted": 3,
    }

    def context_semantic_errors(
        instance: dict[str, Any],
        security_context: dict[str, Any] | None = None,
        maximum_input_tokens: int | None = None,
    ) -> list[str]:
        errors: list[str] = []
        context_ceiling = instance["policy"]["data_classification_ceiling"]
        context_ceiling_rank = classification_rank[context_ceiling]
        security_ceiling = (
            security_context["data_classification_ceiling"]
            if security_context is not None
            else None
        )
        if (
            security_ceiling is not None
            and context_ceiling_rank > classification_rank[security_ceiling]
        ):
            errors.append("context classification ceiling exceeds security ceiling")
        for layer in instance["layers"]:
            layer_rank = classification_rank[layer["classification"]]
            if layer_rank > context_ceiling_rank:
                errors.append(
                    f"context layer exceeds context classification ceiling: {layer['name']}"
                )
            if (
                security_ceiling is not None
                and layer_rank > classification_rank[security_ceiling]
            ):
                errors.append(
                    f"context layer exceeds security classification ceiling: {layer['name']}"
                )
        estimated = instance["manifest"]["input_tokens_estimated"]
        actual = instance["manifest"]["input_tokens_actual"]
        context_token_budget = instance["policy"]["token_budget"]
        if estimated > context_token_budget:
            errors.append("estimated input tokens exceed context policy")
        if actual is not None and actual > context_token_budget:
            errors.append("actual input tokens exceed context policy")
        if maximum_input_tokens is not None:
            if estimated > maximum_input_tokens:
                errors.append("estimated input tokens exceed request budget")
            if actual is not None and actual > maximum_input_tokens:
                errors.append("actual input tokens exceed request budget")
        return errors

    def traceability_semantic_errors(instance: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        features = instance["features"]
        local_feature_ids = [item["feature_id"] for item in features]
        local_test_ids = [
            test["test_id"] for feature in features for test in feature["tests"]
        ]
        local_evidence_ids = [
            evidence["evidence_id"]
            for feature in features
            for evidence in feature["evidence"]
        ]
        if duplicate_values(local_feature_ids):
            errors.append("duplicate feature_id")
        if duplicate_values(local_test_ids):
            errors.append("duplicate test_id")
        if duplicate_values(local_evidence_ids):
            errors.append("duplicate evidence_id")
        for feature in features:
            feature_segment = feature["feature_id"].lower()
            expected_test_prefix = f"test.{feature_segment}."
            expected_evidence_prefix = f"evidence.{feature_segment}."
            if feature["implementation_owner"] == feature["verification_owner"]:
                errors.append(
                    f"implementation and verification owner must differ: "
                    f"{feature['feature_id']}"
                )
            declared_tests = {item["test_id"]: item for item in feature["tests"]}
            declared_evidence = {
                item["evidence_id"]: item for item in feature["evidence"]
            }
            for test_id in declared_tests:
                if not test_id.startswith(expected_test_prefix):
                    errors.append(
                        f"test_id not bound to parent feature: {test_id}"
                    )
            for evidence_id in declared_evidence:
                if not evidence_id.startswith(expected_evidence_prefix):
                    errors.append(
                        f"evidence_id not bound to parent feature: {evidence_id}"
                    )
            referenced_evidence_ids = [
                item["evidence_id"] for item in feature["valid_evidence_refs"]
            ]
            if duplicate_values(referenced_evidence_ids):
                errors.append(
                    f"duplicate valid evidence reference: {feature['feature_id']}"
                )
            for evidence_ref in feature["valid_evidence_refs"]:
                evidence_id = evidence_ref["evidence_id"]
                test_id = evidence_ref["test_id"]
                if evidence_id not in declared_evidence:
                    errors.append(f"undeclared evidence reference: {evidence_id}")
                    continue
                if test_id not in declared_tests:
                    errors.append(f"undeclared test reference: {test_id}")
                evidence_definition = declared_evidence[evidence_id]
                if evidence_ref["artifact_path"] != evidence_definition["path_pattern"]:
                    errors.append(f"evidence path mismatch: {evidence_id}")
                if evidence_ref["verifier_role"] != feature["verification_owner"]:
                    errors.append(f"evidence verifier mismatch: {evidence_id}")
                artifact_path = (ROOT / evidence_ref["artifact_path"]).resolve()
                if not artifact_path.is_relative_to(ROOT):
                    errors.append(f"evidence path escaped repository: {evidence_id}")
                elif not artifact_path.is_file():
                    errors.append(f"evidence artifact missing: {evidence_id}")
                elif evidence_ref["artifact_hash"] != sha256(artifact_path):
                    errors.append(f"evidence artifact hash mismatch: {evidence_id}")
        return errors

    def evaluation_registry_semantic_errors(instance: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        local_assertion_ids = [
            item["assertion_id"] for item in instance["deterministic_assertions"]
        ]
        local_rubric_ids = [item["rubric_id"] for item in instance["judge_rubrics"]]
        local_implementation_keys = [
            item["implementation_key"]
            for item in instance["deterministic_assertions"]
        ]
        local_categories = [
            category
            for categories in instance["categories"].values()
            for category in categories
        ]
        if duplicate_values(local_assertion_ids):
            errors.append("duplicate assertion_id")
        if duplicate_values(local_rubric_ids):
            errors.append("duplicate rubric_id")
        if duplicate_values(local_implementation_keys):
            errors.append("duplicate assertion implementation_key")
        if duplicate_values(local_categories):
            errors.append("duplicate evaluation category")
        assertion_entries = {
            item["assertion_id"]: item for item in instance["deterministic_assertions"]
        }
        primary_expected_counts = {
            "functional": 120,
            "safety_fault": 36,
        }
        safety_required_domains = {
            "tenant_isolation": {"tenant"},
            "rbac_abac_sod": {"approval"},
            "prompt_injection_malicious_mcp": {"security", "tool"},
            "approval_replay_tamper_duplicate_write": {"approval", "tool"},
            "dependency_failure_unknown": {"flow", "observability", "tool"},
            "secret_dlp_audit": {"security", "observability"},
        }
        for suite_name, categories in instance["categories"].items():
            policy = instance["suite_policies"][suite_name]
            category_set = set(categories)
            if set(policy["category_counts"]) != category_set:
                errors.append(f"category count keys mismatch: {suite_name}")
            if set(policy["required_assertions_by_category"]) != category_set:
                errors.append(f"category gate keys mismatch: {suite_name}")
            if sum(policy["category_counts"].values()) != policy["expected_case_count"]:
                errors.append(f"category counts do not sum to suite total: {suite_name}")
            expected_count = primary_expected_counts.get(suite_name)
            if (
                expected_count is not None
                and policy["expected_case_count"] != expected_count
            ):
                errors.append(f"required suite count mismatch: {suite_name}")
            for category, required_ids in policy[
                "required_assertions_by_category"
            ].items():
                required_domains: set[str] = set()
                for assertion_id in required_ids:
                    assertion_entry = assertion_entries.get(assertion_id)
                    if assertion_entry is None:
                        errors.append(
                            f"category gate references unknown assertion: "
                            f"{suite_name}/{category}/{assertion_id}"
                        )
                    elif suite_name not in assertion_entry["allowed_suites"]:
                        errors.append(
                            f"category gate assertion not allowed in suite: "
                            f"{suite_name}/{category}/{assertion_id}"
                        )
                    else:
                        required_domains.add(assertion_entry["gate_domain"])
                if (
                    suite_name == "safety_fault"
                    and not safety_required_domains.get(category, set())
                    <= required_domains
                ):
                    errors.append(
                        f"safety category gate domains insufficient: {category}"
                    )
        if instance["status"] == "frozen":
            for rubric in instance["judge_rubrics"]:
                prompt_ref = rubric["prompt_ref"]
                prompt_hash = rubric["prompt_hash"]
                if prompt_ref is None or prompt_hash is None:
                    errors.append(f"frozen Judge prompt missing: {rubric['rubric_id']}")
                    continue
                prompt_path = (ROOT / prompt_ref.removeprefix("repo://").split("#", 1)[0]).resolve()
                if not prompt_path.is_relative_to(ROOT) or not prompt_path.is_file():
                    errors.append(f"Judge prompt reference missing: {rubric['rubric_id']}")
                elif prompt_hash != sha256(prompt_path):
                    errors.append(f"Judge prompt hash mismatch: {rubric['rubric_id']}")
                for ref_name in ("output_schema_ref", "calibration_policy_ref"):
                    ref_value = rubric[ref_name]
                    ref_path = (
                        ROOT
                        / ref_value.removeprefix("repo://").split("#", 1)[0]
                    ).resolve()
                    if not ref_path.is_relative_to(ROOT) or not ref_path.is_file():
                        errors.append(
                            f"Judge {ref_name} missing: {rubric['rubric_id']}"
                        )
        return errors

    def evaluation_dataset_semantic_errors(instance: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        local_case_ids = [item["case_id"] for item in instance["cases"]]
        local_paths = [item["path"] for item in instance["cases"]]
        if duplicate_values(local_case_ids):
            errors.append("duplicate dataset case_id")
        if duplicate_values(local_paths):
            errors.append("duplicate dataset case path")
        if instance["status"] == "frozen":
            for suite_name, policy in evaluation_registry["suite_policies"].items():
                suite_cases = [
                    item for item in instance["cases"] if item["suite"] == suite_name
                ]
                if len(suite_cases) != policy["expected_case_count"]:
                    errors.append(f"frozen dataset suite count mismatch: {suite_name}")
                for category, expected_count in policy["category_counts"].items():
                    actual_count = sum(
                        item["category"] == category for item in suite_cases
                    )
                    if actual_count != expected_count:
                        errors.append(
                            f"frozen dataset category count mismatch: "
                            f"{suite_name}/{category}"
                        )
            for case_ref in instance["cases"]:
                case_path = (ROOT / case_ref["path"]).resolve()
                if not case_path.is_relative_to(ROOT) or not case_path.is_file():
                    errors.append(f"dataset case file missing: {case_ref['case_id']}")
                    continue
                if case_ref["sha256"] != sha256(case_path):
                    errors.append(f"dataset case hash mismatch: {case_ref['case_id']}")
                    continue
                case_instance = load_json(case_path)
                if (
                    case_instance["case_id"] != case_ref["case_id"]
                    or case_instance["suite"] != case_ref["suite"]
                    or case_instance["category"] != case_ref["category"]
                ):
                    errors.append(
                        f"dataset case manifest fields mismatch: {case_ref['case_id']}"
                    )
        return errors

    def evaluation_fixture_semantic_errors(instance: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        tenant_ids = [
            item["tenant_fixture_id"] for item in instance["tenant_fixtures"]
        ]
        principal_ids = [
            item["principal_fixture_id"] for item in instance["principal_fixtures"]
        ]
        if duplicate_values(tenant_ids):
            errors.append("duplicate tenant fixture id")
        if duplicate_values(principal_ids):
            errors.append("duplicate principal fixture id")
        return errors

    for label, errors in (
        ("traceability", traceability_semantic_errors(traceability)),
        (
            "evaluation registry",
            evaluation_registry_semantic_errors(evaluation_registry),
        ),
        (
            "evaluation dataset",
            evaluation_dataset_semantic_errors(evaluation_dataset),
        ),
        (
            "evaluation fixtures",
            evaluation_fixture_semantic_errors(evaluation_fixtures),
        ),
    ):
        if errors:
            raise AssertionError(
                f"{label}: invalid semantic baseline: {', '.join(errors)}"
            )

    known_features = set(feature_ids)
    known_assertions = set(assertion_ids)
    known_rubrics = set(rubric_ids)
    registry_path = CONTRACTS / "registries" / "evaluation-registry.v1.json"
    dataset_path = (
        CONTRACTS / "registries" / "evaluation-dataset-manifest.v1.json"
    )
    fixture_path = (
        CONTRACTS / "registries" / "evaluation-fixture-manifest.v1.json"
    )
    known_tenant_fixtures = {
        item["tenant_fixture_id"] for item in evaluation_fixtures["tenant_fixtures"]
    }
    known_principal_fixtures = {
        item["principal_fixture_id"]
        for item in evaluation_fixtures["principal_fixtures"]
    }

    def evaluation_semantic_errors(instance: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if not set(instance["feature_ids"]) <= known_features:
            errors.append("unknown feature_id")
        suite = instance["suite"]
        if instance["category"] not in evaluation_registry["categories"][suite]:
            errors.append("category not registered for suite")
        assertion_id_list = [
            item["assertion_id"] for item in instance["deterministic_assertions"]
        ]
        assertion_id_set = set(assertion_id_list)
        if duplicate_values(assertion_id_list):
            errors.append("duplicate assertion_id in evaluation case")
        if not assertion_id_set <= known_assertions:
            errors.append("unknown assertion_id")
        for assertion in instance["deterministic_assertions"]:
            registry_entry = assertion_registry.get(assertion["assertion_id"])
            if registry_entry is None:
                continue
            if suite not in registry_entry["allowed_suites"]:
                errors.append(
                    f"assertion not allowed in suite: {assertion['assertion_id']}"
                )
            parameter_errors = list(
                Draft202012Validator(
                    registry_entry["parameters_schema"],
                    format_checker=format_checker,
                ).iter_errors(assertion["parameters"])
            )
            if parameter_errors:
                errors.append(
                    f"assertion parameters invalid: {assertion['assertion_id']}"
                )
        required_assertions = set(
            evaluation_registry["suite_policies"][suite][
                "required_assertions_by_category"
            ].get(instance["category"], [])
        )
        if not required_assertions <= assertion_id_set:
            errors.append("required category assertion missing")
        terminal_expected = instance["expected"].get("terminal_status")
        terminal_assertions = [
            item
            for item in instance["deterministic_assertions"]
            if item["assertion_id"] == "assert.task.terminal_status.v1"
        ]
        if terminal_expected is not None and any(
            item["parameters"].get("expected") != terminal_expected
            for item in terminal_assertions
        ):
            errors.append("terminal status expectation/assertion mismatch")
        allowed_tools = set(instance["expected"].get("allowed_tools", []))
        forbidden_tools = set(instance["expected"].get("forbidden_tools", []))
        if allowed_tools & forbidden_tools:
            errors.append("allowed_tools and forbidden_tools overlap")
        if not {
            item["rubric_id"] for item in instance.get("judge_rubrics", [])
        } <= known_rubrics:
            errors.append("unknown rubric_id")
        for rubric in instance.get("judge_rubrics", []):
            registry_entry = rubric_registry.get(rubric["rubric_id"])
            if registry_entry is not None and suite not in registry_entry["allowed_suites"]:
                errors.append(f"rubric not allowed in suite: {rubric['rubric_id']}")
        registry_ref = instance["registry_ref"]
        if (
            registry_ref["registry_id"] != evaluation_registry["registry_id"]
            or registry_ref["registry_version"] != evaluation_registry["version"]
            or registry_ref["registry_hash"] != sha256(registry_path)
        ):
            errors.append("evaluation registry reference mismatch")
        dataset_ref = instance["dataset_ref"]
        if (
            dataset_ref["dataset_id"] != evaluation_dataset["dataset_id"]
            or dataset_ref["dataset_version"] != evaluation_dataset["version"]
            or dataset_ref["dataset_hash"] != sha256(dataset_path)
        ):
            errors.append("evaluation dataset reference mismatch")
        fixture_ref = instance["fixture_bundle_ref"]
        if (
            fixture_ref["fixture_id"] != evaluation_fixtures["fixture_id"]
            or fixture_ref["fixture_version"] != evaluation_fixtures["version"]
            or fixture_ref["fixture_hash"] != sha256(fixture_path)
        ):
            errors.append("evaluation fixture reference mismatch")
        if instance["tenant_fixture"] not in known_tenant_fixtures:
            errors.append("unknown tenant fixture")
        if (
            instance.get("principal_fixture") is not None
            and instance["principal_fixture"] not in known_principal_fixtures
        ):
            errors.append("unknown principal fixture")
        if evaluation_dataset["status"] == "frozen" and instance["case_id"] not in {
            item["case_id"] for item in evaluation_dataset["cases"]
        }:
            errors.append("evaluation case not declared by frozen dataset")
        return errors

    def agent_request_semantic_errors(instance: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        context = instance["context"]
        security_context = instance["security_context"]
        if instance["task_id"] != context["task_id"]:
            errors.append("request/context task mismatch")
        if len(
            {
                instance["tenant_id"],
                context["tenant_id"],
                security_context["tenant_id"],
            }
        ) != 1:
            errors.append("request/context/security tenant mismatch")
        if instance["agent"]["id"] != context["agent_id"]:
            errors.append("request/context agent mismatch")
        if context["purpose"] != security_context["purpose"]:
            errors.append("context/security purpose mismatch")
        if (
            instance["provider_selection"]["provider"]
            not in context["policy"]["provider_allowlist"]
        ):
            errors.append("provider outside context allowlist")
        if (
            instance["budget"]["maximum_input_tokens"]
            > context["policy"]["token_budget"]
        ):
            errors.append("request input budget exceeds context policy")
        errors.extend(
            context_semantic_errors(
                context,
                security_context=security_context,
                maximum_input_tokens=instance["budget"]["maximum_input_tokens"],
            )
        )
        return errors

    def task_command_semantic_errors(instance: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        security_context = instance["security_context"]
        actor = instance["actor"]
        digest_projection = {
            "command_type": instance["command_type"],
            "tenant_id": instance["tenant_id"],
            "task_id": instance["task_id"],
            "actor": actor,
            "expected_task_version": instance["expected_task_version"],
            "payload": instance["payload"],
        }
        if instance["command_digest"] != canonical_digest(digest_projection):
            errors.append("task command digest mismatch")
        if instance["tenant_id"] != security_context["tenant_id"]:
            errors.append("task command/security tenant mismatch")
        if actor["id"] != security_context["subject_id"]:
            errors.append("task command/security subject id mismatch")
        if actor["type"] != security_context["subject_type"]:
            errors.append("task command/security subject type mismatch")
        if (
            instance["command_type"] == "task.create.v1"
            and instance["payload"]["purpose"] != security_context["purpose"]
        ):
            errors.append("task command/security purpose mismatch")
        return errors

    policy_fixture = cases_by_id["policy.single_approval.valid"]["instance"]
    approval_fixture = cases_by_id["approval.sod.valid"]["instance"]
    tool_request_fixture = cases_by_id["tool_request.bound_identities.valid"]["instance"]

    def policy_decision_semantic_errors(instance: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        context = tool_request_fixture["security_context"]
        action = tool_request_fixture["planned_action"]
        approval = approval_fixture
        if len({instance["tenant_id"], action["tenant_id"], approval["tenant_id"]}) != 1:
            errors.append("policy tenant binding mismatch")
        if len({instance["task_id"], action["task_id"], approval["task_id"]}) != 1:
            errors.append("policy task binding mismatch")
        if instance["subject_ref"] != context["context_ref"]:
            errors.append("policy subject reference mismatch")
        if instance["subject_context_hash"] != context["context_hash"]:
            errors.append("policy subject context hash mismatch")
        if len(
            {
                instance["action"]["action_digest"],
                approval["action_digest"],
                canonical_digest(action),
            }
        ) != 1:
            errors.append("policy action digest mismatch")
        if (
            instance["action"]["tool"],
            instance["action"]["operation"],
        ) != (
            action["tool"]["name"],
            action["tool"]["operation"],
        ):
            errors.append("policy tool operation mismatch")
        if approval["policy_decision_id"] != instance["decision_id"]:
            errors.append("approval policy decision id mismatch")
        if len(
            {
                instance["policy_version"],
                action["policy_version"],
                approval["policy_version"],
            }
        ) != 1:
            errors.append("policy version binding mismatch")
        if len(
            {
                instance["expires_at"],
                action["expires_at"],
                approval["expires_at"],
            }
        ) != 1:
            errors.append("policy expiry binding mismatch")
        return errors

    def approval_semantic_errors(instance: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        action = tool_request_fixture["planned_action"]
        policy = policy_fixture
        if (
            instance["status"] == "approved"
            and instance["approver_id"] == instance["requester_id"]
        ):
            errors.append("approver must differ from requester")
        if len(
            {
                instance["tenant_id"],
                action["tenant_id"],
                policy["tenant_id"],
            }
        ) != 1:
            errors.append("approval tenant binding mismatch")
        if instance["requester_id"] != action["requester_id"]:
            errors.append("approval requester binding mismatch")
        if len({instance["task_id"], action["task_id"], policy["task_id"]}) != 1:
            errors.append("approval task binding mismatch")
        if instance["action_id"] != action["action_id"]:
            errors.append("approval action id mismatch")
        if len(
            {
                instance["action_digest"],
                policy["action"]["action_digest"],
                canonical_digest(action),
            }
        ) != 1:
            errors.append("approval action digest mismatch")
        if instance["tool_schema_hash"] != action["tool"]["schema_hash"]:
            errors.append("approval tool schema hash mismatch")
        if instance["policy_decision_id"] != policy["decision_id"]:
            errors.append("approval policy decision id mismatch")
        if len(
            {
                instance["policy_version"],
                action["policy_version"],
                policy["policy_version"],
            }
        ) != 1:
            errors.append("approval policy version mismatch")
        if len(
            {
                instance["expires_at"],
                action["expires_at"],
                policy["expires_at"],
            }
        ) != 1:
            errors.append("approval expiry binding mismatch")
        return errors

    def tool_request_semantic_errors(instance: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        context = instance["security_context"]
        action = instance["planned_action"]
        agent = instance["agent_principal"]
        policy = policy_fixture
        approval = approval_fixture
        if len({context["tenant_id"], action["tenant_id"], policy["tenant_id"], approval["tenant_id"]}) != 1:
            errors.append("tool request tenant binding mismatch")
        if len({context["subject_id"], action["requester_id"], approval["requester_id"]}) != 1:
            errors.append("tool request requester binding mismatch")
        if len({action["task_id"], policy["task_id"], approval["task_id"]}) != 1:
            errors.append("tool request task binding mismatch")
        if context["context_ref"] != policy["subject_ref"]:
            errors.append("policy subject reference mismatch")
        if context["context_hash"] != policy["subject_context_hash"]:
            errors.append("policy subject context hash mismatch")
        if (agent["id"], agent["version"]) != (
            action["agent"]["id"],
            action["agent"]["version"],
        ):
            errors.append("tool request/action agent mismatch")
        if (agent["id"], agent["version"], agent["principal_ref"]) != (
            policy["agent"]["id"],
            policy["agent"]["version"],
            policy["agent"]["principal_ref"],
        ):
            errors.append("tool request/policy agent mismatch")
        if instance["policy_decision_id"] != policy["decision_id"]:
            errors.append("policy decision id mismatch")
        if len(
            {
                instance["action_digest"],
                policy["action"]["action_digest"],
                approval["action_digest"],
                canonical_digest(action),
            }
        ) != 1:
            errors.append("planned action digest mismatch")
        if (action["tool"]["name"], action["tool"]["operation"]) != (
            policy["action"]["tool"],
            policy["action"]["operation"],
        ):
            errors.append("tool operation policy mismatch")
        if len(
            {
                action["policy_version"],
                policy["policy_version"],
                approval["policy_version"],
            }
        ) != 1:
            errors.append("action policy version mismatch")
        if action["tool"]["schema_hash"] != approval["tool_schema_hash"]:
            errors.append("approval tool schema hash mismatch")
        if len(
            {
                action["expires_at"],
                policy["expires_at"],
                approval["expires_at"],
            }
        ) != 1:
            errors.append("action approval policy expiry mismatch")
        if policy["decision"] == "require_approval":
            if (
                instance.get("approval_id") != approval["approval_id"]
                or approval["status"] != "approved"
                or approval["policy_decision_id"] != policy["decision_id"]
                or approval["action_id"] != action["action_id"]
                or approval["separation_of_duties_result"] is not True
                or approval["approver_id"] == approval["requester_id"]
            ):
                errors.append("approval binding mismatch")
        return errors

    def tool_result_semantic_errors(instance: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if instance["request_id"] != tool_request_fixture["request_id"]:
            errors.append("tool result request id mismatch")
        if (
            instance["policy_decision_id"]
            != tool_request_fixture["policy_decision_id"]
        ):
            errors.append("tool result policy decision mismatch")
        if (
            instance["operation"]
            != tool_request_fixture["planned_action"]["tool"]["operation"]
        ):
            errors.append("tool result operation mismatch")
        return errors

    audit_fixture = cases_by_id["audit.denied_linked.valid"]["instance"]
    audit_second_fixture = cases_by_id["audit.chain_second.valid"]["instance"]
    security_event_fixture = cases_by_id["security_event.blocked.valid"]["instance"]

    def audit_event_semantic_errors(instance: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if instance["integrity"]["event_hash"] != audit_event_hash(instance):
            errors.append("AUDIT_HASH_MISMATCH")
        if instance["sequence"] > 1:
            if instance["stream_id"] != audit_fixture["stream_id"]:
                errors.append("AUDIT_STREAM_MISMATCH")
            if instance["tenant_id"] != audit_fixture["tenant_id"]:
                errors.append("AUDIT_STREAM_TENANT_MISMATCH")
            if instance["sequence"] != audit_fixture["sequence"] + 1:
                errors.append("AUDIT_SEQUENCE_GAP")
            if (
                instance["integrity"]["previous_hash"]
                != audit_fixture["integrity"]["event_hash"]
            ):
                errors.append("AUDIT_PREVIOUS_HASH_MISMATCH")
        return errors

    trusted_audit_streams = {
        "audit://tenant-a/2026-07": "tenant-a",
        "audit://tenant-a/security": "tenant-a",
    }

    def audit_chain_errors(events: list[dict[str, Any]]) -> list[str]:
        errors: list[str] = []
        event_ids = [event["event_id"] for event in events]
        if duplicate_values(event_ids):
            errors.append("AUDIT_DUPLICATE_EVENT_ID")
        streams: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            stream_id = event["stream_id"]
            streams.setdefault(stream_id, []).append(event)
            expected_tenant = trusted_audit_streams.get(stream_id)
            if expected_tenant is None:
                errors.append("AUDIT_UNTRUSTED_STREAM")
            elif expected_tenant != event["tenant_id"]:
                errors.append("AUDIT_STREAM_TENANT_MISMATCH")
            if event["integrity"]["event_hash"] != audit_event_hash(event):
                errors.append("AUDIT_HASH_MISMATCH")
        for stream_id, stream_events in streams.items():
            ordered = sorted(stream_events, key=lambda item: item["sequence"])
            sequences = [item["sequence"] for item in ordered]
            if duplicate_values([str(value) for value in sequences]):
                errors.append("AUDIT_DUPLICATE_SEQUENCE")
            if sequences != list(range(1, len(ordered) + 1)):
                errors.append("AUDIT_SEQUENCE_GAP")
            expected_previous: str | None = None
            for event in ordered:
                if event["integrity"]["previous_hash"] != expected_previous:
                    errors.append("AUDIT_PREVIOUS_HASH_MISMATCH")
                expected_previous = event["integrity"]["event_hash"]
        return errors

    def signal_link_errors(
        audit: dict[str, Any],
        security_event: dict[str, Any],
    ) -> list[str]:
        errors: list[str] = []
        if (
            audit["security_event_id"] != security_event["event_id"]
            or security_event["audit_event_id"] != audit["event_id"]
        ):
            errors.append("audit/security bidirectional id mismatch")
        keys = [
            "tenant_id",
            "trace_id",
            "thread_id",
            "task_id",
            "run_id",
            "correlation_id",
            "causation_id",
        ]
        if any(audit[key] != security_event[key] for key in keys):
            errors.append("audit/security correlation mismatch")
        return errors

    def semantic_errors_for(
        schema_name: str,
        instance: dict[str, Any],
    ) -> list[str]:
        if schema_name == "evaluation-case.v1.schema.json":
            return evaluation_semantic_errors(instance)
        if schema_name == "context-envelope.v1.schema.json":
            return context_semantic_errors(instance)
        if schema_name == "agent-run-request.v1.schema.json":
            return agent_request_semantic_errors(instance)
        if schema_name == "task-command.v1.schema.json":
            return task_command_semantic_errors(instance)
        if schema_name == "policy-decision.v1.schema.json":
            return policy_decision_semantic_errors(instance)
        if schema_name == "approval.v1.schema.json":
            return approval_semantic_errors(instance)
        if schema_name == "tool-request.v1.schema.json":
            return tool_request_semantic_errors(instance)
        if schema_name == "tool-result.v1.schema.json":
            return tool_result_semantic_errors(instance)
        if schema_name == "audit-event.v1.schema.json":
            errors = audit_event_semantic_errors(instance)
            if instance.get("security_event_id") is not None:
                errors.extend(signal_link_errors(instance, security_event_fixture))
            return errors
        if schema_name == "security-event.v1.schema.json":
            return signal_link_errors(audit_fixture, instance)
        raise AssertionError(f"unsupported semantic schema: {schema_name}")

    semantic_schema_names = {
        "evaluation-case.v1.schema.json",
        "context-envelope.v1.schema.json",
        "agent-run-request.v1.schema.json",
        "task-command.v1.schema.json",
        "policy-decision.v1.schema.json",
        "approval.v1.schema.json",
        "tool-request.v1.schema.json",
        "tool-result.v1.schema.json",
        "audit-event.v1.schema.json",
        "security-event.v1.schema.json",
    }
    for case in suite["cases"]:
        if not case["expect_valid"] or case["schema"] not in semantic_schema_names:
            continue
        errors = semantic_errors_for(case["schema"], case["instance"])
        if errors:
            raise AssertionError(
                f"{case['case_id']}: invalid semantic baseline: {', '.join(errors)}"
            )

    semantic_cases = suite.get("semantic_cases", [])
    semantic_ids = [case["case_id"] for case in semantic_cases]
    require_unique(case_ids + mutation_ids + semantic_ids, "all conformance case_id")
    semantic_positive = semantic_negative = 0
    for case in semantic_cases:
        base = cases_by_id[case["base_case_id"]]
        if not base["expect_valid"]:
            raise AssertionError(
                f"{case['case_id']}: semantic base must be an expected-valid case"
            )
        instance = copy.deepcopy(base["instance"])
        for mutation in case.get("mutations", [case.get("mutation")]):
            if mutation is not None:
                apply_json_pointer(instance, mutation)
        semantic_validator = Draft202012Validator(
            schemas[base["schema"]],
            registry=registry,
            format_checker=format_checker,
        )
        schema_errors = list(semantic_validator.iter_errors(instance))
        if schema_errors:
            raise AssertionError(
                f"{case['case_id']}: semantic fixture is schema-invalid: "
                f"{schema_errors[0].message}"
            )
        semantic_errors = semantic_errors_for(base["schema"], instance)
        actual_valid = not semantic_errors
        if actual_valid != case["expect_valid"]:
            raise AssertionError(f"{case['case_id']}: semantic expectation mismatch")
        semantic_positive += int(actual_valid)
        semantic_negative += int(not actual_valid)

    audit_chain_cases = suite.get("audit_chain_cases", [])
    audit_chain_ids = [case["case_id"] for case in audit_chain_cases]
    require_unique(
        case_ids + mutation_ids + semantic_ids + audit_chain_ids,
        "all conformance case_id",
    )
    audit_chain_positive = audit_chain_negative = 0
    audit_schema_validator = Draft202012Validator(
        schemas["audit-event.v1.schema.json"],
        registry=registry,
        format_checker=format_checker,
    )
    for case in audit_chain_cases:
        events = [
            copy.deepcopy(cases_by_id[case_id]["instance"])
            for case_id in case["event_case_ids"]
        ]
        for mutation in case.get("mutations", []):
            apply_json_pointer(events[mutation["event_index"]], mutation)
        for event_index in case.get("rehash_event_indexes", []):
            events[event_index]["integrity"]["event_hash"] = audit_event_hash(
                events[event_index]
            )
        for event in events:
            schema_errors = list(audit_schema_validator.iter_errors(event))
            if schema_errors:
                raise AssertionError(
                    f"{case['case_id']}: audit chain fixture is schema-invalid: "
                    f"{schema_errors[0].message}"
                )
        actual_valid = not audit_chain_errors(events)
        if actual_valid != case["expect_valid"]:
            raise AssertionError(
                f"{case['case_id']}: audit chain expectation mismatch"
            )
        audit_chain_positive += int(actual_valid)
        audit_chain_negative += int(not actual_valid)

    manifest_cases = suite.get("manifest_semantic_cases", [])
    manifest_ids = [case["case_id"] for case in manifest_cases]
    require_unique(
        case_ids + mutation_ids + semantic_ids + audit_chain_ids + manifest_ids,
        "all conformance case_id",
    )
    manifest_positive = manifest_negative = 0

    def contract_set_semantic_errors(instance: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if instance["content_digest"] != contract_content_digest(instance):
            errors.append("contract-set content digest mismatch")
        for review in instance["reviews"]:
            if review["decision"] != "PENDING":
                if review["reviewed_content_digest"] != instance["content_digest"]:
                    errors.append(f"review digest mismatch: {review['role']}")
                evidence_path = (ROOT / review["evidence_ref"]).resolve()
                if not evidence_path.is_relative_to(ROOT) or not evidence_path.is_file():
                    errors.append(f"review evidence missing: {review['role']}")
                elif review["evidence_sha256"] != sha256(evidence_path):
                    errors.append(f"review evidence hash mismatch: {review['role']}")
        for dependency_name, (source_path, source_instance) in dependency_sources.items():
            dependency = instance["release_dependencies"][dependency_name]
            if (
                dependency["sha256"] != sha256(source_path)
                or dependency["version"] != source_instance["version"]
                or dependency["status"] != source_instance["status"]
            ):
                errors.append(f"release dependency mismatch: {dependency_name}")
        return errors

    manifest_targets = {
        "contract_set": (
            manifest,
            "contract-set.v1.schema.json",
            contract_set_semantic_errors,
        ),
        "traceability": (
            traceability,
            "feature-traceability.v1.schema.json",
            traceability_semantic_errors,
        ),
        "evaluation_registry": (
            evaluation_registry,
            "evaluation-registry.v1.schema.json",
            evaluation_registry_semantic_errors,
        ),
        "evaluation_dataset": (
            evaluation_dataset,
            "evaluation-dataset-manifest.v1.schema.json",
            evaluation_dataset_semantic_errors,
        ),
        "evaluation_fixtures": (
            evaluation_fixtures,
            "evaluation-fixture-manifest.v1.schema.json",
            evaluation_fixture_semantic_errors,
        ),
    }
    for case in manifest_cases:
        source, schema_name, semantic_check = manifest_targets[case["target"]]
        instance = copy.deepcopy(source)
        for mutation in case.get("mutations", [case.get("mutation")]):
            if mutation is not None:
                apply_json_pointer(instance, mutation)
        validator = Draft202012Validator(
            schemas[schema_name],
            registry=registry,
            format_checker=format_checker,
        )
        schema_errors = list(validator.iter_errors(instance))
        actual_schema_valid = not schema_errors
        expected_schema_valid = case.get("expect_schema_valid", True)
        if actual_schema_valid != expected_schema_valid:
            raise AssertionError(
                f"{case['case_id']}: manifest schema expectation mismatch"
            )
        actual_valid = actual_schema_valid and not semantic_check(instance)
        if actual_valid != case["expect_valid"]:
            raise AssertionError(
                f"{case['case_id']}: manifest semantic expectation mismatch"
            )
        manifest_positive += int(actual_valid)
        manifest_negative += int(not actual_valid)

    print(
        "CONTRACT_CONFORMANCE_OK "
        f"schemas={len(schemas)} cases={len(suite['cases'])} "
        f"positive={positive} negative={negative} "
        f"mutation_cases={len(mutation_cases)} "
        f"mutation_positive={mutation_positive} mutation_negative={mutation_negative} "
        f"semantic_cases={len(semantic_cases)} "
        f"semantic_positive={semantic_positive} semantic_negative={semantic_negative} "
        f"audit_chain_cases={len(audit_chain_cases)} "
        f"audit_chain_positive={audit_chain_positive} "
        f"audit_chain_negative={audit_chain_negative} "
        f"manifest_cases={len(manifest_cases)} "
        f"manifest_positive={manifest_positive} manifest_negative={manifest_negative} "
        f"features={len(feature_ids)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
