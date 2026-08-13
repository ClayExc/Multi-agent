"""Verify the M8 production OIDC BFF against a disposable real Keycloak."""

from __future__ import annotations

import argparse
import asyncio
import html
import json
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import httpx
from flowpilot_api import LocalKeycloakSettings, create_local_keycloak_app


class LoginFormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.action: str | None = None
        self.hidden_fields: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "form" and self.action is None:
            self.action = values.get("action")
        if tag == "input" and values.get("type") == "hidden":
            name, value = values.get("name"), values.get("value")
            if name is not None and value is not None:
                self.hidden_fields[name] = value


def _loopback_cookie_header(client: httpx.Client, target: str) -> str:
    return "; ".join(
        f"{cookie.name}={cookie.value}"
        for cookie in client.cookies.jar
        if cookie.secure and target.startswith("http://127.0.0.1:")
    )


@dataclass(frozen=True, slots=True)
class LiveIdentityResult:
    production_bootstrap: bool
    code_pkce_callbacks: int
    opaque_cookie_sessions: int
    same_second_refreshes: int
    concurrent_refresh_successes: int
    concurrent_refresh_rejections: int
    logout_successes: int
    revoked_session_rejections: int
    cross_tenant_successful_reads: int
    model_calls: int
    tool_calls: int


def _cookie(response: httpx.Response, name: str) -> str:
    for value in response.headers.get_list("set-cookie"):
        if value.startswith(name + "="):
            return value.split(";", 1)[0]
    raise AssertionError(f"response did not set {name}")


def _keycloak_login(location: str, username: str, password: str) -> str:
    with httpx.Client(follow_redirects=False, timeout=20.0) as browser:
        page = browser.get(location)
        if page.status_code != 200:
            raise AssertionError("Keycloak authorization page was unavailable")
        parser = LoginFormParser()
        parser.feed(page.text)
        if parser.action is None:
            raise AssertionError("Keycloak login form omitted its action")
        form = dict(parser.hidden_fields)
        form.update({"username": username, "password": password, "credentialId": ""})
        action = urljoin(str(page.url), html.unescape(parser.action))
        result = browser.post(
            action,
            data=form,
            headers={"cookie": _loopback_cookie_header(browser, action)},
        )
        if result.status_code not in {302, 303} or "location" not in result.headers:
            raise AssertionError("Keycloak did not complete the browser login")
        return result.headers["location"]


async def _run(args: argparse.Namespace) -> LiveIdentityResult:
    settings = LocalKeycloakSettings(
        issuer=args.issuer,
        client_id="flowpilot-web",
        client_secret=args.client_secret,
        redirect_uri=args.redirect_uri,
        allow_insecure_loopback=True,
    )
    app = create_local_keycloak_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url=args.api_origin,
        follow_redirects=False,
    ) as api:
        login = await api.get("/v1/auth/login")
        if login.status_code != 302:
            raise AssertionError("production BFF did not begin login")
        transaction = _cookie(login, "__Host-flowpilot-login")
        callback_url = await asyncio.to_thread(
            _keycloak_login,
            login.headers["location"],
            args.username,
            args.password,
        )
        callback = await api.get(callback_url, headers={"cookie": transaction})
        if callback.status_code != 303:
            raise AssertionError("production BFF rejected the real callback")
        session = _cookie(callback, "__Host-flowpilot-session")
        if any(word in session.lower() for word in ("eyj", "token", "bearer")):
            raise AssertionError("browser cookie is not opaque")

        refresh = await api.post("/v1/auth/refresh", headers={"cookie": session})
        if refresh.status_code != 200:
            raise AssertionError("same-second refresh failed")
        rotated = _cookie(refresh, "__Host-flowpilot-session")

        first, second = await asyncio.gather(
            api.post("/v1/auth/refresh", headers={"cookie": rotated}),
            api.post("/v1/auth/refresh", headers={"cookie": rotated}),
        )
        statuses = sorted((first.status_code, second.status_code))
        if statuses != [200, 401]:
            raise AssertionError("concurrent refresh was not single-winner")
        winner = first if first.status_code == 200 else second
        winner_cookie = _cookie(winner, "__Host-flowpilot-session")

        forbidden = await api.get(
            "/v1/tasks/task_tenant_a_private",
            headers={"cookie": winner_cookie, "x-tenant-id": "tenant-a"},
        )
        if forbidden.status_code != 403:
            raise AssertionError("cross-tenant identity input was not rejected")

        logout = await api.post("/v1/auth/logout", headers={"cookie": winner_cookie})
        if logout.status_code != 204:
            raise AssertionError("logout failed")
        rejected = await api.post("/v1/auth/refresh", headers={"cookie": winner_cookie})
        if rejected.status_code != 401:
            raise AssertionError("revoked browser session remained usable")

    return LiveIdentityResult(
        production_bootstrap=True,
        code_pkce_callbacks=1,
        opaque_cookie_sessions=1,
        same_second_refreshes=1,
        concurrent_refresh_successes=1,
        concurrent_refresh_rejections=1,
        logout_successes=1,
        revoked_session_rejections=1,
        cross_tenant_successful_reads=0,
        model_calls=0,
        tool_calls=0,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issuer", required=True)
    parser.add_argument("--api-origin", required=True)
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
        "M8_LIVE_IDENTITY_OK " + " ".join(f"{k}={v}" for k, v in asdict(result).items())
    )


if __name__ == "__main__":
    main()
