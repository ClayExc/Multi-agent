from __future__ import annotations

from enum import StrEnum


class ApiErrorCode(StrEnum):
    DEPENDENCY_UNAVAILABLE = "API_DEPENDENCY_UNAVAILABLE"
    AUTHENTICATION_REQUIRED = "API_AUTHENTICATION_REQUIRED"
    AUTHENTICATION_INVALID = "API_AUTHENTICATION_INVALID"
    AUTHORIZATION_DENIED = "API_AUTHORIZATION_DENIED"
    AUTH_FLOW_INVALID = "API_AUTH_FLOW_INVALID"
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
