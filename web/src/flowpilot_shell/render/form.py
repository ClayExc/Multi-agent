"""Info completion form fragment (WAITING_USER) with recovery entry."""

from __future__ import annotations

from ..models import TaskView
from .html import esc, fmt_dt

_FIELD_LABELS = {
    "contact_phone": "联系电话",
    "asset_location": "设备位置",
    "preferred_window": "期望处理时段",
    "full_name": "姓名",
    "department": "部门",
    "manager": "直属经理",
    "start_date": "入职日期",
    "site": "办公地点",
    "description": "问题描述",
    "cost_center": "成本中心",
}


def render_completion_form(task: TaskView, missing_fields: tuple[str, ...]) -> str:
    request_id = task.waiting_on.request_id if task.waiting_on else ""
    expiry = task.waiting_on.expires_at if task.waiting_on else None
    expiry_html = f"（截止 {fmt_dt(expiry)}）" if expiry else ""
    if not missing_fields:
        fields = (
            '<p class="completion-missing-unknown">缺少字段列表不可用'
            "（事件流缺口或未收到 input.required 事件），"
            "请先使用恢复入口补齐事件流。</p>"
        )
    else:
        fields = ""
        for name in missing_fields:
            label = _FIELD_LABELS.get(name, name)
            fields += (
                f'<div class="form-field">'
                f'<label for="field-{esc(name)}">{esc(label)}</label>'
                f'<input id="field-{esc(name)}" name="{esc(name)}" '
                f"required />"
                f"</div>"
            )
    fields_hint = "、".join(missing_fields) if missing_fields else "未知"
    return (
        f'<section class="completion-section" '
        f'data-request-id="{esc(request_id)}">'
        f"<h3>信息补全{expiry_html}</h3>"
        f'<p class="completion-hint">任务等待信息：{esc(fields_hint)}</p>'
        f'<form id="completion-form" method="post" '
        f'action="/shell/commands/submit">'
        f'<input type="hidden" name="task_id" '
        f'value="{esc(task.task_id)}" />'
        f'<input type="hidden" name="request_id" '
        f'value="{esc(request_id)}" />'
        f"{fields}"
        f'<button type="submit" class="btn btn-primary" '
        f'data-action="submit-completion">提交补全信息</button>'
        f"</form>"
        f'<p class="recovery-entry">恢复入口：'
        f'<a href="/views/tasks/{esc(task.task_id)}?rebuild=1">'
        f"从事件流重建本任务视图</a>"
        f"</p>"
        f"</section>"
    )
