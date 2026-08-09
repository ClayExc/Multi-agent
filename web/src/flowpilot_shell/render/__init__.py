"""Pure HTML render functions for the replaceable shell.

Every render function is a pure function of adapter-view data, so the
shell's presentation layer is testable without a browser. Values are HTML-
escaped; no approval write controls are ever rendered.
"""

from __future__ import annotations

from .approval import render_approval_card
from .citations import render_result_artifact
from .error import render_error_panel, render_task_error_panel
from .form import render_completion_form
from .progress import render_studio_progress
from .task_detail import render_task_detail
from .task_list import render_task_list
from .timeline import render_timeline

__all__ = [
    "render_approval_card",
    "render_completion_form",
    "render_error_panel",
    "render_result_artifact",
    "render_studio_progress",
    "render_task_detail",
    "render_task_error_panel",
    "render_task_list",
    "render_timeline",
]
