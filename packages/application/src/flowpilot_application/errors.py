from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    CONTRACT_INVALID = "CORE_CONTRACT_INVALID"
    COMMAND_DIGEST_MISMATCH = "CORE_COMMAND_DIGEST_MISMATCH"
    SECURITY_BINDING_MISMATCH = "CORE_SECURITY_BINDING_MISMATCH"
    IDEMPOTENCY_CONFLICT = "CORE_IDEMPOTENCY_CONFLICT"
    COMMAND_ID_CONFLICT = "CORE_COMMAND_ID_CONFLICT"
    TASK_NOT_FOUND = "CORE_TASK_NOT_FOUND"
    TASK_ALREADY_EXISTS = "CORE_TASK_ALREADY_EXISTS"
    TASK_VERSION_CONFLICT = "CORE_TASK_VERSION_CONFLICT"
    VERSION_SLOT_CONFLICT = "CORE_VERSION_SLOT_CONFLICT"
    INVALID_STATE_TRANSITION = "CORE_INVALID_STATE_TRANSITION"
    APPROVAL_BINDING_MISMATCH = "CORE_APPROVAL_BINDING_MISMATCH"
    EXECUTION_UNAVAILABLE = "CORE_EXECUTION_UNAVAILABLE"
    EXECUTION_PROTOCOL_ERROR = "CORE_EXECUTION_PROTOCOL_ERROR"
    REPOSITORY_UNAVAILABLE = "CORE_REPOSITORY_UNAVAILABLE"


class ApplicationError(RuntimeError):
    """Stable application failure that is safe to map to an API response."""

    def __init__(
        self,
        code: ErrorCode,
        safe_message: str,
        *,
        retryable: bool = False,
        detail_ref: str | None = None,
    ) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.retryable = retryable
        self.detail_ref = detail_ref
