"""In-memory SSE transport for the task event stream.

Fan-out is per tenant and per connection queue. A bounded per-tenant replay
buffer lets a reconnecting subscriber catch up on events that were emitted
while it was disconnected; the client deduplicates by the SSE event id.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque

from flowpilot_application import EventStreamPort, TaskEventEnvelope


class InMemoryEventStream(EventStreamPort):
    def __init__(self, *, replay_buffer_size: int = 256) -> None:
        if replay_buffer_size < 1:
            raise ValueError("replay_buffer_size must be positive")
        self._replay_buffer_size = replay_buffer_size
        self._subscribers: dict[str, set[asyncio.Queue[TaskEventEnvelope]]] = (
            defaultdict(set)
        )
        self._replay: dict[str, deque[TaskEventEnvelope]] = defaultdict(
            lambda: deque(maxlen=replay_buffer_size)
        )

    def subscribe(
        self, tenant_id: str
    ) -> asyncio.Queue[TaskEventEnvelope]:
        """Register a connection queue, replaying buffered events first."""
        _require_tenant_route(tenant_id)
        buffered = tuple(self._replay[tenant_id])
        for event in buffered:
            _assert_event_route(tenant_id, event)
        queue: asyncio.Queue[TaskEventEnvelope] = asyncio.Queue()
        for event in buffered:
            queue.put_nowait(event)
        self._subscribers[tenant_id].add(queue)
        return queue

    def unsubscribe(
        self, tenant_id: str, queue: asyncio.Queue[TaskEventEnvelope]
    ) -> None:
        _require_tenant_route(tenant_id)
        subscribers = self._subscribers.get(tenant_id)
        if subscribers is None:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._subscribers.pop(tenant_id, None)

    async def emit(self, tenant_id: str, event: TaskEventEnvelope) -> None:
        _require_tenant_route(tenant_id)
        _assert_event_route(tenant_id, event)
        self._replay[tenant_id].append(event)
        for queue in tuple(self._subscribers.get(tenant_id, ())):
            queue.put_nowait(event)


def _require_tenant_route(tenant_id: str) -> None:
    if not isinstance(tenant_id, str) or not tenant_id or len(tenant_id) > 128:
        raise ValueError("stream tenant must be a bounded non-empty string")


def _assert_event_route(tenant_id: str, event: TaskEventEnvelope) -> None:
    if event.tenant_id != tenant_id:
        raise ValueError("event tenant does not match the stream route")
    event.assert_valid()
