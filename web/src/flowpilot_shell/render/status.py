"""Task status display mapping (运行/等待/失败 states)."""

from __future__ import annotations

STATUS_LABELS = {
    "RECEIVED": "已接收",
    "RUNNABLE": "可运行",
    "RUNNING": "运行中",
    "WAITING_USER": "等待信息补全",
    "WAITING_APPROVAL": "等待审批",
    "VERIFYING": "验证中",
    "COMPLETED": "已完成",
    "CANCELLED": "已取消",
    "ESCALATED": "已升级",
    "FAILED": "失败",
}

# 时间线三态分组：运行 / 等待 / 失败
RUNNING_STATUSES = frozenset({"RUNNING", "VERIFYING", "RUNNABLE"})
WAITING_STATUSES = frozenset({"WAITING_USER", "WAITING_APPROVAL"})
FAILED_STATUSES = frozenset({"FAILED", "ESCALATED"})


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def status_class(status: str) -> str:
    if status in WAITING_STATUSES:
        return "status-waiting"
    if status in FAILED_STATUSES:
        return "status-failed"
    if status == "COMPLETED":
        return "status-done"
    return "status-running"
