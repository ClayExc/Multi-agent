"""Pure server-side rendering for the read-only governance console."""

from __future__ import annotations

from datetime import UTC, datetime

from ..governance import (
    AuditEventView,
    GovernanceCorrelationView,
    GovernanceQuery,
    GovernanceSnapshot,
    PolicyDecisionView,
    SecurityEventView,
)
from .html import esc, hash_short


def render_governance_dashboard(
    snapshot: GovernanceSnapshot,
    query: GovernanceQuery,
) -> str:
    active = next(
        (item for item in snapshot.policy_versions if item.active),
        None,
    )
    current = (
        '<dl class="governance-current">'
        f"<dt>当前策略版本</dt><dd>{esc(active.version)}</dd>"
        "<dt>Bundle 摘要</dt><dd><code>"
        f"{esc(hash_short(active.bundle_digest))}</code></dd>"
        f"<dt>发布时间</dt><dd>{esc(active.published_at)}</dd>"
        "</dl>"
        if active is not None
        else '<p class="empty-state">当前没有已激活的策略版本。</p>'
    )
    return (
        '<header class="governance-header">'
        "<h2>治理与安全控制台</h2>"
        "<p>只读展示安全治理投影；租户、角色与权限始终由服务端会话判定。</p>"
        f"{current}</header>"
        f"{_filter_form(query)}"
        f"{_tabs(query)}"
        '<div class="governance-streams">'
        '<section id="policy-versions" data-governance-stream="policy">'
        "<h3>策略版本</h3>"
        f"{_policy_versions(snapshot, query)}"
        "</section>"
        '<section id="policy-decisions" data-governance-stream="decision">'
        "<h3>策略决策</h3>"
        f"{_policy_decisions(snapshot.policy_decisions)}"
        f"{_next_page(query, 'decisions', snapshot.policy_decisions_cursor)}"
        "</section>"
        '<section id="audit-events" data-governance-stream="audit">'
        "<h3>Audit 审计事件</h3>"
        '<p class="stream-note">不可采样的审计事实流，不以 Trace 代替。</p>'
        f"{_audit_events(snapshot.audit_events)}"
        f"{_next_page(query, 'audit', snapshot.audit_events_cursor)}"
        "</section>"
        '<section id="security-events" data-governance-stream="security">'
        "<h3>Security Event 安全事件</h3>"
        '<p class="stream-note">不可采样的安全控制流，与 Audit 独立展示。</p>'
        f"{_security_events(snapshot.security_events)}"
        f"{_next_page(query, 'security', snapshot.security_events_cursor)}"
        "</section></div>"
    )


def render_governance_correlation(chain: GovernanceCorrelationView) -> str:
    return (
        '<header class="governance-header">'
        "<h2>关联链</h2>"
        f"<p><code>{esc(chain.correlation_id)}</code></p>"
        '<a class="btn" href="#/governance">返回治理控制台</a>'
        "</header>"
        '<section data-governance-stream="decision"><h3>策略决策</h3>'
        f"{_policy_decisions(chain.policy_decisions)}</section>"
        '<section data-governance-stream="audit"><h3>Audit 审计事件</h3>'
        f"{_audit_events(chain.audit_events)}</section>"
        '<section data-governance-stream="security"><h3>Security Event 安全事件</h3>'
        f"{_security_events(chain.security_events)}</section>"
    )


def render_governance_demo_notice() -> str:
    return (
        '<section class="empty-state governance-demo" role="status">'
        "<h2>治理控制台需要真实会话</h2>"
        "<p>合成演示模式不生成策略、审计或安全事实。</p>"
        "</section>"
    )


def _filter_form(query: GovernanceQuery) -> str:
    return (
        '<form id="governance-filter" class="governance-filter" '
        'aria-label="治理记录筛选">'
        f'<input type="hidden" name="tab" value="{esc(query.tab)}">'
        '<label>任务 ID<input name="task_id" type="text" '
        'pattern="task_[A-Za-z0-9_-]{8,128}" maxlength="133" '
        f'value="{esc(query.task_id or "")}"></label>'
        '<label>关联 ID<input name="correlation_id" type="text" maxlength="128" '
        f'value="{esc(query.correlation_id or "")}"></label>'
        '<label>开始时间（UTC）<input name="occurred_after" type="datetime-local" '
        f'value="{esc(_datetime_local(query.occurred_after))}"></label>'
        '<label>结束时间（UTC）<input name="occurred_before" type="datetime-local" '
        f'value="{esc(_datetime_local(query.occurred_before))}"></label>'
        '<button class="btn btn-primary" type="submit">应用筛选</button>'
        '<a class="btn" href="#/governance">清除筛选</a>'
        "</form>"
    )


def _tabs(query: GovernanceQuery) -> str:
    entries = (
        ("versions", "策略版本"),
        ("decisions", "策略决策"),
        ("audit", "Audit"),
        ("security", "Security Event"),
    )
    links = []
    for name, label in entries:
        current = ' aria-current="page"' if query.tab == name else ""
        links.append(f'<a href="{esc(query.href(tab=name))}"{current}>{esc(label)}</a>')
    return (
        '<nav class="governance-tabs" aria-label="治理记录类型">'
        + "".join(links)
        + "</nav>"
    )


def _policy_versions(snapshot: GovernanceSnapshot, query: GovernanceQuery) -> str:
    if not snapshot.policy_versions:
        return '<p class="empty-state">暂无策略版本。</p>'
    rows = []
    for item in snapshot.policy_versions:
        status = "当前" if item.active else ("已撤销" if item.revoked_at else "历史")
        rows.append(
            "<tr>"
            f"<td><code>{esc(item.version)}</code></td>"
            f"<td>{esc(status)}</td>"
            f"<td><code>{esc(hash_short(item.bundle_digest))}</code></td>"
            f"<td>{esc(item.parent_version or '—')}</td>"
            f"<td>{esc(item.published_at)}</td>"
            "</tr>"
        )
    return (
        '<div class="table-scroll"><table><caption>策略版本记录</caption>'
        "<thead><tr><th>版本</th><th>状态</th><th>摘要</th><th>父版本</th><th>发布时间</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
        f"{_next_page(query, 'versions', snapshot.policy_versions_cursor)}"
    )


def _policy_decisions(items: tuple[PolicyDecisionView, ...]) -> str:
    if not items:
        return '<p class="empty-state">暂无策略决策。</p>'
    rows = []
    for item in items:
        rows.append(
            "<tr>"
            f"<td><code>{esc(item.decision_id)}</code></td>"
            f"<td><code>{esc(item.task_id)}</code></td>"
            f"<td>{esc(_decision_label(item.decision))}</td>"
            f"<td><code>{esc(item.policy_version)}</code></td>"
            f"<td>{esc(', '.join(item.reason_codes) or '—')}</td>"
            f"<td>{esc(', '.join(item.obligation_names) or '—')}</td>"
            f"<td>{esc(item.evaluated_at)}</td>"
            "</tr>"
        )
    return (
        '<div class="table-scroll"><table><caption>策略决策记录</caption>'
        "<thead><tr><th>决策 ID</th><th>任务</th><th>结论</th><th>策略</th>"
        "<th>原因</th><th>义务</th><th>时间</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _audit_events(items: tuple[AuditEventView, ...]) -> str:
    if not items:
        return '<p class="empty-state">暂无 Audit 事件。</p>'
    rows = []
    for item in items:
        correlation = _correlation_link(item.correlation_id)
        rows.append(
            "<tr>"
            f"<td><code>{esc(item.event_id)}</code></td>"
            f"<td>{esc(item.event_type)}</td>"
            f"<td>{esc(item.action)}</td>"
            f"<td>{esc(_decision_label(item.decision))} / {esc(item.result)}</td>"
            f"<td>{correlation}</td>"
            f"<td>{item.sequence}</td>"
            f"<td>{esc(item.occurred_at)}</td>"
            "</tr>"
        )
    return (
        '<div class="table-scroll"><table><caption>不可采样 Audit 事件</caption>'
        "<thead><tr><th>事件 ID</th><th>类型</th><th>动作</th><th>决策 / 结果</th>"
        "<th>关联链</th><th>序号</th><th>时间</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _security_events(items: tuple[SecurityEventView, ...]) -> str:
    if not items:
        return '<p class="empty-state">暂无 Security Event。</p>'
    rows = []
    for item in items:
        rows.append(
            "<tr>"
            f"<td><code>{esc(item.event_id)}</code></td>"
            f"<td>{esc(item.category)}</td>"
            f"<td>{esc(item.severity)}</td>"
            f"<td>{esc(item.control_outcome)}</td>"
            f"<td>{esc(', '.join(item.reason_codes) or '—')}</td>"
            f"<td>{_correlation_link(item.correlation_id)}</td>"
            f"<td>{esc(item.occurred_at)}</td>"
            "</tr>"
        )
    return (
        '<div class="table-scroll"><table><caption>不可采样 Security Event</caption>'
        "<thead><tr><th>事件 ID</th><th>类别</th><th>严重度</th><th>控制结果</th>"
        "<th>原因</th><th>关联链</th><th>时间</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _next_page(query: GovernanceQuery, tab: str, cursor: str | None) -> str:
    if cursor is None:
        return ""
    return (
        '<p class="pagination">'
        f'<a class="btn" rel="next" href="{esc(query.href(tab=tab, cursor=cursor))}">'
        "下一页</a></p>"
    )


def _correlation_link(correlation_id: str) -> str:
    return (
        f'<a href="#/governance/correlations/{esc(correlation_id)}">'
        f"<code>{esc(correlation_id)}</code></a>"
    )


def _decision_label(value: str) -> str:
    return {
        "allow": "允许",
        "deny": "拒绝",
        "require_approval": "需要审批",
        "not_applicable": "不适用",
    }.get(value, value)


def _datetime_local(value: str | None) -> str:
    if value is None:
        return ""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M")
