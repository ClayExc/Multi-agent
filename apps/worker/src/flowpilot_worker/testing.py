from __future__ import annotations

from collections import deque

from .queue import ExecutionEnvelope


class InMemoryExecutionQueue:
    def __init__(self) -> None:
        self._envelopes: dict[tuple[str, str], ExecutionEnvelope] = {}
        self._pending: deque[tuple[str, str]] = deque()
        self._inflight: dict[tuple[str, str], str] = {}
        self._acknowledged: set[tuple[str, str]] = set()

    async def enqueue(self, envelope: ExecutionEnvelope) -> bool:
        key = envelope.key
        if key in self._envelopes:
            return False
        self._envelopes[key] = envelope
        self._pending.append(key)
        return True

    async def dequeue(self, worker_id: str) -> ExecutionEnvelope | None:
        if not self._pending:
            return None
        key = self._pending.popleft()
        self._inflight[key] = worker_id
        return self._envelopes[key]

    async def acknowledge(
        self,
        worker_id: str,
        envelope: ExecutionEnvelope,
    ) -> None:
        self._assert_owner(worker_id, envelope)
        self._inflight.pop(envelope.key)
        self._acknowledged.add(envelope.key)

    async def retry(
        self,
        worker_id: str,
        envelope: ExecutionEnvelope,
    ) -> None:
        self._assert_owner(worker_id, envelope)
        self._inflight.pop(envelope.key)
        self._pending.append(envelope.key)

    def recover_inflight(self, worker_id: str) -> int:
        recovered = [
            key for key, owner in self._inflight.items() if owner == worker_id
        ]
        for key in recovered:
            del self._inflight[key]
            self._pending.appendleft(key)
        return len(recovered)

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def acknowledged_count(self) -> int:
        return len(self._acknowledged)

    def _assert_owner(
        self,
        worker_id: str,
        envelope: ExecutionEnvelope,
    ) -> None:
        if self._inflight.get(envelope.key) != worker_id:
            raise RuntimeError("worker does not own the in-flight envelope")
