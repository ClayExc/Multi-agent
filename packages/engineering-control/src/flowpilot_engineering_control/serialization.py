"""Canonical JSON and digest helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

type JsonValue = object


def canonical_json_bytes(value: object) -> bytes:
    """Serialize JSON deterministically with a trailing newline."""

    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def string_list(values: Sequence[str]) -> list[JsonValue]:
    return list(values)


def string_map(values: Mapping[str, str]) -> dict[str, JsonValue]:
    return dict(sorted(values.items()))
