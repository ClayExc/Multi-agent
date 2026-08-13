from __future__ import annotations

import asyncio
import hmac
import ipaddress
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlencode, urlsplit

import httpx

from .errors import ApiError, ApiErrorCode
from .oidc import OidcCodeExchange, OidcRefreshResult

_JSON_TYPES = ("application/json",)
_MAX_TOKEN_LENGTH = 32768


@dataclass(frozen=True, slots=True, repr=False)
class KeycloakOidcConfig:
    issuer: str
    client_id: str
    client_secret: str
    redirect_uri: str
    allow_insecure_loopback: bool = False
    timeout_seconds: float = 5.0
    max_response_bytes: int = 131072
    max_jwks_keys: int = 64

    def __post_init__(self) -> None:
        issuer = self.issuer.rstrip("/")
        if not issuer or not self.client_id or not self.client_secret:
            raise ValueError("OIDC provider configuration is incomplete")
        if not self.redirect_uri:
            raise ValueError("OIDC redirect URI is required")
        _validate_base_url(
            issuer,
            field="OIDC issuer",
            allow_insecure_loopback=self.allow_insecure_loopback,
        )
        _validate_redirect_uri(
            self.redirect_uri,
            allow_insecure_loopback=self.allow_insecure_loopback,
        )
        if not 0.1 <= self.timeout_seconds <= 30:
            raise ValueError("OIDC timeout must be within 0.1..30 seconds")
        if not 4096 <= self.max_response_bytes <= 1048576:
            raise ValueError("OIDC response limit must be within 4096..1048576 bytes")
        if not 1 <= self.max_jwks_keys <= 256:
            raise ValueError("OIDC JWKS key limit must be within 1..256")
        object.__setattr__(self, "issuer", issuer)

    def __repr__(self) -> str:
        return (
            "KeycloakOidcConfig(issuer="
            f"{self.issuer!r}, client_id={self.client_id!r}, "
            "client_secret=<redacted>, "
            f"redirect_uri={self.redirect_uri!r}, "
            f"allow_insecure_loopback={self.allow_insecure_loopback!r}, "
            f"timeout_seconds={self.timeout_seconds!r}, "
            f"max_response_bytes={self.max_response_bytes!r}, "
            f"max_jwks_keys={self.max_jwks_keys!r})"
        )


@dataclass(frozen=True, slots=True)
class _OidcEndpoints:
    authorization: str
    token: str
    revocation: str
    jwks: str


class KeycloakOidcProvider:
    """Strict local Keycloak HTTP adapter and JWKS source.

    The adapter transports opaque credentials only. JWT signature, claims,
    identity mapping, nonce, and refresh lineage remain owned by S3.
    """

    def __init__(
        self,
        config: KeycloakOidcConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport
        self._discovery: _OidcEndpoints | None = None
        self._jwks: dict[str, Mapping[str, object]] | None = None
        self._discovery_lock = asyncio.Lock()
        self._jwks_lock = asyncio.Lock()

    def __repr__(self) -> str:
        return f"KeycloakOidcProvider(issuer={self._config.issuer!r})"

    async def authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        pkce_challenge: str,
        redirect_uri: str,
    ) -> str:
        _require_bounded(state, "OIDC state", 512)
        _require_bounded(nonce, "OIDC nonce", 512)
        _require_bounded(pkce_challenge, "OIDC PKCE challenge", 256)
        self._assert_redirect_uri(redirect_uri)
        endpoint = (await self._endpoints()).authorization
        query = urlencode(
            {
                "client_id": self._config.client_id,
                "code_challenge": pkce_challenge,
                "code_challenge_method": "S256",
                "nonce": nonce,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": "openid",
                "state": state,
            }
        )
        return f"{endpoint}?{query}"

    async def exchange_code(
        self,
        *,
        code: str,
        pkce_verifier: str,
        redirect_uri: str,
    ) -> OidcCodeExchange:
        _require_bounded(code, "OIDC authorization code", 4096)
        _require_bounded(pkce_verifier, "OIDC PKCE verifier", 256)
        self._assert_redirect_uri(redirect_uri)
        endpoints = await self._endpoints()
        payload = await self._post_token_form(
            endpoints.token,
            data={
                "client_id": self._config.client_id,
                "client_secret": self._config.client_secret,
                "code": code,
                "code_verifier": pkce_verifier,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
            invalid_code=ApiErrorCode.AUTH_FLOW_INVALID,
            invalid_message="OIDC authorization code was rejected",
        )
        return OidcCodeExchange(
            id_token=_token_field(payload, "id_token"),
            access_token=_token_field(payload, "access_token"),
            refresh_token=_token_field(payload, "refresh_token"),
        )

    async def refresh(self, *, refresh_token: str) -> OidcRefreshResult:
        _require_bounded(refresh_token, "OIDC refresh token", _MAX_TOKEN_LENGTH)
        endpoints = await self._endpoints()
        payload = await self._post_token_form(
            endpoints.token,
            data={
                "client_id": self._config.client_id,
                "client_secret": self._config.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            invalid_code=ApiErrorCode.AUTHENTICATION_INVALID,
            invalid_message="OIDC browser session refresh was rejected",
        )
        rotated = _token_field(payload, "refresh_token")
        if hmac.compare_digest(rotated, refresh_token):
            raise ApiError(
                ApiErrorCode.AUTHENTICATION_INVALID,
                "OIDC refresh token was not rotated",
                status_code=401,
            )
        optional_id = payload.get("id_token")
        if optional_id is not None:
            optional_id = _token_value(optional_id, "id_token")
        return OidcRefreshResult(
            access_token=_token_field(payload, "access_token"),
            refresh_token=rotated,
            id_token=optional_id,
        )

    async def revoke(self, *, refresh_token: str) -> None:
        _require_bounded(refresh_token, "OIDC refresh token", _MAX_TOKEN_LENGTH)
        endpoint = (await self._endpoints()).revocation
        await self._request(
            "POST",
            endpoint,
            data={
                "client_id": self._config.client_id,
                "client_secret": self._config.client_secret,
                "token": refresh_token,
                "token_type_hint": "refresh_token",
            },
            expected_statuses=frozenset({200, 204}),
            read_json=False,
            invalid_code=None,
            invalid_message="",
        )

    async def resolve(
        self,
        *,
        issuer: str,
        key_id: str,
        force_refresh: bool,
    ) -> Mapping[str, object] | None:
        if issuer != self._config.issuer or not key_id or len(key_id) > 512:
            return None
        keys = await self._load_jwks(force_refresh=force_refresh)
        return keys.get(key_id)

    async def _endpoints(self) -> _OidcEndpoints:
        cached = self._discovery
        if cached is not None:
            return cached
        async with self._discovery_lock:
            cached = self._discovery
            if cached is not None:
                return cached
            document = await self._request_json(
                "GET",
                f"{self._config.issuer}/.well-known/openid-configuration",
            )
            if document.get("issuer") != self._config.issuer:
                raise _dependency_error("OIDC discovery issuer is invalid")
            endpoints = _OidcEndpoints(
                authorization=self._endpoint(document, "authorization_endpoint"),
                token=self._endpoint(document, "token_endpoint"),
                revocation=self._endpoint(document, "revocation_endpoint"),
                jwks=self._endpoint(document, "jwks_uri"),
            )
            self._discovery = endpoints
            return endpoints

    def _endpoint(self, document: Mapping[str, object], field: str) -> str:
        value = document.get(field)
        if not isinstance(value, str) or not value or len(value) > 2048:
            raise _dependency_error("OIDC discovery document is invalid")
        _validate_endpoint(value, issuer=self._config.issuer)
        return value

    async def _load_jwks(
        self,
        *,
        force_refresh: bool,
    ) -> dict[str, Mapping[str, object]]:
        if self._jwks is not None and not force_refresh:
            return self._jwks
        async with self._jwks_lock:
            if self._jwks is not None and not force_refresh:
                return self._jwks
            document = await self._request_json("GET", (await self._endpoints()).jwks)
            raw_keys = document.get("keys")
            if (
                not isinstance(raw_keys, list)
                or not raw_keys
                or len(raw_keys) > self._config.max_jwks_keys
            ):
                raise _dependency_error("OIDC JWKS document is invalid")
            selected: dict[str, Mapping[str, object]] = {}
            for raw_key in raw_keys:
                if not isinstance(raw_key, dict):
                    raise _dependency_error("OIDC JWKS document is invalid")
                key = cast(dict[str, object], raw_key)
                kid = key.get("kid")
                if not isinstance(kid, str) or not kid or kid in selected:
                    raise _dependency_error("OIDC JWKS document is invalid")
                selected[kid] = dict(key)
            self._jwks = selected
            return selected

    async def _post_token_form(
        self,
        endpoint: str,
        *,
        data: Mapping[str, str],
        invalid_code: ApiErrorCode,
        invalid_message: str,
    ) -> Mapping[str, object]:
        result = await self._request(
            "POST",
            endpoint,
            data=data,
            expected_statuses=frozenset({200}),
            read_json=True,
            invalid_code=invalid_code,
            invalid_message=invalid_message,
        )
        if result is None:
            raise _dependency_error("OIDC token response is invalid")
        return result

    async def _request_json(self, method: str, url: str) -> Mapping[str, object]:
        result = await self._request(
            method,
            url,
            data=None,
            expected_statuses=frozenset({200}),
            read_json=True,
            invalid_code=None,
            invalid_message="",
        )
        if result is None:
            raise _dependency_error("OIDC JSON response is invalid")
        return result

    async def _request(
        self,
        method: str,
        url: str,
        *,
        data: Mapping[str, str] | None,
        expected_statuses: frozenset[int],
        read_json: bool,
        invalid_code: ApiErrorCode | None,
        invalid_message: str,
    ) -> Mapping[str, object] | None:
        timeout = httpx.Timeout(self._config.timeout_seconds)
        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=timeout,
                transport=self._transport,
                trust_env=False,
            ) as client, client.stream(
                method,
                url,
                data=data,
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                },
            ) as response:
                if response.status_code not in expected_statuses:
                    if invalid_code is not None and 400 <= response.status_code < 500:
                        raise ApiError(
                            invalid_code,
                            invalid_message,
                            status_code=401,
                        )
                    raise _dependency_error("OIDC provider response was unsuccessful")
                if not read_json:
                    return None
                _assert_json_response_headers(
                    response.headers,
                    maximum=self._config.max_response_bytes,
                )
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > self._config.max_response_bytes:
                        raise _dependency_error("OIDC provider response is too large")
        except ApiError:
            raise
        except (httpx.HTTPError, OSError, UnicodeError, ValueError):
            raise _dependency_error("OIDC provider is unavailable") from None
        try:
            decoded: Any = json.loads(bytes(body))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise _dependency_error("OIDC provider response is invalid") from None
        if not isinstance(decoded, dict):
            raise _dependency_error("OIDC provider response is invalid")
        return cast(dict[str, object], decoded)

    def _assert_redirect_uri(self, redirect_uri: str) -> None:
        if not hmac.compare_digest(redirect_uri, self._config.redirect_uri):
            raise ApiError(
                ApiErrorCode.AUTH_FLOW_INVALID,
                "OIDC redirect URI does not match the configured callback",
                status_code=401,
            )


def _token_field(payload: Mapping[str, object], field: str) -> str:
    return _token_value(payload.get(field), field)


def _token_value(value: object, _field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > _MAX_TOKEN_LENGTH:
        raise _dependency_error("OIDC token response is invalid")
    return value


def _require_bounded(value: str, field: str, maximum: int) -> None:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"{field} is invalid")


def _assert_json_response_headers(headers: httpx.Headers, *, maximum: int) -> None:
    encoding = headers.get("content-encoding", "identity").strip().lower()
    if encoding != "identity":
        raise _dependency_error("OIDC provider response encoding is invalid")
    content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if not (
        content_type in _JSON_TYPES
        or (content_type.startswith("application/") and content_type.endswith("+json"))
    ):
        raise _dependency_error("OIDC provider response content type is invalid")
    length = headers.get("content-length")
    if length is not None:
        try:
            parsed = int(length)
        except ValueError:
            raise _dependency_error(
                "OIDC provider response length is invalid"
            ) from None
        if parsed < 0 or parsed > maximum:
            raise _dependency_error("OIDC provider response is too large")


def _validate_base_url(
    value: str,
    *,
    field: str,
    allow_insecure_loopback: bool,
) -> None:
    parsed = urlsplit(value)
    if (
        not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{field} is invalid")
    if parsed.scheme == "https":
        return
    if (
        parsed.scheme == "http"
        and allow_insecure_loopback
        and parsed.hostname is not None
        and _is_numeric_loopback(parsed.hostname)
    ):
        return
    raise ValueError(f"{field} must use HTTPS or explicit local loopback HTTP")


def _validate_redirect_uri(value: str, *, allow_insecure_loopback: bool) -> None:
    parsed = urlsplit(value)
    if (
        not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("OIDC redirect URI is invalid")
    if parsed.scheme == "https":
        return
    if (
        parsed.scheme == "http"
        and allow_insecure_loopback
        and parsed.hostname is not None
        and _is_numeric_loopback(parsed.hostname)
    ):
        return
    raise ValueError("OIDC redirect URI must use HTTPS or explicit local loopback HTTP")


def _validate_endpoint(value: str, *, issuer: str) -> None:
    parsed = urlsplit(value)
    expected = urlsplit(issuer)
    if (
        not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or _origin(parsed) != _origin(expected)
    ):
        raise _dependency_error("OIDC discovery endpoint is not allowed")


def _origin(value: Any) -> tuple[str, str, int]:
    scheme = value.scheme.lower()
    hostname = (value.hostname or "").lower()
    try:
        port = value.port
    except ValueError:
        raise _dependency_error("OIDC URL port is invalid") from None
    return scheme, hostname, port or (443 if scheme == "https" else 80)


def _is_numeric_loopback(hostname: str) -> bool:
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _dependency_error(message: str) -> ApiError:
    return ApiError(
        ApiErrorCode.DEPENDENCY_UNAVAILABLE,
        message,
        status_code=503,
        retryable=True,
    )
