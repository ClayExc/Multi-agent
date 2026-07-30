from __future__ import annotations

from enum import StrEnum


class PolicyErrorCode(StrEnum):
    UNAVAILABLE = "PLATFORM_POLICY_UNAVAILABLE"
    INVALID = "PLATFORM_POLICY_INVALID"
    INPUT_HASH_MISMATCH = "PLATFORM_POLICY_INPUT_HASH_MISMATCH"
    DENIED = "PLATFORM_POLICY_DENIED"
    EXPIRED = "PLATFORM_POLICY_EXPIRED"
    BINDING_MISMATCH = "PLATFORM_POLICY_BINDING_MISMATCH"
    OBLIGATION_UNSUPPORTED = "PLATFORM_OBLIGATION_UNSUPPORTED"
    OBLIGATION_CONFLICT = "PLATFORM_OBLIGATION_CONFLICT"
    MFA_REQUIRED = "PLATFORM_MFA_REQUIRED"
    PROVIDER_RESTRICTED = "PLATFORM_PROVIDER_RESTRICTED"
    APPROVAL_REQUIRED = "PLATFORM_APPROVAL_REQUIRED"
    APPROVAL_INVALID = "PLATFORM_APPROVAL_INVALID"
    APPROVAL_EXPIRED = "PLATFORM_APPROVAL_EXPIRED"
    SEPARATION_OF_DUTIES = "PLATFORM_SEPARATION_OF_DUTIES"


class PolicyError(RuntimeError):
    def __init__(
        self,
        code: PolicyErrorCode,
        safe_message: str,
        *,
        reason_codes: tuple[str, ...] = (),
    ) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.reason_codes = reason_codes or (code.value,)
