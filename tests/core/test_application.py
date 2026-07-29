from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Self

import pytest
from flowpilot_application import (
    ApplicationError,
    CommandIntakeService,
    ErrorCode,
    ExecutionDisposition,
    TaskQueryService,
)
from flowpilot_application.testing import (
    FakeExecutionPort,
    FakeUnitOfWorkFactory,
)
from flowpilot_domain import TaskCommand


class FailingTaskQueryUnitOfWork:
    tasks: Self

    async def __aenter__(self) -> Self:
        self.tasks = self
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: object,
    ) -> None:
        return None

    async def get(self, _tenant_id: str, _task_id: str) -> None:
        raise RuntimeError("database password=never expose")


class FailingTaskQueryUnitOfWorkFactory:
    def __call__(self) -> FailingTaskQueryUnitOfWork:
        return FailingTaskQueryUnitOfWork()


def run(coroutine: object) -> object:
    return asyncio.run(coroutine)  # type: ignore[arg-type]


def _message(
    command_factory: Callable[..., TaskCommand],
    *,
    command_id: str,
    idempotency_character: str,
    expected_version: int,
    reference: str,
) -> TaskCommand:
    return command_factory(
        command_id=command_id,
        command_type="task.message.submit.v1",
        expected_task_version=expected_version,
        idempotency_key="sha256:" + idempotency_character * 64,
        payload={
            "message_id": "msg_" + command_id.removeprefix("cmd_"),
            "message_ref": reference,
            "attachment_refs": [],
        },
    )


def test_intake_persists_dispatches_and_replays_without_redispatch(
    command_factory: Callable[..., TaskCommand],
) -> None:
    unit_of_work = FakeUnitOfWorkFactory()
    execution = FakeExecutionPort()
    service = CommandIntakeService(
        unit_of_work=unit_of_work, execution=execution
    )
    command = command_factory()

    accepted = run(service.accept(command))
    replay = run(service.accept(command))

    assert accepted.replayed is False
    assert replay.replayed is True
    assert accepted.execution_receipt.disposition is ExecutionDisposition.ACCEPTED
    assert len(execution.calls) == 1
    assert (
        unit_of_work.store.commands_by_id[
            (command.tenant_id, command.command_id)
        ].execution_receipt
        is not None
    )


def test_idempotency_conflict_precedes_task_version_check(
    command_factory: Callable[..., TaskCommand],
) -> None:
    unit_of_work = FakeUnitOfWorkFactory()
    execution = FakeExecutionPort()
    service = CommandIntakeService(
        unit_of_work=unit_of_work, execution=execution
    )
    original = command_factory()
    run(service.accept(original))
    unit_of_work.store.task_versions[(original.tenant_id, original.task_id)] = 99
    conflict = command_factory(
        command_id="cmd_abcdefgh",
        payload={
            "initial_message_id": "msg_abcdefgh",
            "initial_message_ref": "message://different",
            "attachment_refs": [],
            "channel": "web",
            "purpose": "it_support",
        },
    )

    with pytest.raises(ApplicationError) as captured:
        run(service.accept(conflict))

    assert captured.value.code is ErrorCode.IDEMPOTENCY_CONFLICT


def test_idempotency_replay_keeps_original_command_identity(
    command_factory: Callable[..., TaskCommand],
) -> None:
    unit_of_work = FakeUnitOfWorkFactory()
    execution = FakeExecutionPort()
    service = CommandIntakeService(
        unit_of_work=unit_of_work, execution=execution
    )
    original = command_factory()
    same_intent = command_factory(command_id="cmd_abcdefgh")

    first = run(service.accept(original))
    replay = run(service.accept(same_intent))

    assert replay.replayed is True
    assert replay.command_id == first.command_id == original.command_id
    assert len(execution.calls) == 1


def test_version_conflict_and_version_slot_conflict_are_stable(
    command_factory: Callable[..., TaskCommand],
) -> None:
    unit_of_work = FakeUnitOfWorkFactory()
    unit_of_work.store.task_versions[("tenant-a", "task_12345678")] = 3
    execution = FakeExecutionPort()
    service = CommandIntakeService(
        unit_of_work=unit_of_work, execution=execution
    )
    stale = _message(
        command_factory,
        command_id="cmd_stale000",
        idempotency_character="b",
        expected_version=2,
        reference="message://stale",
    )

    with pytest.raises(ApplicationError) as stale_error:
        run(service.accept(stale))
    assert stale_error.value.code is ErrorCode.TASK_VERSION_CONFLICT

    first = _message(
        command_factory,
        command_id="cmd_first000",
        idempotency_character="c",
        expected_version=3,
        reference="message://first",
    )
    second = _message(
        command_factory,
        command_id="cmd_second00",
        idempotency_character="d",
        expected_version=3,
        reference="message://second",
    )
    run(service.accept(first))

    with pytest.raises(ApplicationError) as slot_error:
        run(service.accept(second))
    assert slot_error.value.code is ErrorCode.VERSION_SLOT_CONFLICT


def test_persisted_command_recovers_after_runtime_failure(
    command_factory: Callable[..., TaskCommand],
) -> None:
    unit_of_work = FakeUnitOfWorkFactory()
    execution = FakeExecutionPort()
    execution.failure = RuntimeError("provider secret: never expose")
    service = CommandIntakeService(
        unit_of_work=unit_of_work, execution=execution
    )
    command = command_factory()

    with pytest.raises(ApplicationError) as unavailable:
        run(service.accept(command))

    assert unavailable.value.code is ErrorCode.EXECUTION_UNAVAILABLE
    assert unavailable.value.retryable is True
    assert "secret" not in unavailable.value.safe_message
    execution.failure = None
    recovered = run(service.accept(command))

    assert recovered.replayed is True
    assert recovered.execution_receipt.disposition is ExecutionDisposition.ACCEPTED
    assert len(execution.calls) == 2


def test_invalid_execution_receipt_fails_closed(
    command_factory: Callable[..., TaskCommand],
) -> None:
    unit_of_work = FakeUnitOfWorkFactory()
    execution = FakeExecutionPort()
    execution.invalid_receipt = True
    service = CommandIntakeService(
        unit_of_work=unit_of_work, execution=execution
    )

    with pytest.raises(ApplicationError) as captured:
        run(service.accept(command_factory()))

    assert captured.value.code is ErrorCode.EXECUTION_PROTOCOL_ERROR


def test_task_query_repository_failure_is_stable_and_sanitized() -> None:
    service = TaskQueryService(FailingTaskQueryUnitOfWorkFactory())

    with pytest.raises(ApplicationError) as captured:
        run(service.get("tenant-a", "task_12345678"))

    assert captured.value.code is ErrorCode.REPOSITORY_UNAVAILABLE
    assert captured.value.retryable is True
    assert "password" not in captured.value.safe_message
