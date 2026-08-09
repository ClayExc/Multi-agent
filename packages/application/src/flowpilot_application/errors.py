from __future__ import annotations

import re
from enum import StrEnum

_SAFE_TASK_EVENT_PATH = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*|\[\d+\])*$")


class ErrorCode(StrEnum):
    CONTRACT_INVALID = "CORE_CONTRACT_INVALID"
    COMMAND_DIGEST_MISMATCH = "CORE_COMMAND_DIGEST_MISMATCH"
    SECURITY_BINDING_MISMATCH = "CORE_SECURITY_BINDING_MISMATCH"
    IDEMPOTENCY_CONFLICT = "CORE_IDEMPOTENCY_CONFLICT"
    COMMAND_ID_CONFLICT = "CORE_COMMAND_ID_CONFLICT"
    TASK_NOT_FOUND = "CORE_TASK_NOT_FOUND"
    TASK_ALREADY_EXISTS = "CORE_TASK_ALREADY_EXISTS"
    TASK_INITIALIZATION_PROTOCOL_ERROR = "CORE_TASK_INITIALIZATION_PROTOCOL_ERROR"
    TASK_VERSION_CONFLICT = "CORE_TASK_VERSION_CONFLICT"
    VERSION_SLOT_CONFLICT = "CORE_VERSION_SLOT_CONFLICT"
    INVALID_STATE_TRANSITION = "CORE_INVALID_STATE_TRANSITION"
    APPROVAL_BINDING_MISMATCH = "CORE_APPROVAL_BINDING_MISMATCH"
    APPROVAL_NOT_FOUND = "CORE_APPROVAL_NOT_FOUND"
    APPROVAL_CONFLICT = "CORE_APPROVAL_CONFLICT"
    APPROVAL_EXPIRED = "CORE_APPROVAL_EXPIRED"
    APPROVAL_DUTIES_VIOLATION = "CORE_APPROVAL_DUTIES_VIOLATION"
    EXECUTION_UNAVAILABLE = "CORE_EXECUTION_UNAVAILABLE"
    EXECUTION_PROTOCOL_ERROR = "CORE_EXECUTION_PROTOCOL_ERROR"
    REPOSITORY_UNAVAILABLE = "CORE_REPOSITORY_UNAVAILABLE"
    REPOSITORY_PROTOCOL_ERROR = "CORE_REPOSITORY_PROTOCOL_ERROR"
    DOMAIN_PACK_INVALID = "CORE_DOMAIN_PACK_INVALID"
    DOMAIN_PACK_CONFLICT = "CORE_DOMAIN_PACK_CONFLICT"
    DOMAIN_PACK_NOT_FOUND = "CORE_DOMAIN_PACK_NOT_FOUND"
    REQUEST_REFERENCE_NOT_FOUND = "CORE_REQUEST_REFERENCE_NOT_FOUND"
    REQUEST_REFERENCE_BINDING_MISMATCH = "CORE_REQUEST_REFERENCE_BINDING_MISMATCH"
    REQUEST_REFERENCE_TAMPERED = "CORE_REQUEST_REFERENCE_TAMPERED"
    REQUEST_REFERENCE_UNAVAILABLE = "CORE_REQUEST_REFERENCE_UNAVAILABLE"
    REQUEST_REFERENCE_PROTOCOL_ERROR = "CORE_REQUEST_REFERENCE_PROTOCOL_ERROR"
    RESULT_ARTIFACT_CONFLICT = "CORE_RESULT_ARTIFACT_CONFLICT"
    RESULT_ARTIFACT_TAMPERED = "CORE_RESULT_ARTIFACT_TAMPERED"
    RESULT_ARTIFACT_UNAVAILABLE = "CORE_RESULT_ARTIFACT_UNAVAILABLE"
    RESULT_ARTIFACT_PROTOCOL_ERROR = "CORE_RESULT_ARTIFACT_PROTOCOL_ERROR"


class TaskEventErrorCode(StrEnum):
    """Stable in-process codes for safe TaskEvent boundary failures."""

    INVALID_SHAPE = "CORE_TASK_EVENT_INVALID_SHAPE"
    SCHEMA_VIOLATION = "CORE_TASK_EVENT_SCHEMA_VIOLATION"
    MISSING_FIELDS = "CORE_TASK_EVENT_MISSING_FIELDS"
    ADDITIONAL_FIELDS = "CORE_TASK_EVENT_ADDITIONAL_FIELDS"
    PRODUCER_MISMATCH = "CORE_TASK_EVENT_PRODUCER_MISMATCH"
    INVALID_REFERENCE = "CORE_TASK_EVENT_INVALID_REFERENCE"
    SENSITIVE_PROJECTION = "CORE_TASK_EVENT_SENSITIVE_PROJECTION"
    INVALID_ROUTE = "CORE_TASK_EVENT_INVALID_ROUTE"
    TENANT_MISMATCH = "CORE_TASK_EVENT_TENANT_MISMATCH"


class TaskEventValidationError(ValueError):
    """TaskEvent failure containing only a code, count and structural path."""

    def __init__(
        self,
        code: TaskEventErrorCode,
        *,
        path: str,
        count: int = 1,
    ) -> None:
        safe_path = path if _SAFE_TASK_EVENT_PATH.fullmatch(path) else "task_event"
        safe_count = (
            count if isinstance(count, int) and not isinstance(count, bool) else 1
        )
        if safe_count < 1:
            safe_count = 1
        self.code = code
        self.path = safe_path
        self.count = safe_count
        self.safe_message = f"{code.value}; path={safe_path}; count={safe_count}"
        super().__init__(self.safe_message)


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
