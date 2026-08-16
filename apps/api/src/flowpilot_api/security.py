from __future__ import annotations

import hmac
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from fastapi import Request
from flowpilot_domain import ActorType, SecurityContextRef, TaskCommand
from flowpilot_security import (
    SecurityContextSource,
    SecurityError,
    SecurityErrorCode,
    SecurityVerifier,
    TrustedSecurityContext,
)

from .errors import ApiError, ApiErrorCode

_FORBIDDEN_IDENTITY_HEADERS = frozenset(
    {
        "x-data-classification",
        "x-flowpilot-security-context",
        "x-flowpilot-tenant",
        "x-purpose",
        "x-role",
        "x-roles",
        "x-security-context",
        "x-security-context-ref",
        "x-subject-id",
        "x-tenant-id",
    }
)


@dataclass(frozen=True, slots=True)
class TrustedRequestIdentity:
    tenant_id: str
    subject_id: str
    subject_type: ActorType
    purpose: str
    security_context_id: str
    security_context_ref: str
    security_context_hash: str
    security_context: SecurityContextRef | None = None
    roles: frozenset[str] = frozenset()
    scopes: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.security_context is None:
            return
        context = self.security_context
        if (
            self.tenant_id != context.tenant_id
            or self.subject_id != context.subject_id
            or self.subject_type is not context.subject_type
            or self.purpose != context.purpose
            or self.security_context_id != context.context_id
            or self.security_context_ref != context.context_ref
            or self.security_context_hash != context.context_hash
        ):
            raise ValueError("trusted request identity does not match its context")


@dataclass(frozen=True, slots=True)
class GovernanceAccessPolicy:
    """Composition-owned role and purpose allowlist for governance reads."""

    allowed_roles: frozenset[str]
    allowed_purposes: frozenset[str]

    def __post_init__(self) -> None:
        if (
            not self.allowed_roles
            or not self.allowed_purposes
            or any(not value or len(value) > 256 for value in self.allowed_roles)
            or any(not value or len(value) > 256 for value in self.allowed_purposes)
        ):
            raise ValueError("governance access allowlists must be non-empty")


class RequestSecurityPort(Protocol):
    """Authentication/authorization boundary supplied by the API composition."""

    async def authenticate(self, request: Request) -> TrustedRequestIdentity: ...

    async def authorize_command(
        self, identity: TrustedRequestIdentity, command: TaskCommand
    ) -> None: ...

    async def authorize_task_read(
        self, identity: TrustedRequestIdentity, task_id: str
    ) -> None: ...

    async def authorize_event_stream(self, identity: TrustedRequestIdentity) -> None:
        """Authorize a tenant-scoped subscription to the task event stream."""

    async def authorize_governance_read(
        self,
        identity: TrustedRequestIdentity,
        access: GovernanceAccessPolicy,
    ) -> None:
        """Revalidate identity and apply an explicit governance allowlist."""


@dataclass(frozen=True, slots=True)
class BrowserSessionBinding:
    """Credential-free projection resolved from an opaque browser cookie."""

    session_id_hash: str
    security_context: SecurityContextRef
    active: bool
    expires_at: datetime

    def __post_init__(self) -> None:
        if not self.session_id_hash.startswith("sha256:"):
            raise ValueError("browser session hash must be a SHA-256 digest")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("browser session expiry must be timezone-aware")
        object.__setattr__(self, "expires_at", self.expires_at.astimezone(UTC))


class RequestSessionSourcePort(Protocol):
    async def resolve_binding(
        self,
        session_id: str,
    ) -> BrowserSessionBinding | None: ...


class OidcRequestSecurity(RequestSecurityPort):
    """Cookie-only production request boundary backed by trusted S3 contexts."""

    def __init__(
        self,
        *,
        sessions: RequestSessionSourcePort,
        contexts: SecurityContextSource,
        verifier: SecurityVerifier,
        cookie_name: str,
        clock: Callable[[], datetime],
    ) -> None:
        if not cookie_name:
            raise ValueError("session cookie name must not be empty")
        self._sessions = sessions
        self._contexts = contexts
        self._verifier = verifier
        self._cookie_name = cookie_name
        self._clock = clock

    async def authenticate(self, request: Request) -> TrustedRequestIdentity:
        self._reject_untrusted_identity_inputs(request)
        session_id = request.cookies.get(self._cookie_name)
        if not session_id:
            raise ApiError(
                ApiErrorCode.AUTHENTICATION_REQUIRED,
                "an active browser session is required",
                status_code=401,
            )
        try:
            binding = await self._sessions.resolve_binding(session_id)
        except Exception:
            raise ApiError(
                ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                "browser session store is unavailable",
                status_code=503,
                retryable=True,
            ) from None
        now = self._utc_now()
        if binding is None or not binding.active or now >= binding.expires_at:
            raise ApiError(
                ApiErrorCode.AUTHENTICATION_INVALID,
                "browser session is invalid or expired",
                status_code=401,
            )
        trusted = await self._resolve_and_verify(binding.security_context, now=now)
        context = trusted.context
        return TrustedRequestIdentity(
            tenant_id=context.tenant_id,
            subject_id=context.subject_id,
            subject_type=context.subject_type,
            purpose=context.purpose,
            security_context_id=context.context_id,
            security_context_ref=context.context_ref,
            security_context_hash=context.context_hash,
            security_context=context,
            roles=trusted.roles,
            scopes=trusted.scopes,
        )

    async def authorize_command(
        self, identity: TrustedRequestIdentity, command: TaskCommand
    ) -> None:
        await self._reverify_identity(identity, presented=command.security_context)

    async def authorize_task_read(
        self, identity: TrustedRequestIdentity, _task_id: str
    ) -> None:
        await self._reverify_identity(identity)

    async def authorize_event_stream(self, identity: TrustedRequestIdentity) -> None:
        await self._reverify_identity(identity)

    async def authorize_governance_read(
        self,
        identity: TrustedRequestIdentity,
        access: GovernanceAccessPolicy,
    ) -> None:
        trusted = await self._reverify_identity(identity)
        if (
            trusted.context.purpose not in access.allowed_purposes
            or not trusted.roles.intersection(access.allowed_roles)
        ):
            raise ApiError(
                ApiErrorCode.AUTHORIZATION_DENIED,
                "trusted identity is not authorized for governance reads",
                status_code=403,
            )

    async def _reverify_identity(
        self,
        identity: TrustedRequestIdentity,
        *,
        presented: SecurityContextRef | None = None,
    ) -> TrustedSecurityContext:
        if identity.security_context is None:
            raise ApiError(
                ApiErrorCode.AUTHORIZATION_DENIED,
                "trusted request context is required",
                status_code=403,
            )
        trusted = await self._resolve_and_verify(
            presented or identity.security_context,
            now=self._utc_now(),
        )
        expected = trusted.context
        values_match = (
            hmac.compare_digest(identity.tenant_id, expected.tenant_id)
            and hmac.compare_digest(identity.subject_id, expected.subject_id)
            and identity.subject_type is expected.subject_type
            and hmac.compare_digest(identity.purpose, expected.purpose)
            and hmac.compare_digest(identity.security_context_id, expected.context_id)
            and hmac.compare_digest(identity.security_context_ref, expected.context_ref)
            and hmac.compare_digest(
                identity.security_context_hash,
                expected.context_hash,
            )
        )
        if not values_match:
            raise ApiError(
                ApiErrorCode.AUTHORIZATION_DENIED,
                "trusted request identity no longer matches its context",
                status_code=403,
            )
        return trusted

    async def _resolve_and_verify(
        self,
        presented: SecurityContextRef,
        *,
        now: datetime,
    ) -> TrustedSecurityContext:
        try:
            trusted = await self._contexts.resolve(presented.context_ref)
            self._verifier.verify_context(
                presented=presented,
                trusted=trusted,
                now=now,
            )
        except SecurityError as error:
            raise security_error_to_api(error) from None
        except Exception:
            raise ApiError(
                ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                "trusted security context source is unavailable",
                status_code=503,
                retryable=True,
            ) from None
        return trusted

    @staticmethod
    def _reject_untrusted_identity_inputs(request: Request) -> None:
        if "authorization" in request.headers:
            raise ApiError(
                ApiErrorCode.AUTHENTICATION_INVALID,
                "browser bearer credentials are not accepted",
                status_code=401,
            )
        if _FORBIDDEN_IDENTITY_HEADERS.intersection(request.headers):
            raise ApiError(
                ApiErrorCode.AUTHORIZATION_DENIED,
                "request identity override headers are forbidden",
                status_code=403,
            )

    def _utc_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("request security clock must be timezone-aware")
        return value.astimezone(UTC)


def security_error_to_api(error: SecurityError) -> ApiError:
    if error.code is SecurityErrorCode.IDENTITY_SOURCE_UNAVAILABLE:
        return ApiError(
            ApiErrorCode.DEPENDENCY_UNAVAILABLE,
            "identity source is unavailable",
            status_code=503,
            retryable=True,
        )
    if error.code in {
        SecurityErrorCode.IDENTITY_MAPPING_DENIED,
        SecurityErrorCode.PURPOSE_DENIED,
        SecurityErrorCode.TENANT_MISMATCH,
    }:
        return ApiError(
            ApiErrorCode.AUTHORIZATION_DENIED,
            "trusted identity is not authorized for this request",
            status_code=403,
        )
    return ApiError(
        ApiErrorCode.AUTHENTICATION_INVALID,
        "trusted identity or security context is invalid",
        status_code=401,
    )
