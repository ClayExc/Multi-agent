from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from flowpilot_domain import (
    CommandType,
    DomainErrorCode,
    DomainViolation,
    Task,
    TaskCommand,
)

from .errors import ApplicationError, ErrorCode
from .models import CommandAcceptance, ExecutionReceipt, StoredCommand
from .ports import (
    ExecutionPort,
    TaskQueryPort,
    UnitOfWorkFactory,
    VersionSlotReservation,
)

Clock = Callable[[], datetime]


class TaskQueryService:
    """Read a tenant-scoped Task projection without mutating workflow state."""

    def __init__(self, repository: TaskQueryPort) -> None:
        self._repository = repository

    async def get(self, tenant_id: str, task_id: str) -> Task:
        try:
            task = await self._repository.get(tenant_id, task_id)
        except Exception as exc:
            raise ApplicationError(
                ErrorCode.REPOSITORY_UNAVAILABLE,
                "task repository is unavailable",
                retryable=True,
            ) from exc
        if task is None:
            raise ApplicationError(ErrorCode.TASK_NOT_FOUND, "task was not found")
        if task.tenant_id != tenant_id or task.task_id != task_id:
            raise ApplicationError(
                ErrorCode.REPOSITORY_PROTOCOL_ERROR,
                "task repository returned a mismatched projection",
            )
        return task


class CommandIntakeService:
    """Deterministic TaskCommand intake; it never mutates task state directly."""

    def __init__(
        self,
        *,
        unit_of_work: UnitOfWorkFactory,
        execution: ExecutionPort,
        clock: Clock | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._execution = execution
        self._clock = clock or (lambda: datetime.now(UTC))

    async def accept(self, command: TaskCommand) -> CommandAcceptance:
        self._validate_command(command)
        stored, replayed = await self._persist(command)
        effective_command = stored.command
        receipt = stored.execution_receipt
        if receipt is None:
            receipt = await self._dispatch(effective_command)
            await self._record_execution(effective_command, receipt)
        return CommandAcceptance(
            command_id=effective_command.command_id,
            tenant_id=effective_command.tenant_id,
            task_id=effective_command.task_id,
            accepted_at=stored.accepted_at,
            replayed=replayed,
            execution_receipt=receipt,
        )

    def _validate_command(self, command: TaskCommand) -> None:
        try:
            command.assert_digest()
            command.assert_security_binding()
        except DomainViolation as exc:
            mapping = {
                DomainErrorCode.DIGEST_MISMATCH: ErrorCode.COMMAND_DIGEST_MISMATCH,
                DomainErrorCode.SECURITY_BINDING_MISMATCH: (
                    ErrorCode.SECURITY_BINDING_MISMATCH
                ),
            }
            raise ApplicationError(
                mapping.get(exc.code, ErrorCode.CONTRACT_INVALID),
                exc.safe_message,
            ) from exc

    async def _persist(self, command: TaskCommand) -> tuple[StoredCommand, bool]:
        try:
            async with self._unit_of_work() as unit_of_work:
                by_key = await unit_of_work.commands.get_by_idempotency_key(
                    command.tenant_id, command.idempotency_key
                )
                if by_key is not None:
                    self._assert_same_digest(
                        command,
                        by_key,
                        ErrorCode.IDEMPOTENCY_CONFLICT,
                        "idempotency key is already bound to another command",
                    )
                    return by_key, True

                by_id = await unit_of_work.commands.get_by_command_id(
                    command.tenant_id, command.command_id
                )
                if by_id is not None:
                    self._assert_same_digest(
                        command,
                        by_id,
                        ErrorCode.COMMAND_ID_CONFLICT,
                        "command_id is already bound to another command",
                    )
                    if (
                        by_id.command.idempotency_key
                        != command.idempotency_key
                    ):
                        raise ApplicationError(
                            ErrorCode.COMMAND_ID_CONFLICT,
                            "command_id is already bound to another idempotency key",
                        )
                    return by_id, True

                current_version = await unit_of_work.tasks.get_version(
                    command.tenant_id, command.task_id
                )
                self._validate_version(command, current_version)
                reservation = await unit_of_work.commands.reserve_version_slot(
                    command.tenant_id,
                    command.task_id,
                    command.expected_task_version,
                    command.command_id,
                )
                if reservation is VersionSlotReservation.CONFLICT:
                    raise ApplicationError(
                        ErrorCode.VERSION_SLOT_CONFLICT,
                        "another command already reserved the task version",
                    )
                stored = StoredCommand(command=command, accepted_at=self._clock())
                await unit_of_work.commands.add(stored)
                await unit_of_work.commit()
                return stored, False
        except ApplicationError:
            raise
        except Exception as exc:
            raise ApplicationError(
                ErrorCode.REPOSITORY_UNAVAILABLE,
                "command repository is unavailable",
                retryable=True,
            ) from exc

    @staticmethod
    def _assert_same_digest(
        command: TaskCommand,
        stored: StoredCommand,
        error_code: ErrorCode,
        message: str,
    ) -> None:
        if stored.command.command_digest != command.command_digest:
            raise ApplicationError(error_code, message)

    @staticmethod
    def _validate_version(
        command: TaskCommand, current_version: int | None
    ) -> None:
        if command.command_type is CommandType.CREATE:
            if current_version is not None:
                raise ApplicationError(
                    ErrorCode.TASK_ALREADY_EXISTS,
                    "task already exists",
                )
            return
        if current_version is None:
            raise ApplicationError(ErrorCode.TASK_NOT_FOUND, "task was not found")
        if current_version != command.expected_task_version:
            raise ApplicationError(
                ErrorCode.TASK_VERSION_CONFLICT,
                "task version does not match expected_task_version",
            )

    async def _dispatch(self, command: TaskCommand) -> ExecutionReceipt:
        try:
            receipt = await self._execution.submit(command)
        except Exception as exc:
            raise ApplicationError(
                ErrorCode.EXECUTION_UNAVAILABLE,
                "runtime execution is unavailable",
                retryable=True,
            ) from exc
        if (
            receipt.command_id != command.command_id
            or receipt.tenant_id != command.tenant_id
            or receipt.task_id != command.task_id
            or not receipt.execution_ref
        ):
            raise ApplicationError(
                ErrorCode.EXECUTION_PROTOCOL_ERROR,
                "runtime returned an invalid execution receipt",
            )
        return receipt

    async def _record_execution(
        self, command: TaskCommand, receipt: ExecutionReceipt
    ) -> None:
        try:
            async with self._unit_of_work() as unit_of_work:
                await unit_of_work.commands.record_execution(
                    command.tenant_id, command.command_id, receipt
                )
                await unit_of_work.commit()
        except Exception as exc:
            raise ApplicationError(
                ErrorCode.REPOSITORY_UNAVAILABLE,
                "execution receipt could not be persisted",
                retryable=True,
            ) from exc
