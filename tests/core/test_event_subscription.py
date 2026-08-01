"""TaskEventSubscriptionService: transactional-outbox consumer for the SSE stream.

RUN_ID: run_g2_event_subscription_001

Evidence scope (tests/core/test_event_subscription.py):
- schema-valid task-event.v1 envelopes, ordered by outbox sequence
- at-least-once redelivery when the consumer transaction crashes
- durable dedup: committed redeliveries are drained without re-emission
- reconnect: a restarted consumer never loses unaccepted events
- sequence_gaps hole reporting (FP-DATA-003)
- cross-tenant isolation (FP-SEC-002) and secret-free payloads (FP-SEC-006)
"""

from __future__ import annotations

import asyncio
import copy
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jsonschema
import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
for _package in ("domain", "application", "persistence"):
    _source = REPOSITORY_ROOT / "packages" / _package / "src"
    if str(_source) not in sys.path:
        sys.path.insert(0, str(_source))

from flowpilot_application import (  # noqa: E402
    EventStreamPort,
    TaskEventEnvelope,
    TaskEventStreamConfig,
    TaskEventSubscriptionService,
)
from flowpilot_domain import Task  # noqa: E402
from flowpilot_persistence import (  # noqa: E402
    MemoryDataUnitOfWorkFactory,
    OutboxEvent,
)

CONTRACTS_ROOT = REPOSITORY_ROOT / "contracts" / "jsonschema"
TASK_EVENT_SCHEMA = json.loads(
    (CONTRACTS_ROOT / "task-event.v1.schema.json").read_text(encoding="utf-8")
)
NOW = datetime(2026, 7, 28, 8, 0, tzinfo=UTC)
FIXED_NOW = NOW


def _load_case(case_id: str) -> dict[str, Any]:
    case_file = REPOSITORY_ROOT / "contracts" / "conformance" / "rc2-cases.json"
    content = json.loads(case_file.read_text(encoding="utf-8"))
    for case in content["cases"]:
        if case["case_id"] == case_id:
            return copy.deepcopy(case["instance"])
    raise LookupError(case_id)


def make_task(
    *,
    task_id: str = "task_12345678",
    thread_id: str = "thread_12345678",
    tenant_id: str = "tenant-a",
    version: int = 0,
) -> Task:
    value = _load_case("task.completed.valid")
    value["task_id"] = task_id
    value["thread_id"] = thread_id
    value["tenant_id"] = tenant_id
    value["version"] = version
    value["security_context"]["tenant_id"] = tenant_id
    return Task.from_mapping(value)


def make_event(
    event_id: str,
    sequence: int,
    *,
    event_type: str = "task.status.changed.v1",
    task_id: str = "task_12345678",
    tenant_id: str = "tenant-a",
    payload: dict[str, Any] | None = None,
) -> OutboxEvent:
    return OutboxEvent(
        event_id=event_id,
        tenant_id=tenant_id,
        aggregate_type="task",
        aggregate_id=task_id,
        sequence=sequence,
        event_type=event_type,
        payload=payload
        or {"from": "RUNNING", "to": "COMPLETED", "reason_code": None},
        occurred_at=NOW + timedelta(seconds=sequence),
        available_at=NOW,
    )


class RecordingEventStream(EventStreamPort):
    def __init__(self) -> None:
        self.emits: list[tuple[str, TaskEventEnvelope]] = []

    async def emit(self, tenant_id: str, event: TaskEventEnvelope) -> None:
        self.emits.append((tenant_id, event))


class FaultyUnitOfWork:
    """Proxy that fails the next commit once (crash before commit)."""

    def __init__(self, inner: object, *, fail_next_commit: bool) -> None:
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_fail_next_commit", fail_next_commit)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_inner"), name)

    async def __aenter__(self) -> FaultyUnitOfWork:
        await object.__getattribute__(self, "_inner").__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await object.__getattribute__(self, "_inner").__aexit__(*args)

    async def commit(self) -> None:
        if object.__getattribute__(self, "_fail_next_commit"):
            object.__setattr__(self, "_fail_next_commit", False)
            raise RuntimeError("fault injection: consumer commit")
        await object.__getattribute__(self, "_inner").commit()


class FaultyUnitOfWorkFactory:
    def __init__(
        self, inner: MemoryDataUnitOfWorkFactory, *, fail_next_commit: bool
    ) -> None:
        self._inner = inner
        self._fail_next_commit = fail_next_commit

    def __call__(self) -> FaultyUnitOfWork:
        fail = self._fail_next_commit
        self._fail_next_commit = False
        return FaultyUnitOfWork(self._inner(), fail_next_commit=fail)


def make_service(
    factory: MemoryDataUnitOfWorkFactory,
    stream: RecordingEventStream | None = None,
    *,
    poll_interval: float = 0.01,
) -> tuple[TaskEventSubscriptionService, RecordingEventStream]:
    recording = stream or RecordingEventStream()
    service = TaskEventSubscriptionService(
        unit_of_work=factory,
        stream=recording,
        config=TaskEventStreamConfig(
            poll_interval=poll_interval,
        ),
        clock=lambda: FIXED_NOW,
    )
    return service, recording


async def seed(
    factory: MemoryDataUnitOfWorkFactory,
    *events: OutboxEvent,
    task: Task | None = None,
) -> None:
    database = factory.database
    if task is not None:
        database.seed_task(task)
    async with factory() as unit_of_work:
        for event in events:
            await unit_of_work.outbox.append(event)
        await unit_of_work.commit()


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_poll_publishes_schema_valid_envelopes_in_outbox_order() -> None:
    factory = MemoryDataUnitOfWorkFactory()
    task = make_task()
    run(
        seed(
            factory,
            make_event(
                "evt_00000001",
                1,
                event_type="task.created.v1",
                payload={"status": "RECEIVED", "task_ref": "task://task_12345678"},
            ),
            make_event("evt_00000002", 2),
            make_event(
                "evt_00000003",
                3,
                event_type="task.completed.v1",
                payload={"result_ref": "runtime-result://abc"},
            ),
            task=task,
        )
    )
    service, stream = make_service(factory)

    async def scenario() -> None:
        emitted = await service._poll_once("tenant-a")
        assert emitted == 3
        await service.close()

    run(scenario())

    assert [event.sequence for _, event in stream.emits] == [1, 2, 3]
    assert [event.event_type for _, event in stream.emits] == [
        "task.created.v1",
        "task.status.changed.v1",
        "task.completed.v1",
    ]
    for _tenant, envelope in stream.emits:
        jsonschema.validate(envelope.to_mapping(), TASK_EVENT_SCHEMA)


def test_poll_drains_outbox_and_records_consumer_dedup() -> None:
    factory = MemoryDataUnitOfWorkFactory()
    run(
        seed(
            factory,
            make_event("evt_00000001", 1),
            make_event("evt_00000002", 2),
            task=make_task(),
        )
    )
    service, stream = make_service(factory)

    async def scenario() -> None:
        assert await service._poll_once("tenant-a") == 2
        async with factory() as unit_of_work:
            unpublished = await unit_of_work.outbox.unpublished(
                "tenant-a", now=NOW + timedelta(seconds=60), limit=10
            )
            assert unpublished == ()
        await service.close()

    run(scenario())

    # The durable consumer inbox recorded the exact fingerprints that were
    # emitted; an identical redelivery is now a duplicate.
    recorded = [
        (envelope.event_id, envelope.fingerprint())
        for _, envelope in stream.emits
    ]

    async def verify_dedup() -> None:
        async with factory() as unit_of_work:
            for event_id, digest in recorded:
                duplicate = await unit_of_work.consumer_inbox.accept_once(
                    "tenant-a",
                    "stream:tenant-a",
                    event_id,
                    digest,
                    processed_at=NOW,
                )
                assert duplicate is False

    run(verify_dedup())


def test_committed_redelivery_is_deduplicated() -> None:
    factory = MemoryDataUnitOfWorkFactory()
    run(
        seed(
            factory,
            make_event("evt_00000001", 1),
            task=make_task(),
        )
    )
    service, stream = make_service(factory)

    async def scenario() -> None:
        assert await service._poll_once("tenant-a") == 1
        assert await service._poll_once("tenant-a") == 0
        await service.close()

    run(scenario())

    assert len(stream.emits) == 1


def test_crash_before_commit_redelivers_at_least_once() -> None:
    """A crash between emit and commit leaves the event unpublished; the next
    poll redelivers it (at-least-once); clients deduplicate by event_id."""
    factory = MemoryDataUnitOfWorkFactory()
    run(
        seed(
            factory,
            make_event("evt_00000001", 1),
            task=make_task(),
        )
    )
    stream = RecordingEventStream()
    service = TaskEventSubscriptionService(
        unit_of_work=FaultyUnitOfWorkFactory(
            factory, fail_next_commit=True
        ),
        stream=stream,
        config=TaskEventStreamConfig(poll_interval=0.01),
        clock=lambda: FIXED_NOW,
    )

    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="fault injection"):
            await service._poll_once("tenant-a")
        # Redelivery after the crash: the event is emitted again.
        assert await service._poll_once("tenant-a") == 1
        await service.close()

    run(scenario())

    emitted_ids = [event.event_id for _, event in stream.emits]
    assert emitted_ids == ["evt_00000001", "evt_00000001"]
    async def verify_drained() -> None:
        async with factory() as unit_of_work:
            unpublished = await unit_of_work.outbox.unpublished(
                "tenant-a", now=NOW + timedelta(seconds=60), limit=10
            )
            assert unpublished == ()
    run(verify_drained())


def test_reconnect_never_loses_unaccepted_events() -> None:
    """A restarted consumer resumes from its durable inbox: committed events
    are not re-emitted, unaccepted events are delivered."""
    factory = MemoryDataUnitOfWorkFactory()
    run(
        seed(
            factory,
            make_event("evt_00000001", 1),
            make_event("evt_00000002", 2),
            task=make_task(),
        )
    )
    first_stream = RecordingEventStream()
    second_stream: RecordingEventStream = RecordingEventStream()
    first = TaskEventSubscriptionService(
        unit_of_work=factory,
        stream=first_stream,
        config=TaskEventStreamConfig(poll_interval=0.01),
        clock=lambda: FIXED_NOW,
    )

    async def scenario() -> None:
        # Consumer processes both events, then crashes.
        assert await first._poll_once("tenant-a") == 2
        await first.close()

        # A new event arrives while the consumer is down.
        async with factory() as unit_of_work:
            await unit_of_work.outbox.append(
                make_event(
                    "evt_00000003",
                    3,
                    event_type="task.failed.v1",
                    payload={"error_code": "E1", "retryable": False},
                )
            )
            await unit_of_work.commit()

        # Reconnect with the same consumer identity.
        second = TaskEventSubscriptionService(
            unit_of_work=factory,
            stream=second_stream,
            config=TaskEventStreamConfig(poll_interval=0.01),
            clock=lambda: FIXED_NOW,
        )
        assert await second._poll_once("tenant-a") == 1
        await second.close()

    run(scenario())

    first_emitted = {event.event_id for _, event in first_stream.emits}
    second_emitted = [event.event_id for _, event in second_stream.emits]
    assert first_emitted == {"evt_00000001", "evt_00000002"}
    assert second_emitted == ["evt_00000003"]
    assert len(second_emitted) == 1


def test_gaps_report_missing_task_sequences() -> None:
    factory = MemoryDataUnitOfWorkFactory()
    run(
        seed(
            factory,
            make_event("evt_00000001", 1),
            make_event("evt_00000003", 3),
            task=make_task(),
        )
    )
    service, _stream = make_service(factory)

    async def scenario() -> None:
        assert await service.gaps("tenant-a", "task_12345678") == (2,)
        await service.close()

    run(scenario())


def test_cross_tenant_isolation_reads_zero_foreign_events() -> None:
    """FP-SEC-002: a tenant subscription never reads another tenant's events."""
    factory = MemoryDataUnitOfWorkFactory()
    run(
        seed(
            factory,
            make_event(
                "evt_00000001",
                1,
                tenant_id="tenant-a",
                task_id="task_12345678",
            ),
            task=make_task(tenant_id="tenant-a"),
        )
    )
    service, stream = make_service(factory)

    async def scenario() -> None:
        assert await service._poll_once("tenant-b") == 0
        await service.close()

    run(scenario())

    assert stream.emits == []


def test_emitted_payloads_contain_no_secret_material() -> None:
    """FP-SEC-006: the event stream cannot carry plaintext secret fields."""
    factory = MemoryDataUnitOfWorkFactory()
    run(
        seed(
            factory,
            make_event("evt_00000001", 1),
            task=make_task(),
        )
    )
    service, stream = make_service(factory)

    async def scenario() -> None:
        await service._poll_once("tenant-a")
        await service.close()

    run(scenario())

    secret_keys = {
        "access_token",
        "api_key",
        "authorization",
        "cookie",
        "password",
        "private_key",
        "refresh_token",
        "secret",
        "session_token",
    }
    for _tenant, envelope in stream.emits:
        serialized = json.dumps(envelope.to_mapping()).casefold()
        for key in secret_keys:
            assert key not in serialized


def test_envelope_trace_identity_is_stable_per_task_event() -> None:
    """trace_id/run_id/correlation_id are deterministic per outbox event."""
    factory = MemoryDataUnitOfWorkFactory()
    run(
        seed(
            factory,
            make_event("evt_00000001", 1),
            make_event("evt_00000002", 2),
            task=make_task(),
        )
    )
    service, stream = make_service(factory)

    async def scenario() -> None:
        await service._poll_once("tenant-a")
        await service.close()

    run(scenario())

    envelopes = [event for _, event in stream.emits]
    # Each event has a deterministic trace identity: distinct events differ,
    # and the identity derives from the event itself (stable across replay).
    assert len({event.trace_id for event in envelopes}) == 2
    assert len({event.trace_id for event in envelopes}) == len(envelopes)
    assert all(event.run_id == f"run_{event.trace_id[:16]}" for event in envelopes)
    assert all(
        event.correlation_id == f"corr_{event.trace_id[:16]}"
        for event in envelopes
    )
    assert all(event.producer == "worker" for event in envelopes)
    assert [event.sequence for event in envelopes] == [1, 2]
    # Reconstructing the same event yields the same trace identity.
    assert (
        envelopes[0].trace_id
        == TaskEventSubscriptionService._enrich_trace_id(
            "tenant-a", "task_12345678", "task.status.changed.v1", 1
        )
    )
