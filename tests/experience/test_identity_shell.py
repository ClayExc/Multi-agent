"""M8 Web identity experience at the browser/proxy observation boundary."""

from __future__ import annotations

import json
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
COOKIE_A = "__Host-flowpilot-session=sess_a"
COOKIE_B = "__Host-flowpilot-session=sess_b"
ACCESS_CANARY = "access-sensitive-canary"
REFRESH_CANARY = "refresh-sensitive-canary"
CODE_CANARY = "code-sensitive-canary"
NONCE_CANARY = "nonce-sensitive-canary"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        return None


class IdentityApiState:
    def __init__(self, fixture_files: dict[str, Any]) -> None:
        first, second = deepcopy(fixture_files["tasks.v1.json"]["tasks"][:2])
        self.task_a = self._bind_tenant(first, "tenant-a")
        self.task_b = self._bind_tenant(second, "tenant-b")
        event = deepcopy(fixture_files["events.v1.json"]["events"][0])
        event.update(
            {
                "tenant_id": "tenant-a",
                "task_id": self.task_a["task_id"],
                "thread_id": self.task_a["thread_id"],
                "task_version": self.task_a["version"],
                "event_id": "evt_identity_shell_0001",
                "sequence": 1,
            }
        )
        self.event = event
        self.calls: list[dict[str, Any]] = []
        self.sessions = {COOKIE_A: "a", COOKIE_B: "b"}

    @staticmethod
    def _bind_tenant(task: dict[str, Any], tenant_id: str) -> dict[str, Any]:
        task["tenant_id"] = tenant_id
        task["security_context"] = dict(task["security_context"])
        task["security_context"]["tenant_id"] = tenant_id
        return task


class IdentityApiHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: IdentityApiServer

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        del format, args

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        self._record(parsed.path)
        if parsed.path == "/v1/auth/login":
            if urllib.parse.parse_qs(parsed.query).get("cookie_case") == ["comment"]:
                self._send(
                    302,
                    b"",
                    {
                        "Location": "https://idp.example/authorize?request=opaque",
                        "Set-Cookie": (
                            "__Host-flowpilot-login=txn_opaque; Path=/; Secure; "
                            "SameSite=Lax; Comment=HttpOnly"
                        ),
                    },
                )
                return
            self._send(
                302,
                b"",
                {
                    "Location": "https://idp.example/authorize?request=opaque",
                    "Set-Cookie": (
                        "__Host-flowpilot-login=txn_opaque; Max-Age=300; Path=/; "
                        "HttpOnly; Secure; SameSite=lax"
                    ),
                },
            )
            return
        if parsed.path == "/v1/auth/callback":
            self.send_response(303)
            self.send_header("Location", "/studio")
            self.send_header(
                "Set-Cookie",
                "__Host-flowpilot-login=; Max-Age=0; Path=/; "
                "HttpOnly; Secure; SameSite=lax",
            )
            self.send_header(
                "Set-Cookie",
                "__Host-flowpilot-session=sess_a; Max-Age=3600; Path=/; "
                "HttpOnly; Secure; SameSite=lax",
            )
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if parsed.path == "/v1/tasks/events":
            if self._session() != "a":
                self._auth_error("API_AUTHENTICATION_INVALID")
                return
            payload = json.dumps(
                self.server.state.event,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            frame = (
                "id: evt_identity_shell_0001\n"
                "event: task.event\n"
                f"data: {payload}\n\n"
            ).encode()
            self._send(200, frame, {"Content-Type": "text/event-stream"})
            return
        if parsed.path.startswith("/v1/tasks/"):
            task_id = parsed.path.removeprefix("/v1/tasks/")
            session = self._session()
            allowed = {
                "a": self.server.state.task_a,
                "b": self.server.state.task_b,
            }.get(session)
            if allowed is None:
                self._auth_error("API_AUTHENTICATION_INVALID")
            elif allowed["task_id"] != task_id:
                self._json_error(403, "API_AUTHORIZATION_DENIED", "forbidden")
            else:
                self._json(200, allowed)
            return
        self._json_error(404, "TASK_NOT_FOUND", "not found")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        self._record(parsed.path)
        if parsed.path == "/v1/auth/refresh":
            cookie = self.headers.get("Cookie", "")
            session = self._session()
            if session is not None:
                rotated = f"__Host-flowpilot-session=sess_{session}_rotated"
                self.server.state.sessions.pop(cookie, None)
                self.server.state.sessions[rotated] = session
                self._send(
                    200,
                    json.dumps(
                        {
                            "status": "active",
                            "expires_at": "2026-08-11T16:00:00Z",
                        },
                        separators=(",", ":"),
                    ).encode(),
                    {
                        "Content-Type": "application/json",
                        "Set-Cookie": (
                            f"{rotated}; Max-Age=3600; "
                            "Path=/; HttpOnly; Secure; SameSite=lax"
                        ),
                    },
                )
            else:
                self._json_error(
                    401,
                    "API_AUTHENTICATION_INVALID",
                    ACCESS_CANARY + REFRESH_CANARY + NONCE_CANARY,
                    clear_cookie=True,
                )
            return
        if parsed.path == "/v1/auth/logout":
            self.server.state.sessions.pop(self.headers.get("Cookie", ""), None)
            self._send(
                204,
                b"",
                {
                    "Set-Cookie": (
                        "__Host-flowpilot-session=; Max-Age=0; Path=/; "
                        "HttpOnly; Secure; SameSite=lax"
                    )
                },
            )
            return
        if parsed.path == "/v1/task-commands":
            self._json_error(
                409,
                "TASK_VERSION_CONFLICT",
                ACCESS_CANARY + REFRESH_CANARY + NONCE_CANARY,
            )
            return
        self._json_error(404, "TASK_NOT_FOUND", "not found")

    def _record(self, path: str) -> None:
        self.server.state.calls.append(
            {
                "path": path,
                "cookie": self.headers.get("Cookie"),
                "last_event_id": self.headers.get("Last-Event-ID"),
                "forged_tenant": self.headers.get("X-FlowPilot-Tenant-Id"),
                "forged_role": self.headers.get("X-FlowPilot-Roles"),
            }
        )

    def _session(self) -> str | None:
        return self.server.state.sessions.get(self.headers.get("Cookie", ""))

    def _auth_error(self, code: str) -> None:
        self._json_error(401, code, "authentication failed")

    def _json_error(
        self,
        status: int,
        code: str,
        message: str,
        *,
        clear_cookie: bool = False,
    ) -> None:
        headers = (
            {
                "Set-Cookie": (
                    "__Host-flowpilot-session=; Max-Age=0; Path=/; "
                    "HttpOnly; Secure; SameSite=lax"
                )
            }
            if clear_cookie
            else None
        )
        self._json(
            status,
            {
                "error": {
                    "code": code,
                    "message": message,
                    "retryable": False,
                    "detail_ref": None,
                }
            },
            headers=headers,
        )

    def _json(
        self,
        status: int,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self._send(
            status,
            body,
            {"Content-Type": "application/json", **(headers or {})},
        )

    def _send(
        self,
        status: int,
        body: bytes,
        headers: dict[str, str],
    ) -> None:
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)


class IdentityApiServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, state: IdentityApiState) -> None:
        super().__init__(("127.0.0.1", 0), IdentityApiHandler)
        self.state = state


@pytest.fixture
def identity_servers():
    from web.server import DemoServer, LiveBackend

    fixture_files = {
        name: json.loads((ROOT / "web" / "fixtures" / name).read_text("utf-8"))
        for name in ("tasks.v1.json", "events.v1.json")
    }
    state = IdentityApiState(fixture_files)
    upstream = IdentityApiServer(state)
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()
    host, port = upstream.server_address[:2]
    backend = LiveBackend(f"http://{host}:{port}")
    shell = DemoServer(backend, 0)
    shell_thread = threading.Thread(target=shell.serve_forever, daemon=True)
    shell_thread.start()
    shell_host, shell_port = shell.server_address[:2]
    try:
        yield state, backend, f"http://{shell_host}:{shell_port}"
    finally:
        shell.shutdown()
        shell.server_close()
        shell_thread.join(timeout=5)
        upstream.shutdown()
        upstream.server_close()
        upstream_thread.join(timeout=5)


def _request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
) -> tuple[int, Any, bytes]:
    request = urllib.request.Request(
        url,
        data=(body if body is not None else b"") if method == "POST" else None,
        headers=headers or {},
        method=method,
    )
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        response = opener.open(request, timeout=5)
        body = response.read()
        result = response.status, response.headers, body
        response.close()
        return result
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


def _header_text(headers: Any) -> str:
    return "\n".join(f"{name}: {value}" for name, value in headers.items())


def test_identity_markup_is_accessible_and_has_no_authority_inputs() -> None:
    html = (ROOT / "web" / "shell" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "web" / "shell" / "app.js").read_text(encoding="utf-8")

    assert 'id="session-status"' in html and 'role="status"' in html
    assert "登录" in html and "退出登录" in html and "验证并刷新会话" in html
    assert 'href="/api/v1/auth/login"' in html
    assert 'name="tenant' not in html.lower()
    assert 'name="role' not in html.lower()
    for forbidden in (
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "Authorization",
        "X-FlowPilot-Tenant",
        "X-FlowPilot-Roles",
        "atob(",
    ):
        assert forbidden not in script
    assert "SAFE_AUTH_CODES" in script
    assert "seenEventIds" in script
    assert "replaceViewMessage" in script
    assert "authEpoch" in script
    assert "AbortController" in script
    assert "isCurrentAuthOperation" in script


def test_browser_identity_epoch_blocks_stale_logout_races() -> None:
    completed = subprocess.run(
        ["node", str(ROOT / "tests/experience/browser_identity_race.cjs")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "browser identity race gate: PASS" in completed.stdout


def test_auth_proxy_login_callback_refresh_logout_is_token_safe(
    identity_servers,
) -> None:
    _state, _backend, base = identity_servers
    status, headers, body = _request(base + "/api/v1/auth/login")
    assert status == 302
    assert headers["Location"].startswith("https://idp.example/")
    assert "HttpOnly" in headers["Set-Cookie"]
    assert "Secure" in headers["Set-Cookie"]
    assert "SameSite=lax" in headers["Set-Cookie"]
    assert headers["Cache-Control"] == "no-store"

    status, callback_headers, callback_body = _request(
        base + "/api/v1/auth/callback?state=opaque&code=" + CODE_CANARY,
        headers={"Cookie": "__Host-flowpilot-login=txn_opaque"},
    )
    assert status == 303
    assert callback_headers["Location"] == "/studio"
    assert len(callback_headers.get_all("Set-Cookie")) == 2

    status, refresh_headers, refresh_body = _request(
        base + "/api/v1/auth/refresh",
        method="POST",
        headers={"Cookie": COOKIE_A},
    )
    assert status == 200
    assert json.loads(refresh_body) == {
        "expires_at": "2026-08-11T16:00:00Z",
        "status": "active",
    }
    assert "sess_a_rotated" in refresh_headers["Set-Cookie"]

    status, logout_headers, logout_body = _request(
        base + "/api/v1/auth/logout",
        method="POST",
        headers={"Cookie": "__Host-flowpilot-session=sess_a_rotated"},
    )
    assert status == 204 and logout_body == b""
    assert "Max-Age=0" in logout_headers["Set-Cookie"]

    exposed = b"".join((body, callback_body, refresh_body, logout_body)).decode()
    exposed += _header_text(headers)
    exposed += _header_text(callback_headers)
    exposed += _header_text(refresh_headers)
    exposed += _header_text(logout_headers)
    for canary in (ACCESS_CANARY, REFRESH_CANARY, CODE_CANARY, NONCE_CANARY):
        assert canary not in exposed


@pytest.mark.parametrize("cookie", ["sess_expired", "sess_revoked"])
def test_refresh_failure_clears_cookie_and_sanitizes_upstream_error(
    identity_servers,
    cookie: str,
) -> None:
    _state, _backend, base = identity_servers
    status, headers, body = _request(
        base + "/api/v1/auth/refresh",
        method="POST",
        headers={"Cookie": "__Host-flowpilot-session=" + cookie},
    )

    assert status == 401
    assert json.loads(body)["error"] == {
        "code": "API_AUTHENTICATION_INVALID",
        "detail_ref": None,
        "message": "会话已过期或已撤销，请重新认证。",
        "retryable": False,
    }
    assert "Max-Age=0" in headers["Set-Cookie"]
    exposed = body.decode() + _header_text(headers)
    assert ACCESS_CANARY not in exposed
    assert REFRESH_CANARY not in exposed
    assert NONCE_CANARY not in exposed


@pytest.mark.parametrize(
    "cookie",
    [
        "__Host-flowpilot-session=value; Path=/; Secure; SameSite=Lax; "
        "Comment=HttpOnly",
        "__Host-flowpilot-session=value; Path=/; HttpOnly; Secure=1; "
        "SameSite=Lax",
        "__Host-flowpilot-session=value; Path=/; Path=/other; HttpOnly; "
        "Secure; SameSite=Lax",
        "__Host-flowpilot-session=value; Path=/; Domain=example.test; "
        "HttpOnly; Secure; SameSite=Lax",
    ],
)
def test_cookie_security_attributes_are_parsed_not_substring_matched(
    cookie: str,
) -> None:
    from web.server import _safe_set_cookie

    assert not _safe_set_cookie(cookie)


def test_malformed_upstream_cookie_fails_closed_without_forwarding(
    identity_servers,
) -> None:
    _state, _backend, base = identity_servers
    status, headers, body = _request(
        base + "/api/v1/auth/login?cookie_case=comment"
    )

    assert status == 503
    assert headers.get_all("Set-Cookie") is None
    assert json.loads(body)["error"]["code"] == "API_DEPENDENCY_UNAVAILABLE"


def test_live_command_error_does_not_expose_upstream_message(
    identity_servers,
) -> None:
    state, _backend, base = identity_servers
    task_id = state.task_a["task_id"]
    assert _request(
        base + "/api/v1/tasks/" + task_id,
        headers={"Cookie": COOKIE_A},
    )[0] == 200

    status, _headers, body = _request(
        base + "/shell/commands/submit",
        method="POST",
        headers={
            "Cookie": COOKIE_A,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        body=urllib.parse.urlencode({"task_id": task_id}).encode(),
    )

    assert status == 409
    payload = json.loads(body)
    assert payload["error"]["code"] == "TASK_VERSION_CONFLICT"
    assert payload["error"]["message"] == (
        "请求与当前任务状态冲突，请刷新后重试。"
    )
    exposed = body.decode()
    for canary in (ACCESS_CANARY, REFRESH_CANARY, NONCE_CANARY):
        assert canary not in exposed


def test_live_cache_and_authority_are_isolated_by_opaque_session(
    identity_servers,
) -> None:
    state, _backend, base = identity_servers
    task_a = state.task_a["task_id"]
    task_b = state.task_b["task_id"]
    status, _headers, _body = _request(
        base + "/api/v1/tasks/" + task_a,
        headers={
            "Cookie": COOKIE_A,
            "X-FlowPilot-Tenant-Id": "tenant-b",
            "X-FlowPilot-Roles": "admin",
        },
    )
    assert status == 200
    upstream = state.calls[-1]
    assert upstream["cookie"] == COOKIE_A
    assert upstream["forged_tenant"] is None
    assert upstream["forged_role"] is None

    assert _request(base + "/api/v1/tasks/" + task_b, headers={"Cookie": COOKIE_B})[
        0
    ] == 200
    _status, _headers, view_a = _request(
        base + "/views/tasks",
        headers={"Cookie": COOKIE_A},
    )
    _status, _headers, view_b = _request(
        base + "/views/tasks",
        headers={"Cookie": COOKIE_B},
    )
    assert task_a in view_a.decode() and task_b not in view_a.decode()
    assert task_b in view_b.decode() and task_a not in view_b.decode()

    denied, denied_headers, denied_body = _request(
        base + "/api/v1/tasks/" + task_b,
        headers={"Cookie": COOKIE_A},
    )
    assert denied == 403
    assert denied_headers["Cache-Control"] == "no-store"
    assert json.loads(denied_body)["error"]["code"] == "API_AUTHORIZATION_DENIED"


def test_unvalidated_or_ambiguous_session_cannot_activate_live_views(
    identity_servers,
) -> None:
    state, _backend, base = identity_servers
    task_id = state.task_a["task_id"]

    for cookie in (
        "__Host-flowpilot-session=forged",
        COOKIE_A + "; " + COOKIE_B,
    ):
        status, _headers, body = _request(
            base + "/views/tasks",
            headers={"Cookie": cookie},
        )
        assert status == 401
        assert "重新认证".encode() in body or "登录".encode() in body

    demo_status, _headers, demo_body = _request(
        base + f"/views/tasks/{task_id}?demo=missing",
        headers={"Cookie": "__Host-flowpilot-session=forged"},
    )
    assert demo_status == 401
    assert task_id.encode() not in demo_body

    simulate_status, _headers, simulate_body = _request(
        base + f"/api/v1/tasks/{task_id}?simulate=unavailable",
        headers={"Cookie": "__Host-flowpilot-session=forged"},
    )
    assert simulate_status == 401
    assert json.loads(simulate_body)["error"]["code"] == (
        "API_AUTHENTICATION_INVALID"
    )


def test_sse_replay_forwards_last_id_and_deduplicates_session_store(
    identity_servers,
) -> None:
    state, backend, _base = identity_servers
    first = b"".join(
        backend.iter_event_frames(
            last_event_id=None,
            task_id=None,
            cookie_header=COOKIE_A,
        )
    )
    replay = b"".join(
        backend.iter_event_frames(
            last_event_id="evt_identity_shell_0001",
            task_id=None,
            cookie_header=COOKIE_A,
        )
    )

    assert first == replay
    timeline = backend.store_for(COOKIE_A).timeline_events(state.task_a["task_id"])
    assert len(timeline) == 1
    sse_calls = [call for call in state.calls if call["path"] == "/v1/tasks/events"]
    assert [call["last_event_id"] for call in sse_calls] == [
        None,
        "evt_identity_shell_0001",
    ]
