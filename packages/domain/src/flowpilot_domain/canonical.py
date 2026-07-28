from __future__ import annotations

import hashlib
from typing import Any

import rfc8785

from .errors import DomainErrorCode, DomainViolation


def canonical_sha256(value: Any) -> str:
    try:
        canonical = rfc8785.dumps(value)
    except (rfc8785.FloatDomainError, rfc8785.IntegerDomainError) as exc:
        raise DomainViolation(
            DomainErrorCode.CONTRACT_VIOLATION,
            "value cannot be represented by the RFC 8785 I-JSON profile",
        ) from exc
    return "sha256:" + hashlib.sha256(canonical).hexdigest()
