from __future__ import annotations

import copy
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
COOKIE_A = "__Host-flowpilot-session=sess_knowledge_a"
COOKIE_B = "__Host-flowpilot-session=sess_knowledge_b"
CONTENT_CANARY = "M10_RAW_BODY_SHOULD_NEVER_RETURN"
SECRET_CANARY = "sk-m10-secret-should-never-return"
REASONING_CANARY = "M10_HIDDEN_REASONING_SHOULD_NEVER_RETURN"
VECTOR_CANARY = "[0.123456,0.987654]"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
EXPECTED_DRIFT = "sha256:" + "c" * 64


def _document(document_id: str, *, content_hash: str = HASH_A) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "revision": 2,
        "current_version": 1,
        "lifecycle": "active",
        "document_version": 1,
        "source_type": "manual",
        "source_version": "v1",
        "source_digest": "sha256:" + "d" * 64,
        "acl_digest": "sha256:" + "e" * 64,
        "data_classification": "internal",
        "effective_at": "2026-08-16T00:00:00Z",
        "expires_at": None,
        "content_hash": content_hash,
        "created_at": "2026-08-16T00:00:00Z",
        "updated_at": "2026-08-16T01:00:00Z",
    }


class KnowledgeApiState:
    def __init__(self) -> None:
        fixtures = json.loads(
            (ROOT / "web" / "fixtures" / "tasks.v1.json").read_text("utf-8")
        )
        failed = next(
            copy.deepcopy(item)
            for item in fixtures["tasks"]
            if item["task_id"] == "task_inventory_005"
        )
        failed["error"] = {
            "code": "RUNTIME_KNOWLEDGE_NO_RESULT",
            "retryable": False,
            "detail_ref": None,
        }
        self.task = failed
        events = json.loads(
            (ROOT / "web" / "fixtures" / "events.v1.json").read_text("utf-8")
        )["events"]
        self.event = next(
            copy.deepcopy(item)
            for item in events
            if item["task_id"] == "task_inventory_005"
        )
        self.documents = {
            "tenant-a": {"doc_knowledge_a": _document("doc_knowledge_a")},
            "tenant-b": {
                "doc_knowledge_b": _document("doc_knowledge_b", content_hash=HASH_B)
            },
        }
        self.calls: list[dict[str, Any]] = []
        self.unavailable = False
        self.poison_projection = False


class KnowledgeApiHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: KnowledgeApiServer

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        del format, args

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        self._record(parsed.path, None)
        if self.server.state.unavailable and parsed.path.startswith("/v1/knowledge/"):
            self._error(503, "KNOWLEDGE_UNAVAILABLE", CONTENT_CANARY)
            return
        if parsed.path == "/v1/tasks/events":
            if self._tenant() != "tenant-a":
                self._error(401, "API_AUTHENTICATION_INVALID", SECRET_CANARY)
                return
            payload = json.dumps(
                self.server.state.event,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            frame = (
                f"id: {self.server.state.event['event_id']}\n"
                "event: task.event\n"
                f"data: {payload}\n\n"
            ).encode()
            self._send(200, frame, {"Content-Type": "text/event-stream"})
            return
        if parsed.path == "/v1/tasks/task_inventory_005":
            if self._tenant() != "tenant-a":
                self._error(403, "API_AUTHORIZATION_DENIED", SECRET_CANARY)
                return
            self._json(200, self.server.state.task)
            return
        if parsed.path.startswith("/v1/knowledge/documents/"):
            self._knowledge_get(parsed)
            return
        self._error(404, "RESOURCE_NOT_FOUND", "not found")

    def do_POST(self) -> None:  # noqa: N802
        self._knowledge_write("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._knowledge_write("PUT")

    def _knowledge_get(self, parsed: urllib.parse.SplitResult) -> None:
        tenant = self._tenant()
        if tenant is None:
            self._error(401, "API_AUTHENTICATION_INVALID", SECRET_CANARY)
            return
        suffix = parsed.path.removeprefix("/v1/knowledge/documents/")
        diagnostic = suffix.endswith("/diagnostic")
        document_id = suffix.removesuffix("/diagnostic")
        document = self.server.state.documents.get(tenant, {}).get(document_id)
        if document is None:
            self._error(404, "KNOWLEDGE_NOT_FOUND", REASONING_CANARY)
            return
        values = urllib.parse.parse_qs(parsed.query)
        if values and values != {
            "document_version": [str(document["document_version"])]
        }:
            self._error(404, "KNOWLEDGE_VERSION_NOT_FOUND", CONTENT_CANARY)
            return
        if diagnostic:
            self._json(
                200,
                {
                    "document_id": document_id,
                    "document_version": document["document_version"],
                    "document_revision": document["revision"],
                    "content_hash": document["content_hash"],
                    "index_state": "ready",
                    "last_job_id": "job_m10_knowledge_0001",
                    "indexed_at": "2026-08-16T01:02:00Z",
                    "failure_code": None,
                },
                private=True,
            )
            return
        projection = dict(document)
        if self.server.state.poison_projection:
            projection.update(
                {
                    "content": CONTENT_CANARY,
                    "vector": VECTOR_CANARY,
                    "reasoning": REASONING_CANARY,
                    "secret": SECRET_CANARY,
                }
            )
        self._json(200, projection, private=True)

    def _knowledge_write(self, method: str) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        body = self._read_json()
        self._record(parsed.path, body)
        tenant = self._tenant()
        if tenant != "tenant-a":
            self._error(403, "API_AUTHORIZATION_DENIED", SECRET_CANARY)
            return
        if "tenant_id" in body or "role" in body:
            self._error(422, "KNOWLEDGE_CONTRACT_INVALID", REASONING_CANARY)
            return
        if method == "PUT":
            document_id = parsed.path.rsplit("/", 1)[-1]
            document = self.server.state.documents[tenant].get(document_id)
            if document is None:
                self._error(404, "KNOWLEDGE_NOT_FOUND", CONTENT_CANARY)
                return
            if body.get("expected_revision") != document["revision"]:
                self._error(
                    409,
                    "KNOWLEDGE_REVISION_CONFLICT",
                    CONTENT_CANARY + SECRET_CANARY,
                )
                return
            document = dict(document)
            document["revision"] += 1
            document["current_version"] += 1
            document["document_version"] += 1
            document["content_hash"] = "sha256:" + "f" * 64
            self.server.state.documents[tenant][document_id] = document
            self._receipt(document, "update")
            return
        if parsed.path == "/v1/knowledge/documents":
            document_id = str(body["document_id"])
            document = _document(document_id)
            document["revision"] = 0
            document["current_version"] = 0
            document["document_version"] = 0
            self.server.state.documents[tenant][document_id] = document
            self._receipt(document, "import", status=201)
            return
        suffix = parsed.path.removeprefix("/v1/knowledge/documents/")
        document_id, _, operation = suffix.partition("/")
        document = self.server.state.documents[tenant].get(document_id)
        if document is None:
            self._error(404, "KNOWLEDGE_NOT_FOUND", CONTENT_CANARY)
            return
        if body.get("expected_revision") != document["revision"]:
            self._error(409, "KNOWLEDGE_REVISION_CONFLICT", SECRET_CANARY)
            return
        if operation not in {"retire", "rebuild"}:
            self._error(422, "KNOWLEDGE_CONTRACT_INVALID", REASONING_CANARY)
            return
        self._receipt(document, operation)

    def _receipt(
        self, document: dict[str, Any], operation: str, *, status: int = 200
    ) -> None:
        self._json(
            status,
            {
                "document_id": document["document_id"],
                "operation": operation,
                "revision": document["revision"],
                "document_version": document["document_version"],
                "disposition": "applied",
                "event_id": f"evt_m10_{operation}_0001",
                "index_job_id": f"job_m10_{operation}_0001",
            },
        )

    def _tenant(self) -> str | None:
        return {
            COOKIE_A: "tenant-a",
            COOKIE_B: "tenant-b",
        }.get(self.headers.get("Cookie"))

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        value: object = json.loads(self.rfile.read(length).decode())
        assert isinstance(value, dict)
        return dict(value)

    def _record(self, path: str, body: dict[str, Any] | None) -> None:
        self.server.state.calls.append(
            {
                "path": path,
                "cookie": self.headers.get("Cookie"),
                "forged_tenant": self.headers.get("X-FlowPilot-Tenant-Id"),
                "forged_role": self.headers.get("X-FlowPilot-Roles"),
                "last_event_id": self.headers.get("Last-Event-ID"),
                "body": body,
            }
        )

    def _error(self, status: int, code: str, message: str) -> None:
        self._json(
            status,
            {
                "error": {
                    "code": code,
                    "message": message,
                    "retryable": status >= 500,
                    "detail_ref": None,
                }
            },
        )

    def _json(
        self, status: int, payload: dict[str, Any], *, private: bool = False
    ) -> None:
        headers = {"Content-Type": "application/json"}
        if private:
            headers.update({"Cache-Control": "no-store", "Vary": "Cookie"})
        self._send(status, json.dumps(payload, ensure_ascii=False).encode(), headers)

    def _send(self, status: int, body: bytes, headers: dict[str, str]) -> None:
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)


class KnowledgeApiServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, state: KnowledgeApiState) -> None:
        super().__init__(("127.0.0.1", 0), KnowledgeApiHandler)
        self.state = state


@contextmanager
def _servers() -> Iterator[tuple[KnowledgeApiState, Any, str]]:
    from web.server import DemoServer, LiveBackend

    state = KnowledgeApiState()
    upstream = KnowledgeApiServer(state)
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
    cookie: str = COOKIE_A,
    form: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any, bytes]:
    body = urllib.parse.urlencode(form).encode() if form is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Cookie": cookie,
            **(
                {"Content-Type": "application/x-www-form-urlencoded"}
                if form is not None
                else {}
            ),
            **(headers or {}),
        },
    )
    try:
        response = urllib.request.urlopen(request, timeout=5)
        result = response.status, response.headers, response.read()
        response.close()
        return result
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


def _write_form(
    document_id: str, *, expected_revision: str | None = None
) -> dict[str, str]:
    form = {
        "document_id": document_id,
        "source_type": "manual",
        "source_ref": "ref://knowledge/input",
        "source_version": "v2",
        "data_classification": "internal",
        "effective_at": "2026-08-16T00:00:00Z",
        "expires_at": "",
        "content": CONTENT_CANARY,
    }
    if expected_revision is not None:
        form["expected_revision"] = expected_revision
    return form


def _exposed(body: bytes) -> str:
    return body.decode("utf-8", errors="replace")


def test_cookie_only_lookup_and_session_scoped_safe_list() -> None:
    with _servers() as (state, _backend, base):
        status, headers, body = _request(
            base + "/views/knowledge?document_id=doc_knowledge_a",
            headers={
                "X-FlowPilot-Tenant-Id": "tenant-b",
                "X-FlowPilot-Roles": "admin",
            },
        )
        assert status == 200
        assert headers["Cache-Control"] == "no-store"
        page = _exposed(body)
        assert "doc_knowledge_a" in page and "可检索" in page
        assert "tenant-a" not in page and "tenant-b" not in page
        assert state.calls[-2]["forged_tenant"] is None
        assert state.calls[-2]["forged_role"] is None

        denied, _, denied_body = _request(
            base + "/views/knowledge?document_id=doc_knowledge_b"
        )
        assert denied == 404
        assert "doc_knowledge_b" not in _exposed(denied_body)

        status_b, _, body_b = _request(
            base + "/views/knowledge?document_id=doc_knowledge_b",
            cookie=COOKIE_B,
        )
        assert status_b == 200 and "doc_knowledge_b" in _exposed(body_b)
        assert "doc_knowledge_a" not in _exposed(body_b)


def test_exact_version_and_citation_drift_fail_closed_without_content() -> None:
    with _servers() as (_state, _backend, base):
        drift_url = (
            base
            + "/views/knowledge?"
            + urllib.parse.urlencode(
                {
                    "document_id": "doc_knowledge_a",
                    "document_version": "1",
                    "expected_hash": EXPECTED_DRIFT,
                }
            )
        )
        status, _, body = _request(drift_url)
        page = _exposed(body)
        assert status == 200
        assert 'data-citation-status="drift"' in page
        assert "拒绝展示正文或替代版本" in page
        for forbidden in (
            CONTENT_CANARY,
            SECRET_CANARY,
            REASONING_CANARY,
            VECTOR_CANARY,
        ):
            assert forbidden not in page

        missing, _, missing_body = _request(
            base + "/views/knowledge?document_id=doc_knowledge_a&document_version=0"
        )
        assert missing == 404
        assert "未尝试重定向到其他版本" in _exposed(missing_body)


def test_unknown_projection_fields_are_rejected_without_leaking_values() -> None:
    with _servers() as (state, _backend, base):
        state.poison_projection = True
        status, _, body = _request(
            base + "/views/knowledge?document_id=doc_knowledge_a"
        )
        page = _exposed(body)
        assert status == 502
        assert "知识投影不可用" in page
        for forbidden in (
            CONTENT_CANARY,
            SECRET_CANARY,
            REASONING_CANARY,
            VECTOR_CANARY,
        ):
            assert forbidden not in page


def test_import_body_is_single_use_and_never_echoed_to_browser() -> None:
    with _servers() as (state, _backend, base):
        status, headers, body = _request(
            base + "/shell/knowledge/import",
            method="POST",
            form=_write_form("doc_imported_01"),
            headers={
                "X-FlowPilot-Tenant-Id": "tenant-b",
                "X-FlowPilot-Roles": "admin",
            },
        )
        assert status == 200 and headers["Cache-Control"] == "no-store"
        response = _exposed(body)
        assert json.loads(response)["receipt"]["document_id"] == "doc_imported_01"
        assert CONTENT_CANARY not in response
        write_call = next(
            item for item in state.calls if item["path"] == "/v1/knowledge/documents"
        )
        assert write_call["cookie"] == COOKIE_A
        assert write_call["forged_tenant"] is None
        assert write_call["forged_role"] is None
        assert write_call["body"]["content"] == CONTENT_CANARY
        assert "tenant_id" not in write_call["body"]

        list_status, _, list_body = _request(base + "/views/knowledge")
        assert list_status == 200 and "doc_imported_01" in _exposed(list_body)
        assert CONTENT_CANARY not in _exposed(list_body)


def test_rebuild_update_and_retire_preserve_exact_revision_bindings() -> None:
    with _servers() as (state, _backend, base):
        rebuild, _, rebuild_body = _request(
            base + "/shell/knowledge/rebuild",
            method="POST",
            form={
                "document_id": "doc_knowledge_a",
                "expected_revision": "2",
                "document_version": "1",
            },
        )
        assert rebuild == 200
        assert json.loads(rebuild_body)["receipt"]["operation"] == "rebuild"

        updated, _, updated_body = _request(
            base + "/shell/knowledge/update",
            method="POST",
            form=_write_form("doc_knowledge_a", expected_revision="2"),
        )
        update_receipt = json.loads(updated_body)["receipt"]
        assert updated == 200
        assert (update_receipt["revision"], update_receipt["document_version"]) == (
            3,
            2,
        )
        assert CONTENT_CANARY not in _exposed(updated_body)

        retired, _, retired_body = _request(
            base + "/shell/knowledge/retire",
            method="POST",
            form={
                "document_id": "doc_knowledge_a",
                "expected_revision": "3",
            },
        )
        assert retired == 200
        assert json.loads(retired_body)["receipt"]["operation"] == "retire"
        status, _, list_body = _request(base + "/views/knowledge")
        assert status == 200 and "doc_knowledge_a" not in _exposed(list_body)

        writes = [
            call
            for call in state.calls
            if call["path"].startswith("/v1/knowledge/") and call["body"] is not None
        ]
        assert [call["body"] for call in writes] == [
            {"document_version": 1, "expected_revision": 2},
            {
                "content": CONTENT_CANARY,
                "data_classification": "internal",
                "effective_at": "2026-08-16T00:00:00Z",
                "expected_revision": 2,
                "expires_at": None,
                "source_ref": "ref://knowledge/input",
                "source_type": "manual",
                "source_version": "v2",
            },
            {"expected_revision": 3},
        ]


def test_concurrent_update_conflict_is_stable_and_sanitized() -> None:
    with _servers() as (_state, _backend, base):
        status, _, body = _request(
            base + "/shell/knowledge/update",
            method="POST",
            form=_write_form("doc_knowledge_a", expected_revision="1"),
        )
        payload = json.loads(body)
        assert status == 409
        assert payload["error"]["code"] == "KNOWLEDGE_REVISION_CONFLICT"
        assert CONTENT_CANARY not in _exposed(body)
        assert SECRET_CANARY not in _exposed(body)


@pytest.mark.parametrize("authority_field", ["tenant_id", "role"])
def test_browser_authority_fields_are_rejected_before_upstream(
    authority_field: str,
) -> None:
    with _servers() as (state, _backend, base):
        form = _write_form("doc_imported_02")
        form[authority_field] = (
            "tenant-b" if authority_field == "tenant_id" else "admin"
        )
        status, _, body = _request(
            base + "/shell/knowledge/import",
            method="POST",
            form=form,
        )
        assert status == 422
        assert json.loads(body)["error"]["code"] == "CONTRACT_INVALID"
        assert not any(
            call["path"] == "/v1/knowledge/documents" for call in state.calls
        )


@pytest.mark.parametrize("cookie", ["", "__Host-flowpilot-session=forged"])
def test_missing_or_forged_session_cannot_read_knowledge(cookie: str) -> None:
    with _servers() as (_state, _backend, base):
        status, _, body = _request(
            base + "/views/knowledge?document_id=doc_knowledge_a",
            cookie=cookie,
        )
        assert status == 401
        assert "需要重新认证" in _exposed(body)
        assert HASH_A not in _exposed(body)


def test_unavailable_recovery_uses_fresh_authoritative_projection() -> None:
    with _servers() as (state, _backend, base):
        state.unavailable = True
        failed, _, failed_body = _request(
            base + "/views/knowledge?document_id=doc_knowledge_a"
        )
        assert failed == 503
        assert HASH_A not in _exposed(failed_body)
        assert CONTENT_CANARY not in _exposed(failed_body)

        state.unavailable = False
        recovered, _, recovered_body = _request(
            base + "/views/knowledge?document_id=doc_knowledge_a"
        )
        assert recovered == 200
        assert HASH_A in _exposed(recovered_body)


def test_no_evidence_and_sse_replay_do_not_invent_answer_or_duplicate_event() -> None:
    with _servers() as (state, backend, base):
        status, _, body = _request(base + "/views/tasks/task_inventory_005")
        page = _exposed(body)
        assert status == 200
        assert "不知道；需要更多信息" in page
        assert "没有生成推测性答案" in page
        assert "result_ref" not in page

        first = b"".join(
            backend.iter_event_frames(
                last_event_id=None,
                task_id="task_inventory_005",
                cookie_header=COOKIE_A,
            )
        )
        replay = b"".join(
            backend.iter_event_frames(
                last_event_id=state.event["event_id"],
                task_id="task_inventory_005",
                cookie_header=COOKIE_A,
            )
        )
        assert first == replay
        timeline = backend.store_for(COOKIE_A).timeline_events("task_inventory_005")
        assert len(timeline) == 1
        sse_calls = [call for call in state.calls if call["path"] == "/v1/tasks/events"]
        assert [call["last_event_id"] for call in sse_calls] == [
            None,
            state.event["event_id"],
        ]


def test_knowledge_markup_is_accessible_and_has_no_authority_inputs() -> None:
    html = (ROOT / "web" / "shell" / "index.html").read_text("utf-8")
    script = (ROOT / "web" / "shell" / "app.js").read_text("utf-8")
    assert 'href="#/knowledge"' in html
    assert 'aria-label="知识版本与引用回查"' in (
        ROOT / "web" / "src" / "flowpilot_shell" / "render" / "knowledge.py"
    ).read_text("utf-8")
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
