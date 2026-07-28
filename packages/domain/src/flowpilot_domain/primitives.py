from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from math import isfinite
from types import MappingProxyType
from typing import Any

from .errors import DomainErrorCode, DomainViolation

type JsonScalar = str | int | float | bool | None
type FrozenJson = (
    JsonScalar | tuple["FrozenJson", ...] | Mapping[str, "FrozenJson"]
)
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

MAX_SAFE_INTEGER = 2**53 - 1
SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")


def require_text(value: object, field: str, *, maximum: int) -> None:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise DomainViolation(
            DomainErrorCode.CONTRACT_VIOLATION,
            f"{field} must contain between 1 and {maximum} characters",
        )


def require_identifier(value: object, field: str, pattern: str) -> None:
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise DomainViolation(
            DomainErrorCode.CONTRACT_VIOLATION,
            f"{field} has an invalid format",
        )


def require_sha256(value: object, field: str) -> None:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise DomainViolation(
            DomainErrorCode.CONTRACT_VIOLATION,
            f"{field} must be a lowercase sha256 digest",
        )


def ensure_utc(value: object, field: str) -> datetime:
    if isinstance(value, str):
        candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                f"{field} must be an RFC 3339 timestamp",
            ) from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise DomainViolation(
            DomainErrorCode.CONTRACT_VIOLATION,
            f"{field} must be an RFC 3339 timestamp",
        )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DomainViolation(
            DomainErrorCode.CONTRACT_VIOLATION,
            f"{field} must be timezone-aware",
        )
    return parsed.astimezone(UTC)


def format_utc(value: datetime) -> str:
    normalized = ensure_utc(value, "timestamp")
    return normalized.isoformat().replace("+00:00", "Z")


def freeze_json(value: Any, field: str = "json") -> FrozenJson:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        if not -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                f"{field} contains an integer outside the I-JSON safe range",
            )
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                f"{field} contains a non-finite number",
            )
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                f"{field} object keys must be strings",
            )
        return MappingProxyType(
            {key: freeze_json(item, field) for key, item in value.items()}
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(freeze_json(item, field) for item in value)
    raise DomainViolation(
        DomainErrorCode.CONTRACT_VIOLATION,
        f"{field} contains a non-JSON value",
    )


def thaw_json(value: FrozenJson) -> JsonValue:
    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


def require_exact_keys(
    value: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str],
    field: str,
) -> None:
    keys = set(value)
    missing = required - keys
    extra = keys - required - optional
    if missing or extra:
        raise DomainViolation(
            DomainErrorCode.CONTRACT_VIOLATION,
            f"{field} fields do not match the v1 contract",
        )
