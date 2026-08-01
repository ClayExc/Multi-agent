"""Approval card fragment (display-only).

Renders the M5-1 isomorphic card input: 动作摘要 (tool + action_id + agent),
影响 (resource + purpose), 参数 (arguments), 依据 (policy_version +
policy_decision_id + tool schema hash) and 过期时间 (expires_at). The card
never renders approve/reject write controls: the shell does not infer
approval success and does not issue approval write calls.
"""

from __future__ import annotations

from ..models import ApprovalView, PlannedActionView
from .html import esc, fmt_dt, hash_short

_STATUS_LABELS = {
    "pending": "待审批",
    "approved": "已批准",
    "rejected": "已拒绝",
    "expired": "已过期",
    "revoked": "已撤销",
}


def render_approval_card(approval: ApprovalView, action: PlannedActionView) -> str:
    status_text = _STATUS_LABELS.get(approval.status, approval.status)
    status_class = (
        "approval-pending" if approval.status == "pending" else "approval-decided"
    )
    params = "".join(
        f"<tr><th>{esc(key)}</th><td>{esc(value)}</td></tr>"
        for key, value in sorted(action.arguments.items())
    )
    decided = ""
    if approval.status != "pending":
        approver = approval.approver_id or "（系统）"
        decided = (
            f'<p class="approval-decided-line">'
            f"<span>决策人：{esc(approver)}</span>"
            f"<span>时间：{fmt_dt(approval.decided_at)}</span>"
            f"</p>"
        )
        if approval.decision_reason:
            decided += (
                f'<p class="approval-reason">理由：{esc(approval.decision_reason)}</p>'
            )
    return (
        f'<article class="approval-card {status_class}" '
        f'data-approval-id="{esc(approval.approval_id)}">'
        f'<header class="approval-head">'
        f"<h3>审批卡 · {esc(approval.approval_id)}</h3>"
        f'<span class="approval-status">{esc(status_text)}</span>'
        f"</header>"
        f'<section class="approval-field"><h4>动作摘要</h4>'
        f"<p>{esc(action.tool_name)} · {esc(action.action_id)} · "
        f"申请方 {esc(approval.requester_id)} · 代理 {esc(action.agent_id)}</p>"
        f"</section>"
        f'<section class="approval-field"><h4>影响</h4>'
        f"<p>资源 {esc(action.resource_type)}"
        f"{'/' + esc(action.resource_id) if action.resource_id else ''}"
        f" · {esc(action.purpose)}</p>"
        f"</section>"
        f'<section class="approval-field"><h4>参数</h4>'
        f'<table class="approval-params"><tbody>{params}</tbody></table>'
        f"</section>"
        f'<section class="approval-field"><h4>依据</h4>'
        f"<p>策略 {esc(approval.policy_version)} · "
        f"决策 {esc(approval.policy_decision_id)}"
        f" · 工具 Schema {hash_short(action.tool_schema_hash)}</p>"
        f"</section>"
        f'<section class="approval-field"><h4>过期时间</h4>'
        f"<p>{fmt_dt(approval.expires_at)}"
        f'（<span class="approval-digest">动作摘要 '
        f"{hash_short(approval.action_digest)}</span>）</p>"
        f"</section>"
        f"{decided}"
        f'<footer class="approval-foot">'
        f'<p class="approval-note">本外壳仅展示审批卡，不发起审批写调用；'
        f"审批决策请在受信任的审批入口完成。</p>"
        f"</footer>"
        f"</article>"
    )
