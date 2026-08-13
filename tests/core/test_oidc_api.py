from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest
from flowpilot_api import (
    ApiError,
    InMemoryEventStream,
    InMemoryOidcSessionStore,
    OidcApiSecurityBundle,
    OidcBffConfig,
    OidcCodeExchange,
    OidcRefreshResult,
    compose_oidc_api_security,
    create_app,
)
from flowpilot_domain import AssuranceLevel, DataClassification
from flowpilot_security import (
    InMemorySecurityContextSource,
    RefreshLineageState,
    SecurityError,
    SecurityErrorCode,
    TrustedContextMapper,
    TrustedContextMappingPolicy,
    VerifiedUserIdentity,
)

NOW = datetime(2026, 8, 11, 8, 0, tzinfo=UTC)
USER_TOKEN = "header.payload.signature-sensitive"
ID_TOKEN = "id.header.payload.signature-sensitive"
ROTATED_USER_TOKEN = "rotated.header.payload.signature-sensitive"
REFRESH_TOKEN = "refresh-sensitive-value"
ROTATED_REFRESH_TOKEN = "rotated-refresh-sensitive-value"


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _identity(*, token_hash_char: str = "c") -> VerifiedUserIdentity:
    return VerifiedUserIdentity(
        issuer="https://idp.example/realms/flowpilot",
        subject_id="user-123",
        tenant_id="tenant-a",
        authorized_party="flowpilot-web",
        roles=frozenset({"support-agent"}),
        scopes=frozenset({"tasks:read", "tasks:write"}),
        assurance_level=AssuranceLevel.SUBSTANTIAL,
        session_id_hash="sha256:" + "b" * 64,
        token_hash="sha256:" + token_hash_char * 64,
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=2),
    )


class FakeOidcProvider:
    def __init__(self) -> None:
        self.authorization: dict[str, str] = {}
        self.exchange_calls: list[dict[str, str]] = []
        self.refresh_calls: list[str] = []
        self.revoke_calls: list[str] = []
        self.refresh_failure: SecurityError | None = None

    async def authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        pkce_challenge: str,
        redirect_uri: str,
    ) -> str:
        self.authorization = {
            "state": state,
            "nonce": nonce,
            "code_challenge": pkce_challenge,
            "redirect_uri": redirect_uri,
        }
        return "https://idp.example/authorize?" + urlencode(self.authorization)

    async def exchange_code(
        self,
        *,
        code: str,
        pkce_verifier: str,
        redirect_uri: str,
    ) -> OidcCodeExchange:
        self.exchange_calls.append(
            {
                "code": code,
                "pkce_verifier": pkce_verifier,
                "redirect_uri": redirect_uri,
            }
        )
        return OidcCodeExchange(
            id_token=ID_TOKEN,
            access_token=USER_TOKEN,
            refresh_token=REFRESH_TOKEN,
        )

    async def refresh(
        self,
        *,
        refresh_token: str,
    ) -> OidcRefreshResult:
        self.refresh_calls.append(refresh_token)
        if self.refresh_failure is not None:
            raise self.refresh_failure
        return OidcRefreshResult(
            access_token=ROTATED_USER_TOKEN,
            refresh_token=ROTATED_REFRESH_TOKEN,
        )

    async def revoke(self, *, refresh_token: str) -> None:
        self.revoke_calls.append(refresh_token)


class FakeUserTokenVerifier:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, datetime]] = []
        self.refresh_calls: list[
            tuple[str, str | None, VerifiedUserIdentity, datetime]
        ] = []
        self.failure: SecurityError | None = None

    async def verify_user_token_pair(
        self,
        *,
        id_token: str,
        access_token: str,
        expected_nonce: str,
        now: datetime,
    ) -> VerifiedUserIdentity:
        self.calls.append((id_token, access_token, expected_nonce, now))
        if self.failure is not None:
            raise self.failure
        return _identity()

    async def verify_user_refresh(
        self,
        *,
        access_token: str,
        previous_identity: VerifiedUserIdentity,
        now: datetime,
        id_token: str | None = None,
    ) -> VerifiedUserIdentity:
        self.refresh_calls.append((access_token, id_token, previous_identity, now))
        if self.failure is not None:
            raise self.failure
        return _identity(token_hash_char="d")


class SecretFactory:
    def __init__(self) -> None:
        self._index = 0

    def __call__(self) -> str:
        self._index += 1
        return f"server-secret-{self._index:03d}"


@dataclass(slots=True)
class Harness:
    bundle: OidcApiSecurityBundle
    provider: FakeOidcProvider
    verifier: FakeUserTokenVerifier
    contexts: InMemorySecurityContextSource
    sessions: InMemoryOidcSessionStore
    config: OidcBffConfig


def _harness() -> Harness:
    provider = FakeOidcProvider()
    verifier = FakeUserTokenVerifier()
    contexts = InMemorySecurityContextSource()
    config = OidcBffConfig(
        issuer="https://idp.example/realms/flowpilot",
        authorized_party="flowpilot-web",
        redirect_uri="https://flowpilot.test/v1/auth/callback",
        post_login_redirect="/studio",
    )
    sessions = InMemoryOidcSessionStore(clock=lambda: NOW)
    bundle = compose_oidc_api_security(
        provider=provider,
        token_verifier=verifier,
        context_mapper=TrustedContextMapper(
            TrustedContextMappingPolicy(
                allowed_purposes=frozenset({"it_support"}),
                data_classification_ceiling=DataClassification.CONFIDENTIAL,
                maximum_ttl_seconds=3600,
            )
        ),
        contexts=contexts,
        sessions=sessions,
        config=config,
        clock=lambda: NOW,
        random_token=SecretFactory(),
    )
    return Harness(bundle, provider, verifier, contexts, sessions, config)


def _state(response: httpx.Response) -> str:
    return parse_qs(urlsplit(response.headers["location"]).query)["state"][0]


def _cookie_headers(response: httpx.Response) -> list[str]:
    return response.headers.get_list("set-cookie")


async def _login(
    client: httpx.AsyncClient,
    harness: Harness,
) -> tuple[str, httpx.Response]:
    login = await client.get("/v1/auth/login")
    assert login.status_code == 302
    state = _state(login)
    callback = await client.get(
        "/v1/auth/callback",
        params={"state": state, "code": "one-time-code-sensitive"},
    )
    assert callback.status_code == 303
    cookie = client.cookies.get(harness.config.session_cookie_name)
    assert cookie is not None
    return cookie, callback


def _run[T](scenario: Callable[[], Coroutine[Any, Any, T]]) -> T:
    return asyncio.run(scenario())


def test_login_callback_uses_state_nonce_pkce_and_secure_opaque_cookies() -> None:
    harness = _harness()
    app = create_app(
        oidc_bff=harness.bundle.bff,
        request_security=harness.bundle.request_security,
    )

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://flowpilot.test",
            follow_redirects=False,
        ) as client:
            login = await client.get("/v1/auth/login")
            assert login.status_code == 302
            transaction_headers = _cookie_headers(login)
            assert any(
                item.startswith(harness.config.transaction_cookie_name + "=")
                and "HttpOnly" in item
                and "Secure" in item
                and "SameSite=lax" in item
                and "Path=/" in item
                for item in transaction_headers
            )
            assert harness.provider.authorization["state"] == _state(login)
            assert harness.provider.authorization["nonce"]
            assert harness.provider.authorization["code_challenge"]

            session_cookie, callback = await _login_from_response(
                client,
                harness,
                login,
            )
            assert callback.headers["location"] == "/studio"
            assert session_cookie.startswith("sess_")
            assert USER_TOKEN not in callback.text
            assert REFRESH_TOKEN not in callback.text
            assert "one-time-code-sensitive" not in callback.text
            assert any(
                item.startswith(harness.config.session_cookie_name + "=")
                and "HttpOnly" in item
                and "Secure" in item
                and "SameSite=lax" in item
                and "Path=/" in item
                for item in _cookie_headers(callback)
            )
            exchange = harness.provider.exchange_calls[0]
            assert _pkce_challenge(exchange["pkce_verifier"]) == (
                harness.provider.authorization["code_challenge"]
            )
            assert harness.verifier.calls == [
                (
                    ID_TOKEN,
                    USER_TOKEN,
                    harness.provider.authorization["nonce"],
                    NOW,
                )
            ]

            replay = await client.get(
                "/v1/auth/callback",
                params={
                    "state": harness.provider.authorization["state"],
                    "code": "one-time-code-sensitive",
                },
            )
            assert replay.status_code == 401
            assert replay.json()["error"]["code"] == "API_AUTH_FLOW_INVALID"
            assert len(harness.provider.exchange_calls) == 1

    _run(scenario)


async def _login_from_response(
    client: httpx.AsyncClient,
    harness: Harness,
    login: httpx.Response,
) -> tuple[str, httpx.Response]:
    callback = await client.get(
        "/v1/auth/callback",
        params={
            "state": _state(login),
            "code": "one-time-code-sensitive",
        },
    )
    assert callback.status_code == 303
    cookie = client.cookies.get(harness.config.session_cookie_name)
    assert cookie is not None
    return cookie, callback


def test_state_mismatch_consumes_transaction_and_never_exchanges_code() -> None:
    harness = _harness()
    app = create_app(oidc_bff=harness.bundle.bff)

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://flowpilot.test",
        ) as client:
            login = await client.get("/v1/auth/login")
            first = await client.get(
                "/v1/auth/callback",
                params={"state": "attacker-state", "code": "stolen-code"},
            )
            retry = await client.get(
                "/v1/auth/callback",
                params={"state": _state(login), "code": "stolen-code"},
            )
            assert first.status_code == retry.status_code == 401
            assert first.json()["error"]["code"] == "API_AUTH_FLOW_INVALID"
            assert harness.provider.exchange_calls == []
            assert REFRESH_TOKEN not in first.text + retry.text

    _run(scenario)


@pytest.mark.parametrize(
    "error_code",
    (SecurityErrorCode.AUDIENCE_MISMATCH, SecurityErrorCode.IDENTITY_EXPIRED),
)
def test_invalid_audience_or_expired_callback_is_stable_and_token_free(
    error_code: SecurityErrorCode,
) -> None:
    harness = _harness()
    harness.verifier.failure = SecurityError(error_code, "secret token detail")
    app = create_app(oidc_bff=harness.bundle.bff)

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://flowpilot.test",
        ) as client:
            login = await client.get("/v1/auth/login")
            response = await client.get(
                "/v1/auth/callback",
                params={"state": _state(login), "code": "sensitive-code"},
            )
            assert response.status_code == 401
            assert response.json()["error"] == {
                "code": "API_AUTHENTICATION_INVALID",
                "message": "trusted identity or security context is invalid",
                "retryable": False,
                "detail_ref": None,
            }
            assert "secret token detail" not in response.text
            assert USER_TOKEN not in response.text
            assert harness.config.session_cookie_name not in client.cookies

    _run(scenario)


def test_cookie_only_request_security_rejects_headers_and_command_claims(
    valid_create_mapping: dict[str, Any],
) -> None:
    harness = _harness()
    app = create_app(
        oidc_bff=harness.bundle.bff,
        request_security=harness.bundle.request_security,
    )

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://flowpilot.test",
        ) as client:
            await _login(client, harness)
            bearer = await client.get(
                "/v1/tasks/task_12345678",
                headers={"Authorization": "Bearer attacker-token"},
            )
            override = await client.get(
                "/v1/tasks/task_12345678",
                headers={
                    "X-Tenant-Id": "tenant-b",
                    "X-Roles": "administrator",
                    "X-Purpose": "attacker-purpose",
                },
            )
            forged = dict(valid_create_mapping)
            forged["tenant_id"] = "tenant-b"
            tenant_command = await client.post("/v1/task-commands", json=forged)
            forged_purpose = copy.deepcopy(valid_create_mapping)
            forged_purpose["security_context"]["purpose"] = "attacker-purpose"
            purpose_command = await client.post(
                "/v1/task-commands",
                json=forged_purpose,
            )
            forged_classification = copy.deepcopy(valid_create_mapping)
            forged_classification["security_context"][
                "data_classification_ceiling"
            ] = "restricted"
            classification_command = await client.post(
                "/v1/task-commands",
                json=forged_classification,
            )
            forged_roles = copy.deepcopy(valid_create_mapping)
            forged_roles["roles"] = ["administrator"]
            roles_command = await client.post(
                "/v1/task-commands",
                json=forged_roles,
            )
            trusted = await client.get("/v1/tasks/task_12345678")

            assert bearer.status_code == 401
            assert bearer.json()["error"]["code"] == "API_AUTHENTICATION_INVALID"
            assert override.status_code == 403
            assert override.json()["error"]["code"] == "API_AUTHORIZATION_DENIED"
            for command in (
                tenant_command,
                purpose_command,
                classification_command,
            ):
                assert command.status_code == 403
                assert command.json()["error"]["code"] == (
                    "API_REQUEST_IDENTITY_MISMATCH"
                )
            assert roles_command.status_code == 422
            assert roles_command.json()["error"]["code"] == (
                "CORE_CONTRACT_INVALID"
            )
            assert trusted.status_code == 503
            assert trusted.json()["error"]["code"] == "API_DEPENDENCY_UNAVAILABLE"
            combined = "".join(
                response.text
                for response in (
                    bearer,
                    override,
                    tenant_command,
                    purpose_command,
                    classification_command,
                    roles_command,
                    trusted,
                )
            )
            assert "attacker-token" not in combined
            assert REFRESH_TOKEN not in combined

    _run(scenario)


@pytest.mark.parametrize(
    "error_code",
    (SecurityErrorCode.AUDIENCE_MISMATCH, SecurityErrorCode.IDENTITY_EXPIRED),
)
def test_refresh_failure_invalidates_session_and_clears_cookie(
    error_code: SecurityErrorCode,
) -> None:
    harness = _harness()
    app = create_app(
        oidc_bff=harness.bundle.bff,
        request_security=harness.bundle.request_security,
    )

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://flowpilot.test",
        ) as client:
            old_cookie, _callback = await _login(client, harness)
            harness.provider.refresh_failure = SecurityError(
                error_code,
                "provider token failure sensitive detail",
            )
            response = await client.post("/v1/auth/refresh")
            assert response.status_code == 401
            assert response.json()["error"]["code"] == (
                "API_AUTHENTICATION_INVALID"
            )
            assert harness.config.session_cookie_name not in client.cookies
            assert "sensitive detail" not in response.text
            async with httpx.AsyncClient(
                transport=transport,
                base_url="https://flowpilot.test",
                cookies={harness.config.session_cookie_name: old_cookie},
            ) as replay_client:
                replay = await replay_client.get("/v1/tasks/task_12345678")
            assert replay.status_code == 401

    _run(scenario)


def test_refresh_rotates_cookie_and_old_session_cannot_replay() -> None:
    harness = _harness()
    app = create_app(
        oidc_bff=harness.bundle.bff,
        request_security=harness.bundle.request_security,
    )

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://flowpilot.test",
        ) as client:
            old_cookie, _callback = await _login(client, harness)
            refresh = await client.post("/v1/auth/refresh")
            new_cookie = client.cookies.get(harness.config.session_cookie_name)
            assert refresh.status_code == 200
            assert refresh.json()["status"] == "active"
            assert old_cookie != new_cookie
            assert harness.provider.refresh_calls == [REFRESH_TOKEN]
            assert REFRESH_TOKEN not in refresh.text
            assert ROTATED_REFRESH_TOKEN not in refresh.text

            trusted = await client.get("/v1/tasks/task_12345678")
            assert trusted.status_code == 503
            async with httpx.AsyncClient(
                transport=transport,
                base_url="https://flowpilot.test",
                cookies={harness.config.session_cookie_name: old_cookie},
            ) as replay_client:
                replay = await replay_client.post("/v1/auth/refresh")
            assert replay.status_code == 401
            assert replay.json()["error"]["code"] == "API_AUTHENTICATION_INVALID"

    _run(scenario)


class FakeSubscription:
    async def attach(self, _tenant_id: str) -> None:
        return

    async def detach(self, _tenant_id: str) -> None:
        return


def test_logout_and_invalidation_revoke_task_and_sse_reconnects() -> None:
    harness = _harness()
    app = create_app(
        oidc_bff=harness.bundle.bff,
        request_security=harness.bundle.request_security,
        task_event_subscription=FakeSubscription(),  # type: ignore[arg-type]
        event_stream=InMemoryEventStream(),
    )

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://flowpilot.test",
        ) as client:
            old_cookie, _callback = await _login(client, harness)
            logout = await client.post("/v1/auth/logout")
            assert logout.status_code == 204
            assert harness.provider.revoke_calls == [REFRESH_TOKEN]
            assert REFRESH_TOKEN not in logout.text
            assert harness.config.session_cookie_name not in client.cookies

            async with httpx.AsyncClient(
                transport=transport,
                base_url="https://flowpilot.test",
                cookies={harness.config.session_cookie_name: old_cookie},
            ) as reconnect:
                task = await reconnect.get("/v1/tasks/task_12345678")
                sse = await reconnect.get("/v1/tasks/events")
            assert task.status_code == sse.status_code == 401
            assert sse.json()["error"]["code"] == "API_AUTHENTICATION_INVALID"

            await _login(client, harness)
            invalidated = await client.post("/v1/auth/session/invalidate")
            assert invalidated.status_code == 204
            assert harness.provider.revoke_calls == [REFRESH_TOKEN, REFRESH_TOKEN]

    _run(scenario)


def test_revoked_trusted_context_fails_closed_even_if_cookie_remains() -> None:
    harness = _harness()
    app = create_app(
        oidc_bff=harness.bundle.bff,
        request_security=harness.bundle.request_security,
    )

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://flowpilot.test",
        ) as client:
            cookie, _callback = await _login(client, harness)
            binding = await harness.sessions.resolve_binding(cookie)
            assert binding is not None
            await harness.contexts.revoke(
                binding.security_context.context_ref,
                revoked_at=NOW,
                reason_code="SECURITY_ADMIN_REVOKED",
            )
            response = await client.get("/v1/tasks/task_12345678")
            assert response.status_code == 401
            assert response.json()["error"] == {
                "code": "API_AUTHENTICATION_INVALID",
                "message": "trusted identity or security context is invalid",
                "retryable": False,
                "detail_ref": None,
            }

    _run(scenario)


def test_auth_models_and_reprs_never_project_raw_tokens() -> None:
    exchange = OidcCodeExchange(ID_TOKEN, USER_TOKEN, REFRESH_TOKEN)
    refreshed = OidcRefreshResult(ROTATED_USER_TOKEN, ROTATED_REFRESH_TOKEN)
    combined = repr(exchange) + repr(refreshed)
    assert ID_TOKEN not in combined
    assert USER_TOKEN not in combined
    assert ROTATED_USER_TOKEN not in combined
    assert REFRESH_TOKEN not in combined
    assert ROTATED_REFRESH_TOKEN not in combined


def _lineage(
    *,
    generation: int,
    token: str,
    token_id: str,
    issued_at: datetime = NOW,
) -> RefreshLineageState:
    return RefreshLineageState(
        session_identity_hash="sha256:" + "a" * 64,
        access_token_hash="sha256:" + token * 64,
        access_token_id_hash="sha256:" + token_id * 64,
        issued_at=issued_at,
        generation=generation,
    )


def test_local_refresh_lineage_guard_is_atomic_and_rejects_history() -> None:
    store = InMemoryOidcSessionStore(clock=lambda: NOW)
    initial = _lineage(generation=1, token="b", token_id="c")
    same_second = _lineage(generation=2, token="d", token_id="e")

    async def scenario() -> None:
        assert await store.establish(initial=initial)
        assert not await store.establish(initial=initial)
        results = await asyncio.gather(
            store.compare_and_swap(expected=initial, replacement=same_second),
            store.compare_and_swap(expected=initial, replacement=same_second),
        )
        assert sorted(results) == [False, True]
        historical = _lineage(generation=3, token="b", token_id="f")
        reused_jti = _lineage(generation=3, token="f", token_id="c")
        rollback = _lineage(
            generation=3,
            token="f",
            token_id="a",
            issued_at=NOW - timedelta(seconds=1),
        )
        assert not await store.compare_and_swap(
            expected=same_second,
            replacement=historical,
        )
        assert not await store.compare_and_swap(
            expected=same_second,
            replacement=reused_jti,
        )
        assert not await store.compare_and_swap(
            expected=same_second,
            replacement=rollback,
        )

    _run(scenario)


def test_concurrent_refresh_claims_provider_once_and_loser_cannot_cleanup_winner(
) -> None:
    harness = _harness()
    app = create_app(
        oidc_bff=harness.bundle.bff,
        request_security=harness.bundle.request_security,
    )

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://flowpilot.test",
        ) as client:
            cookie, _callback = await _login(client, harness)
        outcomes = await asyncio.gather(
            harness.bundle.bff.refresh(cookie),
            harness.bundle.bff.refresh(cookie),
            return_exceptions=True,
        )
        successes = [item for item in outcomes if not isinstance(item, Exception)]
        failures = [item for item in outcomes if isinstance(item, ApiError)]
        assert len(successes) == len(failures) == 1
        assert failures[0].status_code == 401
        assert harness.provider.refresh_calls == [REFRESH_TOKEN]
        winner = successes[0]
        assert not isinstance(winner, Exception)
        binding = await harness.sessions.resolve_binding(winner.session_cookie)
        assert binding is not None
        assert harness.provider.revoke_calls == []

    _run(scenario)


def test_refresh_verifier_failure_revokes_old_and_rotated_tokens_without_retry(
) -> None:
    harness = _harness()
    app = create_app(
        oidc_bff=harness.bundle.bff,
        request_security=harness.bundle.request_security,
    )

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://flowpilot.test",
        ) as client:
            old_cookie, _callback = await _login(client, harness)
            harness.verifier.failure = SecurityError(
                SecurityErrorCode.IDENTITY_TOKEN_INVALID,
                "rotated token sensitive failure",
            )
            response = await client.post("/v1/auth/refresh")
            assert response.status_code == 401
            assert "sensitive" not in response.text
            assert await harness.sessions.resolve_session(old_cookie) is None
        assert harness.provider.refresh_calls == [REFRESH_TOKEN]
        assert harness.provider.revoke_calls == [
            REFRESH_TOKEN,
            ROTATED_REFRESH_TOKEN,
        ]

    _run(scenario)
