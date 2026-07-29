from __future__ import annotations

from enum import StrEnum


class DomainErrorCode(StrEnum):
    CONTRACT_VIOLATION = "CORE_CONTRACT_VIOLATION"
    DIGEST_MISMATCH = "CORE_COMMAND_DIGEST_MISMATCH"
    SECURITY_BINDING_MISMATCH = "CORE_SECURITY_BINDING_MISMATCH"
    INVALID_STATE = "CORE_INVALID_TASK_STATE"
    INVALID_TRANSITION = "CORE_INVALID_STATE_TRANSITION"
    APPROVAL_BINDING_MISMATCH = "CORE_APPROVAL_BINDING_MISMATCH"


class DomainViolation(ValueError):
    """A deterministic domain rejection with a stable, non-sensitive code."""

    def __init__(self, code: DomainErrorCode, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
