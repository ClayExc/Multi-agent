from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import SecurityError, SecurityErrorCode

_FORBIDDEN_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "chain_of_thought",
        "context",
        "cookie",
        "credential",
        "hidden_reasoning",
        "messages",
        "password",
        "payload",
        "private_key",
        "prompt",
        "raw",
        "reasoning",
        "refresh_token",
        "secret",
        "session_token",
        "tool_arguments",
        "tool_output",
    }
)
_SECRET_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:api[_-]?key|password|secret)\s*[:=]\s*\S+"),
    re.compile(r"(?i)\b(?:sk|ghp|xox[baprs])[-_][A-Za-z0-9]{16,}"),
)


def _forbidden_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    return normalized in _FORBIDDEN_KEYS or normalized.endswith(
        (
            "_access_token",
            "_api_key",
            "_authorization",
            "_chain_of_thought",
            "_credential",
            "_hidden_reasoning",
            "_password",
            "_private_key",
            "_prompt",
            "_refresh_token",
            "_secret",
            "_session_token",
        )
    )


def assert_safe_projection(value: Any, *, field: str = "projection") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise SecurityError(
                    SecurityErrorCode.UNSAFE_PROJECTION,
                    f"{field} contains a non-string key",
                )
            if _forbidden_key(key):
                raise SecurityError(
                    SecurityErrorCode.UNSAFE_PROJECTION,
                    f"{field} contains a forbidden field",
                )
            assert_safe_projection(child, field=field)
        return
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for child in value:
            assert_safe_projection(child, field=field)
        return
    if isinstance(value, str) and any(
        pattern.search(value) for pattern in _SECRET_PATTERNS
    ):
        raise SecurityError(
            SecurityErrorCode.UNSAFE_PROJECTION,
            f"{field} contains secret-like material",
        )
