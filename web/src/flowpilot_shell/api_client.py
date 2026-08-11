"""API adapter boundary: read Task projections and submit non-approval commands.

The adapter is the shell's only path to the backend. It
- reads GET /v1/tasks/{task_id} (Task v1 projection)
- submits task.message.submit.v1 / task.retry.request.v1 via
  POST /v1/task-commands
- never issues approval write calls (task.approval.decide.v1 is out of
  scope by design; tests/experience asserts this statically)
- maps HTTP failures to typed Shell* errors so the shell can render the
  error panel and retry entry without fabricating data
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from .models import (
    ShellAuthenticationError,
    ShellAuthorizationError,
    ShellContractError,
    ShellError,
    ShellNotFoundError,
    ShellServerError,
    ShellUnavailableError,
    TaskView,
)

Transport = Callable[
    [str, str, dict[str, str], bytes | None], tuple[int, dict[str, str], bytes]
]


def _urllib_transport(base_url: str, *, timeout: float) -> Transport:
    def request(
        method: str, path: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, dict[str, str], bytes]:
        url = base_url.rstrip("/") + path
        payload = urllib.request.Request(url, data=body, method=method)
        for key, value in headers.items():
            payload.add_header(key, value)
        try:
            with urllib.request.urlopen(payload, timeout=timeout) as response:
                return (
                    response.status,
                    dict(response.headers.items()),
                    response.read(),
                )
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers.items()), exc.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ShellUnavailableError(f"API unreachable: {exc}") from exc

    return request


class ApiClient:
    """Cookie-authenticated client for Task reads and command intake.

    Tenant, subject, role and purpose are never client configuration. The API
    derives them from its opaque server session.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        *,
        transport: Transport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._base_url = base_url
        self._transport = transport or _urllib_transport(base_url, timeout=timeout)

    def get_task(
        self,
        task_id: str,
        *,
        cookie_header: str | None = None,
    ) -> TaskView:
        payload = self.get_task_mapping(task_id, cookie_header=cookie_header)
        try:
            return TaskView.from_mapping(payload)
        except ShellContractError as exc:
            raise ShellContractError(
                f"task projection {task_id} violates the v1 contract: {exc}"
            ) from exc

    def get_task_mapping(
        self,
        task_id: str,
        *,
        cookie_header: str | None = None,
    ) -> dict[str, Any]:
        """Return the validated JSON object for server-side command building."""

        headers = _browser_session_headers(cookie_header)
        status, _response_headers, body = self._transport(
            "GET", f"/v1/tasks/{task_id}", headers, None
        )
        payload = _parse_json_body(status, body)
        if status == 200:
            mapping = _require_json_object(payload, "task projection")
            TaskView.from_mapping(mapping)
            return mapping
        raise _map_error(status, payload)

    def submit_command(
        self,
        command: dict[str, Any],
        *,
        cookie_header: str | None = None,
    ) -> dict[str, Any]:
        """Submit a non-approval TaskCommand and return the acceptance body."""
        headers = {
            **_browser_session_headers(cookie_header),
            "Content-Type": "application/json",
        }
        body = json.dumps(command, ensure_ascii=False).encode("utf-8")
        status, _response_headers, raw = self._transport(
            "POST", "/v1/task-commands", headers, body
        )
        payload = _parse_json_body(status, raw)
        if status in (200, 202):
            return _require_json_object(payload, "command acceptance response")
        raise _map_error(status, payload)


def _parse_json_body(status: int, body: bytes) -> object:
    if not body:
        raise ShellContractError(f"empty response body for HTTP {status}")
    try:
        payload: object = json.loads(body.decode("utf-8"))
        return payload
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ShellContractError(f"response body is not JSON (HTTP {status})") from exc


def _require_json_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ShellContractError(f"{label} must be a JSON object")
    validated: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ShellContractError(f"{label} keys must be strings")
        validated[key] = item
    return validated


def _browser_session_headers(cookie_header: str | None) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if cookie_header is None:
        return headers
    if not cookie_header or "\r" in cookie_header or "\n" in cookie_header:
        raise ShellContractError("browser session cookie header is invalid")
    sessions = [
        item.strip().partition("=")
        for item in cookie_header.split(";")
        if item.strip().partition("=")[0] == "__Host-flowpilot-session"
    ]
    if len(sessions) > 1 or any(
        not separator or not value for _, separator, value in sessions
    ):
        raise ShellContractError("browser session cookie header is ambiguous")
    headers["Cookie"] = cookie_header
    return headers


def _map_error(status: int, payload: object) -> ShellError:
    envelope = _require_json_object(payload, f"error response for HTTP {status}")
    error = (
        _require_json_object(envelope["error"], "error response error")
        if "error" in envelope
        else {}
    )

    if "code" in error:
        raw_code = error["code"]
        if not isinstance(raw_code, str) or not raw_code:
            raise ShellContractError("error response error.code must be a string")

    message = f"API request failed (HTTP {status})"
    if "message" in error:
        raw_message = error["message"]
        if not isinstance(raw_message, str) or not raw_message:
            raise ShellContractError("error response error.message must be a string")

    retryable = status in {502, 503, 504}
    if "retryable" in error:
        raw_retryable = error["retryable"]
        if not isinstance(raw_retryable, bool):
            raise ShellContractError("error response error.retryable must be a boolean")
        retryable = raw_retryable
    if status == 404:
        return ShellNotFoundError("API resource was not found")
    if status == 401:
        return ShellAuthenticationError(
            "browser session is invalid",
            code="API_AUTHENTICATION_INVALID",
        )
    if status == 403:
        return ShellAuthorizationError(
            "browser session is not authorized",
            code="API_AUTHORIZATION_DENIED",
        )
    if status in {502, 503, 504} or (retryable and status >= 500):
        return ShellUnavailableError("API dependency is unavailable")
    if status in {400, 409, 422}:
        return ShellContractError(f"API request was rejected (HTTP {status})")
    return ShellServerError(
        message,
        code="API_SERVER_ERROR",
        retryable=retryable,
    )
