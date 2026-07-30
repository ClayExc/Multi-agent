from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

import yaml
from flowpilot_domain import (
    CommandType,
    DataClassification,
    RiskLevel,
    TaskCommand,
)

from .errors import ApplicationError, ErrorCode
from .models import (
    RequestReferenceQuery,
    ResolvedRequestReference,
    ResultCitation,
)

MAX_DOMAIN_PACK_FILE_BYTES = 256 * 1024
_DOMAIN_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


class _NoAliasSafeLoader(yaml.SafeLoader):
    def compose_node(self, parent: Any, index: Any) -> yaml.Node:
        if self.check_event(yaml.AliasEvent):  # type: ignore[no-untyped-call]
            raise ApplicationError(
                ErrorCode.DOMAIN_PACK_INVALID,
                "domain pack YAML aliases are not allowed",
            )
        return cast(yaml.Node, super().compose_node(parent, index))

    def construct_mapping(
        self, node: yaml.MappingNode, deep: bool = False
    ) -> dict[Any, Any]:
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError as exc:
                raise _invalid_pack("domain pack YAML key is invalid") from exc
            if duplicate:
                raise _invalid_pack("domain pack YAML keys must be unique")
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


@dataclass(frozen=True, slots=True)
class DomainPackManifest:
    schema_version: str
    domain_id: str
    version: str
    display_name: str
    intents_ref: str
    required_fields_ref: str
    risk_rules_ref: str
    fixture_refs: tuple[str, ...]
    knowledge_refs: tuple[str, ...] = ()
    reference_expectations_ref: str | None = None


@dataclass(frozen=True, slots=True)
class DomainIntent:
    id: str
    description: str
    allowed_command_types: tuple[CommandType, ...]


@dataclass(frozen=True, slots=True)
class DomainRiskRule:
    id: str
    intent_id: str
    risk_level: RiskLevel


@dataclass(frozen=True, slots=True)
class DomainPackFixture:
    case_id: str
    expected_intent: str
    command: TaskCommand
    resolved_request: ResolvedRequestReference | None = None
    expected_missing_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DomainKnowledgeSample:
    source_ref: str
    tenant_id: str
    document_id: str
    document_version: str
    section: str
    chunk_id: str
    data_classification: DataClassification
    acl_subjects: tuple[str, ...]
    effective_at: datetime
    expires_at: datetime | None
    content_summary: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class DomainReferenceExpectation:
    case_id: str
    expected_citations: tuple[ResultCitation, ...]
    excluded_source_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DomainPackDefinition:
    manifest: DomainPackManifest
    intents: tuple[DomainIntent, ...]
    required_fields: Mapping[str, tuple[str, ...]]
    risk_rules: tuple[DomainRiskRule, ...]
    fixtures: tuple[DomainPackFixture, ...]
    knowledge_samples: tuple[DomainKnowledgeSample, ...] = ()
    reference_expectations: tuple[DomainReferenceExpectation, ...] = ()


class DomainPackRegistry:
    """In-memory registry for validated, declarative domain packs."""

    def __init__(self) -> None:
        self._packs: dict[tuple[str, str], DomainPackDefinition] = {}

    def register(self, definition: DomainPackDefinition) -> None:
        key = (definition.manifest.domain_id, definition.manifest.version)
        if key in self._packs:
            raise ApplicationError(
                ErrorCode.DOMAIN_PACK_CONFLICT,
                "domain pack version is already registered",
            )
        self._packs[key] = definition

    def get(self, domain_id: str, version: str) -> DomainPackDefinition:
        try:
            return self._packs[(domain_id, version)]
        except KeyError as exc:
            raise ApplicationError(
                ErrorCode.DOMAIN_PACK_NOT_FOUND,
                "domain pack version was not found",
            ) from exc


def load_domain_pack(root: Path) -> DomainPackDefinition:
    """Load a bounded declarative pack without importing executable code."""

    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise _invalid_pack("domain pack root was not found") from exc
    if not resolved_root.is_dir():
        raise _invalid_pack("domain pack root must be a directory")

    manifest_data = _load_yaml_mapping(resolved_root, resolved_root / "manifest.yaml")
    manifest = _parse_manifest(manifest_data)
    intents = _parse_intents(_load_yaml_ref(resolved_root, manifest.intents_ref))
    intent_ids = {intent.id for intent in intents}
    required_fields = _parse_required_fields(
        _load_yaml_ref(resolved_root, manifest.required_fields_ref),
        intent_ids,
    )
    risk_rules = _parse_risk_rules(
        _load_yaml_ref(resolved_root, manifest.risk_rules_ref),
        intent_ids,
    )
    fixtures = tuple(
        _parse_fixture(
            _load_json_ref(resolved_root, reference),
            manifest.domain_id,
            intent_ids,
            required_fields,
        )
        for reference in manifest.fixture_refs
    )
    if not fixtures:
        raise _invalid_pack("domain pack must declare at least one fixture")
    fixture_case_ids = [fixture.case_id for fixture in fixtures]
    if len(fixture_case_ids) != len(set(fixture_case_ids)):
        raise _invalid_pack("domain pack fixture case ids must be unique")
    knowledge_samples = tuple(
        _parse_knowledge_sample(_load_json_ref(resolved_root, reference))
        for reference in manifest.knowledge_refs
    )
    source_refs = [sample.source_ref for sample in knowledge_samples]
    if len(source_refs) != len(set(source_refs)):
        raise _invalid_pack("knowledge sample source refs must be unique")
    knowledge_by_ref = {
        sample.source_ref: sample for sample in knowledge_samples
    }
    reference_expectations = (
        _parse_reference_expectations(
            _load_json_ref(
                resolved_root,
                manifest.reference_expectations_ref,
            ),
            {fixture.case_id: fixture for fixture in fixtures},
            knowledge_by_ref,
        )
        if manifest.reference_expectations_ref is not None
        else ()
    )
    return DomainPackDefinition(
        manifest=manifest,
        intents=intents,
        required_fields=required_fields,
        risk_rules=risk_rules,
        fixtures=fixtures,
        knowledge_samples=knowledge_samples,
        reference_expectations=reference_expectations,
    )


def _parse_manifest(value: Mapping[str, Any]) -> DomainPackManifest:
    common_keys = {
        "schema_version",
        "domain_id",
        "version",
        "display_name",
        "intents_ref",
        "required_fields_ref",
        "risk_rules_ref",
        "fixture_refs",
    }
    schema_version = value.get("schema_version")
    if schema_version == "flowpilot.domain-pack.v1":
        _require_exact_keys(value, common_keys, "manifest")
        knowledge_refs: tuple[str, ...] = ()
        reference_expectations_ref = None
    elif schema_version == "flowpilot.domain-pack.v2":
        _require_exact_keys(
            value,
            common_keys | {"knowledge_refs", "reference_expectations_ref"},
            "manifest",
        )
        knowledge_refs = tuple(
            _require_ref(reference, "knowledge_refs", ".json")
            for reference in _require_string_list(
                value["knowledge_refs"],
                "knowledge_refs",
                unique=True,
            )
        )
        if not knowledge_refs:
            raise _invalid_pack("v2 domain pack must declare knowledge samples")
        reference_expectations_ref = _require_ref(
            value["reference_expectations_ref"],
            "reference_expectations_ref",
            ".json",
        )
    else:
        raise _invalid_pack("domain pack schema_version is unsupported")
    domain_id = _require_string(value["domain_id"], "domain_id", maximum=64)
    version = _require_string(value["version"], "version", maximum=32)
    if _DOMAIN_ID_PATTERN.fullmatch(domain_id) is None:
        raise _invalid_pack("domain_id has an invalid format")
    if _VERSION_PATTERN.fullmatch(version) is None:
        raise _invalid_pack("domain pack version must use x.y.z")
    fixture_refs = _require_string_list(
        value["fixture_refs"], "fixture_refs", unique=True
    )
    return DomainPackManifest(
        schema_version=cast(str, schema_version),
        domain_id=domain_id,
        version=version,
        display_name=_require_string(
            value["display_name"], "display_name", maximum=128
        ),
        intents_ref=_require_ref(value["intents_ref"], "intents_ref", ".yaml"),
        required_fields_ref=_require_ref(
            value["required_fields_ref"], "required_fields_ref", ".yaml"
        ),
        risk_rules_ref=_require_ref(value["risk_rules_ref"], "risk_rules_ref", ".yaml"),
        fixture_refs=tuple(
            _require_ref(reference, "fixture_refs", ".json")
            for reference in fixture_refs
        ),
        knowledge_refs=knowledge_refs,
        reference_expectations_ref=reference_expectations_ref,
    )


def _parse_intents(value: Mapping[str, Any]) -> tuple[DomainIntent, ...]:
    _require_exact_keys(value, {"schema_version", "intents"}, "intents")
    if value["schema_version"] != "flowpilot.domain-pack.intents.v1":
        raise _invalid_pack("intent schema_version is unsupported")
    entries = _require_mapping_list(value["intents"], "intents")
    intents: list[DomainIntent] = []
    seen: set[str] = set()
    for entry in entries:
        _require_exact_keys(
            entry,
            {"id", "description", "allowed_command_types"},
            "intent",
        )
        intent_id = _require_local_id(entry["id"], "intent.id")
        if intent_id in seen:
            raise _invalid_pack("intent ids must be unique")
        seen.add(intent_id)
        command_values = _require_string_list(
            entry["allowed_command_types"],
            "intent.allowed_command_types",
            unique=True,
        )
        try:
            command_types = tuple(
                CommandType(command_value) for command_value in command_values
            )
        except ValueError as exc:
            raise _invalid_pack("intent contains an unsupported command type") from exc
        if not command_types:
            raise _invalid_pack("intent must allow at least one command type")
        intents.append(
            DomainIntent(
                id=intent_id,
                description=_require_string(
                    entry["description"], "intent.description", maximum=512
                ),
                allowed_command_types=command_types,
            )
        )
    if not intents:
        raise _invalid_pack("domain pack must declare at least one intent")
    return tuple(intents)


def _parse_required_fields(
    value: Mapping[str, Any], intent_ids: set[str]
) -> Mapping[str, tuple[str, ...]]:
    _require_exact_keys(value, {"schema_version", "required_fields"}, "required_fields")
    if value["schema_version"] != "flowpilot.domain-pack.required-fields.v1":
        raise _invalid_pack("required-fields schema_version is unsupported")
    raw_fields = _require_mapping(value["required_fields"], "required_fields")
    if set(raw_fields) != intent_ids:
        raise _invalid_pack("required fields must cover every intent exactly")
    parsed: dict[str, tuple[str, ...]] = {}
    for intent_id, fields in raw_fields.items():
        field_names = _require_string_list(
            fields, f"required_fields.{intent_id}", unique=True
        )
        parsed[intent_id] = tuple(
            _require_local_id(field, f"required_fields.{intent_id}")
            for field in field_names
        )
    return MappingProxyType(parsed)


def _parse_risk_rules(
    value: Mapping[str, Any], intent_ids: set[str]
) -> tuple[DomainRiskRule, ...]:
    _require_exact_keys(value, {"schema_version", "rules"}, "risk_rules")
    if value["schema_version"] != "flowpilot.domain-pack.risk-rules.v1":
        raise _invalid_pack("risk-rules schema_version is unsupported")
    entries = _require_mapping_list(value["rules"], "risk_rules.rules")
    rules: list[DomainRiskRule] = []
    seen: set[str] = set()
    for entry in entries:
        _require_exact_keys(entry, {"id", "intent_id", "risk_level"}, "risk_rule")
        rule_id = _require_local_id(entry["id"], "risk_rule.id")
        intent_id = _require_local_id(entry["intent_id"], "risk_rule.intent_id")
        if rule_id in seen:
            raise _invalid_pack("risk rule ids must be unique")
        if intent_id not in intent_ids:
            raise _invalid_pack("risk rule references an unknown intent")
        seen.add(rule_id)
        try:
            risk_level = RiskLevel(entry["risk_level"])
        except ValueError as exc:
            raise _invalid_pack("risk rule has an unsupported risk level") from exc
        rules.append(
            DomainRiskRule(
                id=rule_id,
                intent_id=intent_id,
                risk_level=risk_level,
            )
        )
    if not rules:
        raise _invalid_pack("domain pack must declare at least one risk rule")
    if {rule.intent_id for rule in rules} != intent_ids:
        raise _invalid_pack("risk rules must cover every intent")
    return tuple(rules)


def _parse_fixture(
    value: Mapping[str, Any],
    domain_id: str,
    intent_ids: set[str],
    required_fields: Mapping[str, tuple[str, ...]],
) -> DomainPackFixture:
    fixture_version = value.get("fixture_version")
    common_keys = {
        "fixture_version",
        "case_id",
        "domain_id",
        "expected_intent",
        "command",
    }
    if fixture_version == "flowpilot.domain-pack.fixture.v1":
        _require_exact_keys(value, common_keys, "fixture")
        resolved_request = None
        expected_missing_fields: tuple[str, ...] = ()
    elif fixture_version == "flowpilot.domain-pack.fixture.v2":
        _require_exact_keys(
            value,
            common_keys | {"resolved_request", "expected_missing_fields"},
            "fixture",
        )
        resolved_request = _parse_resolved_request(
            _require_mapping(value["resolved_request"], "resolved_request")
        )
        expected_missing_fields = tuple(
            _require_local_id(field, "expected_missing_fields")
            for field in _require_string_list(
                value["expected_missing_fields"],
                "expected_missing_fields",
                unique=True,
            )
        )
    else:
        raise _invalid_pack("fixture_version is unsupported")
    if value["domain_id"] != domain_id:
        raise _invalid_pack("fixture domain_id does not match the manifest")
    expected_intent = _require_local_id(
        value["expected_intent"], "fixture.expected_intent"
    )
    if expected_intent not in intent_ids:
        raise _invalid_pack("fixture references an unknown intent")
    command_mapping = _require_mapping(value["command"], "fixture.command")
    try:
        command = TaskCommand.from_mapping(dict(command_mapping))
        command.assert_digest()
        command.assert_security_binding()
    except (KeyError, TypeError, ValueError) as exc:
        raise _invalid_pack("fixture command is invalid") from exc
    if resolved_request is not None:
        _assert_fixture_request_binding(command, resolved_request)
        computed_missing = tuple(
            field_name
            for field_name in required_fields[expected_intent]
            if field_name not in resolved_request.fields
        )
        if expected_missing_fields != computed_missing:
            raise _invalid_pack(
                "fixture expected_missing_fields do not match required fields"
            )
    return DomainPackFixture(
        case_id=_require_local_id(value["case_id"], "fixture.case_id"),
        expected_intent=expected_intent,
        command=command,
        resolved_request=resolved_request,
        expected_missing_fields=expected_missing_fields,
    )


def _parse_resolved_request(
    value: Mapping[str, Any],
) -> ResolvedRequestReference:
    _require_exact_keys(
        value,
        {
            "query",
            "observation_ref",
            "source_digest",
            "intent",
            "fields",
            "data_classification",
            "observation_digest",
        },
        "resolved_request",
    )
    query = _require_mapping(value["query"], "resolved_request.query")
    _require_exact_keys(
        query,
        {
            "tenant_id",
            "task_id",
            "message_id",
            "message_ref",
            "purpose",
            "security_context_ref",
        },
        "resolved_request.query",
    )
    fields = _require_mapping(value["fields"], "resolved_request.fields")
    if any(not isinstance(item, str) for item in fields.values()):
        raise _invalid_pack("resolved request fields must be strings")
    try:
        resolved = ResolvedRequestReference(
            query=RequestReferenceQuery(
                tenant_id=query["tenant_id"],
                task_id=query["task_id"],
                message_id=query["message_id"],
                message_ref=query["message_ref"],
                purpose=query["purpose"],
                security_context_ref=query["security_context_ref"],
            ),
            observation_ref=value["observation_ref"],
            source_digest=value["source_digest"],
            intent=value["intent"],
            fields=cast(Mapping[str, str], fields),
            data_classification=DataClassification(value["data_classification"]),
            observation_digest=value["observation_digest"],
        )
        resolved.assert_digest()
    except (TypeError, ValueError) as exc:
        raise _invalid_pack("resolved request fixture is invalid") from exc
    return resolved


def _assert_fixture_request_binding(
    command: TaskCommand,
    resolved: ResolvedRequestReference,
) -> None:
    if command.command_type is CommandType.CREATE:
        message_id = command.payload["initial_message_id"]
        message_ref = command.payload["initial_message_ref"]
    elif command.command_type is CommandType.SUBMIT_MESSAGE:
        message_id = command.payload["message_id"]
        message_ref = command.payload["message_ref"]
    else:
        raise _invalid_pack("fixture command does not contain a message reference")
    query = resolved.query
    if (
        query.tenant_id != command.tenant_id
        or query.task_id != command.task_id
        or query.message_id != message_id
        or query.message_ref != message_ref
        or query.purpose != command.security_context.purpose
        or query.security_context_ref != command.security_context.context_ref
        or resolved.intent == ""
    ):
        raise _invalid_pack(
            "resolved request does not match the fixture command binding"
        )


def _parse_knowledge_sample(
    value: Mapping[str, Any],
) -> DomainKnowledgeSample:
    _require_exact_keys(
        value,
        {
            "knowledge_fixture_version",
            "source_ref",
            "tenant_id",
            "document_id",
            "document_version",
            "section",
            "chunk_id",
            "data_classification",
            "acl_subjects",
            "effective_at",
            "expires_at",
            "content_summary",
            "content_hash",
        },
        "knowledge sample",
    )
    if value["knowledge_fixture_version"] != (
        "flowpilot.domain-pack.knowledge-fixture.v1"
    ):
        raise _invalid_pack("knowledge fixture version is unsupported")
    acl_subjects = _require_string_list(
        value["acl_subjects"],
        "knowledge.acl_subjects",
        unique=True,
    )
    if not acl_subjects:
        raise _invalid_pack("knowledge sample ACL must not be empty")
    expires_at = value["expires_at"]
    parsed_expires_at = (
        _require_timestamp(expires_at, "knowledge.expires_at")
        if expires_at is not None
        else None
    )
    try:
        data_classification = DataClassification(value["data_classification"])
    except ValueError as exc:
        raise _invalid_pack(
            "knowledge sample data classification is invalid"
        ) from exc
    effective_at = _require_timestamp(
        value["effective_at"], "knowledge.effective_at"
    )
    if parsed_expires_at is not None and parsed_expires_at <= effective_at:
        raise _invalid_pack("knowledge expires_at must be after effective_at")
    tenant_id = _require_string(
        value["tenant_id"], "knowledge.tenant_id", maximum=128
    )
    source_ref = _require_string(
        value["source_ref"], "knowledge.source_ref", maximum=512
    )
    if not source_ref.startswith(f"knowledge://{tenant_id}/"):
        raise _invalid_pack(
            "knowledge source_ref does not match the trusted tenant binding"
        )
    return DomainKnowledgeSample(
        source_ref=source_ref,
        tenant_id=tenant_id,
        document_id=_require_local_id(
            value["document_id"], "knowledge.document_id"
        ),
        document_version=_require_string(
            value["document_version"],
            "knowledge.document_version",
            maximum=128,
        ),
        section=_require_string(
            value["section"], "knowledge.section", maximum=256
        ),
        chunk_id=_require_local_id(value["chunk_id"], "knowledge.chunk_id"),
        data_classification=data_classification,
        acl_subjects=acl_subjects,
        effective_at=effective_at,
        expires_at=parsed_expires_at,
        content_summary=_require_string(
            value["content_summary"],
            "knowledge.content_summary",
            maximum=2048,
        ),
        content_hash=_require_sha256(
            value["content_hash"], "knowledge.content_hash"
        ),
    )


def _parse_reference_expectations(
    value: Mapping[str, Any],
    fixtures_by_case_id: Mapping[str, DomainPackFixture],
    knowledge_by_ref: Mapping[str, DomainKnowledgeSample],
) -> tuple[DomainReferenceExpectation, ...]:
    _require_exact_keys(
        value,
        {"schema_version", "cases"},
        "reference expectations",
    )
    if value["schema_version"] != (
        "flowpilot.domain-pack.reference-expectations.v1"
    ):
        raise _invalid_pack("reference expectations version is unsupported")
    entries = _require_mapping_list(value["cases"], "reference expectations")
    expectations: list[DomainReferenceExpectation] = []
    for entry in entries:
        _require_exact_keys(
            entry,
            {"case_id", "expected_citations", "excluded_source_refs"},
            "reference expectation",
        )
        citations = tuple(
            _parse_citation(item)
            for item in _require_mapping_list(
                entry["expected_citations"],
                "expected_citations",
            )
        )
        excluded = _require_string_list(
            entry["excluded_source_refs"],
            "excluded_source_refs",
            unique=True,
        )
        referenced = {
            citation.source_ref for citation in citations
        } | set(excluded)
        if not referenced <= set(knowledge_by_ref):
            raise _invalid_pack(
                "reference expectation points to an unknown knowledge sample"
            )
        if {citation.source_ref for citation in citations} & set(excluded):
            raise _invalid_pack(
                "reference expectation cannot include and exclude one source"
            )
        for citation in citations:
            sample = knowledge_by_ref[citation.source_ref]
            if (
                citation.document_version != sample.document_version
                or citation.section != sample.section
                or citation.content_hash != sample.content_hash
            ):
                raise _invalid_pack(
                    "citation expectation does not match the knowledge sample"
                )
        expectations.append(
            DomainReferenceExpectation(
                case_id=_require_local_id(
                    entry["case_id"], "reference expectation case_id"
                ),
                expected_citations=citations,
                excluded_source_refs=excluded,
            )
        )
    case_ids = [expectation.case_id for expectation in expectations]
    if set(case_ids) != set(fixtures_by_case_id) or len(case_ids) != len(
        set(case_ids)
    ):
        raise _invalid_pack(
            "reference expectations must cover every fixture case exactly"
        )
    for expectation in expectations:
        fixture = fixtures_by_case_id[expectation.case_id]
        if not fixture.expected_missing_fields and not expectation.expected_citations:
            raise _invalid_pack(
                "complete request fixtures must expect at least one citation"
            )
        if fixture.expected_missing_fields and expectation.expected_citations:
            raise _invalid_pack(
                "incomplete request fixtures cannot expect result citations"
            )
    return tuple(expectations)


def _parse_citation(value: Mapping[str, Any]) -> ResultCitation:
    _require_exact_keys(
        value,
        {"source_ref", "document_version", "section", "content_hash"},
        "citation",
    )
    try:
        return ResultCitation(
            source_ref=value["source_ref"],
            document_version=value["document_version"],
            section=value["section"],
            content_hash=value["content_hash"],
        )
    except (TypeError, ValueError) as exc:
        raise _invalid_pack("citation expectation is invalid") from exc


def _load_yaml_ref(root: Path, reference: str) -> Mapping[str, Any]:
    return _load_yaml_mapping(root, _resolve_reference(root, reference))


def _load_json_ref(root: Path, reference: str) -> Mapping[str, Any]:
    path = _resolve_reference(root, reference)
    raw = _read_bounded_text(path)
    try:
        parsed = json.loads(raw, object_pairs_hook=_unique_json_object)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise _invalid_pack("domain pack JSON is invalid") from exc
    return _require_mapping(parsed, "fixture")


def _load_yaml_mapping(root: Path, path: Path) -> Mapping[str, Any]:
    if not path.resolve(strict=False).is_relative_to(root):
        raise _invalid_pack("domain pack reference escapes its root")
    raw = _read_bounded_text(path)
    try:
        parsed = yaml.load(raw, Loader=_NoAliasSafeLoader)
    except ApplicationError:
        raise
    except (UnicodeError, yaml.YAMLError) as exc:
        raise _invalid_pack("domain pack YAML is invalid") from exc
    return _require_mapping(parsed, path.name)


def _resolve_reference(root: Path, reference: str) -> Path:
    candidate = (root / reference).resolve(strict=False)
    if not candidate.is_relative_to(root):
        raise _invalid_pack("domain pack reference escapes its root")
    return candidate


def _read_bounded_text(path: Path) -> str:
    try:
        if not path.is_file() or path.stat().st_size > MAX_DOMAIN_PACK_FILE_BYTES:
            raise _invalid_pack("domain pack file is missing or too large")
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise _invalid_pack("domain pack file could not be read") from exc


def _require_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise _invalid_pack(f"{field} must be an object with string keys")
    return value


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _invalid_pack("domain pack JSON keys must be unique")
        result[key] = value
    return result


def _require_mapping_list(value: Any, field: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list):
        raise _invalid_pack(f"{field} must be an array")
    return tuple(_require_mapping(item, field) for item in value)


def _require_string(value: Any, field: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise _invalid_pack(f"{field} must be a bounded non-empty string")
    return value


def _require_string_list(value: Any, field: str, *, unique: bool) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise _invalid_pack(f"{field} must be an array of strings")
    result = tuple(value)
    if unique and len(result) != len(set(result)):
        raise _invalid_pack(f"{field} must contain unique values")
    return result


def _require_local_id(value: Any, field: str) -> str:
    identifier = _require_string(value, field, maximum=64)
    if _IDENTIFIER_PATTERN.fullmatch(identifier) is None:
        raise _invalid_pack(f"{field} has an invalid format")
    return identifier


def _require_ref(value: Any, field: str, suffix: str) -> str:
    reference = _require_string(value, field, maximum=256)
    path = Path(reference)
    if path.is_absolute() or path.suffix != suffix:
        raise _invalid_pack(f"{field} must be a relative {suffix} path")
    return reference


def _require_sha256(value: Any, field: str) -> str:
    digest = _require_string(value, field, maximum=71)
    if re.fullmatch(r"^sha256:[a-f0-9]{64}$", digest) is None:
        raise _invalid_pack(f"{field} must be a lowercase sha256 digest")
    return digest


def _require_timestamp(value: Any, field: str) -> datetime:
    timestamp = _require_string(value, field, maximum=64)
    candidate = (
        timestamp[:-1] + "+00:00" if timestamp.endswith("Z") else timestamp
    )
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise _invalid_pack(f"{field} must be an RFC 3339 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _invalid_pack(f"{field} must be timezone-aware")
    return parsed.astimezone(UTC)


def _require_exact_keys(
    value: Mapping[str, Any], required: set[str], field: str
) -> None:
    if set(value) != required:
        raise _invalid_pack(f"{field} fields do not match the v1 boundary")


def _invalid_pack(message: str) -> ApplicationError:
    return ApplicationError(ErrorCode.DOMAIN_PACK_INVALID, message)
