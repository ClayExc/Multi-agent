from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Protocol, cast

import jwt
from flowpilot_domain import (
    ActorType,
    AssuranceLevel,
    AuthenticationMethod,
    AuthenticationRef,
    DataClassification,
    SecurityContextRef,
)
from jwt import InvalidSignatureError, PyJWK, PyJWTError

from .context_integrity import (
    trusted_context_snapshot_hash,
    verify_trusted_context_integrity,
)
from .digests import require_sha256_digest
from .errors import SecurityError, SecurityErrorCode
from .models import AuthenticatedWorkload, TrustedSecurityContext, utc

_ASYMMETRIC_ALGORITHMS = frozenset(
    {
        "ES256",
        "ES384",
        "ES512",
        "PS256",
        "PS384",
        "PS512",
        "RS256",
        "RS384",
        "RS512",
    }
)
_SHA256_PREFIX = "sha256:"


def _sha256(value: str) -> str:
    return _SHA256_PREFIX + hashlib.sha256(value.encode("utf-8")).hexdigest()


def oidc_nonce_digest(
    *,
    issuer: str,
    authorized_party: str,
    nonce: str,
) -> str:
    if not issuer or not authorized_party or not nonce:
        raise ValueError("OIDC nonce binding fields must not be empty")
    return _sha256(issuer + "\x1f" + authorized_party + "\x1f" + nonce)


def _immutable_mapping(
    value: Mapping[str, str],
    *,
    field: str,
) -> Mapping[str, str]:
    copied = dict(value)
    if not copied or any(not key or not item for key, item in copied.items()):
        raise ValueError(f"{field} must contain non-empty mappings")
    return MappingProxyType(copied)


def _claim_at(claims: Mapping[str, object], path: tuple[str, ...]) -> object:
    current: object = claims
    for component in path:
        if not isinstance(current, Mapping) or component not in current:
            raise SecurityError(
                SecurityErrorCode.IDENTITY_CLAIMS_INVALID,
                "OIDC token is missing a required mapped claim",
            )
        current = current[component]
    return current


def _required_text(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise SecurityError(
            SecurityErrorCode.IDENTITY_CLAIMS_INVALID,
            "OIDC token contains an invalid text claim",
        )
    return value


def _claim_values(value: object) -> frozenset[str]:
    if isinstance(value, str):
        result = frozenset(item for item in value.split() if item)
    elif isinstance(value, (tuple, list)):
        result = frozenset(
            item for item in value if isinstance(item, str) and item
        )
        if len(result) != len(value):
            result = frozenset()
    else:
        result = frozenset()
    if not result:
        raise SecurityError(
            SecurityErrorCode.IDENTITY_CLAIMS_INVALID,
            "OIDC token contains an invalid collection claim",
        )
    return result


def _mapped_values(
    value: object,
    mapping: Mapping[str, str],
) -> frozenset[str]:
    presented = _claim_values(value)
    if not presented <= mapping.keys():
        raise SecurityError(
            SecurityErrorCode.IDENTITY_MAPPING_DENIED,
            "OIDC claim is not allowed by the server mapping",
        )
    return frozenset(mapping[item] for item in presented)


def _numeric_date(claims: Mapping[str, object], name: str) -> datetime:
    value = claims.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SecurityError(
            SecurityErrorCode.IDENTITY_CLAIMS_INVALID,
            "OIDC token contains an invalid time claim",
        )
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OSError, OverflowError, ValueError) as exc:
        raise SecurityError(
            SecurityErrorCode.IDENTITY_CLAIMS_INVALID,
            "OIDC token contains an invalid time claim",
        ) from exc


@dataclass(frozen=True, slots=True)
class OidcAudiencePolicy:
    issuer: str
    audience: str
    authorized_parties: frozenset[str]
    allowed_algorithms: frozenset[str] = frozenset({"RS256"})
    clock_skew_seconds: int = 0

    def __post_init__(self) -> None:
        if not self.issuer or not self.audience or not self.authorized_parties:
            raise ValueError("OIDC issuer, audience and azp allowlist are required")
        if (
            not self.allowed_algorithms
            or not self.allowed_algorithms <= _ASYMMETRIC_ALGORITHMS
        ):
            raise ValueError("OIDC algorithms must use an asymmetric allowlist")
        if self.clock_skew_seconds < 0 or self.clock_skew_seconds > 300:
            raise ValueError("OIDC clock skew must be within 0..300 seconds")


@dataclass(frozen=True, slots=True)
class UserClaimPolicy:
    token: OidcAudiencePolicy
    tenant_mapping: Mapping[str, str]
    role_mapping: Mapping[str, str]
    scope_mapping: Mapping[str, str]
    assurance_mapping: Mapping[str, AssuranceLevel]
    tenant_claim: tuple[str, ...] = ("tenant_id",)
    roles_claim: tuple[str, ...] = ("realm_access", "roles")
    scope_claim: tuple[str, ...] = ("scope",)
    assurance_claim: tuple[str, ...] = ("acr",)
    session_claim: tuple[str, ...] = ("sid",)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "tenant_mapping",
            _immutable_mapping(self.tenant_mapping, field="tenant_mapping"),
        )
        object.__setattr__(
            self,
            "role_mapping",
            _immutable_mapping(self.role_mapping, field="role_mapping"),
        )
        object.__setattr__(
            self,
            "scope_mapping",
            _immutable_mapping(self.scope_mapping, field="scope_mapping"),
        )
        assurance = dict(self.assurance_mapping)
        if not assurance or any(not key for key in assurance):
            raise ValueError("assurance_mapping must not be empty")
        object.__setattr__(self, "assurance_mapping", MappingProxyType(assurance))
        for path in (
            self.tenant_claim,
            self.roles_claim,
            self.scope_claim,
            self.assurance_claim,
            self.session_claim,
        ):
            if not path or any(not component for component in path):
                raise ValueError("OIDC claim paths must not be empty")


@dataclass(frozen=True, slots=True)
class WorkloadRegistration:
    issuer: str
    authorized_party: str
    subject_id: str
    agent_id: str
    agent_version: str
    principal_ref: str
    tenant_ids: frozenset[str]
    purposes: frozenset[str]
    allowed_tools: frozenset[str]

    def __post_init__(self) -> None:
        if not all(
            (
                self.authorized_party,
                self.issuer,
                self.subject_id,
                self.agent_id,
                self.agent_version,
                self.principal_ref,
                self.tenant_ids,
                self.purposes,
                self.allowed_tools,
            )
        ):
            raise ValueError("workload registration fields must not be empty")


@dataclass(frozen=True, slots=True)
class WorkloadClaimPolicy:
    token: OidcAudiencePolicy
    registrations: tuple[WorkloadRegistration, ...]

    def __post_init__(self) -> None:
        identities = tuple(
            (item.issuer, item.authorized_party, item.subject_id)
            for item in self.registrations
        )
        parties = frozenset(item.authorized_party for item in self.registrations)
        if not identities or len(identities) != len(set(identities)):
            raise ValueError("workload registrations must have unique identities")
        if any(item.issuer != self.token.issuer for item in self.registrations):
            raise ValueError("workload registrations must match the token issuer")
        if parties != self.token.authorized_parties:
            raise ValueError("workload registrations must equal the azp allowlist")


@dataclass(frozen=True, slots=True)
class VerifiedUserIdentity:
    issuer: str
    subject_id: str
    tenant_id: str
    authorized_party: str
    roles: frozenset[str]
    scopes: frozenset[str]
    assurance_level: AssuranceLevel
    session_id_hash: str
    token_hash: str
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if not all(
            (
                self.issuer,
                self.subject_id,
                self.tenant_id,
                self.authorized_party,
                self.roles,
                self.scopes,
            )
        ):
            raise ValueError("verified user identity fields must not be empty")
        require_sha256_digest(self.session_id_hash, "identity.session_id_hash")
        require_sha256_digest(self.token_hash, "identity.token_hash")
        issued = utc(self.issued_at, "identity.issued_at")
        expires = utc(self.expires_at, "identity.expires_at")
        if expires <= issued:
            raise ValueError("verified identity must expire after issuance")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)


@dataclass(frozen=True, slots=True)
class SecurityContextReference:
    context_id: str
    context_ref: str

    def __post_init__(self) -> None:
        if not self.context_id or not self.context_ref:
            raise ValueError("security context reference must not be empty")


@dataclass(frozen=True, slots=True)
class TrustedContextMappingPolicy:
    allowed_purposes: frozenset[str]
    data_classification_ceiling: DataClassification
    maximum_ttl_seconds: int

    def __post_init__(self) -> None:
        if not self.allowed_purposes:
            raise ValueError("trusted context purposes must not be empty")
        if self.maximum_ttl_seconds < 1 or self.maximum_ttl_seconds > 86400:
            raise ValueError("trusted context TTL must be within 1..86400 seconds")


class JwksSourcePort(Protocol):
    async def resolve(
        self,
        *,
        issuer: str,
        key_id: str,
        force_refresh: bool,
    ) -> Mapping[str, object] | None: ...


class NonceReplayGuardPort(Protocol):
    """Consumes only a server-issued nonce digest from a trusted session store.

    The implementation must reject unknown digests and atomically reject reuse.
    Browser fields and request-body values are never authoritative inputs.
    """

    async def consume(self, *, nonce_hash: str, expires_at: datetime) -> bool: ...


class WorkloadTokenVerifierPort(Protocol):
    async def verify_workload_token(
        self,
        token: str,
        *,
        now: datetime,
    ) -> AuthenticatedWorkload: ...


class RevocableSecurityContextSource(Protocol):
    async def resolve(self, context_ref: str) -> TrustedSecurityContext: ...

    async def store(self, context: TrustedSecurityContext) -> None: ...

    async def revoke(
        self,
        context_ref: str,
        *,
        revoked_at: datetime,
        reason_code: str,
    ) -> None: ...


class InMemorySecurityContextSource:
    """Deterministic local adapter for a revocable trusted context source."""

    def __init__(self) -> None:
        self._contexts: dict[str, TrustedSecurityContext] = {}

    async def resolve(self, context_ref: str) -> TrustedSecurityContext:
        context = self._contexts.get(context_ref)
        if context is None:
            raise SecurityError(
                SecurityErrorCode.CONTEXT_UNAVAILABLE,
                "trusted security context is unavailable",
            )
        verify_trusted_context_integrity(context)
        return context

    async def store(self, context: TrustedSecurityContext) -> None:
        verify_trusted_context_integrity(context)
        reference = context.context.context_ref
        existing = self._contexts.get(reference)
        if existing is not None and existing != context:
            raise SecurityError(
                SecurityErrorCode.CONTEXT_UNTRUSTED,
                "trusted security context reference already exists",
            )
        self._contexts[reference] = context

    async def revoke(
        self,
        context_ref: str,
        *,
        revoked_at: datetime,
        reason_code: str,
    ) -> None:
        utc(revoked_at, "context.revoked_at")
        if not reason_code:
            raise ValueError("context revocation reason code is required")
        context = await self.resolve(context_ref)
        self._contexts[context_ref] = replace(context, active=False)


class TrustedContextMapper:
    def __init__(self, policy: TrustedContextMappingPolicy) -> None:
        self._policy = policy

    def map_user(
        self,
        *,
        identity: VerifiedUserIdentity,
        reference: SecurityContextReference,
        purpose: str,
        now: datetime,
        ttl_seconds: int,
    ) -> TrustedSecurityContext:
        issued_at = utc(now, "context.issued_at")
        if purpose not in self._policy.allowed_purposes:
            raise SecurityError(
                SecurityErrorCode.PURPOSE_DENIED,
                "requested purpose is not allowed by the server mapping",
            )
        if ttl_seconds < 1 or ttl_seconds > self._policy.maximum_ttl_seconds:
            raise SecurityError(
                SecurityErrorCode.IDENTITY_MAPPING_DENIED,
                "security context TTL is not allowed by the server mapping",
            )
        expires_at = min(
            identity.expires_at,
            issued_at + timedelta(seconds=ttl_seconds),
        )
        if expires_at <= issued_at:
            raise SecurityError(
                SecurityErrorCode.IDENTITY_EXPIRED,
                "verified user identity is no longer active",
            )
        authentication = AuthenticationRef(
            method=AuthenticationMethod.OIDC,
            assurance_level=identity.assurance_level,
            session_id_hash=identity.session_id_hash,
        )
        context = SecurityContextRef(
            context_id=reference.context_id,
            context_ref=reference.context_ref,
            context_hash=trusted_context_snapshot_hash(
                context_id=reference.context_id,
                context_ref=reference.context_ref,
                tenant_id=identity.tenant_id,
                subject_id=identity.subject_id,
                subject_type=ActorType.USER,
                issuer=identity.issuer,
                authorized_party=identity.authorized_party,
                roles=identity.roles,
                scopes=identity.scopes,
                authentication=authentication,
                purpose=purpose,
                data_classification_ceiling=(
                    self._policy.data_classification_ceiling
                ),
                issued_at=issued_at,
                expires_at=expires_at,
                source_token_hash=identity.token_hash,
            ),
            tenant_id=identity.tenant_id,
            subject_id=identity.subject_id,
            subject_type=ActorType.USER,
            purpose=purpose,
            authentication=authentication,
            data_classification_ceiling=(
                self._policy.data_classification_ceiling
            ),
            issued_at=issued_at,
            expires_at=expires_at,
        )
        return TrustedSecurityContext(
            context=context,
            active=True,
            roles=identity.roles,
            scopes=identity.scopes,
            issuer=identity.issuer,
            authorized_party=identity.authorized_party,
            identity_token_hash=identity.token_hash,
        )


class OidcIdentityAdapter:
    def __init__(
        self,
        *,
        jwks: JwksSourcePort,
        nonces: NonceReplayGuardPort,
        users: UserClaimPolicy,
        workloads: WorkloadClaimPolicy,
    ) -> None:
        self._jwks = jwks
        self._nonces = nonces
        self._users = users
        self._workloads = workloads
        self._registrations = {
            (item.issuer, item.authorized_party, item.subject_id): item
            for item in workloads.registrations
        }

    async def verify_user_token(
        self,
        token: str,
        *,
        expected_nonce: str,
        now: datetime,
    ) -> VerifiedUserIdentity:
        if not token or not expected_nonce:
            raise SecurityError(
                SecurityErrorCode.IDENTITY_TOKEN_INVALID,
                "OIDC user token or nonce is missing",
            )
        claims = await self._decode(token, self._users.token, now=now)
        nonce = _required_text(claims.get("nonce"))
        if not hmac.compare_digest(nonce, expected_nonce):
            raise SecurityError(
                SecurityErrorCode.NONCE_REPLAY,
                "OIDC nonce is invalid or already used",
            )
        expires_at = _numeric_date(claims, "exp")
        binding_hash = oidc_nonce_digest(
            issuer=self._users.token.issuer,
            authorized_party=_required_text(claims.get("azp")),
            nonce=nonce,
        )
        try:
            consumed = await self._nonces.consume(
                nonce_hash=binding_hash,
                expires_at=expires_at,
            )
        except SecurityError:
            raise
        except Exception:
            raise SecurityError(
                SecurityErrorCode.IDENTITY_SOURCE_UNAVAILABLE,
                "OIDC nonce replay guard is unavailable",
            ) from None
        if not consumed:
            raise SecurityError(
                SecurityErrorCode.NONCE_REPLAY,
                "OIDC nonce is invalid or already used",
            )
        tenant_claim = _required_text(
            _claim_at(claims, self._users.tenant_claim)
        )
        tenant_id = self._users.tenant_mapping.get(tenant_claim)
        if tenant_id is None:
            raise SecurityError(
                SecurityErrorCode.IDENTITY_MAPPING_DENIED,
                "OIDC tenant is not allowed by the server mapping",
            )
        roles = _mapped_values(
            _claim_at(claims, self._users.roles_claim),
            self._users.role_mapping,
        )
        scopes = _mapped_values(
            _claim_at(claims, self._users.scope_claim),
            self._users.scope_mapping,
        )
        assurance_claim = _required_text(
            _claim_at(claims, self._users.assurance_claim)
        )
        assurance = self._users.assurance_mapping.get(assurance_claim)
        if assurance is None:
            raise SecurityError(
                SecurityErrorCode.IDENTITY_MAPPING_DENIED,
                "OIDC assurance is not allowed by the server mapping",
            )
        session_id = _required_text(
            _claim_at(claims, self._users.session_claim)
        )
        return VerifiedUserIdentity(
            issuer=self._users.token.issuer,
            subject_id=_required_text(claims.get("sub")),
            tenant_id=tenant_id,
            authorized_party=_required_text(claims.get("azp")),
            roles=roles,
            scopes=scopes,
            assurance_level=assurance,
            session_id_hash=_sha256(session_id),
            token_hash=_sha256(token),
            issued_at=_numeric_date(claims, "iat"),
            expires_at=expires_at,
        )

    async def verify_workload_token(
        self,
        token: str,
        *,
        now: datetime,
    ) -> AuthenticatedWorkload:
        if not token:
            raise SecurityError(
                SecurityErrorCode.IDENTITY_TOKEN_INVALID,
                "OIDC workload token is missing",
            )
        claims = await self._decode(token, self._workloads.token, now=now)
        party = _required_text(claims.get("azp"))
        subject = _required_text(claims.get("sub"))
        registration = self._registrations.get(
            (self._workloads.token.issuer, party, subject)
        )
        if registration is None:
            raise SecurityError(
                SecurityErrorCode.WORKLOAD_UNTRUSTED,
                "workload client is not registered",
            )
        return AuthenticatedWorkload(
            agent_id=registration.agent_id,
            agent_version=registration.agent_version,
            principal_ref=registration.principal_ref,
            audience=self._workloads.token.audience,
            tenant_ids=registration.tenant_ids,
            purposes=registration.purposes,
            allowed_tools=registration.allowed_tools,
            issued_at=_numeric_date(claims, "iat"),
            expires_at=_numeric_date(claims, "exp"),
            attested=True,
            issuer=self._workloads.token.issuer,
            authorized_party=party,
            subject_id=subject,
            credential_hash=_sha256(token),
        )

    async def _decode(
        self,
        token: str,
        policy: OidcAudiencePolicy,
        *,
        now: datetime,
    ) -> Mapping[str, object]:
        verified_now = utc(now, "identity.now")
        try:
            header = jwt.get_unverified_header(token)
        except PyJWTError:
            raise SecurityError(
                SecurityErrorCode.IDENTITY_TOKEN_INVALID,
                "OIDC token header is invalid",
            ) from None
        algorithm = header.get("alg")
        key_id = header.get("kid")
        if (
            not isinstance(algorithm, str)
            or algorithm not in policy.allowed_algorithms
            or not isinstance(key_id, str)
            or not key_id
        ):
            raise SecurityError(
                SecurityErrorCode.IDENTITY_TOKEN_INVALID,
                "OIDC token algorithm or key identifier is not allowed",
            )
        claims: Mapping[str, object] | None = None
        for force_refresh in (False, True):
            key = await self._resolve_key(
                issuer=policy.issuer,
                key_id=key_id,
                algorithm=algorithm,
                force_refresh=force_refresh,
            )
            if key is None:
                continue
            try:
                decoded = jwt.decode(
                    token,
                    key=key,
                    algorithms=sorted(policy.allowed_algorithms),
                    audience=policy.audience,
                    issuer=policy.issuer,
                    options={
                        "require": ["aud", "azp", "exp", "iat", "iss", "sub"],
                        "verify_exp": False,
                        "verify_iat": False,
                        "verify_nbf": False,
                    },
                )
            except InvalidSignatureError:
                if not force_refresh:
                    continue
                raise SecurityError(
                    SecurityErrorCode.IDENTITY_TOKEN_INVALID,
                    "OIDC token signature is invalid",
                ) from None
            except PyJWTError:
                raise SecurityError(
                    SecurityErrorCode.IDENTITY_TOKEN_INVALID,
                    "OIDC token claims or signature are invalid",
                ) from None
            if not isinstance(decoded, dict):
                raise SecurityError(
                    SecurityErrorCode.IDENTITY_TOKEN_INVALID,
                    "OIDC token claims are invalid",
                )
            claims = cast(dict[str, object], decoded)
            break
        if claims is None:
            raise SecurityError(
                SecurityErrorCode.IDENTITY_SOURCE_UNAVAILABLE,
                "OIDC signing key is unavailable",
            )
        party = _required_text(claims.get("azp"))
        if party not in policy.authorized_parties:
            raise SecurityError(
                SecurityErrorCode.IDENTITY_TOKEN_INVALID,
                "OIDC authorized party is not allowed",
            )
        issued_at = _numeric_date(claims, "iat")
        expires_at = _numeric_date(claims, "exp")
        not_before = (
            _numeric_date(claims, "nbf") if "nbf" in claims else issued_at
        )
        skew = timedelta(seconds=policy.clock_skew_seconds)
        if (
            issued_at > verified_now + skew
            or not_before > verified_now + skew
            or expires_at <= verified_now - skew
            or expires_at <= issued_at
        ):
            raise SecurityError(
                SecurityErrorCode.IDENTITY_EXPIRED,
                "OIDC token is not active at verification time",
            )
        return claims

    async def _resolve_key(
        self,
        *,
        issuer: str,
        key_id: str,
        algorithm: str,
        force_refresh: bool,
    ) -> PyJWK | None:
        try:
            mapping = await self._jwks.resolve(
                issuer=issuer,
                key_id=key_id,
                force_refresh=force_refresh,
            )
        except SecurityError:
            raise
        except Exception:
            raise SecurityError(
                SecurityErrorCode.IDENTITY_SOURCE_UNAVAILABLE,
                "OIDC signing key source is unavailable",
            ) from None
        if mapping is None:
            return None
        if (
            mapping.get("kid") != key_id
            or mapping.get("use", "sig") != "sig"
            or (
                "key_ops" in mapping
                and (
                    not isinstance(mapping["key_ops"], list)
                    or "verify" not in mapping["key_ops"]
                )
            )
            or mapping.get("alg", algorithm) != algorithm
        ):
            raise SecurityError(
                SecurityErrorCode.IDENTITY_TOKEN_INVALID,
                "OIDC signing key metadata is invalid",
            )
        try:
            return PyJWK.from_dict(dict(mapping), algorithm=algorithm)
        except (KeyError, TypeError, ValueError):
            raise SecurityError(
                SecurityErrorCode.IDENTITY_TOKEN_INVALID,
                "OIDC signing key is invalid",
            ) from None
