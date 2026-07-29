from __future__ import annotations

from enum import StrEnum


class ApiErrorCode(StrEnum):
    DEPENDENCY_UNAVAILABLE = "API_DEPENDENCY_UNAVAILABLE"
    REQUEST_IDENTITY_MISMATCH = "API_REQUEST_IDENTITY_MISMATCH"
    INTERNAL_ERROR = "API_INTERNAL_ERROR"


class ApiError(RuntimeError):
    def __init__(
        self,
        code: ApiErrorCode,
        safe_message: str,
        *,
        status_code: int,
        retryable: bool = False,
    ) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code
        self.retryable = retryable
