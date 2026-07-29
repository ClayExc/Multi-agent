from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator, Iterable
from typing import Protocol

from .models import CoordinationSignal, format_utc


class AsyncRedisClient(Protocol):
    async def set(self, name: str, value: str) -> object: ...

    async def delete(self, *names: str) -> int: ...

    def scan_iter(self, match: str) -> AsyncIterator[str | bytes]: ...


def _segment(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


class RedisCoordinationAdapter:
    """Rebuildable scheduling hints; never task or checkpoint facts."""

    def __init__(
        self,
        client: AsyncRedisClient,
        *,
        namespace: str = "flowpilot:m0:run-signal",
    ) -> None:
        if not namespace or "*" in namespace:
            raise ValueError("coordination namespace must be a fixed key prefix")
        self._client = client
        self._namespace = namespace

    def key(self, tenant_id: str, task_id: str) -> str:
        return (
            f"{self._namespace}:tenant:{_segment(tenant_id)}:"
            f"task:{_segment(task_id)}"
        )

    async def signal(self, signal: CoordinationSignal) -> None:
        payload = json.dumps(
            {
                "task_id": signal.task_id,
                "run_generation": signal.run_generation,
                "available_at": format_utc(signal.available_at),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        await self._client.set(self.key(signal.tenant_id, signal.task_id), payload)

    async def remove(self, tenant_id: str, task_id: str) -> None:
        await self._client.delete(self.key(tenant_id, task_id))

    async def clear(self) -> None:
        keys: list[str] = []
        async for key in self._client.scan_iter(match=f"{self._namespace}:*"):
            keys.append(key.decode("utf-8") if isinstance(key, bytes) else key)
        if keys:
            await self._client.delete(*keys)

    async def rebuild(self, signals: Iterable[CoordinationSignal]) -> int:
        await self.clear()
        count = 0
        seen: set[tuple[str, str]] = set()
        for signal in signals:
            identity = (signal.tenant_id, signal.task_id)
            if identity in seen:
                raise ValueError("rebuild source contains a duplicate task signal")
            await self.signal(signal)
            seen.add(identity)
            count += 1
        return count


class MemoryRedisClient:
    """Tiny Redis protocol fixture used to prove loss and rebuild semantics."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, name: str, value: str) -> object:
        self.values[name] = value
        return True

    async def delete(self, *names: str) -> int:
        removed = 0
        for name in names:
            if name in self.values:
                removed += 1
                del self.values[name]
        return removed

    async def scan_iter(self, match: str) -> AsyncIterator[str | bytes]:
        prefix = match.removesuffix("*")
        for key in tuple(self.values):
            if key.startswith(prefix):
                yield key
