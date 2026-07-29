from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

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
    checkpoint_id: str, run_generation: int, created_at: datetime
) -> CheckpointRecord:
    return CheckpointRecord(
        checkpoint_id=checkpoint_id,
        tenant_id="tenant-a",
        task_id="task_12345678",
        thread_id="thread_12345678",
        run_generation=run_generation,
        graph_version="graph-v1",
        state={"current_step": "plan", "evidence_refs": ["ev://safe/1"]},
        security_context_ref="security-context://tenant-a/12345678",
        security_context_hash="sha256:" + "a" * 64,
        created_at=created_at,
    )


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
                checkpoint("cp_12345678", first.run_generation, NOW),
                first,
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
                        "cp_stale123", first.run_generation, after_expiry
                    ),
                    first,
                )
            assert caught.value.code is PersistenceErrorCode.STALE_FENCE
            await unit_of_work.checkpoints.put(
                checkpoint(
                    "cp_87654321", second.run_generation, after_expiry
                ),
                second,
            )
            await unit_of_work.commit()

        async with factory() as unit_of_work:
            latest = await unit_of_work.checkpoints.latest(
                "tenant-a", "thread_12345678"
            )
            assert latest is not None
            assert latest.checkpoint_id == "cp_87654321"
            assert latest.run_generation == second.run_generation

    asyncio.run(scenario())


def test_checkpoint_rejects_secret_shaped_fields() -> None:
    with pytest.raises(PersistenceError) as caught:
        CheckpointRecord(
            checkpoint_id="cp_secret123",
            tenant_id="tenant-a",
            task_id="task_12345678",
            thread_id="thread_12345678",
            run_generation=1,
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
