from __future__ import annotations

from enum import StrEnum


class PersistenceErrorCode(StrEnum):
    TENANT_REQUIRED = "DATA_TENANT_REQUIRED"
    TENANT_MISMATCH = "DATA_TENANT_MISMATCH"
    NOT_FOUND = "DATA_NOT_FOUND"
    CONFLICT = "DATA_CONFLICT"
    IDEMPOTENCY_CONFLICT = "DATA_IDEMPOTENCY_CONFLICT"
    VERSION_CONFLICT = "DATA_VERSION_CONFLICT"
    INVALID_TRANSITION = "DATA_INVALID_TRANSITION"
    RECONCILIATION_REQUIRED = "DATA_RECONCILIATION_REQUIRED"
    LEASE_UNAVAILABLE = "DATA_LEASE_UNAVAILABLE"
    LEASE_LOST = "DATA_LEASE_LOST"
    STALE_FENCE = "DATA_STALE_FENCE"
    SECRET_MATERIAL = "DATA_SECRET_MATERIAL"
    DRIVER_PROTOCOL = "DATA_DRIVER_PROTOCOL"


class PersistenceError(RuntimeError):
    """Stable persistence failure without driver or secret details."""

    def __init__(
        self,
        code: PersistenceErrorCode,
        safe_message: str,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.retryable = retryable
