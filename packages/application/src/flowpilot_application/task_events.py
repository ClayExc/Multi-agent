from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from flowpilot_security import assert_no_secret_material

from .errors import TaskEventErrorCode, TaskEventValidationError

type _FieldValidator = Callable[[object, str], None]

_TASK_STATUSES = frozenset(
    {
        "RECEIVED",
        "RUNNABLE",
        "RUNNING",
        "WAITING_USER",
        "WAITING_APPROVAL",
        "VERIFYING",
        "COMPLETED",
        "CANCELLED",
        "ESCALATED",
        "FAILED",
    }
)
_TOOL_EXECUTION_STATUSES = frozenset(
    {
        "prepared",
        "running",
        "verified",
        "failed_retryable",
        "failed_final",
        "unknown",
    }
)
_APPROVAL_DECISIONS = frozenset({"approved", "rejected", "expired", "revoked"})
_SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
_RFC3339_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$"
)
_SENSITIVE_PROJECTION_KEY_FRAGMENTS = frozenset(
    {
        "chainofthought",
        "cookie",
        "providersession",
        "reasoning",
        "sessionref",
    }
)
_SENSITIVE_PROJECTION_VALUE_PATTERN = re.compile(
    r"(?i)\b(?:chain[_-]?of[_-]?thought|cookie|provider[_-]?session|"
    r"reasoning|session[_-]?ref)\s*[:=]\s*\S+"
)
_OPAQUE_REF_PATTERN = re.compile(
    r"^[A-Za-z][A-Za-z0-9+.-]*://[A-Za-z0-9][A-Za-z0-9._~:/+-]*$"
)


@dataclass(frozen=True, slots=True)
class TaskEventPayloadRule:
    """Exact in-process projection of one task-event.v1 payload branch."""

    producers: frozenset[str]
    required: frozenset[str]
    fields: Mapping[str, _FieldValidator]


def _rule(
    *,
    producers: set[str],
    required: set[str],
    fields: dict[str, _FieldValidator],
) -> TaskEventPayloadRule:
    return TaskEventPayloadRule(
        producers=frozenset(producers),
        required=frozenset(required),
        fields=MappingProxyType(fields),
    )


def _bounded_string(
    *,
    minimum: int = 0,
    maximum: int,
) -> _FieldValidator:
    def validate(value: object, field: str) -> None:
        if not isinstance(value, str) or len(value) < minimum or len(value) > maximum:
            raise TaskEventValidationError(
                TaskEventErrorCode.SCHEMA_VIOLATION,
                path=field,
            )

    return validate


def _nullable(validator: _FieldValidator) -> _FieldValidator:
    def validate(value: object, field: str) -> None:
        if value is not None:
            validator(value, field)

    return validate


def _enum(values: frozenset[str]) -> _FieldValidator:
    def validate(value: object, field: str) -> None:
        if not isinstance(value, str) or value not in values:
            raise TaskEventValidationError(
                TaskEventErrorCode.SCHEMA_VIOLATION,
                path=field,
            )

    return validate


def _literal(expected: str) -> _FieldValidator:
    def validate(value: object, field: str) -> None:
        if value != expected:
            raise TaskEventValidationError(
                TaskEventErrorCode.SCHEMA_VIOLATION,
                path=field,
            )

    return validate


def _pattern(pattern: str) -> _FieldValidator:
    compiled = re.compile(pattern)

    def validate(value: object, field: str) -> None:
        if not isinstance(value, str) or compiled.fullmatch(value) is None:
            raise TaskEventValidationError(
                TaskEventErrorCode.SCHEMA_VIOLATION,
                path=field,
            )

    return validate


def _boolean(value: object, field: str) -> None:
    if not isinstance(value, bool):
        raise TaskEventValidationError(
            TaskEventErrorCode.SCHEMA_VIOLATION,
            path=field,
        )


def _sha256(value: object, field: str) -> None:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise TaskEventValidationError(
            TaskEventErrorCode.SCHEMA_VIOLATION,
            path=field,
        )


def _rfc3339(value: object, field: str) -> None:
    if not isinstance(value, str) or _RFC3339_PATTERN.fullmatch(value) is None:
        raise TaskEventValidationError(
            TaskEventErrorCode.SCHEMA_VIOLATION,
            path=field,
        )
    normalized = value[:-1] + "+00:00" if value[-1:].casefold() == "z" else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise TaskEventValidationError(
            TaskEventErrorCode.SCHEMA_VIOLATION,
            path=field,
        ) from None
    if parsed.utcoffset() is None:
        raise TaskEventValidationError(
            TaskEventErrorCode.SCHEMA_VIOLATION,
            path=field,
        )


def _missing_fields(value: object, field: str) -> None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TaskEventValidationError(
            TaskEventErrorCode.SCHEMA_VIOLATION,
            path=field,
        )
    if not value:
        raise TaskEventValidationError(
            TaskEventErrorCode.SCHEMA_VIOLATION,
            path=field,
        )
    validated: list[str] = []
    for index, item in enumerate(value):
        _bounded_string(minimum=1, maximum=128)(item, f"{field}[{index}]")
        validated.append(item)
    if len(validated) != len(set(validated)):
        raise TaskEventValidationError(
            TaskEventErrorCode.SCHEMA_VIOLATION,
            path=field,
        )


TASK_EVENT_PAYLOAD_RULES: Mapping[str, TaskEventPayloadRule] = MappingProxyType(
    {
        "task.created.v1": _rule(
            producers={"worker"},
            required={"status", "task_ref"},
            fields={
                "status": _literal("RECEIVED"),
                "task_ref": _bounded_string(minimum=1, maximum=512),
            },
        ),
        "task.status.changed.v1": _rule(
            producers={"worker"},
            required={"from", "to", "reason_code"},
            fields={
                "from": _enum(_TASK_STATUSES),
                "to": _enum(_TASK_STATUSES),
                "reason_code": _nullable(_bounded_string(maximum=128)),
            },
        ),
        "task.input.required.v1": _rule(
            producers={"worker"},
            required={"request_id", "prompt_ref", "missing_fields"},
            fields={
                "request_id": _bounded_string(minimum=1, maximum=256),
                "prompt_ref": _bounded_string(minimum=1, maximum=512),
                "missing_fields": _missing_fields,
            },
        ),
        "task.approval.required.v1": _rule(
            producers={"worker"},
            required={
                "approval_id",
                "action_digest",
                "display_ref",
                "expires_at",
            },
            fields={
                "approval_id": _pattern(r"^apr_[A-Za-z0-9_-]{8,128}$"),
                "action_digest": _sha256,
                "display_ref": _bounded_string(minimum=1, maximum=512),
                "expires_at": _rfc3339,
            },
        ),
        "task.approval.decided.v1": _rule(
            producers={"approval_service"},
            required={"approval_id", "action_digest", "decision"},
            fields={
                "approval_id": _pattern(r"^apr_[A-Za-z0-9_-]{8,128}$"),
                "action_digest": _sha256,
                "decision": _enum(_APPROVAL_DECISIONS),
            },
        ),
        "task.tool_execution.updated.v1": _rule(
            producers={"mcp_gateway", "reconciler"},
            required={"execution_id", "status"},
            fields={
                "execution_id": _pattern(r"^tex_[A-Za-z0-9_-]{8,128}$"),
                "status": _enum(_TOOL_EXECUTION_STATUSES),
            },
        ),
        "task.completed.v1": _rule(
            producers={"worker"},
            required={"result_ref"},
            fields={
                "result_ref": _bounded_string(minimum=1, maximum=512),
            },
        ),
        "task.failed.v1": _rule(
            producers={"worker"},
            required={"error_code", "retryable"},
            fields={
                "error_code": _bounded_string(minimum=1, maximum=128),
                "retryable": _boolean,
                "detail_ref": _nullable(_bounded_string(maximum=512)),
            },
        ),
        "task.escalated.v1": _rule(
            producers={"worker"},
            required={"reason_code"},
            fields={
                "reason_code": _bounded_string(minimum=1, maximum=128),
                "handoff_ref": _nullable(_bounded_string(maximum=512)),
            },
        ),
    }
)
TASK_EVENT_PRODUCERS = frozenset(
    producer
    for rule in TASK_EVENT_PAYLOAD_RULES.values()
    for producer in rule.producers
)


def validate_task_event_payload(
    event_type: str,
    producer: str,
    payload: object,
) -> None:
    """Execute the exact task-event.v1 payload and producer branch."""

    if not isinstance(payload, Mapping):
        raise TaskEventValidationError(
            TaskEventErrorCode.INVALID_SHAPE,
            path="payload",
        )
    assert_task_event_content_safe(payload, "payload")
    rule = TASK_EVENT_PAYLOAD_RULES.get(event_type)
    if rule is None:
        raise TaskEventValidationError(
            TaskEventErrorCode.SCHEMA_VIOLATION,
            path="envelope.event_type",
        )
    if producer not in rule.producers:
        raise TaskEventValidationError(
            TaskEventErrorCode.PRODUCER_MISMATCH,
            path="envelope.producer",
        )
    keys: set[str] = set()
    for index, key in enumerate(payload):
        if not isinstance(key, str):
            raise TaskEventValidationError(
                TaskEventErrorCode.INVALID_SHAPE,
                path=f"payload.keys[{index}]",
            )
        keys.add(key)
    missing = rule.required - keys
    if missing:
        raise TaskEventValidationError(
            TaskEventErrorCode.MISSING_FIELDS,
            path="payload",
            count=len(missing),
        )
    additional = keys - set(rule.fields)
    if additional:
        raise TaskEventValidationError(
            TaskEventErrorCode.ADDITIONAL_FIELDS,
            path="payload",
            count=len(additional),
        )
    for index, (field, validator) in enumerate(rule.fields.items()):
        if field not in payload:
            continue
        value = payload[field]
        structural_path = f"payload.fields[{index}]"
        validator(value, structural_path)
        if field.endswith("_ref") and isinstance(value, str) and value:
            validate_task_event_ref(value, structural_path)


def validate_task_event_ref(value: str, field: str) -> None:
    """Require a non-empty event reference to remain an opaque URI."""

    if _OPAQUE_REF_PATTERN.fullmatch(value) is None:
        raise TaskEventValidationError(
            TaskEventErrorCode.INVALID_REFERENCE,
            path=field,
        )


def assert_task_event_content_safe(value: object, path: str) -> None:
    """Reject hidden projection fields and centralized credential families."""

    assert_no_secret_material(value, field=path)
    _assert_no_sensitive_projection_content(value, path)


def _assert_no_sensitive_projection_content(value: object, path: str) -> None:
    """Keep non-credential session/reasoning fields out of Task Events."""

    if isinstance(value, Mapping):
        for index, (key, item) in enumerate(value.items()):
            if not isinstance(key, str):
                raise TaskEventValidationError(
                    TaskEventErrorCode.INVALID_SHAPE,
                    path=f"{path}.keys[{index}]",
                )
            compact = "".join(
                character for character in key.casefold() if character.isalnum()
            )
            if any(
                fragment in compact for fragment in _SENSITIVE_PROJECTION_KEY_FRAGMENTS
            ):
                raise TaskEventValidationError(
                    TaskEventErrorCode.SENSITIVE_PROJECTION,
                    path=f"{path}.keys[{index}]",
                )
            _assert_no_sensitive_projection_content(
                item,
                f"{path}.values[{index}]",
            )
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _assert_no_sensitive_projection_content(item, f"{path}[{index}]")
        return
    if isinstance(value, str) and (
        _SENSITIVE_PROJECTION_VALUE_PATTERN.search(value) is not None
    ):
        raise TaskEventValidationError(
            TaskEventErrorCode.SENSITIVE_PROJECTION,
            path=path,
        )
