"""Task list fragment."""

from __future__ import annotations

from ..models import TaskView
from .html import esc, fmt_dt
from .status import status_class, status_label


def render_task_list(
    tasks: tuple[TaskView, ...], *, base_href: str = "/views/tasks"
) -> str:
    if not tasks:
        return '<div class="empty-state">暂无任务</div>'
    rows = []
    for task in tasks:
        waiting = ""
        if task.waiting_on is not None:
            waiting = (
                f'<span class="wait-hint">{esc(task.waiting_on.type)} · '
                f"{esc(task.waiting_on.request_id)}</span>"
            )
        rows.append(
            f'<li class="task-row" data-task-id="{esc(task.task_id)}">'
            f'<a class="task-link" href="{esc(base_href)}/{esc(task.task_id)}">'
            f'<span class="task-id">{esc(task.task_id)}</span>'
            f'<span class="task-purpose">{esc(task.purpose)}</span>'
            f'<span class="task-status {status_class(task.status)}">'
            f"{status_label(task.status)}</span>"
            f'<span class="task-updated">{fmt_dt(task.updated_at)}</span>'
            f"</a>{waiting}</li>"
        )
    return f'<ul class="task-list">{"".join(rows)}</ul>'
