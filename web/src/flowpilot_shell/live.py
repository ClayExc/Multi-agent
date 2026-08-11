"""Authoritative API/SSE convergence for the real Web mode."""

from __future__ import annotations

import json
from dataclasses import dataclass

from .api_client import ApiClient
from .models import EventView, ShellContractError, TaskView
from .sse_client import SseEvent
from .store import ShellStore


@dataclass(frozen=True, slots=True)
class LiveUpdate:
    task_id: str
    event_id: str
    gaps: tuple[int, ...]
    projection_refreshed: bool


class LiveSession:
    """Converge untrusted stream notifications onto authoritative Task reads."""

    def __init__(
        self,
        api: ApiClient,
        *,
        store: ShellStore | None = None,
    ) -> None:
        self._api = api
        self.store = store or ShellStore()
        self._last_event_id: str | None = None

    @property
    def last_event_id(self) -> str | None:
        return self._last_event_id

    def reconnect_headers(self) -> dict[str, str]:
        if self._last_event_id is None:
            return {}
        return {"Last-Event-ID": self._last_event_id}

    def refresh(self, task_id: str) -> TaskView:
        task = self._api.get_task(task_id)
        self.store.rebuild_from_projection(task)
        return task

    def ingest(self, frame: SseEvent) -> LiveUpdate:
        if frame.event != "task.event" or not frame.id:
            raise ShellContractError("live stream frame is not a task.event")
        try:
            decoded: object = json.loads(frame.data)
        except json.JSONDecodeError as exc:
            raise ShellContractError("live stream data is not JSON") from exc
        if not isinstance(decoded, dict):
            raise ShellContractError("live stream event must be an object")
        event = EventView.from_mapping(decoded)
        if frame.id != event.event_id:
            raise ShellContractError("SSE id differs from event_id")
        existing = next(
            (
                item
                for item in self.store.timeline_events(event.task_id)
                if item.event_id == event.event_id
            ),
            None,
        )
        if existing is not None:
            self.store.apply_event(event)
            self._last_event_id = event.event_id
            return LiveUpdate(
                task_id=event.task_id,
                event_id=event.event_id,
                gaps=self.store.timeline_gaps(event.task_id),
                projection_refreshed=False,
            )
        task = self._api.get_task(event.task_id)
        if event.tenant_id != task.tenant_id:
            raise ShellContractError(
                "SSE tenant differs from authoritative Task projection"
            )
        _task_id, gaps = self.store.apply_event(event)
        self.store.rebuild_from_projection(task)
        self._last_event_id = event.event_id
        return LiveUpdate(
            task_id=event.task_id,
            event_id=event.event_id,
            gaps=gaps,
            projection_refreshed=True,
        )
