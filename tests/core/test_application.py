from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Self

import pytest
from flowpilot_application import (
    ApplicationError,
    CommandIntakeService,
    ErrorCode,
    ExecutionDisposition,
    TaskInitializationConfig,
    TaskQueryService,
)
from flowpilot_application.testing import (
    FAKE_TASK_INITIALIZATION,
    FakeExecutionPort,
    FakeThreadIdFactory,
    FakeUnitOfWork,
    FakeUnitOfWorkFactory,
)
from flowpilot_domain import DataClassification, TaskCommand, TaskStatus

NOW = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)


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


class UnconfiguredUnitOfWorkFactory:
    def __init__(self) -> None:
        self._inner = FakeUnitOfWorkFactory()

    def __call__(self) -> FakeUnitOfWork:
        return self._inner()


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
    thread_ids = FakeThreadIdFactory()
    service = CommandIntakeService(
        unit_of_work=unit_of_work,
        execution=execution,
        task_initialization=FAKE_TASK_INITIALIZATION,
        thread_id_factory=thread_ids,
        clock=lambda: NOW,
    )
    command = command_factory()

    accepted = run(service.accept(command))
    replay = run(service.accept(command))

    assert accepted.replayed is False
    assert replay.replayed is True
    assert accepted.execution_receipt.disposition is ExecutionDisposition.ACCEPTED
    assert len(execution.calls) == 1
    assert thread_ids.calls == 1
    assert len(unit_of_work.task_initialize_calls) == 1
    task = unit_of_work.store.tasks_by_id[(command.tenant_id, command.task_id)]
    assert task.thread_id == "thread_00000001"
    assert task.status is TaskStatus.RECEIVED
    assert task.version == 0
    assert task.run_generation == 0
    assert task.purpose == command.security_context.purpose
    assert task.security_context is command.security_context
    assert task.release == FAKE_TASK_INITIALIZATION.release
    assert task.data_classification is DataClassification.CONFIDENTIAL
    assert task.created_at == task.updated_at == NOW
    assert task.waiting_on is None
    assert task.result_ref is None
    assert task.error is None
    assert task.completed_at is None
    assert task.active_run_id is None
    assert task.latest_checkpoint_id is None
    assert unit_of_work.store.version_slots[
        (command.tenant_id, command.task_id, -1)
    ] == command.command_id
    assert (
        unit_of_work.store.commands_by_id[
            (command.tenant_id, command.command_id)
        ].execution_receipt
        is not None
    )


def test_direct_service_construction_without_trusted_initialization_fails_closed(
) -> None:
    with pytest.raises(ValueError, match="must be explicitly configured"):
        CommandIntakeService(
            unit_of_work=UnconfiguredUnitOfWorkFactory(),
            execution=FakeExecutionPort(),
        )


def test_idempotency_conflict_precedes_task_version_check(
    command_factory: Callable[..., TaskCommand],
) -> None:
    unit_of_work = FakeUnitOfWorkFactory()
    execution = FakeExecutionPort()
    service = CommandIntakeService(
        unit_of_work=unit_of_work,
        execution=execution,
        task_initialization=FAKE_TASK_INITIALIZATION,
        thread_id_factory=FakeThreadIdFactory(),
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


def test_different_create_for_existing_task_cannot_overwrite_projection(
    command_factory: Callable[..., TaskCommand],
) -> None:
    unit_of_work = FakeUnitOfWorkFactory()
    execution = FakeExecutionPort()
    thread_ids = FakeThreadIdFactory()
    service = CommandIntakeService(
        unit_of_work=unit_of_work,
        execution=execution,
        task_initialization=FAKE_TASK_INITIALIZATION,
        thread_id_factory=thread_ids,
        clock=lambda: NOW,
    )
    original = command_factory()
    conflict = command_factory(
        command_id="cmd_conflict0",
        idempotency_key="sha256:" + "b" * 64,
        payload={
            "initial_message_id": "msg_conflict0",
            "initial_message_ref": "message://different",
            "attachment_refs": [],
            "channel": "web",
            "purpose": "it_support",
        },
    )

    run(service.accept(original))
    original_task = unit_of_work.store.tasks_by_id[
        (original.tenant_id, original.task_id)
    ]
    with pytest.raises(ApplicationError) as captured:
        run(service.accept(conflict))

    assert captured.value.code is ErrorCode.TASK_ALREADY_EXISTS
    assert unit_of_work.store.tasks_by_id[
        (original.tenant_id, original.task_id)
    ] == original_task
    assert (conflict.tenant_id, conflict.command_id) not in (
        unit_of_work.store.commands_by_id
    )
    assert len(unit_of_work.task_initialize_calls) == 1
    assert thread_ids.calls == 1
    assert len(execution.calls) == 1


def test_idempotency_replay_keeps_original_command_identity(
    command_factory: Callable[..., TaskCommand],
) -> None:
    unit_of_work = FakeUnitOfWorkFactory()
    execution = FakeExecutionPort()
    service = CommandIntakeService(
        unit_of_work=unit_of_work,
        execution=execution,
        task_initialization=FAKE_TASK_INITIALIZATION,
        thread_id_factory=FakeThreadIdFactory(),
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
        unit_of_work=unit_of_work,
        execution=execution,
        task_initialization=FAKE_TASK_INITIALIZATION,
        thread_id_factory=FakeThreadIdFactory(),
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
    assert unit_of_work.task_initialize_calls == []

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
        unit_of_work=unit_of_work,
        execution=execution,
        task_initialization=FAKE_TASK_INITIALIZATION,
        thread_id_factory=FakeThreadIdFactory(),
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
        unit_of_work=unit_of_work,
        execution=execution,
        task_initialization=FAKE_TASK_INITIALIZATION,
        thread_id_factory=FakeThreadIdFactory(),
    )

    with pytest.raises(ApplicationError) as captured:
        run(service.accept(command_factory()))

    assert captured.value.code is ErrorCode.EXECUTION_PROTOCOL_ERROR


def test_create_fails_closed_when_trusted_classification_exceeds_ceiling(
    command_factory: Callable[..., TaskCommand],
) -> None:
    unit_of_work = FakeUnitOfWorkFactory()
    execution = FakeExecutionPort()
    service = CommandIntakeService(
        unit_of_work=unit_of_work,
        execution=execution,
        task_initialization=replace(
            FAKE_TASK_INITIALIZATION,
            data_classification=DataClassification.CONFIDENTIAL,
        ),
        thread_id_factory=FakeThreadIdFactory(),
    )
    command = command_factory(security_classification_ceiling="internal")

    with pytest.raises(ApplicationError) as captured:
        run(service.accept(command))

    assert captured.value.code is ErrorCode.SECURITY_BINDING_MISMATCH
    assert unit_of_work.store.tasks_by_id == {}
    assert unit_of_work.store.commands_by_id == {}
    assert unit_of_work.store.version_slots == {}
    assert execution.calls == []


@pytest.mark.parametrize("failure_stage", ["initialize", "command"])
def test_create_rolls_back_task_command_and_version_slot_on_tx_a_failure(
    command_factory: Callable[..., TaskCommand],
    failure_stage: str,
) -> None:
    unit_of_work = FakeUnitOfWorkFactory()
    if failure_stage == "initialize":
        unit_of_work.task_initialize_failure = RuntimeError("database secret")
    else:
        unit_of_work.command_add_failure = RuntimeError("database secret")
    execution = FakeExecutionPort()
    service = CommandIntakeService(
        unit_of_work=unit_of_work,
        execution=execution,
        task_initialization=FAKE_TASK_INITIALIZATION,
        thread_id_factory=FakeThreadIdFactory(),
    )

    with pytest.raises(ApplicationError) as captured:
        run(service.accept(command_factory()))

    assert captured.value.code is ErrorCode.REPOSITORY_UNAVAILABLE
    assert captured.value.retryable is True
    assert "secret" not in captured.value.safe_message
    assert unit_of_work.store.tasks_by_id == {}
    assert unit_of_work.store.task_versions == {}
    assert unit_of_work.store.commands_by_id == {}
    assert unit_of_work.store.command_id_by_key == {}
    assert unit_of_work.store.version_slots == {}
    assert execution.calls == []


def test_invalid_trusted_thread_factory_fails_with_stable_protocol_error(
    command_factory: Callable[..., TaskCommand],
) -> None:
    unit_of_work = FakeUnitOfWorkFactory()
    execution = FakeExecutionPort()
    invalid_config = TaskInitializationConfig(
        release=FAKE_TASK_INITIALIZATION.release,
        data_classification=DataClassification.CONFIDENTIAL,
    )
    service = CommandIntakeService(
        unit_of_work=unit_of_work,
        execution=execution,
        task_initialization=invalid_config,
        thread_id_factory=lambda: "browser-supplied-thread",
    )

    with pytest.raises(ApplicationError) as captured:
        run(service.accept(command_factory()))

    assert captured.value.code is ErrorCode.TASK_INITIALIZATION_PROTOCOL_ERROR
    assert captured.value.safe_message == "trusted task initialization is invalid"
    assert unit_of_work.store.tasks_by_id == {}
    assert unit_of_work.store.commands_by_id == {}
    assert unit_of_work.store.version_slots == {}
    assert execution.calls == []


def test_task_query_repository_failure_is_stable_and_sanitized() -> None:
    service = TaskQueryService(FailingTaskQueryUnitOfWorkFactory())

    with pytest.raises(ApplicationError) as captured:
        run(service.get("tenant-a", "task_12345678"))

    assert captured.value.code is ErrorCode.REPOSITORY_UNAVAILABLE
    assert captured.value.retryable is True
    assert "password" not in captured.value.safe_message
