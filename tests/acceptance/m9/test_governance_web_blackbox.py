"""Independent HTTP blackbox for the read-only M9 governance console."""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "web" / "src"))

COOKIE_A = "__Host-flowpilot-session=governance-a"
COOKIE_B = "__Host-flowpilot-session=governance-b"
SECRET_CANARY = "sk-proj-governancecredential0001"
PROMPT_CANARY = "raw governance prompt canary"
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
CURSOR = "gcur_" + "A" * 24


def _records(marker: str) -> dict[str, dict[str, object]]:
    suffix = "a0000001" if marker == "a" else "b0000001"
    policy = f"policy-{marker}-v9"
    decision_id = f"pd_{suffix}"
    task_id = f"task_{suffix}"
    event_id = f"evt_{suffix}"
    security_id = f"sevt_{suffix}"
    correlation_id = f"correlation-{marker}-001"
    version = {
        "version": policy,
        "bundle_digest": DIGEST_A if marker == "a" else DIGEST_B,
        "active": True,
        "parent_version": f"policy-{marker}-v8",
        "published_at": "2026-08-16T01:00:00Z",
        "revoked_at": None,
        "rollback_of": None,
    }
    decision = {
        "decision_id": decision_id,
        "task_id": task_id,
        "decision": "deny",
        "policy_version": policy,
        "reason_codes": ["TENANT_POLICY"],
        "obligation_names": ["audit_level"],
        "action_digest": DIGEST_B,
        "evaluated_at": "2026-08-16T01:01:00Z",
        "expires_at": "2026-08-16T01:06:00Z",
    }
    audit = {
        "event_id": event_id,
        "event_type": "governance.policy.decision.v1",
        "occurred_at": "2026-08-16T01:01:01Z",
        "trace_id": f"trace-{marker}-governance",
        "thread_id": f"thread_{suffix}",
        "task_id": task_id,
        "run_id": f"run_{suffix}",
        "correlation_id": correlation_id,
        "causation_id": f"cause-{marker}-001",
        "action": "knowledge.read",
        "decision": "deny",
        "reason_codes": ["TENANT_POLICY"],
        "result": "blocked",
        "data_classification": "internal",
        "stream_id": f"audit-stream-{marker}",
        "sequence": 1,
        "event_hash": DIGEST_A,
        "previous_hash": None,
        "policy_decision_id": decision_id,
        "policy_version": policy,
        "approval_id": None,
        "action_digest": DIGEST_B,
        "tool_execution_id": None,
        "security_event_id": security_id,
    }
    security = {
        "event_id": security_id,
        "event_type": "security.authorization.denied.v1",
        "occurred_at": "2026-08-16T01:01:02Z",
        "trace_id": f"trace-{marker}-governance",
        "thread_id": f"thread_{suffix}",
        "task_id": task_id,
        "run_id": f"run_{suffix}",
        "correlation_id": correlation_id,
        "causation_id": event_id,
        "control_component": "mcp-gateway",
        "control_rule_id": "tenant.boundary",
        "control_rule_version": policy,
        "reason_codes": ["TENANT_POLICY"],
        "severity": "high",
        "category": "authorization",
        "control_outcome": "blocked",
        "impact": "attempted",
        "disposition": "contained",
        "data_classification": "restricted",
        "policy_decision_id": decision_id,
        "audit_event_id": event_id,
        "event_hash": DIGEST_B,
    }
    return {
        "version": version,
        "decision": decision,
        "audit": audit,
        "security": security,
    }


class GovernanceApiState:
    def __init__(self) -> None:
        self.records = {"a": _records("a"), "b": _records("b")}
        self.sessions = {COOKIE_A: "a", COOKIE_B: "b"}
        self.revoked: set[str] = set()
        self.mode = "normal"
        self.calls: list[dict[str, Any]] = []


class GovernanceApiHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: GovernanceApiServer

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        del format, args

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        cookie = self.headers.get("Cookie", "")
        marker = self.server.state.sessions.get(cookie)
        self.server.state.calls.append(
            {
                "path": parsed.path,
                "query": urllib.parse.parse_qs(parsed.query),
                "cookie": cookie,
                "tenant_header": self.headers.get("X-FlowPilot-Tenant-Id"),
                "role_header": self.headers.get("X-FlowPilot-Roles"),
            }
        )
        if marker is None or cookie in self.server.state.revoked:
            self._error(401, "API_AUTHENTICATION_INVALID")
            return
        if self.server.state.mode == "unavailable":
            self._error(503, "API_DEPENDENCY_UNAVAILABLE")
            return
        records = self.server.state.records[marker]
        query = urllib.parse.parse_qs(parsed.query)
        selected = self._filtered(records, query)
        if parsed.path == "/v1/governance/policy-versions":
            self._page(selected["version"], query)
        elif parsed.path == "/v1/governance/policy-decisions":
            self._page(selected["decision"], query)
        elif parsed.path == "/v1/governance/audit-events":
            audit = deepcopy(selected["audit"])
            if self.server.state.mode == "compromised" and audit is not None:
                audit["prompt"] = PROMPT_CANARY + SECRET_CANARY
            self._page(audit, query)
        elif parsed.path == "/v1/governance/security-events":
            self._page(selected["security"], query)
        elif parsed.path.startswith("/v1/governance/correlations/"):
            requested = urllib.parse.unquote(
                parsed.path.removeprefix("/v1/governance/correlations/")
            )
            expected = str(records["audit"]["correlation_id"])
            if requested != expected:
                self._error(404, "GOVERNANCE_CORRELATION_NOT_FOUND")
                return
            self._json(
                200,
                {
                    "correlation_id": expected,
                    "policy_decisions": [records["decision"]],
                    "audit_events": [records["audit"]],
                    "security_events": [records["security"]],
                },
            )
        else:
            self._error(404, "GOVERNANCE_NOT_FOUND")

    def _filtered(
        self,
        records: dict[str, object],
        query: dict[str, list[str]],
    ) -> dict[str, dict[str, object] | None]:
        if self.server.state.mode == "empty":
            return {name: None for name in records}
        task = query.get("task_id", [None])[0]
        correlation = query.get("correlation_id", [None])[0]
        result: dict[str, dict[str, object] | None] = {}
        for name, record in records.items():
            assert isinstance(record, dict)
            wrong_task = (
                task is not None and name != "version" and record.get("task_id") != task
            )
            wrong_correlation = (
                correlation is not None
                and name in {"audit", "security"}
                and record.get("correlation_id") != correlation
            )
            if wrong_task or wrong_correlation:
                result[name] = None
            else:
                result[name] = record
        return result

    def _page(
        self,
        item: dict[str, object] | None,
        query: dict[str, list[str]],
    ) -> None:
        if "cursor" in query:
            self._json(200, {"items": [], "next_cursor": None})
            return
        self._json(
            200,
            {"items": [] if item is None else [item], "next_cursor": CURSOR},
        )

    def _error(self, status: int, code: str) -> None:
        self._json(
            status,
            {
                "error": {
                    "code": code,
                    "message": PROMPT_CANARY + SECRET_CANARY,
                    "retryable": status == 503,
                    "detail_ref": None,
                }
            },
        )

    def _json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Vary", "Cookie")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class GovernanceApiServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, state: GovernanceApiState) -> None:
        super().__init__(("127.0.0.1", 0), GovernanceApiHandler)
        self.state = state


@pytest.fixture
def governance_servers():
    from web.server import DemoServer, LiveBackend

    state = GovernanceApiState()
    upstream = GovernanceApiServer(state)
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()
    host, port = upstream.server_address[:2]
    shell = DemoServer(LiveBackend(f"http://{host}:{port}"), 0)
    shell_thread = threading.Thread(target=shell.serve_forever, daemon=True)
    shell_thread.start()
    shell_host, shell_port = shell.server_address[:2]
    try:
        yield state, f"http://{shell_host}:{shell_port}"
    finally:
        shell.shutdown()
        shell.server_close()
        shell_thread.join(timeout=5)
        upstream.shutdown()
        upstream.server_close()
        upstream_thread.join(timeout=5)


def _get(
    base: str,
    path: str,
    *,
    cookie: str | None = None,
    forged: bool = False,
) -> tuple[int, Any, str]:
    headers = {"Accept": "text/html"}
    if cookie is not None:
        headers["Cookie"] = cookie
    if forged:
        headers["X-FlowPilot-Tenant-Id"] = "tenant-forged"
        headers["X-FlowPilot-Roles"] = "admin"
    request = urllib.request.Request(base + path, headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=5)
        body = response.read().decode()
        result = response.status, response.headers, body
        response.close()
        return result
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read().decode()


def test_governance_page_is_cookie_isolated_and_browser_authority_is_ignored(
    governance_servers,
) -> None:
    state, base = governance_servers
    status_a, headers_a, html_a = _get(
        base, "/views/governance", cookie=COOKIE_A, forged=True
    )
    status_b, _headers_b, html_b = _get(base, "/views/governance", cookie=COOKIE_B)

    assert status_a == status_b == 200
    assert headers_a["Cache-Control"] == "no-store"
    assert "policy-a-v9" in html_a and "policy-b-v9" not in html_a
    assert "policy-b-v9" in html_b and "policy-a-v9" not in html_b
    assert 'data-governance-stream="audit"' in html_a
    assert 'data-governance-stream="security"' in html_a
    assert "不以 Trace 代替" in html_a and "与 Audit 独立展示" in html_a
    for call in state.calls:
        assert call["tenant_header"] is None and call["role_header"] is None
    for forbidden in ("tenant_id", "subject_id", "tool_arguments", "prompt"):
        assert forbidden not in html_a + html_b


def test_pagination_filters_and_correlation_use_only_allowlisted_projection(
    governance_servers,
) -> None:
    state, base = governance_servers
    task_id = str(state.records["a"]["decision"]["task_id"])
    correlation = str(state.records["a"]["audit"]["correlation_id"])
    query = urllib.parse.urlencode(
        {
            "tab": "audit",
            "limit": "20",
            "cursor": CURSOR,
            "task_id": task_id,
            "correlation_id": correlation,
            "occurred_after": "2026-08-16T00:00:00Z",
            "occurred_before": "2026-08-16T02:00:00Z",
        }
    )
    status, _headers, html = _get(base, "/views/governance?" + query, cookie=COOKIE_A)
    correlation_status, _correlation_headers, correlation_html = _get(
        base,
        "/views/governance/correlations/" + correlation,
        cookie=COOKIE_A,
    )

    assert status == correlation_status == 200
    assert "暂无 Audit 事件" in html
    assert correlation in correlation_html
    assert str(state.records["a"]["decision"]["decision_id"]) in correlation_html
    relevant = state.calls[:4]
    assert "cursor" not in relevant[0]["query"]
    assert "cursor" not in relevant[1]["query"]
    assert relevant[2]["query"]["cursor"] == [CURSOR]
    assert "cursor" not in relevant[3]["query"]
    assert relevant[1]["query"]["task_id"] == [task_id]
    assert relevant[2]["query"]["correlation_id"] == [correlation]
    assert relevant[3]["query"]["occurred_before"] == ["2026-08-16T02:00:00Z"]


def test_unknown_or_authority_query_is_rejected_before_upstream(
    governance_servers,
) -> None:
    state, base = governance_servers
    before = len(state.calls)
    status, headers, html = _get(
        base,
        "/views/governance?tenant_id=tenant-forged&role=admin",
        cookie=COOKIE_A,
    )

    assert status == 422
    assert headers["Cache-Control"] == "no-store"
    assert len(state.calls) == before
    assert "筛选条件无效" in html
    assert "tenant-forged" not in html and "admin" not in html


def test_revoked_session_and_unavailable_service_never_reuse_old_governance(
    governance_servers,
) -> None:
    state, base = governance_servers
    first_status, _first_headers, first_html = _get(
        base, "/views/governance", cookie=COOKIE_A
    )
    assert first_status == 200 and "policy-a-v9" in first_html

    state.revoked.add(COOKIE_A)
    revoked_status, revoked_headers, revoked_html = _get(
        base, "/views/governance", cookie=COOKIE_A
    )
    assert revoked_status == 401
    assert revoked_headers["Cache-Control"] == "no-store"
    assert "重新认证" in revoked_html and "policy-a-v9" not in revoked_html
    assert SECRET_CANARY not in revoked_html and PROMPT_CANARY not in revoked_html

    state.revoked.clear()
    state.mode = "unavailable"
    failed_status, _failed_headers, failed_html = _get(
        base, "/views/governance", cookie=COOKIE_A
    )
    assert failed_status == 503
    assert "未展示任何缓存或替代数据" in failed_html
    assert "policy-a-v9" not in failed_html
    assert SECRET_CANARY not in failed_html and PROMPT_CANARY not in failed_html


def test_compromised_projection_fails_closed_without_dom_or_error_leak(
    governance_servers,
) -> None:
    state, base = governance_servers
    state.mode = "compromised"
    status, headers, html = _get(base, "/views/governance", cookie=COOKIE_A)

    assert status == 502
    assert headers["Cache-Control"] == "no-store"
    assert "治理投影不可用" in html and "policy-a-v9" not in html
    assert SECRET_CANARY not in html and PROMPT_CANARY not in html


def test_empty_governance_state_is_explicit_and_does_not_fabricate_trace(
    governance_servers,
) -> None:
    state, base = governance_servers
    state.mode = "empty"
    status, _headers, html = _get(base, "/views/governance", cookie=COOKIE_A)

    assert status == 200
    assert "当前没有已激活的策略版本" in html
    assert "暂无策略决策" in html
    assert "暂无 Audit 事件" in html
    assert "暂无 Security Event" in html
    assert "trace-governance" not in html
