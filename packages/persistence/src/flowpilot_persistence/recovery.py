from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from .errors import PersistenceError, PersistenceErrorCode
from .models import CoordinationSignal, utc
from .ports import CoordinationPort, DataUnitOfWorkFactory


class CoordinationRebuilder:
    """Replace disposable coordination state from durable tenant facts."""

    def __init__(
        self,
        unit_of_work: DataUnitOfWorkFactory,
        coordination: CoordinationPort,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._coordination = coordination

    async def rebuild(
        self,
        tenant_ids: Iterable[str],
        *,
        now: datetime,
        limit_per_tenant: int = 1_000,
    ) -> int:
        if isinstance(tenant_ids, str):
            raise TypeError("tenant_ids must be an iterable of tenant identities")
        if limit_per_tenant < 1:
            raise ValueError("limit_per_tenant must be positive")
        normalized = utc(now, "now")
        trusted_tenants: list[str] = []
        seen_tenants: set[str] = set()
        for tenant_id in tenant_ids:
            if not isinstance(tenant_id, str) or not tenant_id:
                raise ValueError("tenant identity must be a non-empty string")
            if tenant_id in seen_tenants:
                raise ValueError("tenant inventory contains a duplicate identity")
            seen_tenants.add(tenant_id)
            trusted_tenants.append(tenant_id)
        if not trusted_tenants:
            raise ValueError("a complete trusted tenant inventory is required")

        signals_by_tenant: dict[str, list[CoordinationSignal]] = {}
        seen_tasks: set[tuple[str, str]] = set()
        for tenant_id in trusted_tenants:
            async with self._unit_of_work() as unit_of_work:
                tenant_signals = await unit_of_work.recovery.runnable_signals(
                    tenant_id,
                    now=normalized,
                    limit=limit_per_tenant,
                )
            for signal in tenant_signals:
                identity = (signal.tenant_id, signal.task_id)
                if signal.tenant_id != tenant_id or identity in seen_tasks:
                    raise PersistenceError(
                        PersistenceErrorCode.DRIVER_PROTOCOL,
                        "durable recovery signal violates its trusted identity",
                    )
                seen_tasks.add(identity)
                signals_by_tenant.setdefault(tenant_id, []).append(signal)

        rebuilt = 0
        for tenant_id in trusted_tenants:
            rebuilt += await self._coordination.rebuild_tenant(
                tenant_id,
                signals_by_tenant.get(tenant_id, ()),
            )
        return rebuilt
