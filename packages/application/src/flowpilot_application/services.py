from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from flowpilot_domain import (
    CommandType,
    DataClassification,
    DomainErrorCode,
    DomainViolation,
    Task,
    TaskCommand,
)

from .errors import ApplicationError, ErrorCode
from .models import (
    ArtifactWriteDisposition,
    CommandAcceptance,
    ExecutionReceipt,
    RequestObservation,
    RequestReferenceQuery,
    ResultArtifactDraft,
    ResultArtifactReceipt,
    StoredCommand,
)
from .ports import (
    ExecutionPort,
    RequestReferenceResolverPort,
    ResultArtifactPort,
    TaskQueryUnitOfWorkFactory,
    UnitOfWorkFactory,
    VersionSlotReservation,
)

Clock = Callable[[], datetime]
_CLASSIFICATION_RANK = {
    DataClassification.PUBLIC: 0,
    DataClassification.INTERNAL: 1,
    DataClassification.CONFIDENTIAL: 2,
    DataClassification.RESTRICTED: 3,
}


class TaskQueryService:
    """Read a tenant-scoped Task projection without mutating workflow state."""

    def __init__(self, unit_of_work: TaskQueryUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def get(self, tenant_id: str, task_id: str) -> Task:
        try:
            async with self._unit_of_work() as unit_of_work:
                task = await unit_of_work.tasks.get(tenant_id, task_id)
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


class RequestObservationService:
    """Resolve opaque message references without exposing original message text."""

    def __init__(
        self,
        *,
        resolver: RequestReferenceResolverPort,
        required_fields: Mapping[str, tuple[str, ...]],
    ) -> None:
        self._resolver = resolver
        self._required_fields = dict(required_fields)

    async def resolve(self, command: TaskCommand) -> RequestObservation:
        query = self._query_from_command(command)
        try:
            resolved = await self._resolver.resolve(query)
        except ApplicationError:
            raise
        except Exception as exc:
            raise ApplicationError(
                ErrorCode.REQUEST_REFERENCE_UNAVAILABLE,
                "request reference resolver is unavailable",
                retryable=True,
            ) from exc
        if resolved is None:
            raise ApplicationError(
                ErrorCode.REQUEST_REFERENCE_NOT_FOUND,
                "request reference was not found",
            )
        if resolved.query != query:
            raise ApplicationError(
                ErrorCode.REQUEST_REFERENCE_BINDING_MISMATCH,
                "resolved request does not match the trusted reference binding",
            )
        if (
            _CLASSIFICATION_RANK[resolved.data_classification]
            > _CLASSIFICATION_RANK[
                command.security_context.data_classification_ceiling
            ]
        ):
            raise ApplicationError(
                ErrorCode.REQUEST_REFERENCE_BINDING_MISMATCH,
                "resolved request exceeds the trusted classification ceiling",
            )
        try:
            resolved.assert_digest()
        except ValueError as exc:
            raise ApplicationError(
                ErrorCode.REQUEST_REFERENCE_TAMPERED,
                "resolved request integrity verification failed",
            ) from exc
        required = self._required_fields.get(resolved.intent)
        if required is None:
            raise ApplicationError(
                ErrorCode.REQUEST_REFERENCE_PROTOCOL_ERROR,
                "resolved request references an unknown intent",
            )
        missing_fields = tuple(
            field_name
            for field_name in required
            if field_name not in resolved.fields
        )
        return RequestObservation(
            tenant_id=query.tenant_id,
            task_id=query.task_id,
            message_id=query.message_id,
            observation_ref=resolved.observation_ref,
            source_digest=resolved.source_digest,
            intent=resolved.intent,
            fields=resolved.fields,
            missing_fields=missing_fields,
            data_classification=resolved.data_classification,
        )

    @staticmethod
    def _query_from_command(command: TaskCommand) -> RequestReferenceQuery:
        if command.command_type is CommandType.CREATE:
            message_id = command.payload["initial_message_id"]
            message_ref = command.payload["initial_message_ref"]
        elif command.command_type is CommandType.SUBMIT_MESSAGE:
            message_id = command.payload["message_id"]
            message_ref = command.payload["message_ref"]
        else:
            raise ApplicationError(
                ErrorCode.CONTRACT_INVALID,
                "command type does not contain a request reference",
            )
        if not isinstance(message_id, str) or not isinstance(message_ref, str):
            raise ApplicationError(
                ErrorCode.CONTRACT_INVALID,
                "command request reference is invalid",
            )
        return RequestReferenceQuery(
            tenant_id=command.tenant_id,
            task_id=command.task_id,
            message_id=message_id,
            message_ref=message_ref,
            purpose=command.security_context.purpose,
            security_context_ref=command.security_context.context_ref,
        )


class ResultArtifactService:
    """Persist result content idempotently while returning only an opaque ref."""

    def __init__(self, artifacts: ResultArtifactPort) -> None:
        self._artifacts = artifacts

    async def save(self, draft: ResultArtifactDraft) -> ResultArtifactReceipt:
        try:
            draft.assert_digest()
        except ValueError as exc:
            raise ApplicationError(
                ErrorCode.RESULT_ARTIFACT_TAMPERED,
                "result artifact integrity verification failed",
            ) from exc
        try:
            receipt = await self._artifacts.put(draft)
        except ApplicationError:
            raise
        except Exception as exc:
            raise ApplicationError(
                ErrorCode.RESULT_ARTIFACT_UNAVAILABLE,
                "result artifact store is unavailable",
                retryable=True,
            ) from exc
        if receipt.disposition is ArtifactWriteDisposition.CONFLICT:
            raise ApplicationError(
                ErrorCode.RESULT_ARTIFACT_CONFLICT,
                "result idempotency key is bound to different content",
            )
        if (
            receipt.tenant_id != draft.tenant_id
            or receipt.task_id != draft.task_id
            or receipt.idempotency_key != draft.idempotency_key
            or receipt.result_digest != draft.result_digest
            or not receipt.result_ref
        ):
            raise ApplicationError(
                ErrorCode.RESULT_ARTIFACT_PROTOCOL_ERROR,
                "result artifact store returned a mismatched receipt",
            )
        return receipt
