from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from flowpilot_api import (
    ApiError,
    KeycloakOidcConfig,
    KeycloakOidcProvider,
)

ISSUER = "http://127.0.0.1:18081/realms/flowpilot-local"
REDIRECT = "http://127.0.0.1:18765/v1/auth/callback"
SECRET = "client-secret-sensitive"
ID_TOKEN = "id-token-sensitive"
ACCESS_TOKEN = "access-token-sensitive"
REFRESH_TOKEN = "refresh-token-sensitive"
ROTATED_ACCESS_TOKEN = "rotated-access-token-sensitive"
ROTATED_REFRESH_TOKEN = "rotated-refresh-token-sensitive"


def _config(**overrides: object) -> KeycloakOidcConfig:
    values: dict[str, object] = {
        "issuer": ISSUER,
        "client_id": "flowpilot-web",
        "client_secret": SECRET,
        "redirect_uri": REDIRECT,
        "allow_insecure_loopback": True,
        "max_response_bytes": 4096,
    }
    values.update(overrides)
    return KeycloakOidcConfig(**values)  # type: ignore[arg-type]


def _json_response(payload: object, *, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        headers={"Content-Type": "application/json; charset=utf-8"},
        content=json.dumps(payload).encode(),
    )


def _discovery(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/protocol/openid-connect/auth",
        "token_endpoint": f"{ISSUER}/protocol/openid-connect/token",
        "revocation_endpoint": f"{ISSUER}/protocol/openid-connect/revoke",
        "jwks_uri": f"{ISSUER}/protocol/openid-connect/certs",
    }
    document.update(overrides)
    return document


def test_adapter_runs_code_refresh_revoke_and_cached_jwks_without_leakage() -> None:
    requests: list[httpx.Request] = []
    jwks_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal jwks_calls
        requests.append(request)
        assert request.headers["accept-encoding"] == "identity"
        path = request.url.path
        if path.endswith("/.well-known/openid-configuration"):
            return _json_response(_discovery())
        if path.endswith("/certs"):
            jwks_calls += 1
            return _json_response(
                {"keys": [{"kid": "kid-1", "kty": "RSA", "use": "sig"}]}
            )
        form = parse_qs(request.content.decode())
        if path.endswith("/token") and form["grant_type"] == [
            "authorization_code"
        ]:
            assert form == {
                "client_id": ["flowpilot-web"],
                "client_secret": [SECRET],
                "code": ["one-time-code"],
                "code_verifier": ["v" * 64],
                "grant_type": ["authorization_code"],
                "redirect_uri": [REDIRECT],
            }
            return _json_response(
                {
                    "id_token": ID_TOKEN,
                    "access_token": ACCESS_TOKEN,
                    "refresh_token": REFRESH_TOKEN,
                }
            )
        if path.endswith("/token"):
            assert form["grant_type"] == ["refresh_token"]
            assert form["refresh_token"] == [REFRESH_TOKEN]
            return _json_response(
                {
                    "access_token": ROTATED_ACCESS_TOKEN,
                    "refresh_token": ROTATED_REFRESH_TOKEN,
                }
            )
        assert path.endswith("/revoke")
        assert form["token"] == [ROTATED_REFRESH_TOKEN]
        assert form["token_type_hint"] == ["refresh_token"]
        return httpx.Response(200)

    provider = KeycloakOidcProvider(
        _config(),
        transport=httpx.MockTransport(handler),
    )

    async def scenario() -> None:
        authorization = await provider.authorization_url(
            state="state-value",
            nonce="nonce-value",
            pkce_challenge="challenge-value",
            redirect_uri=REDIRECT,
        )
        query = parse_qs(urlsplit(authorization).query)
        assert query == {
            "client_id": ["flowpilot-web"],
            "code_challenge": ["challenge-value"],
            "code_challenge_method": ["S256"],
            "nonce": ["nonce-value"],
            "redirect_uri": [REDIRECT],
            "response_type": ["code"],
            "scope": ["openid"],
            "state": ["state-value"],
        }
        assert SECRET not in authorization
        exchanged = await provider.exchange_code(
            code="one-time-code",
            pkce_verifier="v" * 64,
            redirect_uri=REDIRECT,
        )
        assert exchanged.id_token == ID_TOKEN
        assert exchanged.access_token == ACCESS_TOKEN
        refreshed = await provider.refresh(refresh_token=REFRESH_TOKEN)
        assert refreshed.access_token == ROTATED_ACCESS_TOKEN
        assert refreshed.refresh_token == ROTATED_REFRESH_TOKEN
        assert refreshed.id_token is None
        first = await provider.resolve(
            issuer=ISSUER,
            key_id="kid-1",
            force_refresh=False,
        )
        second = await provider.resolve(
            issuer=ISSUER,
            key_id="kid-1",
            force_refresh=False,
        )
        forced = await provider.resolve(
            issuer=ISSUER,
            key_id="kid-1",
            force_refresh=True,
        )
        assert first == second == forced
        await provider.revoke(refresh_token=ROTATED_REFRESH_TOKEN)

    asyncio.run(scenario())
    assert jwks_calls == 2
    combined = repr(provider) + repr(_config())
    for secret in (
        SECRET,
        ID_TOKEN,
        ACCESS_TOKEN,
        REFRESH_TOKEN,
        ROTATED_ACCESS_TOKEN,
        ROTATED_REFRESH_TOKEN,
    ):
        assert secret not in combined
    assert len(requests) == 6


@pytest.mark.parametrize(
    "override",
    [
        {"issuer": "http://localhost:18081/realms/flowpilot-local"},
        {"issuer": "http://keycloak.internal/realms/flowpilot-local"},
        {"issuer": "https://user@example.test/realms/flowpilot-local"},
        {"issuer": "https://example.test/realms/flowpilot?tenant=a"},
        {"redirect_uri": "http://example.test/callback"},
        {"timeout_seconds": 0.01},
        {"max_response_bytes": 1024},
    ],
)
def test_config_rejects_unsafe_urls_and_resource_limits(
    override: dict[str, object],
) -> None:
    with pytest.raises(ValueError) as rejected:
        _config(**override)
    assert SECRET not in str(rejected.value)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://attacker.test/token",
        "http://127.0.0.1:18082/token",
        "http://127.0.0.1:18081/token?next=attacker",
        "http://user@127.0.0.1:18081/token",
        "http://127.0.0.1:18081/token#fragment",
    ],
)
def test_discovery_rejects_endpoint_origin_and_url_injection(endpoint: str) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _json_response(_discovery(token_endpoint=endpoint))

    provider = KeycloakOidcProvider(
        _config(),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ApiError) as rejected:
        asyncio.run(
            provider.authorization_url(
                state="state",
                nonce="nonce",
                pkce_challenge="challenge",
                redirect_uri=REDIRECT,
            )
        )
    assert rejected.value.status_code == 503
    assert calls == 1


@pytest.mark.parametrize(
    "token_response",
    [
        lambda: httpx.Response(302, headers={"Location": "https://attacker.test"}),
        lambda: httpx.Response(500, content=SECRET.encode()),
        lambda: httpx.Response(200, headers={"Content-Type": "text/html"}, text="{}"),
        lambda: httpx.Response(
            200,
            headers={
                "Content-Type": "application/json",
                "Content-Encoding": "gzip",
            },
            content=b"{}",
        ),
        lambda: httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=b"not-json",
        ),
        lambda: _json_response(["not", "an", "object"]),
        lambda: _json_response({"access_token": ACCESS_TOKEN}),
        lambda: httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=b"x" * 4097,
        ),
    ],
)
def test_token_endpoint_protocol_failures_are_stable_single_attempt(
    token_response: Callable[[], httpx.Response],
) -> None:
    token_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return _json_response(_discovery())
        token_calls += 1
        return token_response()

    provider = KeycloakOidcProvider(
        _config(),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ApiError) as rejected:
        asyncio.run(
            provider.exchange_code(
                code="sensitive-code",
                pkce_verifier="v" * 64,
                redirect_uri=REDIRECT,
            )
        )
    assert rejected.value.status_code == 503
    assert token_calls == 1
    combined = str(rejected.value) + repr(rejected.value)
    assert SECRET not in combined
    assert "sensitive-code" not in combined


def test_token_rejection_timeout_and_unrotated_refresh_are_fail_closed() -> None:
    mode = "reject"
    token_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return _json_response(_discovery())
        token_calls += 1
        if mode == "reject":
            return _json_response(
                {"error": "invalid_grant", "error_description": SECRET},
                status=400,
            )
        if mode == "timeout":
            raise httpx.ReadTimeout("sensitive timeout", request=request)
        return _json_response(
            {
                "access_token": ROTATED_ACCESS_TOKEN,
                "refresh_token": REFRESH_TOKEN,
            }
        )

    provider = KeycloakOidcProvider(
        _config(),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ApiError) as rejected:
        asyncio.run(
            provider.exchange_code(
                code="code",
                pkce_verifier="v" * 64,
                redirect_uri=REDIRECT,
            )
        )
    assert rejected.value.status_code == 401
    mode = "timeout"
    with pytest.raises(ApiError) as timeout:
        asyncio.run(provider.refresh(refresh_token=REFRESH_TOKEN))
    assert timeout.value.status_code == 503
    mode = "unrotated"
    with pytest.raises(ApiError) as unrotated:
        asyncio.run(provider.refresh(refresh_token=REFRESH_TOKEN))
    assert unrotated.value.status_code == 401
    assert token_calls == 3
    combined = "".join(
        str(error.value) + repr(error.value)
        for error in (rejected, timeout, unrotated)
    )
    assert SECRET not in combined
    assert REFRESH_TOKEN not in combined


def test_jwks_rejects_duplicate_key_ids() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return _json_response(_discovery())
        return _json_response(
            {
                "keys": [
                    {"kid": "duplicate", "kty": "RSA"},
                    {"kid": "duplicate", "kty": "RSA"},
                ]
            }
        )

    provider = KeycloakOidcProvider(
        _config(),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ApiError):
        asyncio.run(
            provider.resolve(
                issuer=ISSUER,
                key_id="duplicate",
                force_refresh=False,
            )
        )
