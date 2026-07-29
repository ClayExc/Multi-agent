from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

import yaml
from flowpilot_domain import CommandType, RiskLevel, TaskCommand

from .errors import ApplicationError, ErrorCode

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


@dataclass(frozen=True, slots=True)
class DomainPackDefinition:
    manifest: DomainPackManifest
    intents: tuple[DomainIntent, ...]
    required_fields: Mapping[str, tuple[str, ...]]
    risk_rules: tuple[DomainRiskRule, ...]
    fixtures: tuple[DomainPackFixture, ...]


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
    _require_exact_keys(
        manifest_data,
        {
            "schema_version",
            "domain_id",
            "version",
            "display_name",
            "intents_ref",
            "required_fields_ref",
            "risk_rules_ref",
            "fixture_refs",
        },
        "manifest",
    )
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
        )
        for reference in manifest.fixture_refs
    )
    if not fixtures:
        raise _invalid_pack("domain pack must declare at least one fixture")
    fixture_case_ids = [fixture.case_id for fixture in fixtures]
    if len(fixture_case_ids) != len(set(fixture_case_ids)):
        raise _invalid_pack("domain pack fixture case ids must be unique")
    return DomainPackDefinition(
        manifest=manifest,
        intents=intents,
        required_fields=required_fields,
        risk_rules=risk_rules,
        fixtures=fixtures,
    )


def _parse_manifest(value: Mapping[str, Any]) -> DomainPackManifest:
    if value["schema_version"] != "flowpilot.domain-pack.v1":
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
        schema_version="flowpilot.domain-pack.v1",
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
    value: Mapping[str, Any], domain_id: str, intent_ids: set[str]
) -> DomainPackFixture:
    _require_exact_keys(
        value,
        {"fixture_version", "case_id", "domain_id", "expected_intent", "command"},
        "fixture",
    )
    if value["fixture_version"] != "flowpilot.domain-pack.fixture.v1":
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
    return DomainPackFixture(
        case_id=_require_local_id(value["case_id"], "fixture.case_id"),
        expected_intent=expected_intent,
        command=command,
    )


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


def _require_exact_keys(
    value: Mapping[str, Any], required: set[str], field: str
) -> None:
    if set(value) != required:
        raise _invalid_pack(f"{field} fields do not match the v1 boundary")


def _invalid_pack(message: str) -> ApplicationError:
    return ApplicationError(ErrorCode.DOMAIN_PACK_INVALID, message)
