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
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from .governance import (
    AuditEventView,
    GovernanceCorrelationView,
    PolicyDecisionView,
    PolicyVersionView,
    SecurityEventView,
    parse_audit_event_page,
    parse_correlation,
    parse_policy_decision_page,
    parse_policy_version_page,
    parse_security_event_page,
)
from .knowledge import (
    KnowledgeConflictError,
    KnowledgeDiagnosticView,
    KnowledgeDocumentView,
    KnowledgeInputError,
    KnowledgeOperationReceiptView,
)
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

    def get_policy_versions(
        self,
        *,
        limit: int,
        cursor: str | None,
        cookie_header: str | None,
    ) -> tuple[tuple[PolicyVersionView, ...], str | None]:
        payload = self._get_governance(
            "/v1/governance/policy-versions",
            {"limit": limit, "cursor": cursor},
            cookie_header=cookie_header,
        )
        return parse_policy_version_page(payload)

    def get_policy_decisions(
        self,
        *,
        limit: int,
        cursor: str | None,
        task_id: str | None,
        cookie_header: str | None,
    ) -> tuple[tuple[PolicyDecisionView, ...], str | None]:
        payload = self._get_governance(
            "/v1/governance/policy-decisions",
            {"limit": limit, "cursor": cursor, "task_id": task_id},
            cookie_header=cookie_header,
        )
        return parse_policy_decision_page(payload)

    def get_audit_events(
        self,
        *,
        limit: int,
        cursor: str | None,
        task_id: str | None,
        correlation_id: str | None,
        occurred_after: str | None,
        occurred_before: str | None,
        cookie_header: str | None,
    ) -> tuple[tuple[AuditEventView, ...], str | None]:
        payload = self._get_governance(
            "/v1/governance/audit-events",
            {
                "limit": limit,
                "cursor": cursor,
                "task_id": task_id,
                "correlation_id": correlation_id,
                "occurred_after": occurred_after,
                "occurred_before": occurred_before,
            },
            cookie_header=cookie_header,
        )
        return parse_audit_event_page(payload)

    def get_security_events(
        self,
        *,
        limit: int,
        cursor: str | None,
        task_id: str | None,
        correlation_id: str | None,
        occurred_after: str | None,
        occurred_before: str | None,
        cookie_header: str | None,
    ) -> tuple[tuple[SecurityEventView, ...], str | None]:
        payload = self._get_governance(
            "/v1/governance/security-events",
            {
                "limit": limit,
                "cursor": cursor,
                "task_id": task_id,
                "correlation_id": correlation_id,
                "occurred_after": occurred_after,
                "occurred_before": occurred_before,
            },
            cookie_header=cookie_header,
        )
        return parse_security_event_page(payload)

    def get_governance_correlation(
        self,
        correlation_id: str,
        *,
        cookie_header: str | None,
    ) -> GovernanceCorrelationView:
        quoted = urllib.parse.quote(correlation_id, safe="")
        payload = self._get_governance(
            f"/v1/governance/correlations/{quoted}",
            {},
            cookie_header=cookie_header,
        )
        result = parse_correlation(payload)
        if result.correlation_id != correlation_id:
            raise ShellContractError(
                "governance correlation response differs from the requested id"
            )
        return result

    def get_knowledge_document(
        self,
        document_id: str,
        *,
        document_version: int | None,
        cookie_header: str | None,
    ) -> KnowledgeDocumentView:
        quoted = urllib.parse.quote(document_id, safe="")
        query = (
            "?" + urllib.parse.urlencode({"document_version": document_version})
            if document_version is not None
            else ""
        )
        payload = self._get_knowledge(
            f"/v1/knowledge/documents/{quoted}{query}",
            cookie_header=cookie_header,
        )
        result = KnowledgeDocumentView.from_mapping(payload)
        if result.document_id != document_id or (
            document_version is not None
            and result.document_version != document_version
        ):
            raise ShellContractError(
                "knowledge document response differs from the requested binding"
            )
        return result

    def get_knowledge_diagnostic(
        self,
        document_id: str,
        *,
        document_version: int | None,
        cookie_header: str | None,
    ) -> KnowledgeDiagnosticView:
        quoted = urllib.parse.quote(document_id, safe="")
        query = (
            "?" + urllib.parse.urlencode({"document_version": document_version})
            if document_version is not None
            else ""
        )
        payload = self._get_knowledge(
            f"/v1/knowledge/documents/{quoted}/diagnostic{query}",
            cookie_header=cookie_header,
        )
        result = KnowledgeDiagnosticView.from_mapping(payload)
        if result.document_id != document_id or (
            document_version is not None
            and result.document_version != document_version
        ):
            raise ShellContractError(
                "knowledge diagnostic response differs from the requested binding"
            )
        return result

    def submit_knowledge_operation(
        self,
        method: str,
        path: str,
        payload: dict[str, object],
        *,
        idempotency_key: str,
        cookie_header: str | None,
    ) -> KnowledgeOperationReceiptView:
        if method not in {"POST", "PUT"} or not path.startswith(
            "/v1/knowledge/documents"
        ):
            raise ShellContractError("knowledge operation is not registered")
        headers = {
            **_browser_session_headers(cookie_header),
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
        }
        body = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        status, _response_headers, raw = self._transport(method, path, headers, body)
        response = _parse_json_body(status, raw)
        if status in {200, 201, 202}:
            return KnowledgeOperationReceiptView.from_mapping(response)
        if status == 409:
            raise KnowledgeConflictError("knowledge revision conflict")
        if status in {400, 422}:
            raise KnowledgeInputError("knowledge request was rejected")
        raise _map_error(status, response)

    def _get_governance(
        self,
        path: str,
        query: dict[str, str | int | None],
        *,
        cookie_header: str | None,
    ) -> dict[str, Any]:
        encoded = urllib.parse.urlencode(
            {name: value for name, value in query.items() if value is not None}
        )
        target = path + (f"?{encoded}" if encoded else "")
        status, response_headers, body = self._transport(
            "GET", target, _browser_session_headers(cookie_header), None
        )
        payload = _parse_json_body(status, body)
        if status == 200:
            _require_private_json_headers(response_headers)
            return _require_json_object(payload, "governance projection")
        raise _map_error(status, payload)

    def _get_knowledge(
        self,
        path: str,
        *,
        cookie_header: str | None,
    ) -> dict[str, Any]:
        status, response_headers, body = self._transport(
            "GET", path, _browser_session_headers(cookie_header), None
        )
        payload = _parse_json_body(status, body)
        if status == 200:
            _require_private_json_headers(response_headers)
            return _require_json_object(payload, "knowledge projection")
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


def _require_private_json_headers(headers: dict[str, str]) -> None:
    normalized = {name.lower(): value for name, value in headers.items()}
    if not normalized.get("content-type", "").lower().startswith("application/json"):
        raise ShellContractError("governance response content type is invalid")
    cache_directives = {
        item.strip().lower()
        for item in normalized.get("cache-control", "").split(",")
        if item.strip()
    }
    if "no-store" not in cache_directives:
        raise ShellContractError("governance response must be non-cacheable")
    vary = {
        item.strip().lower()
        for item in normalized.get("vary", "").split(",")
        if item.strip()
    }
    if "cookie" not in vary:
        raise ShellContractError("governance response must vary by browser session")


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
