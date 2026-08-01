"""Timeline fragment: 运行/等待/失败 states with gap markers."""

from __future__ import annotations

from ..models import EventView
from .html import esc, fmt_dt


def render_timeline(
    events: tuple[EventView, ...],
    gaps: tuple[int, ...],
    *,
    task_id: str,
) -> str:
    if not events:
        rebuild = f"/views/tasks/{esc(task_id)}?rebuild=1"
        return (
            f'<div class="timeline-empty">暂无事件'
            f"（可通过下方恢复入口从事件流补齐）</div>"
            f'<a class="btn btn-secondary" href="{rebuild}">'
            f"恢复入口：重建时间线</a>"
        )
    items: list[str] = []
    gap_set = set(gaps)
    for event in events:
        if event.sequence in gap_set:
            continue  # gaps are rendered at their own position below
        items.append(
            f'<li class="timeline-item" data-event-id="{esc(event.event_id)}">'
            f'<span class="timeline-seq">#{event.sequence}</span>'
            f'<span class="timeline-type">{esc(_type_label(event.event_type))}</span>'
            f'<span class="timeline-summary">{esc(_summary(event))}</span>'
            f'<span class="timeline-time">{fmt_dt(event.occurred_at)}</span>'
            f"</li>"
        )
    for gap in sorted(gap_set):
        rebuild = f"/views/tasks/{esc(task_id)}?rebuild=1"
        items.append(
            f'<li class="timeline-item timeline-gap" data-gap="{gap}">'
            f'<span class="timeline-seq">#{gap}</span>'
            f'<span class="timeline-type">事件缺口</span>'
            f'<span class="timeline-summary">序列 {gap} 缺失（重连补齐中）</span>'
            f'<a class="btn btn-secondary" href="{rebuild}">'
            f"重建</a>"
            f"</li>"
        )
    return f'<ol class="timeline">{"".join(items)}</ol>'


def _type_label(event_type: str) -> str:
    return {
        "task.created.v1": "创建",
        "task.status.changed.v1": "状态",
        "task.input.required.v1": "信息补全",
        "task.approval.required.v1": "审批请求",
        "task.approval.decided.v1": "审批决定",
        "task.tool_execution.updated.v1": "工具执行",
        "task.completed.v1": "完成",
        "task.failed.v1": "失败",
        "task.escalated.v1": "升级",
    }.get(event_type, event_type)


def _summary(event: EventView) -> str:
    payload = dict(event.payload)
    if event.event_type == "task.status.changed.v1":
        return f"{payload.get('from')} → {payload.get('to')}"
    if event.event_type == "task.input.required.v1":
        missing = ", ".join(payload.get("missing_fields", []))
        return f"请求 {payload.get('request_id')} · 缺少 {missing}"
    if event.event_type == "task.approval.required.v1":
        return f"审批 {payload.get('approval_id')} · 截止 {payload.get('expires_at')}"
    if event.event_type == "task.approval.decided.v1":
        return f"审批 {payload.get('approval_id')} → {payload.get('decision')}"
    if event.event_type == "task.tool_execution.updated.v1":
        return f"{payload.get('execution_id')} → {payload.get('status')}"
    if event.event_type == "task.completed.v1":
        return f"结果 {payload.get('result_ref')}"
    if event.event_type == "task.failed.v1":
        return f"{payload.get('error_code')}（可重试={payload.get('retryable')}）"
    if event.event_type == "task.escalated.v1":
        return f"{payload.get('reason_code')} · handoff {payload.get('handoff_ref')}"
    return ""
