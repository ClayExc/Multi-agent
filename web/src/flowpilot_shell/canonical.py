"""RFC 8785 (JCS) canonicalization for the shell's command digest.

The FlowPilot domain computes command digests with ``rfc8785.dumps`` +
SHA-256. This stdlib-only implementation is bit-compatible for the I-JSON
profile used by the v1 contracts (no floats, no non-BMP characters); an
interop test in tests/experience proves equality against
``flowpilot_domain.canonical.canonical_sha256`` so the replaceable shell
never depends on the domain package.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_bytes(value: Any) -> bytes:
    """RFC 8785 canonical JSON bytes for the I-JSON profile."""

    def encode(item: Any) -> str:
        if item is None:
            return "null"
        if item is True:
            return "true"
        if item is False:
            return "false"
        if isinstance(item, int):
            if isinstance(item, bool) or not -(2**53 - 1) <= item <= 2**53 - 1:
                raise ValueError("RFC 8785 integer exceeds the I-JSON range")
            return str(item)
        if isinstance(item, float):
            raise ValueError("RFC 8785 I-JSON profile rejects floats")
        if isinstance(item, str):
            return json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        if isinstance(item, list):
            return "[" + ",".join(encode(child) for child in item) + "]"
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ValueError("RFC 8785 object keys must be strings")
            ordered = sorted(
                item, key=lambda key: key.encode("utf-16-be", errors="strict")
            )
            return (
                "{"
                + ",".join(f"{encode(key)}:{encode(item[key])}" for key in ordered)
                + "}"
            )
        raise ValueError(f"unsupported RFC 8785 value type: {type(item)!r}")

    return encode(value).encode("utf-8", errors="strict")


def canonical_digest(value: Any) -> str:
    """``sha256:<hex>`` digest over the canonical JSON of ``value``."""
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()
