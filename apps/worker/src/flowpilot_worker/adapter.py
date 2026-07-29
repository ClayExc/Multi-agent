from __future__ import annotations

from flowpilot_application import (
    ExecutionDisposition,
    ExecutionReceipt,
)
from flowpilot_domain import DomainViolation, TaskCommand

from .queue import ExecutionEnvelope, ExecutionQueuePort


class ExecutionSubmissionError(RuntimeError):
    pass


class RuntimeExecutionAdapter:
    """S5 ExecutionPort implementation backed by an idempotent queue boundary."""

    def __init__(self, queue: ExecutionQueuePort) -> None:
        self._queue = queue

    async def submit(self, command: TaskCommand) -> ExecutionReceipt:
        try:
            command.assert_digest()
            command.assert_security_binding()
        except DomainViolation as exc:
            raise ExecutionSubmissionError(
                "command failed deterministic runtime binding"
            ) from exc
        execution_ref = (
            f"execution://{command.tenant_id}/{command.command_id}"
        )
        accepted = await self._queue.enqueue(
            ExecutionEnvelope(execution_ref=execution_ref, command=command)
        )
        return ExecutionReceipt(
            command_id=command.command_id,
            tenant_id=command.tenant_id,
            task_id=command.task_id,
            disposition=(
                ExecutionDisposition.ACCEPTED
                if accepted
                else ExecutionDisposition.DUPLICATE
            ),
            execution_ref=execution_ref,
        )
