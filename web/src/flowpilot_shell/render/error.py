"""Error and retry panels.

Failure mode of the shell: API unavailable / SSE broken / task failed →
the shell renders the error panel with a retry entry and never renders
fabricated data.
"""

from __future__ import annotations

from ..models import ShellContractError, ShellError, TaskView
from .html import esc, fmt_dt


def render_error_panel(error: ShellError, *, retry_href: str = "/views/tasks") -> str:
    code = getattr(error, "code", type(error).__name__)
    retryable = getattr(error, "retryable", False)
    detail = getattr(error, "detail_ref", None)
    retry_badge = (
        '<span class="retryable">可重试</span>'
        if retryable
        else '<span class="not-retryable">不可重试</span>'
    )
    detail_html = (
        f'<p class="error-detail">详情引用：<code>{esc(detail)}</code></p>'
        if detail
        else ""
    )
    return (
        f'<section class="error-panel" data-error-code="{esc(code)}">'
        f"<h3>加载失败 · {esc(code)}</h3>"
        f'<p class="error-message">{esc(str(error))}</p>'
        f"<p>{retry_badge}</p>"
        f"{detail_html}"
        f'<div class="error-actions">'
        f'<a class="btn btn-primary" href="{esc(retry_href)}" '
        f'data-action="retry">重试</a>'
        f'<a class="btn" href="/views/tasks">返回任务列表</a>'
        f"</div>"
        f"</section>"
    )


def render_contract_error_panel(
    message: str, *, retry_href: str = "/views/tasks"
) -> str:
    return render_error_panel(ShellContractError(message), retry_href=retry_href)


def render_task_error_panel(task: TaskView) -> str:
    error = task.error
    code = error.code if error else "UNKNOWN"
    retryable = bool(error and error.retryable)
    detail = error.detail_ref if error else None
    detail_html = (
        f'<p class="error-detail">详情引用：<code>{esc(detail)}</code></p>'
        if detail
        else ""
    )
    retry = ""
    if retryable:
        retry = (
            f'<form class="retry-form" method="post" '
            f'action="/shell/commands/retry">'
            f'<input type="hidden" name="task_id" '
            f'value="{esc(task.task_id)}" />'
            f'<button type="submit" class="btn btn-primary" '
            f'data-action="retry">重试该任务</button>'
            f"</form>"
        )
    return (
        f'<section class="error-panel task-error" '
        f'data-error-code="{esc(code)}">'
        f"<h3>任务失败 · {esc(code)}</h3>"
        f'<p class="error-message">任务于 {fmt_dt(task.completed_at)} 终止，'
        f"错误码 {esc(code)}"
        f"{'（可重试）' if retryable else '（不可重试）'}。</p>"
        f"{detail_html}"
        f'<div class="error-actions">{retry}'
        f'<a class="btn" href="/views/tasks">返回任务列表</a>'
        f"</div>"
        f"</section>"
    )
