"""Exercise production OIDC verification with real Keycloak-signed tokens."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import html
import json
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from flowpilot_api.bootstrap import _local_user_policy, _local_workload_policy
from flowpilot_api.keycloak import KeycloakOidcConfig, KeycloakOidcProvider
from flowpilot_api.oidc import (
    InMemoryOidcSessionStore,
    OidcCodeExchange,
    OidcLoginTransaction,
)
from flowpilot_security import OidcIdentityAdapter, UserClaimPolicy, oidc_nonce_digest


class _Form(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.action: str | None = None
        self.hidden: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "form" and self.action is None:
            self.action = values.get("action")
        if (
            tag == "input"
            and values.get("type") == "hidden"
            and values.get("name")
            and values.get("value") is not None
        ):
            self.hidden[str(values["name"])] = str(values["value"])


@dataclass(frozen=True, slots=True)
class CryptoResult:
    valid_pairs: int
    wrong_nonce_rejections: int
    nonce_replay_rejections: int
    token_swap_rejections: int
    wrong_audience_rejections: int
    tenant_mapping_rejections: int
    role_mapping_rejections: int
    real_jwks: bool
    raw_token_output_count: int


def _browser_code(url: str, redirect_uri: str, username: str, password: str) -> str:
    with httpx.Client(follow_redirects=False, timeout=20) as client:
        page = client.get(url)
        parser = _Form()
        parser.feed(page.text)
        if page.status_code != 200 or parser.action is None:
            raise AssertionError("Keycloak login page unavailable")
        values = dict(parser.hidden)
        values.update({"username": username, "password": password, "credentialId": ""})
        action = urljoin(str(page.url), html.unescape(parser.action))
        cookies = "; ".join(f"{c.name}={c.value}" for c in client.cookies.jar)
        response = client.post(action, data=values, headers={"cookie": cookies})
        location = response.headers.get("location", "")
        parsed, expected = urlparse(location), urlparse(redirect_uri)
        if response.status_code not in {302, 303} or parsed.path != expected.path:
            raise AssertionError("Keycloak authorization failed")
        codes = parse_qs(parsed.query).get("code", [])
        if len(codes) != 1:
            raise AssertionError("Keycloak callback omitted code")
        code: str = codes[0]
        return code


async def _tokens(
    provider: KeycloakOidcProvider, args: argparse.Namespace
) -> tuple[OidcCodeExchange, str]:
    verifier, nonce = secrets.token_urlsafe(48), secrets.token_urlsafe(24)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    url = await provider.authorization_url(
        state=secrets.token_urlsafe(24),
        nonce=nonce,
        pkce_challenge=challenge,
        redirect_uri=args.redirect_uri,
    )
    code = await asyncio.to_thread(
        _browser_code, url, args.redirect_uri, args.username, args.password
    )
    return await provider.exchange_code(
        code=code, pkce_verifier=verifier, redirect_uri=args.redirect_uri
    ), nonce


async def _adapter(
    provider: KeycloakOidcProvider,
    issuer: str,
    client: str,
    nonce: str,
    *,
    users: UserClaimPolicy | None = None,
) -> tuple[OidcIdentityAdapter, datetime]:
    now = datetime.now(UTC)
    store = InMemoryOidcSessionStore(clock=lambda: now)
    await store.create_login(
        secrets.token_urlsafe(12),
        OidcLoginTransaction(
            state_hash="sha256:" + "a" * 64,
            nonce=nonce,
            pkce_verifier=secrets.token_urlsafe(48),
            expires_at=now + timedelta(minutes=5),
        ),
        nonce_hash=oidc_nonce_digest(
            issuer=issuer, authorized_party=client, nonce=nonce
        ),
    )
    return OidcIdentityAdapter(
        jwks=provider,
        nonces=store,
        refresh_lineage=store,
        users=users or _local_user_policy(issuer, client),
        workloads=_local_workload_policy(issuer),
    ), now


async def _reject(call: Callable[[], Awaitable[object]]) -> int:
    try:
        await call()
    except Exception:
        return 1
    raise AssertionError("cryptographic negative was accepted")


async def _run(args: argparse.Namespace) -> CryptoResult:
    provider = KeycloakOidcProvider(
        KeycloakOidcConfig(
            issuer=args.issuer,
            client_id="flowpilot-web",
            client_secret=args.client_secret,
            redirect_uri=args.redirect_uri,
            allow_insecure_loopback=True,
        )
    )
    pair, nonce = await _tokens(provider, args)
    client = "flowpilot-web"

    adapter, now = await _adapter(provider, args.issuer, client, nonce)
    identity = await adapter.verify_user_token_pair(
        id_token=pair.id_token,
        access_token=pair.access_token,
        expected_nonce=nonce,
        now=now,
    )
    if identity.tenant_id != "tenant-a" or not identity.roles:
        raise AssertionError("valid signed identity was not mapped")
    replay = await _reject(
        lambda: adapter.verify_user_token_pair(
            id_token=pair.id_token,
            access_token=pair.access_token,
            expected_nonce=nonce,
            now=now,
        )
    )

    wrong, wrong_now = await _adapter(provider, args.issuer, client, nonce)
    wrong_nonce = await _reject(
        lambda: wrong.verify_user_token_pair(
            id_token=pair.id_token,
            access_token=pair.access_token,
            expected_nonce=nonce + "x",
            now=wrong_now,
        )
    )
    swapped, swap_now = await _adapter(provider, args.issuer, client, nonce)
    token_swap = await _reject(
        lambda: swapped.verify_user_token_pair(
            id_token=pair.access_token,
            access_token=pair.id_token,
            expected_nonce=nonce,
            now=swap_now,
        )
    )

    base = _local_user_policy(args.issuer, client)
    bad_audience = replace(base, token=replace(base.token, audience="wrong-audience"))
    audience_adapter, audience_now = await _adapter(
        provider, args.issuer, client, nonce, users=bad_audience
    )
    audience = await _reject(
        lambda: audience_adapter.verify_user_token_pair(
            id_token=pair.id_token,
            access_token=pair.access_token,
            expected_nonce=nonce,
            now=audience_now,
        )
    )
    bad_tenant = replace(base, tenant_mapping={"tenant-b": "tenant-b"})
    tenant_adapter, tenant_now = await _adapter(
        provider, args.issuer, client, nonce, users=bad_tenant
    )
    tenant = await _reject(
        lambda: tenant_adapter.verify_user_token_pair(
            id_token=pair.id_token,
            access_token=pair.access_token,
            expected_nonce=nonce,
            now=tenant_now,
        )
    )
    bad_role = replace(base, role_mapping={"/tenants/tenant-a/approvers": "approver"})
    role_adapter, role_now = await _adapter(
        provider, args.issuer, client, nonce, users=bad_role
    )
    role = await _reject(
        lambda: role_adapter.verify_user_token_pair(
            id_token=pair.id_token,
            access_token=pair.access_token,
            expected_nonce=nonce,
            now=role_now,
        )
    )
    return CryptoResult(
        1, wrong_nonce, replay, token_swap, audience, tenant, role, True, 0
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issuer", required=True)
    parser.add_argument("--redirect-uri", required=True)
    parser.add_argument("--client-secret", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(_run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(asdict(result), indent=2) + "\n", encoding="utf-8"
    )
    print(
        "M8_LIVE_CRYPTO_OK " + " ".join(f"{k}={v}" for k, v in asdict(result).items())
    )


if __name__ == "__main__":
    main()
