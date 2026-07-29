from __future__ import annotations

from enum import StrEnum


class ContextErrorCode(StrEnum):
    INVALID_CONTEXT = "CONTEXT_INVALID"
    SECURITY_BINDING_MISMATCH = "CONTEXT_SECURITY_BINDING_MISMATCH"
    SECURITY_CONTEXT_EXPIRED = "CONTEXT_SECURITY_CONTEXT_EXPIRED"
    CLASSIFICATION_DENIED = "CONTEXT_CLASSIFICATION_DENIED"
    BUDGET_EXHAUSTED = "CONTEXT_BUDGET_EXHAUSTED"
    HANDOFF_DENIED = "CONTEXT_HANDOFF_DENIED"


class ContextError(ValueError):
    def __init__(self, code: ContextErrorCode, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
