from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from flowpilot_persistence import (
    CheckpointRecord,
    CoordinationSignal,
    MemoryDataUnitOfWorkFactory,
    MemoryRedisClient,
    PersistenceError,
    PersistenceErrorCode,
    RedisCoordinationAdapter,
)

NOW = datetime(2026, 7, 28, 8, 0, tzinfo=UTC)


def checkpoint(
    checkpoint_id: str,
    run_generation: int,
    created_at: datetime,
    *,
    checkpoint_sequence: int,
    tenant_id: str = "tenant-a",
    task_id: str = "task_12345678",
    thread_id: str = "thread_12345678",
    state: dict[str, Any] | None = None,
) -> CheckpointRecord:
    return CheckpointRecord(
        checkpoint_id=checkpoint_id,
        tenant_id=tenant_id,
        task_id=task_id,
        thread_id=thread_id,
        run_generation=run_generation,
        checkpoint_sequence=checkpoint_sequence,
        graph_version="graph-v1",
        state=state
        or {"current_step": "plan", "evidence_refs": ["ev://safe/1"]},
        security_context_ref="security-context://tenant-a/12345678",
        security_context_hash="sha256:" + "a" * 64,
        created_at=created_at,
    )


def test_checkpoint_cas_first_continuous_and_safe_replay() -> None:
    async def scenario() -> None:
        factory = MemoryDataUnitOfWorkFactory()
        async with factory() as unit_of_work:
            fence = await unit_of_work.leases.acquire(
                "tenant-a",
                "task_12345678",
                "worker-a",
                now=NOW,
                ttl=timedelta(minutes=5),
            )
            candidate = checkpoint(
                "cp_12345678",
                fence.run_generation,
                NOW,
                checkpoint_sequence=0,
            )
            first = await unit_of_work.checkpoints.put(
                candidate,
                fence,
                expected_sequence=0,
            )
            assert first.checkpoint_sequence == 1
            assert (
                await unit_of_work.checkpoints.put(
                    candidate,
                    fence,
                    expected_sequence=0,
                )
                == first
            )
            second = await unit_of_work.checkpoints.put(
                checkpoint(
                    "cp_87654321",
                    fence.run_generation,
                    NOW + timedelta(seconds=1),
                    checkpoint_sequence=1,
                    state={"current_step": "resume"},
                ),
                fence,
                expected_sequence=1,
            )
            assert second.checkpoint_sequence == 2
            await unit_of_work.commit()

        async with factory() as unit_of_work:
            latest = await unit_of_work.checkpoints.latest(
                "tenant-a",
                "task_12345678",
                "thread_12345678",
            )
            assert latest == second
            assert (
                await unit_of_work.checkpoints.latest(
                    "tenant-a",
                    "task_other000",
                    "thread_12345678",
                )
                is None
            )
            assert (
                await unit_of_work.checkpoints.latest(
                    "tenant-a",
                    "task_12345678",
                    "thread_other000",
                )
                is None
            )

        async with factory() as unit_of_work:
            assert (
                await unit_of_work.checkpoints.latest(
                    "tenant-b",
                    "task_12345678",
                    "thread_12345678",
                )
                is None
            )

    asyncio.run(scenario())


def test_checkpoint_cas_rejects_wrong_first_and_stale_sequence() -> None:
    async def scenario() -> None:
        factory = MemoryDataUnitOfWorkFactory()
        async with factory() as unit_of_work:
            fence = await unit_of_work.leases.acquire(
                "tenant-a",
                "task_12345678",
                "worker-a",
                now=NOW,
                ttl=timedelta(minutes=5),
            )
            with pytest.raises(PersistenceError) as wrong_first:
                await unit_of_work.checkpoints.put(
                    checkpoint(
                        "cp_wrongfirst",
                        fence.run_generation,
                        NOW,
                        checkpoint_sequence=1,
                    ),
                    fence,
                    expected_sequence=1,
                )
            assert (
                wrong_first.value.code
                is PersistenceErrorCode.VERSION_CONFLICT
            )
            first_candidate = checkpoint(
                "cp_12345678",
                fence.run_generation,
                NOW,
                checkpoint_sequence=0,
            )
            await unit_of_work.checkpoints.put(
                first_candidate,
                fence,
                expected_sequence=0,
            )
            with pytest.raises(PersistenceError) as stale:
                await unit_of_work.checkpoints.put(
                    checkpoint(
                        "cp_stale123",
                        fence.run_generation,
                        NOW + timedelta(seconds=1),
                        checkpoint_sequence=0,
                    ),
                    fence,
                    expected_sequence=0,
                )
            assert stale.value.code is PersistenceErrorCode.VERSION_CONFLICT
            with pytest.raises(PersistenceError) as identity_conflict:
                await unit_of_work.checkpoints.put(
                    replace(
                        first_candidate,
                        state={"current_step": "tampered"},
                    ),
                    fence,
                    expected_sequence=0,
                )
            assert identity_conflict.value.code is PersistenceErrorCode.CONFLICT

    asyncio.run(scenario())


def test_expired_lease_fences_old_worker_and_recovers_latest_checkpoint() -> None:
    async def scenario() -> None:
        factory = MemoryDataUnitOfWorkFactory()
        async with factory() as unit_of_work:
            first = await unit_of_work.leases.acquire(
                "tenant-a",
                "task_12345678",
                "worker-a",
                now=NOW,
                ttl=timedelta(seconds=30),
            )
            await unit_of_work.checkpoints.put(
                checkpoint(
                    "cp_12345678",
                    first.run_generation,
                    NOW,
                    checkpoint_sequence=0,
                ),
                first,
                expected_sequence=0,
            )
            await unit_of_work.commit()

        after_expiry = NOW + timedelta(seconds=31)
        async with factory() as unit_of_work:
            second = await unit_of_work.leases.acquire(
                "tenant-a",
                "task_12345678",
                "worker-b",
                now=after_expiry,
                ttl=timedelta(seconds=30),
            )
            assert second.run_generation == first.run_generation + 1
            with pytest.raises(PersistenceError) as caught:
                await unit_of_work.checkpoints.put(
                    checkpoint(
                        "cp_stale123",
                        first.run_generation,
                        after_expiry,
                        checkpoint_sequence=1,
                    ),
                    first,
                    expected_sequence=1,
                )
            assert caught.value.code is PersistenceErrorCode.STALE_FENCE
            recovered = await unit_of_work.checkpoints.put(
                checkpoint(
                    "cp_87654321",
                    second.run_generation,
                    after_expiry,
                    checkpoint_sequence=1,
                ),
                second,
                expected_sequence=1,
            )
            assert recovered.checkpoint_sequence == 2
            await unit_of_work.commit()

        async with factory() as unit_of_work:
            latest = await unit_of_work.checkpoints.latest(
                "tenant-a",
                "task_12345678",
                "thread_12345678",
            )
            assert latest is not None
            assert latest.checkpoint_id == "cp_87654321"
            assert latest.run_generation == second.run_generation

    asyncio.run(scenario())


def test_checkpoint_rejects_expired_lease_and_cross_tenant_write() -> None:
    async def scenario() -> None:
        factory = MemoryDataUnitOfWorkFactory()
        async with factory() as unit_of_work:
            fence = await unit_of_work.leases.acquire(
                "tenant-a",
                "task_12345678",
                "worker-a",
                now=NOW,
                ttl=timedelta(seconds=30),
            )
            await unit_of_work.commit()

        after_expiry = NOW + timedelta(seconds=31)
        async with factory() as unit_of_work:
            with pytest.raises(PersistenceError) as expired:
                await unit_of_work.checkpoints.put(
                    checkpoint(
                        "cp_expired00",
                        fence.run_generation,
                        after_expiry,
                        checkpoint_sequence=0,
                    ),
                    fence,
                    expected_sequence=0,
                )
            assert expired.value.code is PersistenceErrorCode.STALE_FENCE

        async with factory() as unit_of_work:
            with pytest.raises(PersistenceError) as cross_tenant:
                await unit_of_work.checkpoints.put(
                    checkpoint(
                        "cp_cross000",
                        fence.run_generation,
                        NOW,
                        checkpoint_sequence=0,
                        tenant_id="tenant-b",
                    ),
                    fence,
                    expected_sequence=0,
                )
            assert cross_tenant.value.code is PersistenceErrorCode.STALE_FENCE

    asyncio.run(scenario())


def test_checkpoint_rejects_secret_shaped_fields() -> None:
    with pytest.raises(PersistenceError) as caught:
        CheckpointRecord(
            checkpoint_id="cp_secret123",
            tenant_id="tenant-a",
            task_id="task_12345678",
            thread_id="thread_12345678",
            run_generation=1,
            checkpoint_sequence=0,
            graph_version="graph-v1",
            state={"access_token": "not-allowed"},
            security_context_ref="security-context://tenant-a/12345678",
            security_context_hash="sha256:" + "a" * 64,
            created_at=NOW,
        )
    assert caught.value.code is PersistenceErrorCode.SECRET_MATERIAL


def test_redis_loss_is_rebuilt_from_postgres_derived_signals() -> None:
    async def scenario() -> None:
        client = MemoryRedisClient()
        adapter = RedisCoordinationAdapter(client)
        signals = [
            CoordinationSignal(
                tenant_id="tenant-a",
                task_id="task_12345678",
                run_generation=3,
                available_at=NOW,
            ),
            CoordinationSignal(
                tenant_id="tenant-b",
                task_id="task_87654321",
                run_generation=1,
                available_at=NOW,
            ),
        ]

        assert await adapter.rebuild(signals) == 2
        assert len(client.values) == 2
        await adapter.clear()
        assert client.values == {}
        assert await adapter.rebuild(signals) == 2
        assert len(client.values) == 2
        assert all("checkpoint" not in value for value in client.values.values())

    asyncio.run(scenario())
