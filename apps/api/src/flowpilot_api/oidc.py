from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import ipaddress
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from urllib.parse import urlsplit

from flowpilot_domain import SecurityContextRef
from flowpilot_security import (
    RefreshLineageGuardPort,
    RefreshLineageState,
    RevocableSecurityContextSource,
    SecurityContextReference,
    SecurityError,
    SecurityVerifier,
    TrustedContextMapper,
    TrustedSecurityContext,
    UserTokenPairVerifierPort,
    VerifiedUserIdentity,
    oidc_nonce_digest,
)

from .errors import ApiError, ApiErrorCode
from .security import (
    BrowserSessionBinding,
    OidcRequestSecurity,
    security_error_to_api,
)


def _sha256(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


@dataclass(frozen=True, slots=True)
class OidcBffConfig:
    issuer: str
    authorized_party: str
    redirect_uri: str
    post_login_redirect: str = "/"
    purpose: str = "it_support"
    session_cookie_name: str = "__Host-flowpilot-session"
    transaction_cookie_name: str = "__Host-flowpilot-login"
    cookie_secure: bool = True
    cookie_same_site: Literal["lax", "strict"] = "lax"
    login_ttl_seconds: int = 300
    session_ttl_seconds: int = 3600
    allow_insecure_loopback_provider: bool = False

    def __post_init__(self) -> None:
        if not all(
            (
                self.issuer,
                self.authorized_party,
                self.redirect_uri,
                self.purpose,
                self.session_cookie_name,
                self.transaction_cookie_name,
            )
        ):
            raise ValueError("OIDC BFF configuration fields must not be empty")
        if not self.post_login_redirect.startswith("/") or (
            self.post_login_redirect.startswith("//")
        ):
            raise ValueError("post-login redirect must be a local absolute path")
        if self.cookie_same_site not in {"lax", "strict"}:
            raise ValueError("OIDC cookies must use lax or strict SameSite")
        if self.login_ttl_seconds < 30 or self.login_ttl_seconds > 900:
            raise ValueError("OIDC login TTL must be within 30..900 seconds")
        if self.session_ttl_seconds < 60 or self.session_ttl_seconds > 86400:
            raise ValueError("OIDC session TTL must be within 60..86400 seconds")
        for name in (self.session_cookie_name, self.transaction_cookie_name):
            if name.startswith("__Host-") and not self.cookie_secure:
                raise ValueError("__Host- cookies require Secure")


@dataclass(frozen=True, slots=True, repr=False)
class OidcCodeExchange:
    id_token: str
    access_token: str
    refresh_token: str

    def __post_init__(self) -> None:
        if not self.id_token or not self.access_token or not self.refresh_token:
            raise ValueError("OIDC code exchange tokens must not be empty")

    def __repr__(self) -> str:
        return (
            "OidcCodeExchange(id_token=<redacted>, access_token=<redacted>, "
            "refresh_token=<redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class OidcRefreshResult:
    access_token: str
    refresh_token: str
    id_token: str | None = None

    def __post_init__(self) -> None:
        if not self.access_token or not self.refresh_token:
            raise ValueError("OIDC refreshed tokens must not be empty")
        if self.id_token == "":
            raise ValueError("OIDC refreshed ID token must not be empty")

    def __repr__(self) -> str:
        return (
            "OidcRefreshResult(access_token=<redacted>, "
            f"id_token={'<redacted>' if self.id_token is not None else 'None'}, "
            "refresh_token=<redacted>)"
        )


class OidcProviderPort(Protocol):
    """Trusted IdP client seam; concrete network transport is outside WP-083."""

    async def authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        pkce_challenge: str,
        redirect_uri: str,
    ) -> str: ...

    async def exchange_code(
        self,
        *,
        code: str,
        pkce_verifier: str,
        redirect_uri: str,
    ) -> OidcCodeExchange: ...

    async def refresh(
        self,
        *,
        refresh_token: str,
    ) -> OidcRefreshResult: ...

    async def revoke(self, *, refresh_token: str) -> None: ...


@dataclass(frozen=True, slots=True, repr=False)
class OidcLoginTransaction:
    state_hash: str
    nonce: str
    pkce_verifier: str
    expires_at: datetime

    def __post_init__(self) -> None:
        if not self.state_hash.startswith("sha256:"):
            raise ValueError("OIDC state hash must be a SHA-256 digest")
        if not self.nonce or not self.pkce_verifier:
            raise ValueError("OIDC transaction material must not be empty")
        object.__setattr__(
            self,
            "expires_at",
            _utc(self.expires_at, "OIDC transaction expiry"),
        )

    def __repr__(self) -> str:
        return (
            "OidcLoginTransaction(state_hash=<redacted>, nonce=<redacted>, "
            "pkce_verifier=<redacted>, expires_at=<utc>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class OidcBrowserSession:
    identity: VerifiedUserIdentity
    security_context: SecurityContextRef
    refresh_token: str
    expires_at: datetime

    def __post_init__(self) -> None:
        if not self.refresh_token:
            raise ValueError("browser session refresh token must not be empty")
        object.__setattr__(
            self,
            "expires_at",
            _utc(self.expires_at, "browser session expiry"),
        )

    def __repr__(self) -> str:
        return (
            "OidcBrowserSession(identity=<trusted>, security_context=<ref>, "
            "refresh_token=<redacted>, expires_at=<utc>)"
        )


class OidcSessionStorePort(Protocol):
    async def create_login(
        self,
        flow_id: str,
        transaction: OidcLoginTransaction,
        *,
        nonce_hash: str,
    ) -> None: ...

    async def consume_login(self, flow_id: str) -> OidcLoginTransaction | None: ...

    async def store_session(
        self,
        session_id: str,
        session: OidcBrowserSession,
    ) -> None: ...

    async def resolve_session(self, session_id: str) -> OidcBrowserSession | None: ...

    async def claim_session_refresh(
        self,
        session_id: str,
    ) -> OidcBrowserSession | None: ...

    async def complete_session_refresh(
        self,
        old_session_id: str,
        new_session_id: str,
        *,
        expected: OidcBrowserSession,
        replacement: OidcBrowserSession,
    ) -> bool: ...

    async def invalidate_session(
        self,
        session_id: str,
    ) -> OidcBrowserSession | None: ...

    async def resolve_binding(
        self,
        session_id: str,
    ) -> BrowserSessionBinding | None: ...

    async def consume(self, *, nonce_hash: str, expires_at: datetime) -> bool: ...


class InMemoryOidcSessionStore(RefreshLineageGuardPort):
    """Lock-protected local session, nonce, and hashed refresh-lineage store."""

    def __init__(self, *, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self._lock = asyncio.Lock()
        self._logins: dict[str, OidcLoginTransaction] = {}
        self._nonces: dict[str, datetime] = {}
        self._sessions: dict[str, OidcBrowserSession] = {}
        self._refreshing: dict[str, OidcBrowserSession] = {}
        self._lineages: dict[str, RefreshLineageState] = {}
        self._seen_access_tokens: set[str] = set()
        self._seen_access_token_ids: set[str] = set()

    async def create_login(
        self,
        flow_id: str,
        transaction: OidcLoginTransaction,
        *,
        nonce_hash: str,
    ) -> None:
        async with self._lock:
            if flow_id in self._logins or nonce_hash in self._nonces:
                raise ApiError(
                    ApiErrorCode.AUTH_FLOW_INVALID,
                    "OIDC login transaction already exists",
                    status_code=409,
                )
            self._logins[flow_id] = transaction
            self._nonces[nonce_hash] = transaction.expires_at

    async def consume_login(self, flow_id: str) -> OidcLoginTransaction | None:
        async with self._lock:
            transaction = self._logins.pop(flow_id, None)
            if transaction is None or self._now() >= transaction.expires_at:
                return None
            return transaction

    async def consume(self, *, nonce_hash: str, expires_at: datetime) -> bool:
        _utc(expires_at, "OIDC token expiry")
        async with self._lock:
            nonce_expiry = self._nonces.pop(nonce_hash, None)
            return nonce_expiry is not None and self._now() < nonce_expiry

    async def store_session(
        self,
        session_id: str,
        session: OidcBrowserSession,
    ) -> None:
        async with self._lock:
            if session_id in self._sessions or session_id in self._refreshing:
                raise ApiError(
                    ApiErrorCode.AUTH_FLOW_INVALID,
                    "browser session identifier already exists",
                    status_code=409,
                )
            self._sessions[session_id] = session

    async def resolve_session(self, session_id: str) -> OidcBrowserSession | None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if self._now() >= session.expires_at:
                del self._sessions[session_id]
                return None
            return session

    async def resolve_binding(self, session_id: str) -> BrowserSessionBinding | None:
        session = await self.resolve_session(session_id)
        if session is None:
            return None
        return BrowserSessionBinding(
            session_id_hash=_sha256(session_id),
            security_context=session.security_context,
            active=True,
            expires_at=session.expires_at,
        )

    async def claim_session_refresh(
        self,
        session_id: str,
    ) -> OidcBrowserSession | None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None or self._now() >= session.expires_at:
                self._sessions.pop(session_id, None)
                return None
            del self._sessions[session_id]
            self._refreshing[session_id] = session
            return session

    async def complete_session_refresh(
        self,
        old_session_id: str,
        new_session_id: str,
        *,
        expected: OidcBrowserSession,
        replacement: OidcBrowserSession,
    ) -> bool:
        async with self._lock:
            current = self._refreshing.get(old_session_id)
            if (
                current is not expected
                or new_session_id in self._sessions
                or new_session_id in self._refreshing
            ):
                return False
            del self._refreshing[old_session_id]
            self._sessions[new_session_id] = replacement
            return True

    async def invalidate_session(
        self,
        session_id: str,
    ) -> OidcBrowserSession | None:
        async with self._lock:
            return self._sessions.pop(session_id, None) or self._refreshing.pop(
                session_id,
                None,
            )

    async def establish(self, *, initial: RefreshLineageState) -> bool:
        async with self._lock:
            if (
                initial.generation != 1
                or initial.session_identity_hash in self._lineages
                or initial.access_token_hash in self._seen_access_tokens
                or initial.access_token_id_hash in self._seen_access_token_ids
            ):
                return False
            self._lineages[initial.session_identity_hash] = initial
            self._seen_access_tokens.add(initial.access_token_hash)
            self._seen_access_token_ids.add(initial.access_token_id_hash)
            return True

    async def compare_and_swap(
        self,
        *,
        expected: RefreshLineageState,
        replacement: RefreshLineageState,
    ) -> bool:
        async with self._lock:
            current = self._lineages.get(expected.session_identity_hash)
            if (
                current != expected
                or replacement.session_identity_hash
                != expected.session_identity_hash
                or replacement.generation != expected.generation + 1
                or replacement.issued_at < expected.issued_at
                or replacement.access_token_hash in self._seen_access_tokens
                or replacement.access_token_id_hash in self._seen_access_token_ids
            ):
                return False
            self._lineages[expected.session_identity_hash] = replacement
            self._seen_access_tokens.add(replacement.access_token_hash)
            self._seen_access_token_ids.add(replacement.access_token_id_hash)
            return True

    def _now(self) -> datetime:
        return _utc(self._clock(), "OIDC session store clock")


@dataclass(frozen=True, slots=True)
class OidcLoginStart:
    authorization_url: str
    transaction_cookie: str
    max_age_seconds: int


@dataclass(frozen=True, slots=True)
class OidcSessionStart:
    session_cookie: str
    expires_at: datetime
    max_age_seconds: int


class OidcBffService:
    def __init__(
        self,
        *,
        provider: OidcProviderPort,
        token_verifier: UserTokenPairVerifierPort,
        context_mapper: TrustedContextMapper,
        contexts: RevocableSecurityContextSource,
        sessions: OidcSessionStorePort,
        config: OidcBffConfig,
        clock: Callable[[], datetime],
        random_token: Callable[[], str] | None = None,
    ) -> None:
        self._provider = provider
        self._token_verifier = token_verifier
        self._context_mapper = context_mapper
        self._contexts = contexts
        self._sessions = sessions
        self._config = config
        self._clock = clock
        self._random_token = random_token or (lambda: secrets.token_urlsafe(32))

    @property
    def config(self) -> OidcBffConfig:
        return self._config

    async def begin_login(self) -> OidcLoginStart:
        now = self._now()
        state = self._secret("state")
        nonce = self._secret("nonce")
        verifier = self._secret("pkce") + self._secret("pkce")
        flow_id = "login_" + self._secret("flow")
        expires_at = now + timedelta(seconds=self._config.login_ttl_seconds)
        transaction = OidcLoginTransaction(
            state_hash=_sha256(state),
            nonce=nonce,
            pkce_verifier=verifier,
            expires_at=expires_at,
        )
        try:
            authorization_url = await self._provider.authorization_url(
                state=state,
                nonce=nonce,
                pkce_challenge=_pkce_challenge(verifier),
                redirect_uri=self._config.redirect_uri,
            )
            self._assert_authorization_url(authorization_url)
            await self._sessions.create_login(
                flow_id,
                transaction,
                nonce_hash=oidc_nonce_digest(
                    issuer=self._config.issuer,
                    authorized_party=self._config.authorized_party,
                    nonce=nonce,
                ),
            )
        except ApiError:
            raise
        except SecurityError as error:
            raise security_error_to_api(error) from None
        except Exception:
            raise ApiError(
                ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                "OIDC authorization service is unavailable",
                status_code=503,
                retryable=True,
            ) from None
        return OidcLoginStart(
            authorization_url=authorization_url,
            transaction_cookie=flow_id,
            max_age_seconds=self._config.login_ttl_seconds,
        )

    async def complete_callback(
        self,
        *,
        transaction_cookie: str | None,
        state: str | None,
        code: str | None,
    ) -> OidcSessionStart:
        if not self._bounded(transaction_cookie, 256):
            raise self._invalid_flow()
        flow_id = self._required_flow_cookie(transaction_cookie)
        transaction = await self._consume_login(flow_id)
        if (
            transaction is None
            or not self._bounded(state, 512)
            or not self._bounded(code, 4096)
            or not hmac.compare_digest(
                transaction.state_hash,
                _sha256(self._required_text(state)),
            )
        ):
            raise self._invalid_flow()
        exchange: OidcCodeExchange | None = None
        try:
            exchange = await self._provider.exchange_code(
                code=self._required_text(code),
                pkce_verifier=transaction.pkce_verifier,
                redirect_uri=self._config.redirect_uri,
            )
            identity = await self._token_verifier.verify_user_token_pair(
                id_token=exchange.id_token,
                access_token=exchange.access_token,
                expected_nonce=transaction.nonce,
                now=self._now(),
            )
            self._assert_configured_identity(identity)
            return await self._create_session(
                identity=identity,
                refresh_token=exchange.refresh_token,
            )
        except ApiError:
            if exchange is not None:
                await self._revoke_token_safely(exchange.refresh_token)
            raise
        except SecurityError as error:
            if exchange is not None:
                await self._revoke_token_safely(exchange.refresh_token)
            raise security_error_to_api(error) from None
        except Exception:
            if exchange is not None:
                await self._revoke_token_safely(exchange.refresh_token)
            raise ApiError(
                ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                "OIDC callback service is unavailable",
                status_code=503,
                retryable=True,
            ) from None

    async def refresh(self, session_cookie: str | None) -> OidcSessionStart:
        cookie = self._required_cookie(session_cookie)
        session = await self._claim_refresh(cookie)
        refreshed: OidcRefreshResult | None = None
        try:
            refreshed = await self._provider.refresh(
                refresh_token=session.refresh_token,
            )
            identity = await self._token_verifier.verify_user_refresh(
                access_token=refreshed.access_token,
                id_token=refreshed.id_token,
                previous_identity=session.identity,
                now=self._now(),
            )
            self._assert_configured_identity(identity)
            self._assert_refresh_identity(session.identity, identity)
            replacement, trusted = self._build_session_record(
                identity=identity,
                refresh_token=refreshed.refresh_token,
            )
            new_cookie = "sess_" + self._secret("session")
            start = self._session_start(new_cookie, replacement)
            await self._contexts.store(trusted)
            try:
                await self._contexts.revoke(
                    session.security_context.context_ref,
                    revoked_at=self._now(),
                    reason_code="OIDC_SESSION_REFRESHED",
                )
                rotated = await self._sessions.complete_session_refresh(
                    cookie,
                    new_cookie,
                    expected=session,
                    replacement=replacement,
                )
            except Exception:
                await self._revoke_context_safely(
                    replacement.security_context.context_ref,
                    reason_code="OIDC_REFRESH_STORE_FAILED",
                )
                raise
            if not rotated:
                await self._revoke_context_safely(
                    replacement.security_context.context_ref,
                    reason_code="OIDC_REFRESH_REPLAY",
                )
                raise ApiError(
                    ApiErrorCode.AUTHENTICATION_INVALID,
                    "browser session was already refreshed or invalidated",
                    status_code=401,
                )
            return start
        except ApiError:
            await self._cleanup_refresh_failure(cookie, refreshed)
            raise
        except SecurityError as error:
            await self._cleanup_refresh_failure(cookie, refreshed)
            raise security_error_to_api(error) from None
        except Exception:
            await self._cleanup_refresh_failure(cookie, refreshed)
            raise ApiError(
                ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                "OIDC refresh service is unavailable",
                status_code=503,
                retryable=True,
            ) from None

    async def logout(self, session_cookie: str | None) -> None:
        await self.invalidate(session_cookie)

    async def invalidate(
        self,
        session_cookie: str | None,
    ) -> OidcBrowserSession | None:
        if not self._bounded(session_cookie, 256):
            return None
        try:
            session = await self._sessions.invalidate_session(
                self._required_text(session_cookie)
            )
            if session is None:
                return None
            await self._revoke_context_safely(
                session.security_context.context_ref,
                reason_code="OIDC_SESSION_INVALIDATED",
            )
            await self._revoke_token_safely(session.refresh_token)
            return session
        except ApiError:
            raise
        except SecurityError as error:
            raise security_error_to_api(error) from None
        except Exception:
            raise ApiError(
                ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                "browser session invalidation is unavailable",
                status_code=503,
                retryable=True,
            ) from None

    async def _create_session(
        self,
        *,
        identity: VerifiedUserIdentity,
        refresh_token: str,
    ) -> OidcSessionStart:
        session, trusted = self._build_session_record(
            identity=identity,
            refresh_token=refresh_token,
        )
        cookie = "sess_" + self._secret("session")
        try:
            await self._contexts.store(trusted)
            await self._sessions.store_session(cookie, session)
        except Exception:
            with contextlib.suppress(Exception):
                await self._contexts.revoke(
                    trusted.context.context_ref,
                    revoked_at=self._now(),
                    reason_code="OIDC_SESSION_STORE_FAILED",
                )
            raise
        return self._session_start(cookie, session)

    def _build_session_record(
        self,
        *,
        identity: VerifiedUserIdentity,
        refresh_token: str,
    ) -> tuple[OidcBrowserSession, TrustedSecurityContext]:
        trusted = self._trusted_context(identity)
        return (
            OidcBrowserSession(
                identity=identity,
                security_context=trusted.context,
                refresh_token=refresh_token,
                expires_at=trusted.context.expires_at,
            ),
            trusted,
        )

    def _trusted_context(
        self,
        identity: VerifiedUserIdentity,
    ) -> TrustedSecurityContext:
        reference_id = "secctx_" + self._secret("context")
        return self._context_mapper.map_user(
            identity=identity,
            reference=SecurityContextReference(
                context_id=reference_id,
                context_ref=f"security-context://{reference_id}",
            ),
            purpose=self._config.purpose,
            now=self._now(),
            ttl_seconds=self._config.session_ttl_seconds,
        )

    async def _resolve_session(
        self,
        session_cookie: str | None,
    ) -> OidcBrowserSession:
        cookie = self._required_cookie(session_cookie)
        try:
            session = await self._sessions.resolve_session(cookie)
        except Exception:
            raise ApiError(
                ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                "browser session store is unavailable",
                status_code=503,
                retryable=True,
            ) from None
        if session is None:
            raise ApiError(
                ApiErrorCode.AUTHENTICATION_INVALID,
                "browser session is invalid or expired",
                status_code=401,
            )
        return session

    async def _claim_refresh(self, cookie: str) -> OidcBrowserSession:
        try:
            session = await self._sessions.claim_session_refresh(cookie)
        except Exception:
            raise ApiError(
                ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                "browser session store is unavailable",
                status_code=503,
                retryable=True,
            ) from None
        if session is None:
            raise ApiError(
                ApiErrorCode.AUTHENTICATION_INVALID,
                "browser session was already refreshed or invalidated",
                status_code=401,
            )
        return session

    async def _consume_login(
        self,
        flow_id: str,
    ) -> OidcLoginTransaction | None:
        try:
            return await self._sessions.consume_login(flow_id)
        except Exception:
            raise ApiError(
                ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                "OIDC login session store is unavailable",
                status_code=503,
                retryable=True,
            ) from None

    async def _invalidate_safely(self, session_cookie: str | None) -> None:
        try:
            await self.invalidate(session_cookie)
        except Exception:
            return

    async def _cleanup_refresh_failure(
        self,
        session_cookie: str,
        refreshed: OidcRefreshResult | None,
    ) -> None:
        await self._invalidate_safely(session_cookie)
        if refreshed is not None:
            await self._revoke_token_safely(refreshed.refresh_token)

    def _session_start(
        self,
        cookie: str,
        session: OidcBrowserSession,
    ) -> OidcSessionStart:
        remaining = max(0, int((session.expires_at - self._now()).total_seconds()))
        return OidcSessionStart(
            session_cookie=cookie,
            expires_at=session.expires_at,
            max_age_seconds=remaining,
        )

    def _assert_authorization_url(self, value: str) -> None:
        parsed = urlsplit(value)
        if parsed.scheme == "https" and parsed.netloc:
            return
        if (
            self._config.allow_insecure_loopback_provider
            and parsed.scheme == "http"
            and parsed.hostname is not None
            and _is_loopback(parsed.hostname)
        ):
            return
        raise ApiError(
            ApiErrorCode.AUTH_FLOW_INVALID,
            "OIDC authorization URL is not allowed",
            status_code=503,
        )

    @staticmethod
    def _assert_refresh_identity(
        previous: VerifiedUserIdentity,
        refreshed: VerifiedUserIdentity,
    ) -> None:
        if (
            previous.issuer != refreshed.issuer
            or previous.subject_id != refreshed.subject_id
            or previous.tenant_id != refreshed.tenant_id
            or previous.authorized_party != refreshed.authorized_party
            or previous.session_id_hash != refreshed.session_id_hash
        ):
            raise ApiError(
                ApiErrorCode.AUTHENTICATION_INVALID,
                "refreshed identity does not match the browser session",
                status_code=401,
            )

    def _assert_configured_identity(self, identity: VerifiedUserIdentity) -> None:
        now = self._now()
        if (
            identity.issuer != self._config.issuer
            or identity.authorized_party != self._config.authorized_party
            or now < identity.issued_at
            or now >= identity.expires_at
        ):
            raise ApiError(
                ApiErrorCode.AUTHENTICATION_INVALID,
                "trusted identity is not valid for this API session",
                status_code=401,
            )

    @staticmethod
    def _bounded(value: str | None, maximum: int) -> bool:
        return isinstance(value, str) and 1 <= len(value) <= maximum

    def _required_cookie(self, value: str | None) -> str:
        if not self._bounded(value, 256):
            raise ApiError(
                ApiErrorCode.AUTHENTICATION_REQUIRED,
                "an active browser session is required",
                status_code=401,
            )
        return self._required_text(value)

    @staticmethod
    def _invalid_flow() -> ApiError:
        return ApiError(
            ApiErrorCode.AUTH_FLOW_INVALID,
            "OIDC login transaction is invalid or already used",
            status_code=401,
        )

    def _secret(self, field: str) -> str:
        value = self._random_token()
        if not value or len(value) > 128:
            raise ValueError(f"{field} token factory returned an invalid value")
        return value

    async def _revoke_context_safely(
        self,
        context_ref: str,
        *,
        reason_code: str,
    ) -> None:
        try:
            await self._contexts.revoke(
                context_ref,
                revoked_at=self._now(),
                reason_code=reason_code,
            )
        except Exception:
            return

    async def _revoke_token_safely(self, refresh_token: str) -> None:
        try:
            await self._provider.revoke(refresh_token=refresh_token)
        except Exception:
            # Local session and trusted context remain fail-closed even when
            # the out-of-scope production IdP transport is unavailable.
            return

    def _required_flow_cookie(self, value: str | None) -> str:
        if not self._bounded(value, 256):
            raise self._invalid_flow()
        return self._required_text(value)

    @staticmethod
    def _required_text(value: str | None) -> str:
        if value is None:
            raise ValueError("validated text is unexpectedly absent")
        return value

    def _now(self) -> datetime:
        return _utc(self._clock(), "OIDC BFF clock")


@dataclass(frozen=True, slots=True)
class OidcApiSecurityBundle:
    bff: OidcBffService
    request_security: OidcRequestSecurity


def compose_oidc_api_security(
    *,
    provider: OidcProviderPort,
    token_verifier: UserTokenPairVerifierPort,
    context_mapper: TrustedContextMapper,
    contexts: RevocableSecurityContextSource,
    sessions: OidcSessionStorePort,
    config: OidcBffConfig,
    clock: Callable[[], datetime],
    random_token: Callable[[], str] | None = None,
) -> OidcApiSecurityBundle:
    return OidcApiSecurityBundle(
        bff=OidcBffService(
            provider=provider,
            token_verifier=token_verifier,
            context_mapper=context_mapper,
            contexts=contexts,
            sessions=sessions,
            config=config,
            clock=clock,
            random_token=random_token,
        ),
        request_security=OidcRequestSecurity(
            sessions=sessions,
            contexts=contexts,
            verifier=SecurityVerifier(),
            cookie_name=config.session_cookie_name,
            clock=clock,
        ),
    )


def _is_loopback(hostname: str) -> bool:
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False
