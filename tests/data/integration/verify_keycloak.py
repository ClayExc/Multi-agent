from __future__ import annotations

import base64
import hashlib
import html
import ipaddress
import json
import os
import secrets
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import httpx

REALM = "flowpilot-local"
WEB_CLIENT_ID = "flowpilot-web"
EXPECTED_FIXTURE_REVISION = "WP-081-a1-v1"
EXPECTED_CLIENTS = {
    "flowpilot-web",
    "flowpilot-api",
    "flowpilot-worker",
    "flowpilot-gateway",
}
EXPECTED_USERS = {
    "tenant-a-user",
    "tenant-a-approver",
    "tenant-b-user",
    "tenant-b-approver",
}


class VerificationError(RuntimeError):
    """Safe integration failure without response bodies or identity material."""


class LoginFormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.action: str | None = None
        self.hidden_fields: dict[str, str] = {}
        self._inside_login_form = False

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = dict(attrs)
        if tag == "form" and attributes.get("id") == "kc-form-login":
            self._inside_login_form = True
            self.action = attributes.get("action")
            return
        if tag != "input" or not self._inside_login_form:
            return
        name = attributes.get("name")
        value = attributes.get("value")
        if attributes.get("type") == "hidden" and name and value is not None:
            self.hidden_fields[name] = value

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self._inside_login_form:
            self._inside_login_form = False


@dataclass(frozen=True, slots=True)
class OidcEndpoints:
    issuer: str
    authorization: str
    token: str
    revocation: str


@dataclass(frozen=True, slots=True)
class AuthorizationCode:
    code: str
    verifier: str
    redirect_uri: str


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise VerificationError(f"required environment variable is missing: {name}")
    return value


def _loopback_cookie_header(browser: httpx.Client, target: str) -> str:
    """Model browser secure-cookie handling for a trustworthy loopback URL."""
    parsed = urlparse(target)
    host = parsed.hostname
    if parsed.scheme != "http" or host is None:
        raise VerificationError("local login action is not an HTTP loopback URL")
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError as exc:
        raise VerificationError("local login action has an invalid host") from exc
    if not loopback:
        raise VerificationError("local login action escaped the loopback host")
    cookie_pairs = [
        f"{cookie.name}={cookie.value}"
        for cookie in browser.cookies.jar
        if cookie.domain == host and parsed.path.startswith(cookie.path)
    ]
    if not cookie_pairs:
        raise VerificationError("Keycloak login did not establish a session cookie")
    return "; ".join(cookie_pairs)


def _expect_status(
    response: httpx.Response,
    expected: int | set[int],
    label: str,
) -> None:
    accepted = {expected} if isinstance(expected, int) else expected
    if response.status_code not in accepted:
        raise VerificationError(
            f"{label} returned status {response.status_code}; "
            f"expected {sorted(accepted)}"
        )


def _json_object(response: httpx.Response, label: str) -> dict[str, Any]:
    try:
        value = response.json()
    except ValueError as exc:
        raise VerificationError(f"{label} did not return JSON") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"{label} did not return a JSON object")
    return value


def _decode_claims(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise VerificationError("Keycloak returned a malformed JWT")
    encoded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        value = json.loads(base64.urlsafe_b64decode(encoded))
    except (ValueError, json.JSONDecodeError) as exc:
        raise VerificationError("Keycloak returned an invalid JWT payload") from exc
    if not isinstance(value, dict):
        raise VerificationError("Keycloak JWT payload is not an object")
    return value


def _audiences(claims: dict[str, Any]) -> set[str]:
    audience = claims.get("aud")
    if isinstance(audience, str):
        return {audience}
    if isinstance(audience, list) and all(
        isinstance(item, str) for item in audience
    ):
        return set(audience)
    raise VerificationError("Keycloak token has no valid audience claim")


def _discover(client: httpx.Client, base_url: str) -> OidcEndpoints:
    issuer = f"{base_url}/realms/{REALM}"
    response = client.get(f"{issuer}/.well-known/openid-configuration")
    _expect_status(response, 200, "OIDC discovery")
    document = _json_object(response, "OIDC discovery")
    if document.get("issuer") != issuer:
        raise VerificationError("OIDC discovery returned an unexpected issuer")
    try:
        authorization = str(document["authorization_endpoint"])
        token = str(document["token_endpoint"])
        revocation = str(document["revocation_endpoint"])
    except KeyError as exc:
        raise VerificationError("OIDC discovery omitted a required endpoint") from exc
    return OidcEndpoints(
        issuer=issuer,
        authorization=authorization,
        token=token,
        revocation=revocation,
    )


def _authorization_parameters(
    redirect_uri: str,
    verifier: str,
    state: str,
    nonce: str,
    *,
    challenge_method: str | None = "S256",
    untrusted_overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).decode("ascii").rstrip("=")
    parameters = {
        "client_id": WEB_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid",
        "state": state,
        "nonce": nonce,
    }
    if challenge_method is not None:
        parameters["code_challenge"] = challenge
        parameters["code_challenge_method"] = challenge_method
    if untrusted_overrides:
        parameters.update(untrusted_overrides)
    return parameters


def _obtain_authorization_code(
    endpoints: OidcEndpoints,
    *,
    redirect_uri: str,
    username: str,
    password: str,
    untrusted_overrides: dict[str, str] | None = None,
) -> AuthorizationCode:
    verifier = secrets.token_urlsafe(48)
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    parameters = _authorization_parameters(
        redirect_uri,
        verifier,
        state,
        nonce,
        untrusted_overrides=untrusted_overrides,
    )
    with httpx.Client(follow_redirects=False, timeout=20.0) as browser:
        response = browser.get(endpoints.authorization, params=parameters)
        _expect_status(response, 200, f"authorization page for {username}")
        parser = LoginFormParser()
        parser.feed(response.text)
        if parser.action is None:
            raise VerificationError("Keycloak login form has no action")
        credentials = dict(parser.hidden_fields)
        credentials.update(
            {
                "username": username,
                "password": password,
                "credentialId": "",
            }
        )
        action = urljoin(str(response.url), html.unescape(parser.action))
        login = browser.post(
            action,
            data=credentials,
            headers={"cookie": _loopback_cookie_header(browser, action)},
        )
    _expect_status(login, {302, 303}, f"authorization login for {username}")
    location = login.headers.get("location")
    if location is None:
        raise VerificationError("Keycloak login omitted the callback location")
    parsed = urlparse(location)
    expected = urlparse(redirect_uri)
    if (parsed.scheme, parsed.netloc, parsed.path) != (
        expected.scheme,
        expected.netloc,
        expected.path,
    ):
        raise VerificationError("Keycloak redirected to an unregistered callback")
    query = parse_qs(parsed.query)
    if query.get("state") != [state] or len(query.get("code", [])) != 1:
        raise VerificationError("authorization callback binding is invalid")
    return AuthorizationCode(
        code=query["code"][0],
        verifier=verifier,
        redirect_uri=redirect_uri,
    )


def _exchange_code(
    client: httpx.Client,
    endpoints: OidcEndpoints,
    authorization: AuthorizationCode,
    web_secret: str,
    *,
    verifier: str | None = None,
    redirect_uri: str | None = None,
    expected_status: int = 200,
) -> dict[str, Any] | None:
    response = client.post(
        endpoints.token,
        data={
            "grant_type": "authorization_code",
            "client_id": WEB_CLIENT_ID,
            "client_secret": web_secret,
            "code": authorization.code,
            "code_verifier": verifier or authorization.verifier,
            "redirect_uri": redirect_uri or authorization.redirect_uri,
        },
    )
    _expect_status(response, expected_status, "authorization code exchange")
    return (
        _json_object(response, "authorization code exchange")
        if expected_status == 200
        else None
    )


def _refresh(
    client: httpx.Client,
    endpoints: OidcEndpoints,
    refresh_token: str,
    web_secret: str,
    *,
    expected_status: int = 200,
) -> dict[str, Any] | None:
    response = client.post(
        endpoints.token,
        data={
            "grant_type": "refresh_token",
            "client_id": WEB_CLIENT_ID,
            "client_secret": web_secret,
            "refresh_token": refresh_token,
        },
    )
    _expect_status(response, expected_status, "refresh token exchange")
    return (
        _json_object(response, "refresh token exchange")
        if expected_status == 200
        else None
    )


def _service_token(
    client: httpx.Client,
    endpoints: OidcEndpoints,
    *,
    client_id: str,
    secret: str | None,
    expected_status: int,
) -> dict[str, Any] | None:
    data = {"grant_type": "client_credentials", "client_id": client_id}
    if secret is not None:
        data["client_secret"] = secret
    response = client.post(endpoints.token, data=data)
    _expect_status(response, expected_status, f"client credentials for {client_id}")
    return (
        _json_object(response, f"client credentials for {client_id}")
        if expected_status == 200
        else None
    )


def _admin_token(client: httpx.Client, base_url: str) -> str:
    response = client.post(
        f"{base_url}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": _required_env("KEYCLOAK_ADMIN"),
            "password": _required_env("KEYCLOAK_ADMIN_PASSWORD"),
        },
    )
    _expect_status(response, 200, "bootstrap admin login")
    token = _json_object(response, "bootstrap admin login").get("access_token")
    if not isinstance(token, str):
        raise VerificationError("bootstrap admin login omitted access_token")
    return token


def _fixture_fingerprint(client: httpx.Client, base_url: str) -> tuple[str, str]:
    token = _admin_token(client, base_url)
    headers = {"authorization": f"Bearer {token}"}
    realm_response = client.get(f"{base_url}/admin/realms/{REALM}", headers=headers)
    _expect_status(realm_response, 200, "realm admin read")
    realm = _json_object(realm_response, "realm admin read")
    attributes = realm.get("attributes")
    if not isinstance(attributes, dict) or attributes.get(
        "flowpilot.fixture.revision"
    ) != EXPECTED_FIXTURE_REVISION:
        raise VerificationError("realm fixture revision is missing or stale")

    clients_response = client.get(
        f"{base_url}/admin/realms/{REALM}/clients",
        headers=headers,
        params={"max": "100"},
    )
    users_response = client.get(
        f"{base_url}/admin/realms/{REALM}/users",
        headers=headers,
        params={"max": "100"},
    )
    _expect_status(clients_response, 200, "realm clients read")
    _expect_status(users_response, 200, "realm users read")
    client_rows = clients_response.json()
    user_rows = users_response.json()
    if not isinstance(client_rows, list) or not isinstance(user_rows, list):
        raise VerificationError("realm admin list response is malformed")
    selected_clients = {
        row["clientId"]: row["id"]
        for row in client_rows
        if isinstance(row, dict) and row.get("clientId") in EXPECTED_CLIENTS
    }
    selected_users = {
        row["username"]: row["id"]
        for row in user_rows
        if isinstance(row, dict) and row.get("username") in EXPECTED_USERS
    }
    if set(selected_clients) != EXPECTED_CLIENTS:
        raise VerificationError("realm client fixture is incomplete")
    if set(selected_users) != EXPECTED_USERS:
        raise VerificationError("realm user fixture is incomplete")
    fingerprint_input = json.dumps(
        {
            "realm": realm.get("id"),
            "clients": selected_clients,
            "users": selected_users,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    fingerprint = "sha256:" + hashlib.sha256(fingerprint_input).hexdigest()
    return fingerprint, token


def _logout_user(
    client: httpx.Client,
    base_url: str,
    admin_token: str,
    username: str,
) -> None:
    headers = {"authorization": f"Bearer {admin_token}"}
    response = client.get(
        f"{base_url}/admin/realms/{REALM}/users",
        headers=headers,
        params={"username": username, "exact": "true"},
    )
    _expect_status(response, 200, "admin user lookup")
    rows = response.json()
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise VerificationError("admin user lookup was not exact")
    user_id = rows[0].get("id")
    if not isinstance(user_id, str):
        raise VerificationError("admin user lookup omitted id")
    logout = client.post(
        f"{base_url}/admin/realms/{REALM}/users/{user_id}/logout",
        headers=headers,
    )
    _expect_status(logout, 204, "admin user session logout")


def _assert_user_claims(
    token_response: dict[str, Any],
    *,
    tenant_id: str,
    group_path: str,
    approver: bool,
) -> dict[str, Any]:
    access_token = token_response.get("access_token")
    refresh_token = token_response.get("refresh_token")
    if not isinstance(access_token, str) or not isinstance(refresh_token, str):
        raise VerificationError("user token response omitted required tokens")
    claims = _decode_claims(access_token)
    if claims.get("tenant_id") != tenant_id:
        raise VerificationError("user token tenant claim is invalid")
    if claims.get("azp") != WEB_CLIENT_ID:
        raise VerificationError("user token authorized party is invalid")
    if _audiences(claims) != {"flowpilot-api"}:
        raise VerificationError("user token audience is not exact")
    groups = claims.get("groups")
    if groups != [group_path]:
        raise VerificationError("user token group binding is not exact")
    realm_access = claims.get("realm_access")
    roles = realm_access.get("roles") if isinstance(realm_access, dict) else None
    if not isinstance(roles, list) or "flowpilot-user" not in roles:
        raise VerificationError("user token omitted the user role")
    if ("flowpilot-approver" in roles) is not approver:
        raise VerificationError("user token approver role is invalid")
    return claims


def _assert_authorization_rejected(
    client: httpx.Client,
    endpoints: OidcEndpoints,
    redirect_uri: str,
    *,
    client_id: str = WEB_CLIENT_ID,
    challenge_method: str | None = "S256",
    allow_registered_error_redirect: bool = False,
) -> None:
    verifier = secrets.token_urlsafe(48)
    parameters = _authorization_parameters(
        redirect_uri,
        verifier,
        secrets.token_urlsafe(24),
        secrets.token_urlsafe(24),
        challenge_method=challenge_method,
    )
    parameters["client_id"] = client_id
    response = client.get(endpoints.authorization, params=parameters)
    if response.status_code == 400:
        return
    _expect_status(response, 302, "invalid authorization request")
    location = response.headers.get("location", "")
    parsed = urlparse(location)
    query = parse_qs(parsed.query)
    if "code" in query or "error" not in query:
        raise VerificationError("invalid authorization request was not safely rejected")
    callback = urlparse(redirect_uri)
    if not allow_registered_error_redirect or (
        parsed.scheme,
        parsed.netloc,
        parsed.path,
    ) != (callback.scheme, callback.netloc, callback.path):
        raise VerificationError(
            "invalid authorization request reached an unsafe redirect"
        )


def main() -> None:
    base_url = _required_env("FLOWPILOT_TEST_KEYCLOAK_URL").rstrip("/")
    redirect_uri = _required_env("FLOWPILOT_OIDC_REDIRECT_URI")
    web_secret = _required_env("KEYCLOAK_WEB_CLIENT_SECRET")
    worker_secret = _required_env("KEYCLOAK_WORKER_CLIENT_SECRET")
    gateway_secret = _required_env("KEYCLOAK_GATEWAY_CLIENT_SECRET")
    user_passwords = {
        "tenant-a-user": _required_env("KEYCLOAK_TENANT_A_USER_PASSWORD"),
        "tenant-b-approver": _required_env(
            "KEYCLOAK_TENANT_B_APPROVER_PASSWORD"
        ),
    }

    with httpx.Client(follow_redirects=False, timeout=20.0) as client:
        endpoints = _discover(client, base_url)
        fingerprint, admin_token = _fixture_fingerprint(client, base_url)

        _assert_authorization_rejected(
            client,
            endpoints,
            "http://127.0.0.1:1/unregistered",
        )
        _assert_authorization_rejected(
            client,
            endpoints,
            redirect_uri,
            client_id="missing-client",
        )
        _assert_authorization_rejected(
            client,
            endpoints,
            redirect_uri,
            challenge_method=None,
            allow_registered_error_redirect=True,
        )
        _assert_authorization_rejected(
            client,
            endpoints,
            redirect_uri,
            challenge_method="plain",
            allow_registered_error_redirect=True,
        )

        tenant_a_code = _obtain_authorization_code(
            endpoints,
            redirect_uri=redirect_uri,
            username="tenant-a-user",
            password=user_passwords["tenant-a-user"],
            untrusted_overrides={
                "audience": "wrong-audience",
                "tenant_id": "tenant-b",
            },
        )
        tenant_a_tokens = _exchange_code(
            client,
            endpoints,
            tenant_a_code,
            web_secret,
        )
        assert tenant_a_tokens is not None
        tenant_a_claims = _assert_user_claims(
            tenant_a_tokens,
            tenant_id="tenant-a",
            group_path="/tenants/tenant-a/users",
            approver=False,
        )
        if "wrong-audience" in _audiences(tenant_a_claims):
            raise VerificationError("request parameters changed the token audience")

        refresh_token = tenant_a_tokens["refresh_token"]
        refreshed = _refresh(
            client,
            endpoints,
            refresh_token,
            web_secret,
        )
        assert refreshed is not None
        _assert_user_claims(
            refreshed,
            tenant_id="tenant-a",
            group_path="/tenants/tenant-a/users",
            approver=False,
        )
        rotated_refresh = refreshed["refresh_token"]
        if rotated_refresh == refresh_token:
            raise VerificationError("refresh token rotation did not occur")
        _refresh(
            client,
            endpoints,
            refresh_token,
            web_secret,
            expected_status=400,
        )
        for _ in range(2):
            revoke = client.post(
                endpoints.revocation,
                data={
                    "client_id": WEB_CLIENT_ID,
                    "client_secret": web_secret,
                    "token": rotated_refresh,
                    "token_type_hint": "refresh_token",
                },
            )
            _expect_status(revoke, 200, "refresh token revocation")
        _refresh(
            client,
            endpoints,
            rotated_refresh,
            web_secret,
            expected_status=400,
        )

        tenant_b_code = _obtain_authorization_code(
            endpoints,
            redirect_uri=redirect_uri,
            username="tenant-b-approver",
            password=user_passwords["tenant-b-approver"],
        )
        tenant_b_tokens = _exchange_code(
            client,
            endpoints,
            tenant_b_code,
            web_secret,
        )
        assert tenant_b_tokens is not None
        _assert_user_claims(
            tenant_b_tokens,
            tenant_id="tenant-b",
            group_path="/tenants/tenant-b/approvers",
            approver=True,
        )
        _logout_user(
            client,
            base_url,
            admin_token,
            "tenant-b-approver",
        )
        _refresh(
            client,
            endpoints,
            tenant_b_tokens["refresh_token"],
            web_secret,
            expected_status=400,
        )

        wrong_verifier_code = _obtain_authorization_code(
            endpoints,
            redirect_uri=redirect_uri,
            username="tenant-a-user",
            password=user_passwords["tenant-a-user"],
        )
        _exchange_code(
            client,
            endpoints,
            wrong_verifier_code,
            web_secret,
            verifier=secrets.token_urlsafe(48),
            expected_status=400,
        )
        wrong_redirect_code = _obtain_authorization_code(
            endpoints,
            redirect_uri=redirect_uri,
            username="tenant-a-user",
            password=user_passwords["tenant-a-user"],
        )
        _exchange_code(
            client,
            endpoints,
            wrong_redirect_code,
            web_secret,
            redirect_uri="http://127.0.0.1:1/unregistered",
            expected_status=400,
        )
        expired_code = _obtain_authorization_code(
            endpoints,
            redirect_uri=redirect_uri,
            username="tenant-a-user",
            password=user_passwords["tenant-a-user"],
        )
        time.sleep(6)
        _exchange_code(
            client,
            endpoints,
            expired_code,
            web_secret,
            expected_status=400,
        )

        worker = _service_token(
            client,
            endpoints,
            client_id="flowpilot-worker",
            secret=worker_secret,
            expected_status=200,
        )
        gateway = _service_token(
            client,
            endpoints,
            client_id="flowpilot-gateway",
            secret=gateway_secret,
            expected_status=200,
        )
        assert worker is not None and gateway is not None
        if "refresh_token" in worker or "refresh_token" in gateway:
            raise VerificationError("service client received a refresh token")
        workload_expectations = (
            (worker, "flowpilot-worker", "worker", "mcp://flowpilot-gateway"),
            (
                gateway,
                "flowpilot-gateway",
                "gateway",
                "mcp://flowpilot-upstream",
            ),
        )
        for response, client_id, kind, audience in workload_expectations:
            access_token = response.get("access_token")
            if not isinstance(access_token, str):
                raise VerificationError("service client omitted access_token")
            claims = _decode_claims(access_token)
            if claims.get("azp") != client_id:
                raise VerificationError("service token authorized party is invalid")
            if claims.get("workload_kind") != kind:
                raise VerificationError("service token workload kind is invalid")
            if _audiences(claims) != {audience}:
                raise VerificationError("service token audience is not exact")
            if "tenant_id" in claims or "groups" in claims:
                raise VerificationError("service token inherited user tenant claims")

        _service_token(
            client,
            endpoints,
            client_id="flowpilot-worker",
            secret=None,
            expected_status=401,
        )
        _service_token(
            client,
            endpoints,
            client_id="flowpilot-worker",
            secret=gateway_secret,
            expected_status=401,
        )
        _service_token(
            client,
            endpoints,
            client_id="flowpilot-gateway",
            secret=worker_secret,
            expected_status=401,
        )
        _service_token(
            client,
            endpoints,
            client_id="flowpilot-api",
            secret=None,
            expected_status=401,
        )
        password_grant = client.post(
            endpoints.token,
            data={
                "grant_type": "password",
                "client_id": WEB_CLIENT_ID,
                "client_secret": web_secret,
                "username": "tenant-a-user",
                "password": user_passwords["tenant-a-user"],
            },
        )
        _expect_status(password_grant, 400, "disabled password grant")

    print(
        "KEYCLOAK_FIXTURE_OK "
        f"realm={REALM} clients={len(EXPECTED_CLIENTS)} "
        f"users={len(EXPECTED_USERS)} fingerprint={fingerprint} "
        "user_flows=2 service_flows=2 refresh_rotation=1 revocations=2 "
        "negative_cases=13"
    )


if __name__ == "__main__":
    try:
        main()
    except VerificationError as exc:
        raise SystemExit(f"KEYCLOAK_FIXTURE_FAIL {exc}") from exc
