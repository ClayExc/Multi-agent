"""Canonical JSON helpers used by offline acceptance artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def load_json_strict(path: Path) -> Any:
    """Load UTF-8 JSON and reject duplicate object keys."""

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key in {path}: {key}")
            result[key] = value
        return result

    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicates,
    )


def rfc8785_bytes(value: Any) -> bytes:
    """Encode the integer-only I-JSON profile used by the rc2 baseline."""

    def encode(item: Any) -> str:
        if item is None:
            return "null"
        if item is True:
            return "true"
        if item is False:
            return "false"
        if isinstance(item, int):
            if not -(2**53 - 1) <= item <= 2**53 - 1:
                raise ValueError("integer exceeds the I-JSON safe range")
            return str(item)
        if isinstance(item, float):
            raise ValueError("floating-point values require a full RFC 8785 library")
        if isinstance(item, str):
            return json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        if isinstance(item, list):
            return "[" + ",".join(encode(child) for child in item) + "]"
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ValueError("JSON object keys must be strings")
            keys = sorted(
                item,
                key=lambda key: key.encode("utf-16-be", errors="strict"),
            )
            return (
                "{"
                + ",".join(f"{encode(key)}:{encode(item[key])}" for key in keys)
                + "}"
            )
        raise ValueError(f"unsupported canonical JSON type: {type(item)!r}")

    return encode(value).encode("utf-8", errors="strict")


def canonical_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(rfc8785_bytes(value)).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def portable_bytes_error(path: Path) -> str | None:
    value = path.read_bytes()
    if value.startswith(b"\xef\xbb\xbf"):
        return "UTF-8 BOM is forbidden"
    if b"\r" in value:
        return "hashed sources must use LF line endings"
    try:
        value.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return "source is not valid UTF-8"
    return None


def stable_json_bytes(value: Any) -> bytes:
    """Return deterministic, readable UTF-8 JSON with an LF terminator."""

    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            separators=(",", ": "),
        )
        + "\n"
    ).encode("utf-8")
