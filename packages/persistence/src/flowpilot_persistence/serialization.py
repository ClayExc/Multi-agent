from __future__ import annotations

from datetime import datetime
from typing import Any

from flowpilot_application import (
    ExecutionDisposition,
    ExecutionReceipt,
    StoredCommand,
)
from flowpilot_domain import Task, TaskCommand, TaskStatus

from .models import format_utc, thaw_json


def is_initial_task_projection(task: Task) -> bool:
    """Return whether a Task is the authoritative Command Tx-A projection."""

    return (
        task.status is TaskStatus.RECEIVED
        and task.version == 0
        and task.run_generation == 0
        and task.waiting_on is None
        and task.result_ref is None
        and task.error is None
        and task.completed_at is None
        and task.active_run_id is None
        and task.latest_checkpoint_id is None
        and task.domain is None
        and task.intent is None
        and task.risk_level is None
        and task.created_at == task.updated_at
    )


def task_command_to_mapping(command: TaskCommand) -> dict[str, Any]:
    result: dict[str, Any] = {
        "command_id": command.command_id,
        "command_type": command.command_type.value,
        "tenant_id": command.tenant_id,
        "task_id": command.task_id,
        "actor": command.actor.to_mapping(),
        "security_context": command.security_context.to_mapping(),
        "expected_task_version": command.expected_task_version,
        "idempotency_key": command.idempotency_key,
        "command_digest": command.command_digest,
        "payload": thaw_json(command.payload),
        "issued_at": format_utc(command.issued_at),
    }
    if command.correlation_id is not None:
        result["correlation_id"] = command.correlation_id
    return result


def execution_receipt_to_mapping(receipt: ExecutionReceipt) -> dict[str, str]:
    return {
        "command_id": receipt.command_id,
        "tenant_id": receipt.tenant_id,
        "task_id": receipt.task_id,
        "disposition": receipt.disposition.value,
        "execution_ref": receipt.execution_ref,
    }


def execution_receipt_from_mapping(value: dict[str, Any]) -> ExecutionReceipt:
    return ExecutionReceipt(
        command_id=value["command_id"],
        tenant_id=value["tenant_id"],
        task_id=value["task_id"],
        disposition=ExecutionDisposition(value["disposition"]),
        execution_ref=value["execution_ref"],
    )


def stored_command_from_row(row: dict[str, Any]) -> StoredCommand:
    command_value = row["command"]
    if not isinstance(command_value, dict):
        raise ValueError("stored command must be a JSON object")
    receipt_value = row.get("execution_receipt")
    if receipt_value is not None and not isinstance(receipt_value, dict):
        raise ValueError("execution receipt must be a JSON object")
    accepted_at = row["accepted_at"]
    if not isinstance(accepted_at, datetime):
        raise ValueError("accepted_at must be a datetime")
    return StoredCommand(
        command=TaskCommand.from_mapping(command_value),
        accepted_at=accepted_at,
        execution_receipt=(
            execution_receipt_from_mapping(receipt_value)
            if receipt_value is not None
            else None
        ),
    )
