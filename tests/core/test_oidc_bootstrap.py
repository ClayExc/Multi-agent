from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from flowpilot_api import (
    LocalKeycloakSettings,
    compose_local_keycloak_oidc,
    create_default_app,
)

ISSUER = "http://127.0.0.1:18081/realms/flowpilot-local"
REDIRECT = "http://127.0.0.1:18765/v1/auth/callback"
SECRET = "bootstrap-client-secret-sensitive"
NOW = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)


def _env() -> dict[str, str]:
    return {
        "FLOWPILOT_OIDC_ISSUER": ISSUER,
        "FLOWPILOT_OIDC_CLIENT_ID": "flowpilot-web",
        "KEYCLOAK_WEB_CLIENT_SECRET": SECRET,
        "FLOWPILOT_OIDC_REDIRECT_URI": REDIRECT,
        "FLOWPILOT_OIDC_ALLOW_INSECURE_LOOPBACK": "true",
        "FLOWPILOT_OIDC_POST_LOGIN_REDIRECT": "/studio",
    }


def _discovery() -> httpx.Response:
    return httpx.Response(
        200,
        headers={"Content-Type": "application/json"},
        content=json.dumps(
            {
                "issuer": ISSUER,
                "authorization_endpoint": (
                    f"{ISSUER}/protocol/openid-connect/auth"
                ),
                "token_endpoint": f"{ISSUER}/protocol/openid-connect/token",
                "revocation_endpoint": (
                    f"{ISSUER}/protocol/openid-connect/revoke"
                ),
                "jwks_uri": f"{ISSUER}/protocol/openid-connect/certs",
            }
        ).encode(),
    )


def test_default_app_is_unconfigured_without_oidc_environment() -> None:
    app = create_default_app({})

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="https://flowpilot.test",
        ) as client:
            health = await client.get("/health")
            login = await client.get("/v1/auth/login")
        assert health.json()["configured"] is False
        assert login.status_code == 503
        assert login.json()["error"]["code"] == "API_DEPENDENCY_UNAVAILABLE"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_issuer",
        "empty_secret",
        "bad_boolean",
        "bad_timeout",
        "unsafe_issuer",
    ],
)
def test_partial_or_invalid_environment_fails_startup_without_secret_leakage(
    mutation: str,
) -> None:
    values = _env()
    if mutation == "missing_issuer":
        del values["FLOWPILOT_OIDC_ISSUER"]
    elif mutation == "empty_secret":
        values["KEYCLOAK_WEB_CLIENT_SECRET"] = ""
    elif mutation == "bad_boolean":
        values["FLOWPILOT_OIDC_ALLOW_INSECURE_LOOPBACK"] = "sometimes"
    elif mutation == "bad_timeout":
        values["FLOWPILOT_OIDC_TIMEOUT_SECONDS"] = "secret-timeout"
    else:
        values["FLOWPILOT_OIDC_ISSUER"] = "http://keycloak.internal/realm"

    with pytest.raises(ValueError) as rejected:
        create_default_app(values)
    assert SECRET not in str(rejected.value)
    assert "secret-timeout" not in str(rejected.value)


def test_complete_environment_composes_oidc_atomically_without_import_network() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _discovery()

    transport = httpx.MockTransport(handler)
    app = create_default_app(
        _env(),
        clock=lambda: NOW,
        transport=transport,
    )
    assert calls == 0

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="https://flowpilot.test",
            follow_redirects=False,
        ) as client:
            login = await client.get("/v1/auth/login")
            bearer = await client.get(
                "/v1/tasks/task_12345678",
                headers={"Authorization": "Bearer attacker"},
            )
        assert login.status_code == 302
        assert login.headers["location"].startswith(
            f"{ISSUER}/protocol/openid-connect/auth?"
        )
        assert SECRET not in login.headers["location"]
        assert bearer.status_code == 401
        assert bearer.json()["error"]["code"] == "API_AUTHENTICATION_INVALID"

    asyncio.run(scenario())
    assert calls == 1


def test_explicit_bundle_pairs_bff_and_cookie_only_request_security() -> None:
    settings = LocalKeycloakSettings.from_mapping(_env())
    assert settings is not None
    bundle = compose_local_keycloak_oidc(
        settings,
        clock=lambda: NOW,
        transport=httpx.MockTransport(lambda _request: _discovery()),
    )
    assert bundle.bff.config.issuer == ISSUER
    assert bundle.bff.config.authorized_party == "flowpilot-web"
    combined = repr(settings) + repr(bundle)
    assert SECRET not in combined


def test_default_composition_completes_callback_and_same_second_refresh() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private_key.public_key().public_numbers()
    jwk = {
        "kid": "local-key",
        "kty": "RSA",
        "alg": "RS256",
        "use": "sig",
        "n": _b64uint(public.n),
        "e": _b64uint(public.e),
    }
    nonce = ""
    token_calls = 0
    revoked: list[str] = []

    def access_token(*, token_id: str) -> str:
        timestamp = int(NOW.timestamp())
        return jwt.encode(
            {
                "iss": ISSUER,
                "aud": "flowpilot-api",
                "azp": "flowpilot-web",
                "sub": "user-local",
                "tenant_id": "tenant-a",
                "groups": ["/tenants/tenant-a/users"],
                "scope": "openid flowpilot-identity",
                "acr": "1",
                "sid": "session-local",
                "iat": timestamp,
                "nbf": timestamp,
                "exp": timestamp + 300,
                "jti": token_id,
            },
            private_key,
            algorithm="RS256",
            headers={"kid": "local-key"},
        )

    def id_token(access: str) -> str:
        timestamp = int(NOW.timestamp())
        return jwt.encode(
            {
                "iss": ISSUER,
                "aud": "flowpilot-web",
                "azp": "flowpilot-web",
                "sub": "user-local",
                "sid": "session-local",
                "nonce": nonce,
                "at_hash": _at_hash(access),
                "iat": timestamp,
                "exp": timestamp + 300,
            },
            private_key,
            algorithm="RS256",
            headers={"kid": "local-key"},
        )

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        path = request.url.path
        if path.endswith("/.well-known/openid-configuration"):
            return _discovery()
        if path.endswith("/certs"):
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                json={"keys": [jwk]},
            )
        form = parse_qs(request.content.decode())
        if path.endswith("/revoke"):
            revoked.extend(form["token"])
            return httpx.Response(200)
        token_calls += 1
        if form["grant_type"] == ["authorization_code"]:
            initial = access_token(token_id="access-1")
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                json={
                    "id_token": id_token(initial),
                    "access_token": initial,
                    "refresh_token": "refresh-1-sensitive",
                },
            )
        assert form["grant_type"] == ["refresh_token"]
        assert form["refresh_token"] == ["refresh-1-sensitive"]
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            json={
                "access_token": access_token(token_id="access-2"),
                "refresh_token": "refresh-2-sensitive",
            },
        )

    app = create_default_app(
        _env(),
        clock=lambda: NOW,
        transport=httpx.MockTransport(handler),
    )

    async def scenario() -> None:
        nonlocal nonce
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="https://flowpilot.test",
            follow_redirects=False,
        ) as client:
            login = await client.get("/v1/auth/login")
            query = parse_qs(urlsplit(login.headers["location"]).query)
            nonce = query["nonce"][0]
            callback = await client.get(
                "/v1/auth/callback",
                params={"state": query["state"][0], "code": "local-code"},
            )
            assert callback.status_code == 303
            old_cookie = client.cookies.get("__Host-flowpilot-session")
            assert old_cookie is not None
            refreshed = await client.post("/v1/auth/refresh")
            assert refreshed.status_code == 200
            new_cookie = client.cookies.get("__Host-flowpilot-session")
            assert new_cookie is not None and new_cookie != old_cookie
            assert "refresh-1-sensitive" not in refreshed.text
            assert "refresh-2-sensitive" not in refreshed.text

    asyncio.run(scenario())
    assert token_calls == 2
    assert revoked == []


def _b64uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _at_hash(access_token: str) -> str:
    digest = hashlib.sha256(access_token.encode()).digest()
    return base64.urlsafe_b64encode(digest[: len(digest) // 2]).rstrip(b"=").decode()
