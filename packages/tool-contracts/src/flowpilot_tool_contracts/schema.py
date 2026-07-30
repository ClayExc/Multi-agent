from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Never

from flowpilot_domain import canonical_sha256

from .errors import ToolContractError, ToolContractErrorCode

type JsonScalar = str | int | float | bool | None
type FrozenJson = (
    JsonScalar | tuple["FrozenJson", ...] | Mapping[str, "FrozenJson"]
)
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

_TOOL_NAME = re.compile(
    r"^[a-z0-9]+(?:[._-][a-z0-9]+)*\.v[1-9][0-9]*$"
)
_SCHEMA_TYPES = frozenset(
    {"object", "array", "string", "integer", "number", "boolean", "null"}
)
_SCHEMA_KEYS = frozenset(
    {
        "additionalProperties",
        "const",
        "description",
        "enum",
        "items",
        "maxItems",
        "maxLength",
        "maxProperties",
        "maximum",
        "minItems",
        "minLength",
        "minProperties",
        "minimum",
        "pattern",
        "properties",
        "required",
        "type",
        "uniqueItems",
    }
)


def freeze_json(value: Any, field: str = "value") -> FrozenJson:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ToolContractError(
                ToolContractErrorCode.CONTRACT_INVALID,
                f"{field} contains a non-string key",
            )
        return MappingProxyType(
            {key: freeze_json(item, field) for key, item in value.items()}
        )
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return tuple(freeze_json(item, field) for item in value)
    raise ToolContractError(
        ToolContractErrorCode.CONTRACT_INVALID,
        f"{field} must contain JSON values",
    )


def thaw_json(value: FrozenJson) -> JsonValue:
    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


def _invalid_schema(message: str) -> Never:
    raise ToolContractError(ToolContractErrorCode.SCHEMA_INVALID, message)


def _validate_schema_definition(
    schema: Mapping[str, Any], *, path: str = "$"
) -> None:
    unknown = set(schema) - _SCHEMA_KEYS
    if unknown:
        _invalid_schema(f"tool schema contains an unsupported keyword at {path}")
    expected_type = schema.get("type")
    if not isinstance(expected_type, str) or expected_type not in _SCHEMA_TYPES:
        _invalid_schema(f"tool schema type is invalid at {path}")
    if expected_type == "object":
        if schema.get("additionalProperties") is not False:
            _invalid_schema(f"object schema must be closed at {path}")
        properties = schema.get("properties")
        required = schema.get("required", ())
        if not isinstance(properties, Mapping) or (
            not isinstance(required, Sequence)
            or isinstance(required, (str, bytes, bytearray))
            or any(not isinstance(item, str) for item in required)
            or len(set(required)) != len(required)
            or not set(required) <= set(properties)
        ):
            _invalid_schema(f"object schema fields are invalid at {path}")
        for key, child in properties.items():
            if not isinstance(key, str) or not isinstance(child, Mapping):
                _invalid_schema(f"property schema is invalid at {path}")
            _validate_schema_definition(child, path=f"{path}/{key}")
    elif "properties" in schema or "required" in schema:
        _invalid_schema(f"non-object schema contains object keywords at {path}")
    elif "additionalProperties" in schema:
        _invalid_schema(
            f"non-object schema contains additionalProperties at {path}"
        )
    if expected_type == "array":
        items = schema.get("items")
        if not isinstance(items, Mapping):
            _invalid_schema(f"array item schema is missing at {path}")
        _validate_schema_definition(items, path=f"{path}/*")
    elif "items" in schema:
        _invalid_schema(f"non-array schema contains items at {path}")
    pattern = schema.get("pattern")
    if pattern is not None:
        if not isinstance(pattern, str):
            _invalid_schema(f"schema pattern is invalid at {path}")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ToolContractError(
                ToolContractErrorCode.SCHEMA_INVALID,
                f"schema pattern cannot be compiled at {path}",
            ) from exc
    for key in (
        "maxItems",
        "maxLength",
        "maxProperties",
        "minItems",
        "minLength",
        "minProperties",
    ):
        bound = schema.get(key)
        if bound is not None and (
            isinstance(bound, bool) or not isinstance(bound, int) or bound < 0
        ):
            _invalid_schema(f"schema bound is invalid at {path}")
    for key in ("minimum", "maximum"):
        bound = schema.get(key)
        if bound is not None and (
            isinstance(bound, bool)
            or not isinstance(bound, (int, float))
            or not math.isfinite(bound)
        ):
            _invalid_schema(f"numeric schema bound is invalid at {path}")
    if (
        isinstance(schema.get("minimum"), (int, float))
        and isinstance(schema.get("maximum"), (int, float))
        and schema["minimum"] > schema["maximum"]
    ):
        _invalid_schema(f"schema bounds are reversed at {path}")
    if "enum" in schema:
        enum = schema["enum"]
        if (
            not isinstance(enum, Sequence)
            or isinstance(enum, (str, bytes, bytearray))
            or not enum
        ):
            _invalid_schema(f"schema enum is invalid at {path}")
        fingerprints = [
            canonical_sha256(thaw_json(freeze_json(item))) for item in enum
        ]
        if len(fingerprints) != len(set(fingerprints)):
            _invalid_schema(f"schema enum is not unique at {path}")
    unique_items = schema.get("uniqueItems")
    if unique_items is not None and not isinstance(unique_items, bool):
        _invalid_schema(f"uniqueItems must be boolean at {path}")


@dataclass(frozen=True, slots=True)
class ValidationFinding:
    path: str
    code: str


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, Mapping)
    if expected == "array":
        return isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        )
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
        )
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def validate_schema_value(
    value: Any,
    schema: Mapping[str, Any],
    *,
    path: str = "$",
) -> tuple[ValidationFinding, ...]:
    """Validate the closed JSON Schema subset used by M0 mock tools."""

    findings: list[ValidationFinding] = []
    expected_type = schema.get("type")
    accepted_types = (
        (expected_type,)
        if isinstance(expected_type, str)
        else tuple(expected_type or ())
    )
    if accepted_types and not any(
        _matches_type(value, item) for item in accepted_types
    ):
        return (ValidationFinding(path, "TYPE_MISMATCH"),)
    if "const" in schema and value != schema["const"]:
        findings.append(ValidationFinding(path, "CONST_MISMATCH"))
    if "enum" in schema and value not in schema["enum"]:
        findings.append(ValidationFinding(path, "ENUM_MISMATCH"))

    if isinstance(value, str):
        if len(value) < int(schema.get("minLength", 0)):
            findings.append(ValidationFinding(path, "STRING_TOO_SHORT"))
        maximum = schema.get("maxLength")
        if isinstance(maximum, int) and len(value) > maximum:
            findings.append(ValidationFinding(path, "STRING_TOO_LONG"))
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.fullmatch(pattern, value) is None:
            findings.append(ValidationFinding(path, "PATTERN_MISMATCH"))

    if isinstance(value, Mapping):
        required = schema.get("required", ())
        if isinstance(required, Sequence):
            for key in required:
                if key not in value:
                    findings.append(
                        ValidationFinding(f"{path}/{key}", "FIELD_REQUIRED")
                    )
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            findings.append(ValidationFinding(path, "SCHEMA_PROPERTIES_INVALID"))
            return tuple(findings)
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    findings.append(
                        ValidationFinding(
                            f"{path}/{key}", "ADDITIONAL_FIELD_FORBIDDEN"
                        )
                    )
        for key, child in value.items():
            child_schema = properties.get(key)
            if isinstance(child_schema, Mapping):
                findings.extend(
                    validate_schema_value(
                        child,
                        child_schema,
                        path=f"{path}/{key}",
                    )
                )
        minimum = schema.get("minProperties")
        maximum = schema.get("maxProperties")
        if isinstance(minimum, int) and len(value) < minimum:
            findings.append(ValidationFinding(path, "OBJECT_TOO_SMALL"))
        if isinstance(maximum, int) and len(value) > maximum:
            findings.append(ValidationFinding(path, "OBJECT_TOO_LARGE"))

    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if isinstance(minimum, int) and len(value) < minimum:
            findings.append(ValidationFinding(path, "ARRAY_TOO_SHORT"))
        if isinstance(maximum, int) and len(value) > maximum:
            findings.append(ValidationFinding(path, "ARRAY_TOO_LONG"))
        if schema.get("uniqueItems") is True:
            fingerprints = [
                canonical_sha256(thaw_json(freeze_json(item))) for item in value
            ]
            if len(fingerprints) != len(set(fingerprints)):
                findings.append(ValidationFinding(path, "ARRAY_NOT_UNIQUE"))
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                findings.extend(
                    validate_schema_value(
                        item,
                        item_schema,
                        path=f"{path}/{index}",
                    )
                )

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            findings.append(ValidationFinding(path, "NUMBER_NOT_FINITE"))
            return tuple(findings)
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            findings.append(ValidationFinding(path, "NUMBER_TOO_SMALL"))
        if isinstance(maximum, (int, float)) and value > maximum:
            findings.append(ValidationFinding(path, "NUMBER_TOO_LARGE"))
    return tuple(findings)


@dataclass(frozen=True, slots=True)
class ToolContract:
    name: str
    input_schema: Mapping[str, FrozenJson]
    output_schema: Mapping[str, FrozenJson]
    schema_hash: str

    def __post_init__(self) -> None:
        if _TOOL_NAME.fullmatch(self.name) is None:
            _invalid_schema("tool name is not a versioned identifier")
        for field, schema in (
            ("input_schema", self.input_schema),
            ("output_schema", self.output_schema),
        ):
            thawed = thaw_json(schema)
            if not isinstance(thawed, dict):
                _invalid_schema(f"{field} must be a JSON object")
            if thawed.get("type") != "object":
                _invalid_schema(f"{field} must be an object schema")
            _validate_schema_definition(thawed)
        projection = {
            "name": self.name,
            "input_schema": thaw_json(self.input_schema),
            "output_schema": thaw_json(self.output_schema),
        }
        if canonical_sha256(projection) != self.schema_hash:
            raise ToolContractError(
                ToolContractErrorCode.SCHEMA_HASH_MISMATCH,
                "tool schema hash does not match the registered schemas",
            )

    @classmethod
    def create(
        cls,
        *,
        name: str,
        input_schema: Mapping[str, Any],
        output_schema: Mapping[str, Any],
    ) -> ToolContract:
        if _TOOL_NAME.fullmatch(name) is None:
            raise ToolContractError(
                ToolContractErrorCode.SCHEMA_INVALID,
                "tool name is not a versioned identifier",
            )
        frozen_input = freeze_json(input_schema, "input_schema")
        frozen_output = freeze_json(output_schema, "output_schema")
        if not isinstance(frozen_input, Mapping) or not isinstance(
            frozen_output, Mapping
        ):
            raise ToolContractError(
                ToolContractErrorCode.SCHEMA_INVALID,
                "tool schemas must be JSON objects",
            )
        for schema in (frozen_input, frozen_output):
            thawed = thaw_json(schema)
            if not isinstance(thawed, dict):
                _invalid_schema("M0 tool schemas must be objects")
            if thawed.get("type") != "object":
                _invalid_schema("M0 tool schemas must describe objects")
            _validate_schema_definition(thawed)
        projection = {
            "name": name,
            "input_schema": thaw_json(frozen_input),
            "output_schema": thaw_json(frozen_output),
        }
        return cls(
            name=name,
            input_schema=frozen_input,
            output_schema=frozen_output,
            schema_hash=canonical_sha256(projection),
        )

    def validate_input(self, value: Mapping[str, Any]) -> None:
        findings = validate_schema_value(value, self.input_schema)
        if findings:
            raise ToolContractError(
                ToolContractErrorCode.INPUT_INVALID,
                f"tool input rejected at {findings[0].path}: "
                f"{findings[0].code}",
            )

    def validate_output(self, value: Mapping[str, Any]) -> None:
        findings = validate_schema_value(value, self.output_schema)
        if findings:
            raise ToolContractError(
                ToolContractErrorCode.OUTPUT_INVALID,
                f"tool output rejected at {findings[0].path}: "
                f"{findings[0].code}",
            )
