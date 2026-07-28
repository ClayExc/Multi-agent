"""Evidence safety checks shared by evaluation and observability code."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


class UnsafeEvidenceError(ValueError):
    """Raised when evidence contains raw secrets or forbidden reasoning."""


_FORBIDDEN_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "chain_of_thought",
    "client_secret",
    "credential",
    "hidden_reasoning",
    "password",
    "private_key",
    "raw_attachment",
    "raw_prompt",
    "refresh_token",
}

_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"(?i)\b(?:api[_-]?key|client[_-]?secret|password)\s*[:=]\s*\S+"),
)


def find_unsafe_evidence(value: Any, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower()
            child_path = f"{path}.{key}"
            if normalized in _FORBIDDEN_KEYS:
                findings.append(f"{child_path}: forbidden evidence field")
            findings.extend(find_unsafe_evidence(child, child_path))
        return findings
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            findings.extend(find_unsafe_evidence(child, f"{path}[{index}]"))
        return findings
    if isinstance(value, str):
        for pattern in _SECRET_PATTERNS:
            if pattern.search(value):
                findings.append(f"{path}: secret-like material detected")
                break
    return findings


def require_safe_evidence(value: Any) -> None:
    findings = find_unsafe_evidence(value)
    if findings:
        raise UnsafeEvidenceError("; ".join(findings))
