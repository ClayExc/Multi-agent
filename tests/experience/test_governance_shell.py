"""Closed governance projection and pure-renderer experience gates."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

COOKIE = "__Host-flowpilot-session=opaque-session"
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
CURSOR = "gcur_" + "A" * 24
ROOT = Path(__file__).resolve().parents[2]


def policy_version() -> dict[str, object]:
    return {
        "version": "policy-v9",
        "bundle_digest": DIGEST_A,
        "active": True,
        "parent_version": "policy-v8",
        "published_at": "2026-08-16T01:00:00Z",
        "revoked_at": None,
        "rollback_of": None,
    }


def decision() -> dict[str, object]:
    return {
        "decision_id": "pd_decision01",
        "task_id": "task_task0001",
        "decision": "deny",
        "policy_version": "policy-v9",
        "reason_codes": ["TENANT_POLICY"],
        "obligation_names": ["audit_level"],
        "action_digest": DIGEST_B,
        "evaluated_at": "2026-08-16T01:01:00Z",
        "expires_at": "2026-08-16T01:06:00Z",
    }


def audit_event() -> dict[str, object]:
    return {
        "event_id": "evt_event0001",
        "event_type": "governance.policy.decision.v1",
        "occurred_at": "2026-08-16T01:01:01Z",
        "trace_id": "trace-governance-001",
        "thread_id": "thread_thread01",
        "task_id": "task_task0001",
        "run_id": "run_run00001",
        "correlation_id": "correlation-001",
        "causation_id": "cause-001",
        "action": "knowledge.read",
        "decision": "deny",
        "reason_codes": ["TENANT_POLICY"],
        "result": "blocked",
        "data_classification": "internal",
        "stream_id": "audit-stream-001",
        "sequence": 1,
        "event_hash": DIGEST_A,
        "previous_hash": None,
        "policy_decision_id": "pd_decision01",
        "policy_version": "policy-v9",
        "approval_id": None,
        "action_digest": DIGEST_B,
        "tool_execution_id": None,
        "security_event_id": "sevt_event0001",
    }


def security_event() -> dict[str, object]:
    return {
        "event_id": "sevt_event0001",
        "event_type": "security.authorization.denied.v1",
        "occurred_at": "2026-08-16T01:01:02Z",
        "trace_id": "trace-governance-001",
        "thread_id": "thread_thread01",
        "task_id": "task_task0001",
        "run_id": "run_run00001",
        "correlation_id": "correlation-001",
        "causation_id": "evt_event0001",
        "control_component": "mcp-gateway",
        "control_rule_id": "tenant.boundary",
        "control_rule_version": "policy-v9",
        "reason_codes": ["TENANT_POLICY"],
        "severity": "high",
        "category": "authorization",
        "control_outcome": "blocked",
        "impact": "attempted",
        "disposition": "contained",
        "data_classification": "restricted",
        "policy_decision_id": "pd_decision01",
        "audit_event_id": "evt_event0001",
        "event_hash": DIGEST_B,
    }


def test_api_client_forwards_only_cookie_and_validates_private_headers() -> None:
    from flowpilot_shell.api_client import ApiClient

    calls: list[tuple[str, str, dict[str, str], bytes | None]] = []

    def transport(method, path, headers, body):
        calls.append((method, path, headers, body))
        return (
            200,
            {
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
                "Vary": "Cookie",
            },
            json.dumps({"items": [policy_version()], "next_cursor": CURSOR}).encode(),
        )

    page, cursor = ApiClient(transport=transport).get_policy_versions(
        limit=20,
        cursor=None,
        cookie_header=COOKIE,
    )

    assert page[0].version == "policy-v9" and cursor == CURSOR
    method, path, headers, body = calls[0]
    assert method == "GET" and path == "/v1/governance/policy-versions?limit=20"
    assert headers == {"Accept": "application/json", "Cookie": COOKIE}
    assert body is None
    assert not any(
        "tenant" in name.lower() or "role" in name.lower() for name in headers
    )


def test_governance_response_without_private_cache_boundary_fails_closed() -> None:
    from flowpilot_shell.api_client import ApiClient
    from flowpilot_shell.models import ShellContractError

    def transport(method, path, headers, body):
        del method, path, headers, body
        return (
            200,
            {"Content-Type": "application/json", "Cache-Control": "public"},
            json.dumps({"items": [], "next_cursor": None}).encode(),
        )

    with pytest.raises(ShellContractError, match="non-cacheable"):
        ApiClient(transport=transport).get_policy_versions(
            limit=20,
            cursor=None,
            cookie_header=COOKIE,
        )


def test_closed_projection_rejects_extra_raw_fields_and_credential_values() -> None:
    from flowpilot_shell.governance import (
        parse_audit_event_page,
        parse_policy_decision_page,
    )
    from flowpilot_shell.models import ShellContractError

    raw = audit_event()
    raw["tool_arguments"] = {"query": "raw prompt canary"}
    with pytest.raises(ShellContractError, match="closed projection"):
        parse_audit_event_page({"items": [raw], "next_cursor": None})

    compromised = decision()
    compromised["reason_codes"] = ["sk-proj-credentialcanary0001"]
    with pytest.raises(ShellContractError, match="credential material"):
        parse_policy_decision_page({"items": [compromised], "next_cursor": None})


def test_query_allowlist_and_time_range_fail_closed() -> None:
    from flowpilot_shell.governance import GovernanceQuery
    from flowpilot_shell.models import ShellContractError

    with pytest.raises(ShellContractError, match="unknown"):
        GovernanceQuery.from_http_query({"tenant_id": ["tenant-forged"]})
    with pytest.raises(ShellContractError, match="unique"):
        GovernanceQuery.from_http_query({"tab": ["audit", "security"]})
    with pytest.raises(ShellContractError, match="strictly increasing"):
        GovernanceQuery.from_http_query(
            {
                "occurred_after": ["2026-08-16T02:00:00Z"],
                "occurred_before": ["2026-08-16T01:00:00Z"],
            }
        )


def test_dashboard_renders_distinct_audit_security_and_safe_correlation_links() -> None:
    from flowpilot_shell.governance import (
        GovernanceQuery,
        GovernanceSnapshot,
        parse_audit_event_page,
        parse_policy_decision_page,
        parse_policy_version_page,
        parse_security_event_page,
    )
    from flowpilot_shell.render.governance import render_governance_dashboard

    versions, versions_cursor = parse_policy_version_page(
        {"items": [policy_version()], "next_cursor": CURSOR}
    )
    decisions, decisions_cursor = parse_policy_decision_page(
        {"items": [decision()], "next_cursor": None}
    )
    audits, audits_cursor = parse_audit_event_page(
        {"items": [audit_event()], "next_cursor": None}
    )
    security, security_cursor = parse_security_event_page(
        {"items": [security_event()], "next_cursor": None}
    )
    snapshot = GovernanceSnapshot(
        versions,
        versions_cursor,
        decisions,
        decisions_cursor,
        audits,
        audits_cursor,
        security,
        security_cursor,
    )

    html = render_governance_dashboard(snapshot, GovernanceQuery())

    assert 'data-governance-stream="audit"' in html
    assert 'data-governance-stream="security"' in html
    assert "不可采样的审计事实流，不以 Trace 代替" in html
    assert "不可采样的安全控制流，与 Audit 独立展示" in html
    assert "#/governance/correlations/correlation-001" in html
    assert "当前策略版本" in html and "policy-v9" in html
    assert "<caption>不可采样 Audit 事件</caption>" in html
    assert "<caption>不可采样 Security Event</caption>" in html
    for forbidden in ("tenant_id", "subject_id", "tool_arguments", "prompt"):
        assert forbidden not in html


def test_renderer_escapes_identifier_content_and_empty_states_are_explicit() -> None:
    from flowpilot_shell.governance import GovernanceQuery, GovernanceSnapshot
    from flowpilot_shell.render.governance import render_governance_dashboard

    empty = GovernanceSnapshot((), None, (), None, (), None, (), None)
    html = render_governance_dashboard(empty, GovernanceQuery())

    assert "当前没有已激活的策略版本" in html
    assert "暂无策略决策" in html
    assert "暂无 Audit 事件" in html
    assert "暂无 Security Event" in html
    assert "innerHTML" not in html


def test_multiple_active_policy_versions_are_rejected() -> None:
    from flowpilot_shell.governance import (
        GovernanceSnapshot,
        parse_policy_version_page,
    )
    from flowpilot_shell.models import ShellContractError

    second = deepcopy(policy_version())
    second["version"] = "policy-v10"
    versions, _cursor = parse_policy_version_page(
        {"items": [policy_version(), second], "next_cursor": None}
    )
    with pytest.raises(ShellContractError, match="multiple active"):
        GovernanceSnapshot(versions, None, (), None, (), None, (), None)


def test_correlation_rejects_cross_chain_event_injection() -> None:
    from flowpilot_shell.governance import parse_correlation
    from flowpilot_shell.models import ShellContractError

    injected = security_event()
    injected["correlation_id"] = "correlation-other"
    with pytest.raises(ShellContractError, match="another correlation"):
        parse_correlation(
            {
                "correlation_id": "correlation-001",
                "policy_decisions": [decision()],
                "audit_events": [audit_event()],
                "security_events": [injected],
            }
        )


def test_browser_has_no_governance_json_database_or_policy_engine_path() -> None:
    script = (ROOT / "web" / "shell" / "app.js").read_text(encoding="utf-8")
    governance_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            ROOT / "web" / "src" / "flowpilot_shell" / "governance.py",
            ROOT / "web" / "src" / "flowpilot_shell" / "render" / "governance.py",
        )
    ).lower()

    assert "/v1/governance" not in script
    for forbidden in (
        "Authorization",
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "X-FlowPilot-Tenant",
        "X-FlowPilot-Roles",
    ):
        assert forbidden not in script
    for forbidden_dependency in (
        "import psycopg",
        "import sqlalchemy",
        "import asyncpg",
        "import opa",
    ):
        assert forbidden_dependency not in governance_sources
