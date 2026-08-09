"""Render the content-free five-stage Studio progress card."""

from __future__ import annotations

from ..projection import StudioProgressView
from .html import esc

_PHASE_LABELS = {
    "intake": "接收请求",
    "interrupt": "等待确认",
    "knowledge": "检索知识",
    "model": "生成结果",
    "terminal": "流程完成",
}
_FAILURE_HINTS = {
    "PROVIDER_TIMEOUT": "模型服务超时，可稍后重试。",
    "GRAPH_CHECKPOINT_UNAVAILABLE": "恢复失败，请重新打开任务并重试。",
}


def render_studio_progress(view: StudioProgressView) -> str:
    phase = _PHASE_LABELS[view.phase]
    hint = _FAILURE_HINTS.get(view.failure_code, "")
    error = (
        f'<p class="progress-error" role="alert">{esc(hint)}</p>' if hint else ""
    )
    return (
        f'<article class="studio-progress" data-step="{view.current_step}" '
        f'data-frame-id="{esc(view.frame_id)}">'
        f'<h3>{esc(phase)}（{view.current_step}/{view.total_steps}）</h3>'
        f'<dl><dt>当前节点</dt><dd>{esc(view.node)}</dd>'
        f'<dt>执行角色</dt><dd>{esc(view.actor)}</dd>'
        f'<dt>模型调用</dt><dd>{view.model_call_count}</dd>'
        f'<dt>引用</dt><dd>{view.citation_count}</dd>'
        f'<dt>产物</dt><dd>{view.artifact_count}</dd></dl>'
        f'{error}</article>'
    )
