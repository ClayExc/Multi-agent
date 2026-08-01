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
import json
import os
import sys
import time
import urllib.parse
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

WEB = Path(__file__).resolve().parent
SRC = WEB / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from flowpilot_shell import (  # noqa: E402
    EventView,
    ShellContractError,
    ShellUnavailableError,
    TaskView,
)
from flowpilot_shell.commands import (  # noqa: E402
    build_retry_command,
    build_submit_message_command,
)
from flowpilot_shell.models import (  # noqa: E402
    ApprovalView,
    PlannedActionView,
    ResultArtifactView,
)
from flowpilot_shell.render import (  # noqa: E402
    render_error_panel,
    render_task_detail,
    render_task_list,
)
from flowpilot_shell.render.task_detail import render_task_not_found  # noqa: E402
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
    return json.loads((path / name).read_text(encoding="utf-8"))


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

    def task_projection(self, task_id: str) -> dict[str, Any] | None:
        task = self._live_tasks.get(task_id) or self._tasks.get(task_id)
        return task

    def all_tasks(self) -> tuple[TaskView, ...]:
        merged = dict(self._tasks)
        merged.update(self._live_tasks)
        return tuple(
            sorted(
                (TaskView.from_mapping(item) for item in merged.values()),
                key=lambda task: task.created_at,
            )
        )

    def all_events(self) -> list[dict[str, Any]]:
        fixture = json.loads(
            (WEB / "fixtures" / "events.v1.json").read_text(encoding="utf-8")
        )["events"]
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

    def accept_command(self, command: dict[str, Any]) -> dict[str, Any]:
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

    def rebuild(self, task_id: str) -> TaskView:
        projection = self.task_projection(task_id)
        if projection is None:
            raise ShellContractError(f"unknown task {task_id}")
        view = TaskView.from_mapping(projection)
        self.store.rebuild_from_projection(view)
        return view


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
    server: DemoServer  # type: ignore[assignment]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return  # keep the demo console quiet

    # -- routing -------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        backend = self.server.backend
        try:
            if path == "/" or path == "/index.html":
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
                    200, {"status": "ok", "service": "flowpilot-shell-demo"}
                )
            elif path == "/views/tasks":
                fragment = render_task_list(backend.all_tasks())
                self._send_text(fragment, "text/html; charset=utf-8")
            elif path.startswith("/views/tasks/"):
                self._handle_view_task(path.removeprefix("/views/tasks/"), query)
            elif path == "/api/v1/tasks/events":
                self._handle_sse(query)
            elif path.startswith("/api/v1/tasks/"):
                self._handle_api_task(path.removeprefix("/api/v1/tasks/"), query)
            else:
                self._send_json(404, ERROR_NOT_FOUND)
        except (BrokenPipeError, ConnectionResetError):
            return
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
            if parsed.path == "/api/v1/task-commands":
                body = self._read_body()
                command = json.loads(body.decode("utf-8"))
                receipt = backend.accept_command(command)
                self._send_json(202, receipt)
            elif parsed.path == "/shell/commands/submit":
                form = self._read_form()
                receipt = self._submit_completion(backend, form)
                self._send_json(200, {"accepted": True, "receipt": receipt})
            elif parsed.path == "/shell/commands/retry":
                form = self._read_form()
                receipt = self._retry_task(backend, form)
                self._send_json(200, {"accepted": True, "receipt": receipt})
            else:
                self._send_json(404, ERROR_NOT_FOUND)
        except (BrokenPipeError, ConnectionResetError):
            return
        except ShellContractError as exc:
            self._send_json(
                409,
                {
                    "error": {
                        "code": "TASK_VERSION_CONFLICT",
                        "message": str(exc),
                        "retryable": False,
                        "detail_ref": None,
                    }
                },
            )
        except (ValueError, KeyError) as exc:
            self._send_json(
                422,
                {
                    "error": {
                        "code": "CONTRACT_INVALID",
                        "message": str(exc),
                        "retryable": False,
                        "detail_ref": None,
                    }
                },
            )

    # -- view handlers -------------------------------------------------

    def _handle_view_task(self, task_id: str, query: dict[str, list[str]]) -> None:
        backend = self.server.backend
        if "demo" in query:
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
                backend.rebuild(task_id)
            except ShellContractError:
                self._send_text(
                    render_task_not_found(task_id), "text/html; charset=utf-8"
                )
                return
        projection = backend.task_projection(task_id)
        if projection is None:
            self._send_text(render_task_not_found(task_id), "text/html; charset=utf-8")
            return
        task = TaskView.from_mapping(projection)
        backend.store.rebuild_from_projection(task)
        fragment = render_task_detail(task, backend.store)
        self._send_text(fragment, "text/html; charset=utf-8")

    def _handle_api_task(self, task_id: str, query: dict[str, list[str]]) -> None:
        backend = self.server.backend
        if "simulate" in query and query["simulate"][0] == "unavailable":
            self._send_json(503, ERROR_UNAVAILABLE)
            return
        projection = backend.task_projection(task_id)
        if projection is None:
            self._send_json(404, ERROR_NOT_FOUND)
            return
        self._send_json(200, projection)

    # -- SSE -----------------------------------------------------------

    def _handle_sse(self, query: dict[str, list[str]]) -> None:
        backend = self.server.backend
        events = backend.all_events()
        task_filter = query.get("task_id", [None])[0]
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

    def _send_text(self, text: str, content_type: str) -> None:
        raw = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length) if length else b""

    def _read_form(self) -> dict[str, str]:
        body = self._read_body().decode("utf-8")
        return dict(urllib.parse.parse_qsl(body, keep_blank_values=True))

    def _submit_completion(
        self, backend: DemoBackend, form: dict[str, str]
    ) -> dict[str, Any]:
        task_id = form["task_id"]
        projection = backend.task_projection(task_id)
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
        return backend.accept_command(command)

    def _retry_task(self, backend: DemoBackend, form: dict[str, str]) -> dict[str, Any]:
        task_id = form["task_id"]
        projection = backend.task_projection(task_id)
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
        return backend.accept_command(command)


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

    def __init__(self, backend: DemoBackend, port: int) -> None:
        super().__init__(("127.0.0.1", port), ShellHandler)
        self.backend = backend

    def handle_error(self, request: Any, client_address: Any) -> None:
        # A client closing an SSE connection mid-ping is the normal
        # disconnect path; keep the demo console quiet about it.
        return


def build_backend() -> DemoBackend:
    return DemoBackend(WEB / "fixtures")


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
