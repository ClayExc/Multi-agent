from .errors import SecurityError, SecurityErrorCode
from .models import (
    AuthenticatedWorkload,
    CapabilityHandle,
    CredentialBrokerPort,
    SecurityContextSource,
    TrustedSecurityContext,
)
from .safety import assert_safe_projection
from .verifier import SecurityVerifier

SECURITY_ADAPTER_PORT_VERSION = "flowpilot.security-adapter.m0.v1"

__all__ = [
    "AuthenticatedWorkload",
    "CapabilityHandle",
    "CredentialBrokerPort",
    "SecurityContextSource",
    "SecurityError",
    "SecurityErrorCode",
    "SecurityVerifier",
    "SECURITY_ADAPTER_PORT_VERSION",
    "TrustedSecurityContext",
    "assert_safe_projection",
]
