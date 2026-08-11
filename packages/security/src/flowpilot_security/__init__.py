from .context_integrity import (
    trusted_context_snapshot_hash,
    verify_trusted_context_integrity,
)
from .credentials import (
    CREDENTIAL_FAMILIES,
    CredentialFamily,
    SecretFinding,
    assert_no_secret_material,
    scan_secret_material,
)
from .digests import require_sha256_digest
from .errors import SecurityError, SecurityErrorCode
from .identity import (
    InMemorySecurityContextSource,
    JwksSourcePort,
    NonceReplayGuardPort,
    OidcAudiencePolicy,
    OidcIdentityAdapter,
    RevocableSecurityContextSource,
    SecurityContextReference,
    TrustedContextMapper,
    TrustedContextMappingPolicy,
    UserClaimPolicy,
    VerifiedUserIdentity,
    WorkloadClaimPolicy,
    WorkloadRegistration,
    WorkloadTokenVerifierPort,
    oidc_nonce_digest,
)
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
    "CREDENTIAL_FAMILIES",
    "CredentialFamily",
    "CredentialBrokerPort",
    "InMemorySecurityContextSource",
    "JwksSourcePort",
    "NonceReplayGuardPort",
    "OidcAudiencePolicy",
    "OidcIdentityAdapter",
    "oidc_nonce_digest",
    "RevocableSecurityContextSource",
    "SecurityContextSource",
    "SecurityError",
    "SecurityErrorCode",
    "SecurityVerifier",
    "SecurityContextReference",
    "SecretFinding",
    "SECURITY_ADAPTER_PORT_VERSION",
    "TrustedSecurityContext",
    "TrustedContextMapper",
    "TrustedContextMappingPolicy",
    "UserClaimPolicy",
    "VerifiedUserIdentity",
    "WorkloadClaimPolicy",
    "WorkloadRegistration",
    "WorkloadTokenVerifierPort",
    "assert_no_secret_material",
    "assert_safe_projection",
    "scan_secret_material",
    "require_sha256_digest",
    "trusted_context_snapshot_hash",
    "verify_trusted_context_integrity",
]
