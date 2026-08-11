from __future__ import annotations

import re

_SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")


def require_sha256_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase sha256 digest")
    return value
