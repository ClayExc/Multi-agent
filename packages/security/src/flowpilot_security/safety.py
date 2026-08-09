from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .credentials import _safe_root_path, assert_no_secret_material
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


def _assert_safe_projection_fields(value: Any, *, field: str) -> None:
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
            _assert_safe_projection_fields(child, field=field)
        return
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for child in value:
            _assert_safe_projection_fields(child, field=field)


def assert_safe_projection(value: Any, *, field: str = "projection") -> None:
    """Compatibility wrapper for projection fields and credential material."""

    safe_field = _safe_root_path(field)
    _assert_safe_projection_fields(value, field=safe_field)
    assert_no_secret_material(value, field=safe_field)
