from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from flowpilot_graph import CheckpointPort, GraphExecutionPort
from flowpilot_persistence import CoordinationRebuilder, DataUnitOfWorkFactory

from .events import TaskEventPublisher
from .persistence import (
    PersistenceCheckpointAdapter,
    PersistenceExecutionGuard,
    PersistenceLeaseAdapter,
    PersistenceRuntimeConfig,
    TrustedTenantInventory,
)
from .queue import ExecutionQueuePort
from .worker import RuntimeWorker, WorkerRun


class DurableGraphFactory(Protocol):
    def __call__(
        self,
        *,
        checkpoints: CheckpointPort,
        control_checkpointer: object,
    ) -> GraphExecutionPort: ...


class DurableCoordinationRecovery:
    """Rebuild disposable coordination state from tenant-scoped durable facts."""

    def __init__(
        self,
        rebuilder: CoordinationRebuilder,
        tenants: TrustedTenantInventory,
        *,
        clock: Callable[[], datetime] | None = None,
        limit_per_tenant: int = 1_000,
    ) -> None:
        if limit_per_tenant < 1:
            raise ValueError("limit_per_tenant must be positive")
        self._rebuilder = rebuilder
        self._tenants = tenants
        self._clock = clock or (lambda: datetime.now(UTC))
        self._limit_per_tenant = limit_per_tenant

    async def rebuild(self) -> int:
        observed_at = self._clock()
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("clock must be timezone-aware")
        return await self._rebuilder.rebuild(
            self._tenants.tenant_ids,
            now=observed_at.astimezone(UTC),
            limit_per_tenant=self._limit_per_tenant,
        )


class DurableRuntime:
    """Process-local entry that rebuilds coordination before consuming work."""

    def __init__(
        self,
        worker: RuntimeWorker,
        recovery: DurableCoordinationRecovery,
    ) -> None:
        self._worker = worker
        self._recovery = recovery
        self._started = False
        self._rebuilt_signal_count: int | None = None

    @property
    def rebuilt_signal_count(self) -> int | None:
        return self._rebuilt_signal_count

    async def start(self) -> int:
        if not self._started:
            self._rebuilt_signal_count = await self._recovery.rebuild()
            self._started = True
        assert self._rebuilt_signal_count is not None
        return self._rebuilt_signal_count

    async def run_once(self) -> WorkerRun:
        await self.start()
        return await self._worker.run_once()


def build_durable_runtime(
    *,
    worker_id: str,
    queue: ExecutionQueuePort,
    unit_of_work: DataUnitOfWorkFactory,
    coordination_rebuilder: CoordinationRebuilder,
    tenants: TrustedTenantInventory,
    graph_factory: DurableGraphFactory,
    control_checkpointer: object,
    runtime_config: PersistenceRuntimeConfig | None = None,
    clock: Callable[[], datetime] | None = None,
    run_id_factory: Callable[[], str] | None = None,
    event_publisher: TaskEventPublisher | None = None,
) -> DurableRuntime:
    """Assemble a durable worker without an implicit process-memory checkpointer."""

    if control_checkpointer is None:
        raise ValueError("a control checkpointer must be explicitly configured")
    checkpoints = PersistenceCheckpointAdapter(
        unit_of_work,
        clock=clock,
        event_publisher=event_publisher,
    )
    leases = PersistenceLeaseAdapter(
        unit_of_work,
        config=runtime_config,
        clock=clock,
    )
    graph = graph_factory(
        checkpoints=checkpoints,
        control_checkpointer=control_checkpointer,
    )
    worker = RuntimeWorker(
        worker_id=worker_id,
        queue=queue,
        leases=leases,
        graph=graph,
        execution_guard=PersistenceExecutionGuard(unit_of_work, tenants),
        run_id_factory=run_id_factory,
    )
    recovery = DurableCoordinationRecovery(
        coordination_rebuilder,
        tenants,
        clock=clock,
    )
    return DurableRuntime(worker, recovery)
