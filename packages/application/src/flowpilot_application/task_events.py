from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

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
_APPROVAL_DECISIONS = frozenset(
    {"approved", "rejected", "expired", "revoked"}
)
_SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
_RFC3339_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$"
)
_SENSITIVE_KEY_FRAGMENTS = frozenset(
    {
        "apikey",
        "authorization",
        "chainofthought",
        "cookie",
        "credential",
        "password",
        "privatekey",
        "providersession",
        "reasoning",
        "secret",
        "sessionref",
        "token",
    }
)
_OPAQUE_REF_PATTERN = re.compile(
    r"^[A-Za-z][A-Za-z0-9+.-]*://[A-Za-z0-9][A-Za-z0-9._~:/+-]*$"
)
_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"(?i)\bbasic\s+[A-Za-z0-9+/=]{12,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|authorization|chain[_-]?of[_-]?thought|"
        r"cookie|credential|password|private[_-]?key|provider[_-]?session|"
        r"reasoning|secret|session[_-]?ref|token)\s*[:=]\s*\S+"
    ),
    re.compile(r"(?i)\b(?:sk|gh[pousr]|xox[baprs])[-_][A-Za-z0-9]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."
        r"[A-Za-z0-9_-]{8,}\b"
    ),
    re.compile(r"(?i)\b[A-Za-z][A-Za-z0-9+.-]*://[^\s/@:]+:[^\s/@]+@"),
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
        if (
            not isinstance(value, str)
            or len(value) < minimum
            or len(value) > maximum
        ):
            raise ValueError(f"{field} must be a bounded string")

    return validate


def _nullable(validator: _FieldValidator) -> _FieldValidator:
    def validate(value: object, field: str) -> None:
        if value is not None:
            validator(value, field)

    return validate


def _enum(values: frozenset[str]) -> _FieldValidator:
    def validate(value: object, field: str) -> None:
        if not isinstance(value, str) or value not in values:
            raise ValueError(f"{field} is not allowed by task-event.v1")

    return validate


def _literal(expected: str) -> _FieldValidator:
    def validate(value: object, field: str) -> None:
        if value != expected:
            raise ValueError(f"{field} must equal {expected}")

    return validate


def _pattern(pattern: str) -> _FieldValidator:
    compiled = re.compile(pattern)

    def validate(value: object, field: str) -> None:
        if not isinstance(value, str) or compiled.fullmatch(value) is None:
            raise ValueError(f"{field} has an invalid format")

    return validate


def _boolean(value: object, field: str) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")


def _sha256(value: object, field: str) -> None:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase sha256 digest")


def _rfc3339(value: object, field: str) -> None:
    if not isinstance(value, str) or _RFC3339_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field} must be an RFC 3339 date-time")
    normalized = value[:-1] + "+00:00" if value[-1:].casefold() == "z" else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{field} must be an RFC 3339 date-time") from exc
    if parsed.utcoffset() is None:
        raise ValueError(f"{field} must include an offset")


def _missing_fields(value: object, field: str) -> None:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
        raise ValueError(f"{field} must be an array")
    if not value:
        raise ValueError(f"{field} must not be empty")
    validated: list[str] = []
    for index, item in enumerate(value):
        _bounded_string(minimum=1, maximum=128)(item, f"{field}[{index}]")
        validated.append(item)
    if len(validated) != len(set(validated)):
        raise ValueError(f"{field} must contain unique items")


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
        raise ValueError("payload must be an object")
    assert_task_event_content_safe(payload, "payload")
    rule = TASK_EVENT_PAYLOAD_RULES.get(event_type)
    if rule is None:
        raise ValueError(f"{event_type} is not a task-event.v1 type")
    if producer not in rule.producers:
        raise ValueError(
            f"producer is not allowed for {event_type} by task-event.v1"
        )
    keys: set[str] = set()
    for key in payload:
        if not isinstance(key, str):
            raise ValueError("payload keys must be strings")
        keys.add(key)
    missing = rule.required - keys
    if missing:
        raise ValueError(
            "payload is missing required task-event.v1 fields: "
            + ", ".join(sorted(missing))
        )
    additional = keys - set(rule.fields)
    if additional:
        raise ValueError(
            "payload contains additional task-event.v1 fields: "
            + ", ".join(sorted(additional))
        )
    for field, value in payload.items():
        rule.fields[field](value, f"payload.{field}")
        if field.endswith("_ref") and isinstance(value, str) and value:
            validate_task_event_ref(value, f"payload.{field}")


def validate_task_event_ref(value: str, field: str) -> None:
    """Require a non-empty event reference to remain an opaque URI."""

    if _OPAQUE_REF_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field} must be an opaque URI reference")


def assert_task_event_content_safe(value: object, path: str) -> None:
    """Recursively reject sensitive keys and high-confidence secret values."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} keys must be strings")
            compact = "".join(
                character
                for character in key.casefold()
                if character.isalnum()
            )
            if any(fragment in compact for fragment in _SENSITIVE_KEY_FRAGMENTS):
                raise ValueError(f"{path} contains a sensitive key")
            assert_task_event_content_safe(item, f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for index, item in enumerate(value):
            assert_task_event_content_safe(item, f"{path}[{index}]")
        return
    if isinstance(value, str) and any(
        pattern.search(value) for pattern in _SENSITIVE_VALUE_PATTERNS
    ):
        raise ValueError(f"{path} contains sensitive value material")
