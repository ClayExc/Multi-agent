"""Task detail fragment."""

from __future__ import annotations

from ..models import TaskView
from ..store import ShellStore
from .html import esc, fmt_dt
from .status import status_class, status_label


def render_task_detail(task: TaskView, store: ShellStore) -> str:
    sections = [
        _render_header(task),
        _render_waiting_section(task, store),
        _render_error_section(task, store),
        _render_result_section(task, store),
        _render_actions_section(task, store),
        _render_timeline_section(task, store),
    ]
    return "".join(sections)


def _render_header(task: TaskView) -> str:
    meta = [
        ("线程", task.thread_id),
        ("租户", task.tenant_id),
        ("意图", task.intent or "—"),
        ("风险", task.risk_level or "—"),
        ("版本", f"{task.version} / run_generation={task.run_generation}"),
        ("创建", fmt_dt(task.created_at)),
        ("更新", fmt_dt(task.updated_at)),
        ("完成", fmt_dt(task.completed_at)),
    ]
    meta_html = "".join(
        f"<dt>{esc(label)}</dt><dd>{esc(value)}</dd>" for label, value in meta
    )
    return (
        f'<section class="task-header">'
        f'<h2 class="task-title"><span class="task-id">{esc(task.task_id)}</span>'
        f'<span class="task-status {status_class(task.status)}">'
        f"{status_label(task.status)}</span></h2>"
        f'<p class="task-purpose">{esc(task.purpose)}</p>'
        f'<dl class="task-meta">{meta_html}</dl>'
        f"</section>"
    )


def _render_waiting_section(task: TaskView, store: ShellStore) -> str:
    if task.waiting_on is None:
        return ""
    if task.waiting_on.type == "user_input":
        from .form import render_completion_form

        missing_fields: tuple[str, ...] = ()
        for event in reversed(store.timeline_events(task.task_id)):
            if event.event_type == "task.input.required.v1":
                fields = event.payload.get("missing_fields")
                if isinstance(fields, list):
                    missing_fields = tuple(str(item) for item in fields)
                break
        return render_completion_form(task, missing_fields)
    from .approval import render_approval_card

    cards = []
    for approval in store.approvals_for_task(task.task_id):
        if approval.status != "pending":
            continue
        try:
            approval_view, action = store.approval_card(approval.approval_id)
        except Exception:
            continue
        cards.append(render_approval_card(approval_view, action))
    return f'<section class="approval-section">{"".join(cards)}</section>'


def _render_error_section(task: TaskView, store: ShellStore) -> str:
    if task.status not in {"FAILED", "ESCALATED"}:
        return ""
    from .error import render_task_error_panel

    return render_task_error_panel(task)


def _render_result_section(task: TaskView, store: ShellStore) -> str:
    if task.result_ref is None:
        return ""
    artifact = store.artifact(task.result_ref)
    if artifact is None:
        return (
            f'<section class="result-section"><h3>执行结果</h3>'
            f'<p class="result-ref">引用：{esc(task.result_ref)}'
            f"（结果内容未加载）</p></section>"
        )
    from .citations import render_result_artifact

    return (
        f'<section class="result-section">{render_result_artifact(artifact)}</section>'
    )


def _render_actions_section(task: TaskView, store: ShellStore) -> str:
    actions = store.actions_for_task(task.task_id)
    if not actions:
        return ""
    rows = []
    for action in actions:
        rows.append(
            f'<li class="action-row">'
            f'<span class="action-tool">{esc(action.tool_name)}</span>'
            f'<span class="action-id">{esc(action.action_id)}</span>'
            f'<span class="action-resource">{esc(action.resource_type)}'
            f"{'/' + esc(action.resource_id) if action.resource_id else ''}</span>"
            f"</li>"
        )
    return (
        f'<section class="actions-section"><h3>子动作（计划）</h3>'
        f'<ul class="action-list">{"".join(rows)}</ul></section>'
    )


def _render_timeline_section(task: TaskView, store: ShellStore) -> str:
    from .timeline import render_timeline

    events = store.timeline_events(task.task_id)
    gaps = store.timeline_gaps(task.task_id)
    timeline = render_timeline(events, gaps, task_id=task.task_id)
    return f'<section class="timeline-section"><h3>时间线</h3>{timeline}</section>'


def render_task_not_found(task_id: str) -> str:
    return (
        f'<section class="error-panel error-notfound">'
        f"<h3>任务不存在</h3>"
        f"<p>未找到任务 <code>{esc(task_id)}</code>（租户范围内 404）。</p>"
        f'<a class="btn" href="/views/tasks">返回任务列表</a>'
        f"</section>"
    )
