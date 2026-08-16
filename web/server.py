"""Local demo server for the replaceable track-C web shell.

Pure stdlib (no FastAPI/uvicorn dependency). Serves:
- the static shell at /
- fixture data at /fixtures/*
- a simulated apps/api surface: GET /v1/tasks/{task_id} (Task v1
  projection, 404/503 demo modes), GET /v1/tasks/events (SSE frames in the
  exact stream.py shape: ``id:`` / ``event: task.event`` / ``data:`` plus
  ``: ping`` keep-alives, replay on reconnect with Last-Event-ID) and
  POST /v1/task-commands (digest + version check, acceptance receipt)
- server-rendered view fragments at /views/* (task list, task detail,
  error panels, recovery/rebuild entry)

Everything is in-memory: restarting the server resets the simulated
backend. The shell itself never persists business facts and never issues
approval write calls.

Run:  uv run --frozen python web/server.py [--port 8765]
Config via env: WEB_SHELL_PORT, WEB_SHELL_ROOT (repo root), WEB_SHELL_API_BASE.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

WEB = Path(__file__).resolve().parent
SRC = WEB / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from flowpilot_shell import (  # noqa: E402
    EventView,
    ShellAuthenticationError,
    ShellAuthorizationError,
    ShellContractError,
    ShellError,
    ShellNotFoundError,
    ShellUnavailableError,
    TaskView,
)
from flowpilot_shell.commands import (  # noqa: E402
    build_retry_command,
    build_submit_message_command,
)
from flowpilot_shell.governance import (  # noqa: E402
    GovernanceCorrelationView,
    GovernanceQuery,
    GovernanceSnapshot,
    parse_correlation_id,
)
from flowpilot_shell.knowledge import (  # noqa: E402
    KnowledgeConflictError,
    KnowledgeDocumentView,
    KnowledgeOperationReceiptView,
    KnowledgeSnapshot,
    parse_document_id,
    parse_document_version,
    parse_expected_hash,
)
from flowpilot_shell.models import (  # noqa: E402
    ApprovalView,
    PlannedActionView,
    ResultArtifactView,
)
from flowpilot_shell.render import (  # noqa: E402
    render_error_panel,
    render_governance_correlation,
    render_governance_dashboard,
    render_governance_demo_notice,
    render_knowledge_dashboard,
    render_knowledge_demo_notice,
    render_task_detail,
    render_task_list,
)
from flowpilot_shell.render.task_detail import render_task_not_found  # noqa: E402
from flowpilot_shell.sse_client import parse_sse  # noqa: E402
from flowpilot_shell.store import ShellStore  # noqa: E402

ERROR_NOT_FOUND = {
    "error": {
        "code": "TASK_NOT_FOUND",
        "message": "task projection not found for this tenant",
        "retryable": False,
        "detail_ref": None,
    }
}
ERROR_UNAVAILABLE = {
    "error": {
        "code": "REPOSITORY_UNAVAILABLE",
        "message": "simulated backend unavailable (demo mode)",
        "retryable": True,
        "detail_ref": None,
    }
}


def _load_fixture(path: Path, name: str) -> dict[str, Any]:
    value: object = json.loads((path / name).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ShellContractError(f"fixture {name} must be a JSON object")
    return {str(key): item for key, item in value.items()}


class DemoBackend:
    """In-memory simulated backend fed by the synthetic fixtures."""

    def __init__(self, fixtures_dir: Path) -> None:
        tasks = _load_fixture(fixtures_dir, "tasks.v1.json")["tasks"]
        events = _load_fixture(fixtures_dir, "events.v1.json")["events"]
        approvals = _load_fixture(fixtures_dir, "approvals.v1.json")["approvals"]
        actions = _load_fixture(fixtures_dir, "planned-actions.v1.json")[
            "planned_actions"
        ]
        artifacts = _load_fixture(fixtures_dir, "result-artifacts.v1.json")["artifacts"]

        self.store = ShellStore()
        self._tasks: dict[str, dict[str, Any]] = {}
        for task in tasks:
            self._tasks[task["task_id"]] = task
            self.store.register_task(TaskView.from_mapping(task))
        for event in events:
            self.store.apply_event(EventView.from_mapping(event))
        for approval in approvals:
            self.store.register_approval(ApprovalView.from_mapping(approval))
        for action in actions:
            self.store.register_action(PlannedActionView.from_mapping(action))
        for artifact in artifacts:
            self.store.register_artifact(ResultArtifactView.from_mapping(artifact))
        self._live_events: list[dict[str, Any]] = []
        self._live_tasks: dict[str, dict[str, Any]] = {}
        self._live_sequences: dict[str, int] = {}

    # -- simulated API surface ----------------------------------------

    def task_projection(
        self,
        task_id: str,
        *,
        cookie_header: str | None = None,
    ) -> dict[str, Any] | None:
        del cookie_header
        task = self._live_tasks.get(task_id) or self._tasks.get(task_id)
        return task

    def all_tasks(
        self,
        *,
        cookie_header: str | None = None,
    ) -> tuple[TaskView, ...]:
        del cookie_header
        merged = dict(self._tasks)
        merged.update(self._live_tasks)
        return tuple(
            sorted(
                (TaskView.from_mapping(item) for item in merged.values()),
                key=lambda task: task.created_at,
            )
        )

    def all_events(self) -> list[dict[str, Any]]:
        raw_events = _load_fixture(WEB / "fixtures", "events.v1.json")["events"]
        if not isinstance(raw_events, list) or any(
            not isinstance(item, dict) for item in raw_events
        ):
            raise ShellContractError("events fixture must contain an object array")
        fixture = [dict(item) for item in raw_events]
        return fixture + self._live_events

    def emit(self, event: dict[str, Any]) -> None:
        task_id = event["task_id"]
        projection = self._live_tasks.get(task_id) or self._tasks.get(task_id)
        if projection is not None:
            event["thread_id"] = projection["thread_id"]
        # per-task sequence continues after the fixture stream
        event["sequence"] = self._next_sequence(task_id)
        self._live_events.append(event)
        if event["event_type"] == "task.status.changed.v1":
            payload = event["payload"]
            task = self._live_tasks.setdefault(task_id, dict(self._tasks[task_id]))
            task["status"] = payload["to"]
            task["updated_at"] = event["occurred_at"]
            terminal = payload["to"] in {
                "COMPLETED",
                "CANCELLED",
                "ESCALATED",
                "FAILED",
            }
            if terminal:
                task["completed_at"] = event["occurred_at"]
            else:
                # leaving a terminal state clears the terminal-only fields so
                # the in-memory projection stays task.v1-consistent
                task["completed_at"] = None
                task["error"] = None
                task["result_ref"] = None
                task["active_run_id"] = "run_live" + event["trace_id"][-8:]
            if payload["to"] not in {"WAITING_USER", "WAITING_APPROVAL"}:
                task["waiting_on"] = None
        elif event["event_type"] in {"task.failed.v1", "task.escalated.v1"}:
            task = self._live_tasks.setdefault(task_id, dict(self._tasks[task_id]))
            task["completed_at"] = event["occurred_at"]

    def _next_sequence(self, task_id: str) -> int:
        counter = self._live_sequences.get(task_id, 0)
        if counter == 0:
            fixture = json.loads(
                (WEB / "fixtures" / "events.v1.json").read_text(encoding="utf-8")
            )["events"]
            counter = max(
                (event["sequence"] for event in fixture if event["task_id"] == task_id),
                default=0,
            )
        counter += 1
        self._live_sequences[task_id] = counter
        return counter

    # -- command intake simulation -------------------------------------

    def accept_command(
        self,
        command: dict[str, Any],
        *,
        cookie_header: str | None = None,
    ) -> dict[str, Any]:
        del cookie_header
        if command["command_type"] not in {
            "task.message.submit.v1",
            "task.retry.request.v1",
        }:
            raise ShellContractError(
                f"demo backend only accepts message.submit and retry commands, "
                f"got {command['command_type']}"
            )
        from flowpilot_shell.canonical import canonical_digest

        digest_projection = {
            "command_type": command["command_type"],
            "tenant_id": command["tenant_id"],
            "task_id": command["task_id"],
            "actor": command["actor"],
            "expected_task_version": command["expected_task_version"],
            "payload": command["payload"],
        }
        if command["command_digest"] != canonical_digest(digest_projection):
            raise ShellContractError("command_digest mismatch (RFC 8785)")
        projection = self.task_projection(command["task_id"])
        if projection is None:
            raise ShellContractError("unknown task for command")
        expected = command.get("expected_task_version")
        if expected != projection["version"]:
            raise ShellContractError(
                f"task version conflict: expected {expected}, current "
                f"{projection['version']}"
            )
        receipt = {
            "command_id": command["command_id"],
            "tenant_id": command["tenant_id"],
            "task_id": command["task_id"],
            "accepted_at": _now(),
            "replayed": False,
            "execution_receipt": {
                "command_id": command["command_id"],
                "tenant_id": command["tenant_id"],
                "task_id": command["task_id"],
                "disposition": "accepted",
                "execution_ref": f"ref://executions/{command['command_id']}",
            },
        }
        if command["command_type"] == "task.message.submit.v1":
            self.emit(
                _status_event(
                    command["task_id"],
                    from_status="WAITING_USER",
                    to_status="RUNNABLE",
                    reason_code="user_input_submitted",
                )
            )
            self.emit(
                _status_event(
                    command["task_id"],
                    from_status="RUNNABLE",
                    to_status="RUNNING",
                    reason_code="resume",
                )
            )
        else:
            self.emit(
                _status_event(
                    command["task_id"],
                    from_status="FAILED",
                    to_status="RUNNABLE",
                    reason_code="user_retry_requested",
                )
            )
        return receipt

    # -- recovery entry ------------------------------------------------

    def rebuild(
        self,
        task_id: str,
        *,
        cookie_header: str | None = None,
    ) -> TaskView:
        projection = self.task_projection(task_id, cookie_header=cookie_header)
        if projection is None:
            raise ShellContractError(f"unknown task {task_id}")
        view = TaskView.from_mapping(projection)
        self.store.rebuild_from_projection(view)
        return view


@dataclass(frozen=True, slots=True)
class AuthProxyResponse:
    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        return None


class LiveBackend:
    """Cookie-only server-side adapter for a real API/SSE deployment.

    Browser tenant and role inputs are ignored. Every upstream call forwards
    only the opaque Cookie plus protocol headers; Task caches and replay state
    are isolated by an irreversible browser-session fingerprint.
    """

    _AUTH_PATHS = frozenset(
        {
            "/v1/auth/login",
            "/v1/auth/callback",
            "/v1/auth/refresh",
            "/v1/auth/logout",
        }
    )

    def __init__(self, api_base: str) -> None:
        if not api_base:
            raise ShellContractError("live backend requires WEB_SHELL_API_BASE")
        from flowpilot_shell.api_client import ApiClient

        self._api_base = api_base.rstrip("/")
        self._api = ApiClient(self._api_base)
        self._stores: dict[str, ShellStore] = {}
        self._tasks: dict[str, dict[str, dict[str, Any]]] = {}
        self._knowledge: dict[
            str, dict[tuple[str, int], KnowledgeDocumentView]
        ] = {}
        self._active_sessions: set[str] = set()

    def task_projection(
        self,
        task_id: str,
        *,
        cookie_header: str | None = None,
    ) -> dict[str, Any] | None:
        key = self._session_key(cookie_header)
        try:
            mapping = self._api.get_task_mapping(
                task_id,
                cookie_header=cookie_header,
            )
        except ShellUnavailableError:
            raise
        except Exception as exc:
            from flowpilot_shell import ShellNotFoundError

            if isinstance(exc, ShellNotFoundError):
                return None
            raise
        view = TaskView.from_mapping(mapping)
        self._active_sessions.add(key)
        self._tasks.setdefault(key, {})[task_id] = mapping
        self._stores.setdefault(key, ShellStore()).rebuild_from_projection(view)
        return mapping

    def all_tasks(
        self,
        *,
        cookie_header: str | None = None,
    ) -> tuple[TaskView, ...]:
        key = self._session_key(cookie_header)
        if key not in self._active_sessions:
            raise ShellAuthenticationError(
                "browser session has not been validated",
                code="API_AUTHENTICATION_INVALID",
            )
        for task_id in tuple(self._tasks.get(key, {})):
            self.task_projection(task_id, cookie_header=cookie_header)
        tasks = self._tasks.get(key, {})
        return tuple(
            sorted(
                (TaskView.from_mapping(item) for item in tasks.values()),
                key=lambda task: task.created_at,
            )
        )

    def store_for(self, cookie_header: str | None) -> ShellStore:
        key = self._session_key(cookie_header)
        return self._stores.setdefault(key, ShellStore())

    def governance_snapshot(
        self,
        query: GovernanceQuery,
        *,
        cookie_header: str | None,
    ) -> GovernanceSnapshot:
        self._session_key(cookie_header)
        policy_versions, policy_versions_cursor = self._api.get_policy_versions(
            limit=query.limit,
            cursor=query.cursor_for("versions"),
            cookie_header=cookie_header,
        )
        policy_decisions, policy_decisions_cursor = self._api.get_policy_decisions(
            limit=query.limit,
            cursor=query.cursor_for("decisions"),
            task_id=query.task_id,
            cookie_header=cookie_header,
        )
        audit_events, audit_events_cursor = self._api.get_audit_events(
            limit=query.limit,
            cursor=query.cursor_for("audit"),
            task_id=query.task_id,
            correlation_id=query.correlation_id,
            occurred_after=query.occurred_after,
            occurred_before=query.occurred_before,
            cookie_header=cookie_header,
        )
        security_events, security_events_cursor = self._api.get_security_events(
            limit=query.limit,
            cursor=query.cursor_for("security"),
            task_id=query.task_id,
            correlation_id=query.correlation_id,
            occurred_after=query.occurred_after,
            occurred_before=query.occurred_before,
            cookie_header=cookie_header,
        )
        return GovernanceSnapshot(
            policy_versions=policy_versions,
            policy_versions_cursor=policy_versions_cursor,
            policy_decisions=policy_decisions,
            policy_decisions_cursor=policy_decisions_cursor,
            audit_events=audit_events,
            audit_events_cursor=audit_events_cursor,
            security_events=security_events,
            security_events_cursor=security_events_cursor,
        )

    def governance_correlation(
        self,
        correlation_id: str,
        *,
        cookie_header: str | None,
    ) -> GovernanceCorrelationView:
        self._session_key(cookie_header)
        return self._api.get_governance_correlation(
            correlation_id,
            cookie_header=cookie_header,
        )

    def knowledge_snapshot(
        self,
        *,
        document_id: str | None,
        document_version: int | None,
        expected_hash: str | None,
        cookie_header: str | None,
    ) -> KnowledgeSnapshot:
        key = self._session_key(cookie_header)
        selected = None
        diagnostic = None
        if document_id is not None:
            selected = self._api.get_knowledge_document(
                document_id,
                document_version=document_version,
                cookie_header=cookie_header,
            )
            diagnostic = self._api.get_knowledge_diagnostic(
                document_id,
                document_version=selected.document_version,
                cookie_header=cookie_header,
            )
            if diagnostic.content_hash != selected.content_hash:
                raise ShellContractError(
                    "knowledge diagnostic hash differs from document projection"
                )
            self._knowledge.setdefault(key, {})[
                (selected.document_id, selected.document_version)
            ] = selected
        documents = tuple(
            sorted(
                self._knowledge.get(key, {}).values(),
                key=lambda item: (item.document_id, item.document_version),
            )
        )
        return KnowledgeSnapshot(
            documents=documents,
            selected=selected,
            diagnostic=diagnostic,
            expected_hash=expected_hash,
        )

    def submit_knowledge_operation(
        self,
        operation: str,
        payload: dict[str, object],
        *,
        cookie_header: str | None,
    ) -> KnowledgeOperationReceiptView:
        key = self._session_key(cookie_header)
        document_id = parse_document_id(str(payload["document_id"]))
        quoted = urllib.parse.quote(document_id, safe="")
        if operation == "import":
            method, path = "POST", "/v1/knowledge/documents"
            upstream = dict(payload)
        elif operation == "update":
            method, path = "PUT", f"/v1/knowledge/documents/{quoted}"
            upstream = dict(payload)
            upstream.pop("document_id")
        elif operation in {"retire", "rebuild"}:
            method, path = "POST", f"/v1/knowledge/documents/{quoted}/{operation}"
            upstream = dict(payload)
            upstream.pop("document_id")
        else:
            raise ShellContractError("knowledge operation is not registered")
        canonical = json.dumps(
            {
                "document_id": document_id,
                "operation": operation,
                "payload": upstream,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        receipt = self._api.submit_knowledge_operation(
            method,
            path,
            upstream,
            idempotency_key="sha256:" + hashlib.sha256(canonical).hexdigest(),
            cookie_header=cookie_header,
        )
        if receipt.document_id != document_id or receipt.operation != operation:
            raise ShellContractError(
                "knowledge receipt differs from the requested operation"
            )
        if operation == "retire":
            session_documents = self._knowledge.get(key, {})
            for binding in tuple(session_documents):
                if binding[0] == document_id:
                    session_documents.pop(binding, None)
        else:
            selected = self._api.get_knowledge_document(
                document_id,
                document_version=receipt.document_version,
                cookie_header=cookie_header,
            )
            if selected.revision != receipt.revision:
                raise ShellContractError(
                    "knowledge receipt differs from the authoritative projection"
                )
            self._knowledge.setdefault(key, {})[
                (selected.document_id, selected.document_version)
            ] = selected
        return receipt

    def accept_command(
        self,
        command: dict[str, Any],
        *,
        cookie_header: str | None = None,
    ) -> dict[str, Any]:
        if command.get("command_type") not in {
            "task.message.submit.v1",
            "task.retry.request.v1",
        }:
            raise ShellContractError("live shell command type is not registered")
        key = self._session_key(cookie_header)
        task_id = command.get("task_id")
        cached = (
            self._tasks.get(key, {}).get(task_id)
            if isinstance(task_id, str)
            else None
        )
        if cached is None:
            raise ShellContractError(
                "command requires a session-scoped Task projection"
            )
        if (
            command.get("tenant_id") != cached.get("tenant_id")
            or command.get("security_context") != cached.get("security_context")
        ):
            raise ShellContractError("command identity differs from Task projection")
        return self._api.submit_command(command, cookie_header=cookie_header)

    def rebuild(
        self,
        task_id: str,
        *,
        cookie_header: str | None = None,
    ) -> TaskView:
        mapping = self.task_projection(task_id, cookie_header=cookie_header)
        if mapping is None:
            raise ShellContractError(f"unknown task {task_id}")
        return TaskView.from_mapping(mapping)

    def iter_event_frames(
        self,
        *,
        last_event_id: str | None,
        task_id: str | None,
        cookie_header: str | None,
    ) -> Iterator[bytes]:
        self._session_key(cookie_header)
        query = ""
        if task_id:
            query = "?" + urllib.parse.urlencode({"task_id": task_id})
        headers = {
            "Accept": "text/event-stream",
            **self._cookie_headers(cookie_header),
            **(
                {"Last-Event-ID": last_event_id}
                if last_event_id is not None
                else {}
            ),
        }
        request = urllib.request.Request(
            self._api_base + "/v1/tasks/events" + query,
            headers=headers,
        )
        try:
            response = urllib.request.urlopen(request, timeout=30)
        except urllib.error.HTTPError as exc:
            self._raise_http_error(exc)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ShellUnavailableError("live SSE source is unavailable") from exc

        def validated_frames() -> Iterator[bytes]:
            with response:
                chunks = iter(lambda: response.read(4096), b"")
                for frame in parse_sse(chunks):
                    if frame.event != "task.event" or not frame.id:
                        continue
                    try:
                        decoded: object = json.loads(frame.data)
                    except json.JSONDecodeError as exc:
                        raise ShellContractError("live SSE data is not JSON") from exc
                    if not isinstance(decoded, Mapping):
                        raise ShellContractError("live SSE event must be an object")
                    event = EventView.from_mapping(decoded)
                    if event.event_id != frame.id:
                        raise ShellContractError("live SSE id differs from event_id")
                    if task_id is not None and event.task_id != task_id:
                        raise ShellContractError("live SSE task filter was violated")
                    projection = self.task_projection(
                        event.task_id,
                        cookie_header=cookie_header,
                    )
                    if projection is None or event.tenant_id != projection["tenant_id"]:
                        raise ShellContractError(
                            "SSE tenant differs from authoritative Task projection"
                        )
                    self.store_for(cookie_header).apply_event(event)
                    payload = json.dumps(
                        dict(decoded),
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                    yield (
                        f"id: {event.event_id}\nevent: task.event\n"
                        f"data: {payload}\n\n"
                    ).encode()

        return validated_frames()

    def proxy_auth(
        self,
        *,
        method: str,
        path: str,
        query: str,
        cookie_header: str | None,
    ) -> AuthProxyResponse:
        if path not in self._AUTH_PATHS:
            raise ShellContractError("auth proxy path is not registered")
        if path in {"/v1/auth/refresh", "/v1/auth/logout"}:
            self._session_cookie_pair(cookie_header, required=False)
        request = urllib.request.Request(
            self._api_base + path + ("?" + query if query else ""),
            headers={
                "Accept": "application/json",
                **self._cookie_headers(cookie_header),
            },
            data=b"" if method == "POST" else None,
            method=method,
        )
        opener = urllib.request.build_opener(_NoRedirectHandler())
        try:
            response = opener.open(request, timeout=10)
            status = response.status
            response_headers = response.headers
            body = response.read()
            response.close()
        except urllib.error.HTTPError as exc:
            status = exc.code
            response_headers = exc.headers
            body = exc.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ShellUnavailableError(
                "authentication service is unavailable"
            ) from exc
        normalized = self._normalize_auth_response(
            path=path,
            status=status,
            headers=response_headers,
            body=body,
        )
        if path in {"/v1/auth/refresh", "/v1/auth/logout"}:
            self.clear_session(cookie_header)
        if path in {"/v1/auth/callback", "/v1/auth/refresh"}:
            self._mark_response_session(normalized)
        return normalized

    def clear_session(self, cookie_header: str | None) -> None:
        pair = self._session_cookie_pair(cookie_header, required=False)
        if pair is None:
            return
        key = self._key_from_session_pair(pair)
        self._active_sessions.discard(key)
        store = self._stores.pop(key, None)
        if store is not None:
            store.clear()
        self._tasks.pop(key, None)
        self._knowledge.pop(key, None)

    @classmethod
    def _session_key(cls, cookie_header: str | None) -> str:
        pair = cls._session_cookie_pair(cookie_header, required=True)
        if pair is None:  # pragma: no cover - required=True is exhaustive
            raise ShellAuthenticationError(
                "browser session is required",
                code="API_AUTHENTICATION_REQUIRED",
            )
        return cls._key_from_session_pair(pair)

    @staticmethod
    def _key_from_session_pair(pair: str) -> str:
        return hashlib.sha256(pair.encode("utf-8")).hexdigest()

    @classmethod
    def _session_cookie_pair(
        cls,
        cookie_header: str | None,
        *,
        required: bool,
    ) -> str | None:
        if cookie_header is None:
            if required:
                raise ShellAuthenticationError(
                    "browser session is required",
                    code="API_AUTHENTICATION_REQUIRED",
                )
            return None
        if cookie_header == "":
            raise ShellAuthenticationError(
                "browser session cookie is invalid",
                code="API_AUTHENTICATION_INVALID",
            )
        cls._cookie_headers(cookie_header)
        pairs: list[str] = []
        for item in cookie_header.split(";"):
            name, separator, value = item.strip().partition("=")
            if name != "__Host-flowpilot-session":
                continue
            if not separator or not value:
                raise ShellAuthenticationError(
                    "browser session cookie is invalid",
                    code="API_AUTHENTICATION_INVALID",
                )
            pairs.append(f"{name}={value}")
        if len(pairs) > 1:
            raise ShellAuthenticationError(
                "browser session cookie is ambiguous",
                code="API_AUTHENTICATION_INVALID",
            )
        if not pairs:
            if required:
                raise ShellAuthenticationError(
                    "browser session is required",
                    code="API_AUTHENTICATION_REQUIRED",
                )
            return None
        return pairs[0]

    def _mark_response_session(self, response: AuthProxyResponse) -> None:
        for name, value in response.headers:
            if name.lower() != "set-cookie":
                continue
            pair = value.split(";", 1)[0].strip()
            if not pair.startswith("__Host-flowpilot-session="):
                continue
            if pair.endswith("=") or "max-age=0" in value.lower():
                continue
            self._active_sessions.add(self._key_from_session_pair(pair))

    @staticmethod
    def _cookie_headers(cookie_header: str | None) -> dict[str, str]:
        if cookie_header is None:
            return {}
        if not cookie_header or "\r" in cookie_header or "\n" in cookie_header:
            raise ShellContractError("browser Cookie header is invalid")
        return {"Cookie": cookie_header}

    @staticmethod
    def _raise_http_error(error: urllib.error.HTTPError) -> None:
        code = _safe_error_code(error.read())
        if error.code == 401:
            raise ShellAuthenticationError(
                "browser session is invalid",
                code=code,
            ) from None
        if error.code == 403:
            raise ShellAuthorizationError(
                "browser session is not authorized",
                code=code,
            ) from None
        if error.code in {502, 503, 504}:
            raise ShellUnavailableError("live SSE source is unavailable") from None
        raise ShellContractError("live SSE source rejected the request") from None

    @staticmethod
    def _normalize_auth_response(
        *,
        path: str,
        status: int,
        headers: Any,
        body: bytes,
    ) -> AuthProxyResponse:
        safe_headers: list[tuple[str, str]] = []
        location = headers.get("Location")
        if location is not None:
            if path == "/v1/auth/login":
                parsed = urllib.parse.urlsplit(location)
                loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
                if parsed.scheme != "https" and not (
                    parsed.scheme == "http" and loopback
                ):
                    raise ShellContractError("OIDC redirect location is not trusted")
            elif not location.startswith("/") or location.startswith("//"):
                raise ShellContractError("post-login redirect is not local")
            safe_headers.append(("Location", location))
        get_all = getattr(headers, "get_all", None)
        cookies = get_all("Set-Cookie") if callable(get_all) else []
        for cookie in cookies or []:
            if not _safe_set_cookie(cookie):
                raise ShellContractError("authentication cookie is invalid")
            safe_headers.append(("Set-Cookie", cookie))
        if status == 200 and path == "/v1/auth/refresh":
            payload = _safe_refresh_body(body)
            safe_headers.append(("Content-Type", "application/json; charset=utf-8"))
            return AuthProxyResponse(status, tuple(safe_headers), payload)
        if status in {204, 302, 303}:
            return AuthProxyResponse(status, tuple(safe_headers), b"")
        code = _safe_error_code(body)
        payload = _safe_auth_error_body(status, code)
        safe_headers.append(("Content-Type", "application/json; charset=utf-8"))
        return AuthProxyResponse(status, tuple(safe_headers), payload)


_AUTH_ERROR_MESSAGES = {
    "API_AUTHENTICATION_REQUIRED": "需要登录后继续。",
    "API_AUTHENTICATION_INVALID": "会话已过期或已撤销，请重新认证。",
    "API_AUTHORIZATION_DENIED": "当前会话无权访问该资源。",
    "API_AUTH_FLOW_INVALID": "登录流程已失效，请重新开始登录。",
    "API_DEPENDENCY_UNAVAILABLE": "认证服务暂时不可用，请稍后重试。",
    "API_INTERNAL_ERROR": "认证服务发生内部错误。",
}


def _safe_error_code(body: bytes) -> str:
    try:
        payload: object = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "API_AUTHENTICATION_INVALID"
    if not isinstance(payload, Mapping):
        return "API_AUTHENTICATION_INVALID"
    error = payload.get("error")
    if not isinstance(error, Mapping):
        return "API_AUTHENTICATION_INVALID"
    code = error.get("code")
    if not isinstance(code, str) or code not in _AUTH_ERROR_MESSAGES:
        return "API_AUTHENTICATION_INVALID"
    return code


def _safe_auth_error_body(status: int, code: str) -> bytes:
    fallback = {
        401: "API_AUTHENTICATION_INVALID",
        403: "API_AUTHORIZATION_DENIED",
        503: "API_DEPENDENCY_UNAVAILABLE",
    }.get(status, "API_INTERNAL_ERROR")
    allowed = {
        401: {
            "API_AUTHENTICATION_REQUIRED",
            "API_AUTHENTICATION_INVALID",
            "API_AUTH_FLOW_INVALID",
        },
        403: {"API_AUTHORIZATION_DENIED"},
        503: {"API_DEPENDENCY_UNAVAILABLE"},
        500: {"API_INTERNAL_ERROR"},
    }.get(status, {"API_INTERNAL_ERROR"})
    selected = code if code in allowed else fallback
    payload = {
        "error": {
            "code": selected,
            "message": _AUTH_ERROR_MESSAGES[selected],
            "retryable": selected == "API_DEPENDENCY_UNAVAILABLE",
            "detail_ref": None,
        }
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _safe_governance_error(title: str, message: str) -> str:
    return (
        '<section class="error-panel" role="alert">'
        f"<h2>{html.escape(title, quote=True)}</h2>"
        f"<p>{html.escape(message, quote=True)}</p>"
        '<a class="btn" href="#/governance">返回治理控制台</a>'
        "</section>"
    )


def _safe_knowledge_error(title: str, message: str) -> str:
    return (
        '<section class="error-panel" role="alert">'
        f"<h2>{html.escape(title, quote=True)}</h2>"
        f"<p>{html.escape(message, quote=True)}</p>"
        '<a class="btn" href="#/knowledge">返回知识控制台</a>'
        "</section>"
    )


def _safe_refresh_body(body: bytes) -> bytes:
    try:
        payload: object = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ShellContractError("refresh response is not JSON") from exc
    if not isinstance(payload, Mapping) or set(payload) != {"status", "expires_at"}:
        raise ShellContractError("refresh response shape is invalid")
    status = payload.get("status")
    expires_at = payload.get("expires_at")
    if status != "active" or not isinstance(expires_at, str) or not expires_at:
        raise ShellContractError("refresh response fields are invalid")
    try:
        datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ShellContractError("refresh expiry is invalid") from exc
    return json.dumps(
        {"expires_at": expires_at, "status": "active"},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _safe_set_cookie(cookie: str) -> bool:
    if "\r" in cookie or "\n" in cookie or "=" not in cookie:
        return False
    segments = [segment.strip() for segment in cookie.split(";")]
    name, separator, value = segments[0].partition("=")
    if not separator:
        return False
    if name not in {"__Host-flowpilot-login", "__Host-flowpilot-session"}:
        return False
    attributes: dict[str, str | None] = {}
    allowed = {"expires", "httponly", "max-age", "path", "samesite", "secure"}
    for segment in segments[1:]:
        if not segment:
            return False
        attribute, has_value, attribute_value = segment.partition("=")
        key = attribute.lower()
        if key not in allowed or key in attributes:
            return False
        attributes[key] = attribute_value if has_value else None
    if attributes.get("secure", "missing") is not None:
        return False
    if attributes.get("httponly", "missing") is not None:
        return False
    if attributes.get("path") != "/":
        return False
    if (attributes.get("samesite") or "").lower() not in {"lax", "strict"}:
        return False
    max_age = attributes.get("max-age")
    if max_age is not None:
        try:
            int(max_age)
        except ValueError:
            return False
    return bool(value) or max_age == "0"


def _status_event(
    task_id: str,
    *,
    from_status: str,
    to_status: str,
    reason_code: str,
) -> dict[str, Any]:
    stamp = _now()
    trace = "trc_live_" + str(int(time.time() * 1000))[-12:]
    return {
        "event_id": f"evt_live_{trace}",
        "event_type": "task.status.changed.v1",
        "tenant_id": "tenant-it",
        "task_id": task_id,
        "thread_id": f"thread_{task_id.removeprefix('task_')}",
        "task_version": 1,
        "sequence": 1,  # overridden by emit() with the per-task continuation
        "trace_id": trace,
        "run_id": "run_" + trace[-8:],
        "producer": "worker",
        "producer_principal_ref": "workload://worker/default",
        "correlation_id": "corr_" + trace[-8:],
        "causation_id": None,
        "data_classification": "internal",
        "payload": {
            "from": from_status,
            "to": to_status,
            "reason_code": reason_code,
        },
        "occurred_at": stamp,
    }


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ShellHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: DemoServer

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return  # keep the demo console quiet

    # -- routing -------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        backend = self.server.backend
        try:
            if path in {"/", "/index.html", "/studio"}:
                self._send_file(
                    WEB / "shell" / "index.html", "text/html; charset=utf-8"
                )
            elif path.startswith("/static/"):
                self._send_file(
                    WEB / "shell" / path.removeprefix("/static/"),
                    _guess_content_type(path),
                )
            elif path.startswith("/fixtures/"):
                self._send_file(
                    WEB / "fixtures" / path.removeprefix("/fixtures/"),
                    "application/json; charset=utf-8",
                )
            elif path == "/health":
                self._send_json(
                    200,
                    {
                        "status": "ok",
                        "service": "flowpilot-shell",
                        "mode": (
                            "live" if isinstance(backend, LiveBackend) else "demo"
                        ),
                    },
                )
            elif path in {
                "/api/v1/auth/login",
                "/api/v1/auth/callback",
            }:
                self._handle_auth_proxy("GET", path, parsed.query)
            elif path == "/views/tasks":
                fragment = render_task_list(
                    backend.all_tasks(cookie_header=self._browser_cookie())
                )
                self._send_text(
                    fragment,
                    "text/html; charset=utf-8",
                    no_store=True,
                )
            elif path.startswith("/views/tasks/"):
                self._handle_view_task(path.removeprefix("/views/tasks/"), query)
            elif path == "/views/governance":
                self._handle_view_governance(query)
            elif path.startswith("/views/governance/correlations/"):
                self._handle_view_governance_correlation(
                    path.removeprefix("/views/governance/correlations/")
                )
            elif path == "/views/knowledge":
                self._handle_view_knowledge(query)
            elif path == "/api/v1/tasks/events":
                self._handle_sse(query)
            elif path.startswith("/api/v1/tasks/"):
                self._handle_api_task(path.removeprefix("/api/v1/tasks/"), query)
            else:
                self._send_json(404, ERROR_NOT_FOUND)
        except (BrokenPipeError, ConnectionResetError):
            return
        except ShellAuthenticationError as exc:
            self._send_identity_error(
                401,
                exc.code,
                as_html=path.startswith("/views/"),
            )
        except ShellAuthorizationError as exc:
            self._send_identity_error(
                403,
                exc.code,
                as_html=path.startswith("/views/"),
            )
        except ShellUnavailableError:
            self._send_identity_error(
                503,
                "API_DEPENDENCY_UNAVAILABLE",
                as_html=path.startswith("/views/"),
            )
        except ShellContractError:
            if path.startswith("/api/v1/auth/"):
                self._send_identity_error(
                    503,
                    "API_DEPENDENCY_UNAVAILABLE",
                    as_html=False,
                )
            else:
                self._send_json(
                    500,
                    {
                        "error": {
                            "code": "INTERNAL_ERROR",
                            "message": "request could not be completed",
                            "retryable": False,
                            "detail_ref": None,
                        }
                    },
                    no_store=True,
                )
        except Exception:  # noqa: BLE001 - demo server must never crash a thread
            self._send_json(
                500,
                {
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "demo server error",
                        "retryable": False,
                        "detail_ref": None,
                    }
                },
            )

    def do_POST(self) -> None:  # noqa: N802
        backend = self.server.backend
        parsed = urllib.parse.urlsplit(self.path)
        try:
            if parsed.path in {
                "/api/v1/auth/refresh",
                "/api/v1/auth/logout",
            }:
                self._read_body()
                self._handle_auth_proxy("POST", parsed.path, parsed.query)
            elif parsed.path == "/api/v1/task-commands":
                if isinstance(backend, LiveBackend):
                    self._send_json(
                        403,
                        {
                            "error": {
                                "code": "BROWSER_AUTHORITY_FORBIDDEN",
                                "message": (
                                    "raw TaskCommand submission is not available "
                                    "to the browser"
                                ),
                                "retryable": False,
                                "detail_ref": None,
                            }
                        },
                    )
                    return
                body = self._read_body()
                command = json.loads(body.decode("utf-8"))
                receipt = backend.accept_command(
                    command,
                    cookie_header=self._browser_cookie(),
                )
                self._send_json(202, receipt, no_store=True)
            elif parsed.path == "/shell/commands/submit":
                form = self._read_form()
                receipt = self._submit_completion(backend, form)
                self._send_json(
                    200,
                    {"accepted": True, "receipt": receipt},
                    no_store=True,
                )
            elif parsed.path == "/shell/commands/retry":
                form = self._read_form()
                receipt = self._retry_task(backend, form)
                self._send_json(
                    200,
                    {"accepted": True, "receipt": receipt},
                    no_store=True,
                )
            elif parsed.path.startswith("/shell/knowledge/"):
                self._handle_knowledge_operation(
                    parsed.path.removeprefix("/shell/knowledge/")
                )
            else:
                self._send_json(404, ERROR_NOT_FOUND)
        except (BrokenPipeError, ConnectionResetError):
            return
        except ShellAuthenticationError as exc:
            self._send_identity_error(401, exc.code, as_html=False)
        except ShellAuthorizationError as exc:
            self._send_identity_error(403, exc.code, as_html=False)
        except ShellUnavailableError:
            self._send_identity_error(
                503,
                "API_DEPENDENCY_UNAVAILABLE",
                as_html=False,
            )
        except ShellContractError:
            self._send_json(
                409,
                {
                    "error": {
                        "code": "TASK_VERSION_CONFLICT",
                        "message": "请求与当前任务状态冲突，请刷新后重试。",
                        "retryable": False,
                        "detail_ref": None,
                    }
                },
                no_store=True,
            )
        except (ValueError, KeyError):
            self._send_json(
                422,
                {
                    "error": {
                        "code": "CONTRACT_INVALID",
                        "message": "请求格式无效。",
                        "retryable": False,
                        "detail_ref": None,
                    }
                },
                no_store=True,
            )

    # -- view handlers -------------------------------------------------

    def _handle_view_knowledge(self, query: dict[str, list[str]]) -> None:
        backend = self.server.backend
        if isinstance(backend, DemoBackend):
            self._send_text(
                render_knowledge_demo_notice(),
                "text/html; charset=utf-8",
                no_store=True,
            )
            return
        allowed = {"document_id", "document_version", "expected_hash"}
        if set(query) - allowed or any(len(values) != 1 for values in query.values()):
            self._send_text(
                _safe_knowledge_error(
                    "查询条件无效",
                    "文档、版本或引用摘要格式无效，请清除后重试。",
                ),
                "text/html; charset=utf-8",
                status=422,
                no_store=True,
            )
            return
        try:
            raw_document = query.get("document_id", [None])[0]
            document_id = (
                parse_document_id(raw_document)
                if raw_document is not None and raw_document != ""
                else None
            )
            document_version = parse_document_version(
                query.get("document_version", [None])[0]
            )
            expected_hash = parse_expected_hash(
                query.get("expected_hash", [None])[0]
            )
            if document_id is None and (
                document_version is not None or expected_hash is not None
            ):
                raise ShellContractError(
                    "knowledge version and hash require a document id"
                )
        except ShellContractError:
            self._send_text(
                _safe_knowledge_error(
                    "查询条件无效",
                    "文档、版本或引用摘要格式无效，请清除后重试。",
                ),
                "text/html; charset=utf-8",
                status=422,
                no_store=True,
            )
            return
        try:
            snapshot = backend.knowledge_snapshot(
                document_id=document_id,
                document_version=document_version,
                expected_hash=expected_hash,
                cookie_header=self._browser_cookie(),
            )
        except (ShellAuthenticationError, ShellAuthorizationError):
            raise
        except ShellNotFoundError:
            self._send_text(
                _safe_knowledge_error(
                    "知识版本不存在",
                    "当前会话无法读取该文档或精确版本；未尝试重定向到其他版本。",
                ),
                "text/html; charset=utf-8",
                status=404,
                no_store=True,
            )
            return
        except ShellUnavailableError:
            self._send_text(
                _safe_knowledge_error(
                    "知识服务暂时不可用",
                    "未展示缓存或替代数据，请稍后重新复验。",
                ),
                "text/html; charset=utf-8",
                status=503,
                no_store=True,
            )
            return
        except ShellContractError:
            self._send_text(
                _safe_knowledge_error(
                    "知识投影不可用",
                    "服务返回的数据未通过版本、摘要或安全投影校验。",
                ),
                "text/html; charset=utf-8",
                status=502,
                no_store=True,
            )
            return
        self._send_text(
            render_knowledge_dashboard(snapshot),
            "text/html; charset=utf-8",
            no_store=True,
        )

    def _handle_knowledge_operation(self, operation: str) -> None:
        backend = self.server.backend
        if isinstance(backend, DemoBackend):
            raise ShellAuthorizationError(
                "knowledge mutations require a live session",
                code="API_AUTHORIZATION_DENIED",
            )
        try:
            payload = self._knowledge_operation_payload(operation)
            receipt = backend.submit_knowledge_operation(
                operation,
                payload,
                cookie_header=self._browser_cookie(),
            )
        except (ShellAuthenticationError, ShellAuthorizationError):
            raise
        except KnowledgeConflictError:
            self._send_json(
                409,
                {
                    "error": {
                        "code": "KNOWLEDGE_REVISION_CONFLICT",
                        "message": "知识修订已变化，请刷新后基于最新修订重试。",
                        "retryable": False,
                        "detail_ref": None,
                    }
                },
                no_store=True,
            )
            return
        except ShellNotFoundError:
            self._send_json(
                404,
                {
                    "error": {
                        "code": "KNOWLEDGE_NOT_FOUND",
                        "message": "当前会话无法读取该知识文档。",
                        "retryable": False,
                        "detail_ref": None,
                    }
                },
                no_store=True,
            )
            return
        except ShellContractError:
            self._send_json(
                502,
                {
                    "error": {
                        "code": "KNOWLEDGE_PROJECTION_INVALID",
                        "message": "知识服务响应未通过安全校验。",
                        "retryable": False,
                        "detail_ref": None,
                    }
                },
                no_store=True,
            )
            return
        except ShellError:
            self._send_json(
                502,
                {
                    "error": {
                        "code": "KNOWLEDGE_SERVICE_INVALID",
                        "message": "知识服务未返回可接受的结果。",
                        "retryable": False,
                        "detail_ref": None,
                    }
                },
                no_store=True,
            )
            return
        self._send_json(
            200,
            {
                "accepted": True,
                "receipt": {
                    "document_id": receipt.document_id,
                    "operation": receipt.operation,
                    "revision": receipt.revision,
                    "document_version": receipt.document_version,
                    "disposition": receipt.disposition,
                    "event_id": receipt.event_id,
                    "index_job_id": receipt.index_job_id,
                },
            },
            no_store=True,
        )

    def _knowledge_operation_payload(self, operation: str) -> dict[str, object]:
        version_fields = {
            "document_id",
            "source_type",
            "source_ref",
            "source_version",
            "data_classification",
            "effective_at",
            "expires_at",
            "content",
        }
        expected = {
            "import": version_fields,
            "update": version_fields | {"expected_revision"},
            "retire": {"document_id", "expected_revision"},
            "rebuild": {"document_id", "expected_revision", "document_version"},
        }.get(operation)
        if expected is None:
            raise ValueError("knowledge operation is not registered")
        form = self._read_strict_form(expected, maximum=21 * 1024 * 1024)
        document_id = _form_document_id(form["document_id"])
        if operation in {"retire", "rebuild"}:
            payload: dict[str, object] = {
                "document_id": document_id,
                "expected_revision": _form_version(
                    form["expected_revision"], "expected_revision"
                ),
            }
            if operation == "rebuild":
                payload["document_version"] = _form_version(
                    form["document_version"], "document_version"
                )
            return payload
        source_type = form["source_type"]
        classification = form["data_classification"]
        if source_type not in {"file", "uri", "connector", "manual"}:
            raise ValueError("source_type is invalid")
        if classification not in {
            "public",
            "internal",
            "confidential",
            "restricted",
        }:
            raise ValueError("data_classification is invalid")
        content = form["content"]
        if not content or len(content) > 20 * 1024 * 1024:
            raise ValueError("knowledge content is invalid")
        effective_at = _form_timestamp(form["effective_at"], "effective_at")
        expires_at = (
            _form_timestamp(form["expires_at"], "expires_at")
            if form["expires_at"]
            else None
        )
        if expires_at is not None and expires_at <= effective_at:
            raise ValueError("knowledge expiry must follow effective time")
        payload = {
            "document_id": document_id,
            "source_type": source_type,
            "source_ref": _bounded_form_text(form["source_ref"], 1024),
            "source_version": (
                _bounded_form_text(form["source_version"], 256)
                if form["source_version"]
                else None
            ),
            "data_classification": classification,
            "effective_at": form["effective_at"],
            "expires_at": form["expires_at"] or None,
            "content": content,
        }
        if operation == "update":
            payload["expected_revision"] = _form_version(
                form["expected_revision"], "expected_revision"
            )
        return payload

    def _handle_view_governance(self, query: dict[str, list[str]]) -> None:
        backend = self.server.backend
        if isinstance(backend, DemoBackend):
            self._send_text(
                render_governance_demo_notice(),
                "text/html; charset=utf-8",
                no_store=True,
            )
            return
        try:
            validated = GovernanceQuery.from_http_query(query)
        except ShellContractError:
            self._send_text(
                _safe_governance_error(
                    "筛选条件无效",
                    "筛选字段不受支持或格式无效，请清除筛选后重试。",
                ),
                "text/html; charset=utf-8",
                status=422,
                no_store=True,
            )
            return
        try:
            snapshot = backend.governance_snapshot(
                validated,
                cookie_header=self._browser_cookie(),
            )
        except (ShellAuthenticationError, ShellAuthorizationError):
            raise
        except ShellNotFoundError:
            self._send_text(
                _safe_governance_error(
                    "治理记录不存在",
                    "当前会话无法读取该治理记录。",
                ),
                "text/html; charset=utf-8",
                status=404,
                no_store=True,
            )
            return
        except ShellUnavailableError:
            self._send_text(
                _safe_governance_error(
                    "治理服务暂时不可用",
                    "未展示任何缓存或替代数据，请稍后重试。",
                ),
                "text/html; charset=utf-8",
                status=503,
                no_store=True,
            )
            return
        except ShellContractError:
            self._send_text(
                _safe_governance_error(
                    "治理投影不可用",
                    "服务返回的数据未通过安全投影校验。",
                ),
                "text/html; charset=utf-8",
                status=502,
                no_store=True,
            )
            return
        self._send_text(
            render_governance_dashboard(snapshot, validated),
            "text/html; charset=utf-8",
            no_store=True,
        )

    def _handle_view_governance_correlation(self, raw_id: str) -> None:
        backend = self.server.backend
        if isinstance(backend, DemoBackend):
            self._send_text(
                render_governance_demo_notice(),
                "text/html; charset=utf-8",
                no_store=True,
            )
            return
        try:
            correlation_id = parse_correlation_id(
                urllib.parse.unquote(raw_id, errors="strict")
            )
        except (ShellContractError, UnicodeError):
            self._send_text(
                _safe_governance_error(
                    "关联 ID 无效",
                    "该关联链标识不受支持。",
                ),
                "text/html; charset=utf-8",
                status=422,
                no_store=True,
            )
            return
        try:
            chain = backend.governance_correlation(
                correlation_id,
                cookie_header=self._browser_cookie(),
            )
        except (ShellAuthenticationError, ShellAuthorizationError):
            raise
        except ShellNotFoundError:
            self._send_text(
                _safe_governance_error(
                    "关联链不存在",
                    "当前会话无法读取该关联链。",
                ),
                "text/html; charset=utf-8",
                status=404,
                no_store=True,
            )
            return
        except ShellUnavailableError:
            self._send_text(
                _safe_governance_error(
                    "治理服务暂时不可用",
                    "未展示任何缓存或替代数据，请稍后重试。",
                ),
                "text/html; charset=utf-8",
                status=503,
                no_store=True,
            )
            return
        except ShellContractError:
            self._send_text(
                _safe_governance_error(
                    "关联链投影不可用",
                    "服务返回的数据未通过安全投影校验。",
                ),
                "text/html; charset=utf-8",
                status=502,
                no_store=True,
            )
            return
        self._send_text(
            render_governance_correlation(chain),
            "text/html; charset=utf-8",
            no_store=True,
        )

    def _handle_view_task(self, task_id: str, query: dict[str, list[str]]) -> None:
        backend = self.server.backend
        cookie_header = self._browser_cookie()
        if isinstance(backend, DemoBackend) and "demo" in query:
            mode = query["demo"][0]
            if mode == "unavailable":
                fragment = render_error_panel(
                    ShellUnavailableError("演示：模拟后端不可用（503），请重试。"),
                    retry_href=f"/views/tasks/{task_id}",
                )
                self._send_text(fragment, "text/html; charset=utf-8")
                return
            if mode == "missing":
                self._send_text(
                    render_task_not_found(task_id), "text/html; charset=utf-8"
                )
                return
        if "rebuild" in query:
            try:
                backend.rebuild(task_id, cookie_header=cookie_header)
            except ShellContractError:
                self._send_text(
                    render_task_not_found(task_id), "text/html; charset=utf-8"
                )
                return
        projection = backend.task_projection(
            task_id,
            cookie_header=cookie_header,
        )
        if projection is None:
            self._send_text(render_task_not_found(task_id), "text/html; charset=utf-8")
            return
        task = TaskView.from_mapping(projection)
        store = (
            backend.store_for(cookie_header)
            if isinstance(backend, LiveBackend)
            else backend.store
        )
        store.rebuild_from_projection(task)
        fragment = render_task_detail(task, store)
        self._send_text(
            fragment,
            "text/html; charset=utf-8",
            no_store=True,
        )

    def _handle_api_task(self, task_id: str, query: dict[str, list[str]]) -> None:
        backend = self.server.backend
        if (
            isinstance(backend, DemoBackend)
            and "simulate" in query
            and query["simulate"][0] == "unavailable"
        ):
            self._send_json(503, ERROR_UNAVAILABLE)
            return
        projection = backend.task_projection(
            task_id,
            cookie_header=self._browser_cookie(),
        )
        if projection is None:
            self._send_json(404, ERROR_NOT_FOUND)
            return
        self._send_json(200, projection, no_store=True)

    # -- SSE -----------------------------------------------------------

    def _handle_sse(self, query: dict[str, list[str]]) -> None:
        backend = self.server.backend
        task_filter = query.get("task_id", [None])[0]
        if isinstance(backend, LiveBackend):
            frames = backend.iter_event_frames(
                last_event_id=self.headers.get("Last-Event-ID"),
                task_id=task_filter,
                cookie_header=self._browser_cookie(),
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for frame in frames:
                self._write_chunk(frame)
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            return
        events = backend.all_events()
        if task_filter:
            events = [event for event in events if event["task_id"] == task_filter]
        last_event_id = self.headers.get("Last-Event-ID")
        if last_event_id:
            ids = [event["event_id"] for event in events]
            if last_event_id in ids:
                events = events[ids.index(last_event_id) + 1 :]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        position = 0
        while True:
            while position < len(events):
                event = events[position]
                payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                frame = (
                    f"id: {event['event_id']}\nevent: task.event\ndata: {payload}\n\n"
                ).encode()
                self._write_chunk(frame)
                position += 1
            self._write_chunk(b": ping\n\n")
            time.sleep(3)
            events = backend.all_events()
            if task_filter:
                events = [event for event in events if event["task_id"] == task_filter]

    def _write_chunk(self, frame: bytes) -> None:
        self.wfile.write(f"{len(frame):X}\r\n".encode("ascii") + frame + b"\r\n")
        self.wfile.flush()

    # -- helpers -------------------------------------------------------

    def _browser_cookie(self) -> str | None:
        return self.headers.get("Cookie")

    def _handle_auth_proxy(self, method: str, path: str, query: str) -> None:
        backend = self.server.backend
        if isinstance(backend, DemoBackend):
            if path.endswith("/refresh"):
                body = json.dumps(
                    {
                        "expires_at": (
                            datetime.now(UTC) + timedelta(hours=1)
                        ).isoformat().replace("+00:00", "Z"),
                        "status": "active",
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
                response = AuthProxyResponse(
                    200,
                    (("Content-Type", "application/json; charset=utf-8"),),
                    body,
                )
            elif path.endswith("/logout"):
                response = AuthProxyResponse(204, (), b"")
            else:
                response = AuthProxyResponse(303, (("Location", "/studio"),), b"")
        else:
            response = backend.proxy_auth(
                method=method,
                path=path.removeprefix("/api"),
                query=query,
                cookie_header=self._browser_cookie(),
            )
        self._send_proxy_response(response)

    def _send_proxy_response(self, response: AuthProxyResponse) -> None:
        self.send_response(response.status)
        for name, value in response.headers:
            self.send_header(name, value)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(response.body)))
        self.end_headers()
        if response.body:
            self.wfile.write(response.body)

    def _send_identity_error(
        self,
        status: int,
        code: str,
        *,
        as_html: bool,
    ) -> None:
        selected = code if code in _AUTH_ERROR_MESSAGES else {
            401: "API_AUTHENTICATION_INVALID",
            403: "API_AUTHORIZATION_DENIED",
            503: "API_DEPENDENCY_UNAVAILABLE",
        }.get(status, "API_INTERNAL_ERROR")
        if as_html:
            message = _AUTH_ERROR_MESSAGES[selected]
            fragment = (
                '<section class="auth-error" role="alert">'
                "<h2>需要重新认证</h2>"
                f"<p>{message}</p>"
                '<a class="btn btn-primary" href="/api/v1/auth/login">'
                "重新登录</a></section>"
            )
            self._send_text(
                fragment,
                "text/html; charset=utf-8",
                status=status,
                no_store=True,
            )
            return
        raw = _safe_auth_error_body(status, selected)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _send_file(self, path: Path, content_type: str) -> None:
        if not path.is_file():
            self._send_json(404, ERROR_NOT_FOUND)
            return
        raw = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _send_text(
        self,
        text: str,
        content_type: str,
        *,
        status: int = 200,
        no_store: bool = False,
    ) -> None:
        raw = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        if no_store:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _send_json(
        self,
        status: int,
        payload: dict[str, Any],
        *,
        no_store: bool = False,
    ) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        if no_store:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length) if length else b""

    def _read_form(self) -> dict[str, str]:
        body = self._read_body().decode("utf-8")
        return dict(urllib.parse.parse_qsl(body, keep_blank_values=True))

    def _read_strict_form(
        self,
        expected: set[str],
        *,
        maximum: int,
    ) -> dict[str, str]:
        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("application/x-www-form-urlencoded"):
            raise ValueError("form content type is invalid")
        raw_length = self.headers.get("Content-Length", "0")
        if not raw_length.isascii() or not raw_length.isdecimal():
            raise ValueError("form content length is invalid")
        length = int(raw_length)
        if length <= 0 or length > maximum:
            raise ValueError("form content length is invalid")
        body = self.rfile.read(length).decode("utf-8")
        pairs = urllib.parse.parse_qsl(
            body,
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=16,
        )
        if len(pairs) != len(expected):
            raise ValueError("form fields are invalid")
        form: dict[str, str] = {}
        for name, value in pairs:
            if name not in expected or name in form:
                raise ValueError("form fields are invalid")
            form[name] = value
        if set(form) != expected:
            raise ValueError("form fields are invalid")
        return form

    def _submit_completion(
        self, backend: DemoBackend | LiveBackend, form: dict[str, str]
    ) -> dict[str, Any]:
        task_id = form["task_id"]
        cookie_header = self._browser_cookie()
        projection = backend.task_projection(
            task_id,
            cookie_header=cookie_header,
        )
        if projection is None:
            raise ShellContractError(f"unknown task {task_id}")
        security_context = projection["security_context"]
        message_id = "msg_" + task_id.removeprefix("task_")[:16]
        command = build_submit_message_command(
            tenant_id=projection["tenant_id"],
            task_id=task_id,
            actor={
                "type": security_context["subject_type"],
                "id": security_context["subject_id"],
            },
            security_context=security_context,
            expected_task_version=projection["version"],
            message_id=message_id,
            message_ref=f"ref://messages/{task_id}",
        )
        return backend.accept_command(command, cookie_header=cookie_header)

    def _retry_task(
        self, backend: DemoBackend | LiveBackend, form: dict[str, str]
    ) -> dict[str, Any]:
        task_id = form["task_id"]
        cookie_header = self._browser_cookie()
        projection = backend.task_projection(
            task_id,
            cookie_header=cookie_header,
        )
        if projection is None:
            raise ShellContractError(f"unknown task {task_id}")
        security_context = projection["security_context"]
        command = build_retry_command(
            tenant_id=projection["tenant_id"],
            task_id=task_id,
            actor={
                "type": security_context["subject_type"],
                "id": security_context["subject_id"],
            },
            security_context=security_context,
            expected_task_version=projection["version"],
            failed_run_id=projection.get("active_run_id") or f"run_{task_id[-8:]}",
            reason="demo retry",
        )
        return backend.accept_command(command, cookie_header=cookie_header)


def _bounded_form_text(value: str, maximum: int) -> str:
    if not value or len(value) > maximum or "\x00" in value:
        raise ValueError("form text is invalid")
    return value


def _form_document_id(value: str) -> str:
    try:
        return parse_document_id(value)
    except ShellContractError as exc:
        raise ValueError("document_id is invalid") from exc


def _form_version(value: str, label: str) -> int:
    try:
        parsed = parse_document_version(value)
    except ShellContractError as exc:
        raise ValueError(f"{label} is invalid") from exc
    if parsed is None:
        raise ValueError(f"{label} is invalid")
    return parsed


def _form_timestamp(value: str, label: str) -> datetime:
    if not value or len(value) > 64:
        raise ValueError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} is invalid")
    return parsed.astimezone(UTC)


def _guess_content_type(path: str) -> str:
    if path.endswith(".css"):
        return "text/css; charset=utf-8"
    if path.endswith(".js"):
        return "application/javascript; charset=utf-8"
    if path.endswith(".html"):
        return "text/html; charset=utf-8"
    return "application/octet-stream"


class DemoServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, backend: DemoBackend | LiveBackend, port: int) -> None:
        super().__init__(("127.0.0.1", port), ShellHandler)
        self.backend = backend

    def handle_error(self, request: Any, client_address: Any) -> None:
        # A client closing an SSE connection mid-ping is the normal
        # disconnect path; keep the demo console quiet about it.
        return


def build_backend(
    environment: Mapping[str, str] | None = None,
) -> DemoBackend | LiveBackend:
    effective = os.environ if environment is None else environment
    mode = effective.get("WEB_SHELL_MODE", "demo")
    if mode == "demo":
        return DemoBackend(WEB / "fixtures")
    if mode == "live":
        return LiveBackend(effective.get("WEB_SHELL_API_BASE", ""))
    raise ShellContractError("WEB_SHELL_MODE must be demo or live")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FlowPilot web shell demo server")
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("WEB_SHELL_PORT", "8765"))
    )
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args(argv)
    server = DemoServer(build_backend(), args.port)
    print(f"FlowPilot web shell demo: http://{args.host}:{args.port}/")
    print("fixtures: web/fixtures · SSE: /api/v1/tasks/events · views: /views/tasks")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
