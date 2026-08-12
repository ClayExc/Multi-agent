"""Real HTTP blackbox for the switchable Web API/SSE live adapter."""

from __future__ import annotations

import json
import sys
import threading
import urllib.request
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "web"
SRC = WEB / "src"
for path in (str(SRC), str(WEB), str(ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)


class AuthoritativeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    task: dict[str, Any]
    event: dict[str, Any]
    trusted_cookie = "__Host-flowpilot-session=live-session-opaque"
    observed: list[tuple[str, str | None, str | None, str | None]] = []

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def do_GET(self) -> None:  # noqa: N802
        type(self).observed.append(
            (
                self.path,
                self.headers.get("X-FlowPilot-Tenant-Id"),
                self.headers.get("Last-Event-ID"),
                self.headers.get("Cookie"),
            )
        )
        if self.headers.get("Cookie") != type(self).trusted_cookie:
            raw = json.dumps(
                {
                    "error": {
                        "code": "API_AUTHENTICATION_INVALID",
                        "message": "authentication failed",
                        "retryable": False,
                        "detail_ref": None,
                    }
                }
            ).encode()
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if self.path.startswith("/v1/tasks/events"):
            payload = json.dumps(
                type(self).event,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            raw = (
                f"id: {type(self).event['event_id']}\n"
                f"event: task.event\ndata: {payload}\n\n"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if self.path == f"/v1/tasks/{type(self).task['task_id']}":
            raw = json.dumps(type(self).task, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()


def test_live_web_uses_server_tenant_and_preserves_sse_resume() -> None:
    from flowpilot_shell.sse_client import parse_sse

    from web.server import DemoServer, LiveBackend

    fixtures = WEB / "fixtures"
    tasks = json.loads((fixtures / "tasks.v1.json").read_text(encoding="utf-8"))[
        "tasks"
    ]
    events = json.loads((fixtures / "events.v1.json").read_text(encoding="utf-8"))[
        "events"
    ]
    event = deepcopy(events[0])
    task = deepcopy(next(item for item in tasks if item["task_id"] == event["task_id"]))
    trusted_tenant = "tenant-server-owned"
    task["tenant_id"] = trusted_tenant
    task["security_context"]["tenant_id"] = trusted_tenant
    event["tenant_id"] = trusted_tenant
    AuthoritativeHandler.task = task
    AuthoritativeHandler.event = event
    AuthoritativeHandler.observed = []

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), AuthoritativeHandler)
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()
    upstream_host, upstream_port = upstream.server_address[:2]
    shell = DemoServer(
        LiveBackend(f"http://{upstream_host}:{upstream_port}"),
        0,
    )
    shell_thread = threading.Thread(target=shell.serve_forever, daemon=True)
    shell_thread.start()
    shell_host, shell_port = shell.server_address[:2]
    base = f"http://{shell_host}:{shell_port}"
    try:
        task_request = urllib.request.Request(
            f"{base}/api/v1/tasks/{task['task_id']}",
            headers={
                "Cookie": AuthoritativeHandler.trusted_cookie,
                "X-FlowPilot-Tenant-Id": "tenant-browser-forged",
            },
        )
        with urllib.request.urlopen(task_request, timeout=5) as response:
            projected = json.loads(response.read().decode())
        assert projected["tenant_id"] == trusted_tenant

        prior_event_id = "evt_prior_resume_0001"
        stream_request = urllib.request.Request(
            f"{base}/api/v1/tasks/events?task_id={task['task_id']}",
            headers={
                "Last-Event-ID": prior_event_id,
                "Cookie": AuthoritativeHandler.trusted_cookie,
                "X-FlowPilot-Tenant-Id": "tenant-browser-forged",
            },
        )
        with urllib.request.urlopen(stream_request, timeout=5) as response:
            frames = list(parse_sse([response.read()]))
        assert len(frames) == 1
        assert frames[0].id == event["event_id"]
        assert json.loads(frames[0].data)["tenant_id"] == trusted_tenant

        event_observation = next(
            item for item in AuthoritativeHandler.observed if "events" in item[0]
        )
        assert event_observation[1:] == (
            None,
            prior_event_id,
            AuthoritativeHandler.trusted_cookie,
        )
        assert all(
            tenant is None and cookie == AuthoritativeHandler.trusted_cookie
            for _path, tenant, _last_event_id, cookie in AuthoritativeHandler.observed
        )
    finally:
        shell.shutdown()
        shell.server_close()
        shell_thread.join(timeout=5)
        upstream.shutdown()
        upstream.server_close()
        upstream_thread.join(timeout=5)
