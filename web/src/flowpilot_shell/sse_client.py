"""SSE consumption: frame parsing, deduplication and sequence-gap detection.

The wire format mirrors apps/api stream.py ``_sse_frame``:
``id: <event_id>`` / ``event: task.event`` / ``data: <TaskEvent JSON>`` with
``: ping`` heartbeats. Delivery is at-least-once, so the shell deduplicates
by ``event_id`` and detects missing per-task outbox sequences exactly like
``TaskEventSubscriptionService.gaps`` (the semantics are simulated here in
the adapter layer).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from .models import EventView, ShellContractError


@dataclass(frozen=True, slots=True)
class SseEvent:
    event: str
    id: str | None
    data: str


def parse_sse(chunks: Iterable[bytes]) -> Iterator[SseEvent]:
    """Parse an SSE byte stream into events, tolerating partial frames.

    Handles LF and CRLF line endings, ``: comment`` keep-alives, optional
    ``id:``/``event:`` fields and multi-line ``data:`` blocks.
    """
    buffer = bytearray()
    for chunk in chunks:
        buffer.extend(chunk)
        while True:
            split = _find_frame_end(buffer)
            if split < 0:
                break
            frame = bytes(buffer[:split])
            del buffer[: split + 2]
            event = _parse_frame(frame)
            if event is not None:
                yield event
    if buffer:
        # Trailing bytes without a blank line are an incomplete frame; a
        # healthy stream always closes a frame before EOF.
        raise ShellContractError("SSE stream ended inside a frame")


def _find_frame_end(buffer: bytearray) -> int:
    for index in range(len(buffer) - 1):
        if buffer[index] == 10:  # \n
            if buffer[index + 1] == 10:
                return index
            if (
                buffer[index + 1] == 13
                and index + 2 < len(buffer)
                and buffer[index + 2] == 10
            ):
                return index + 1
        elif buffer[index] == 13 and buffer[index + 1] == 13:
            return index
    return -1


def _parse_frame(frame: bytes) -> SseEvent | None:
    fields: list[tuple[str, str]] = []
    for raw_line in frame.splitlines():
        if not raw_line:
            continue
        try:
            text = raw_line.decode("utf-8")
        except UnicodeDecodeError:
            raise ShellContractError("SSE frame is not valid UTF-8") from None
        if text.startswith(":"):
            continue  # keep-alive comment
        if ":" in text:
            name, value = text.split(":", 1)
            fields.append((name.strip(), value.lstrip()))
        else:
            fields.append((text.strip(), ""))
    if not fields:
        return None
    event_name = "message"
    event_id: str | None = None
    data_lines: list[str] = []
    for name, value in fields:
        if name == "event":
            event_name = value
        elif name == "id":
            event_id = value
        elif name == "data":
            data_lines.append(value)
    if not data_lines:
        return None
    return SseEvent(event=event_name, id=event_id, data="\n".join(data_lines))


class TimelineReconstructor:
    """Per-task event timeline with deduplication and gap detection."""

    def __init__(self) -> None:
        self._events: dict[str, list[EventView]] = {}
        self._fingerprints: dict[str, str] = {}
        self._sequence_ids: dict[tuple[str, int], str] = {}
        self._gaps: dict[str, tuple[int, ...]] = {}

    def ingest(self, event: EventView) -> None:
        fingerprint = _event_fingerprint(event)
        prior_fingerprint = self._fingerprints.get(event.event_id)
        if prior_fingerprint is not None:
            if prior_fingerprint != fingerprint:
                raise ShellContractError(
                    "SSE event_id was reused with different content"
                )
            return  # byte-equivalent at-least-once redelivery
        sequence_key = (event.task_id, event.sequence)
        prior_event_id = self._sequence_ids.get(sequence_key)
        if prior_event_id is not None and prior_event_id != event.event_id:
            raise ShellContractError(
                "SSE task sequence was reused by a different event"
            )
        self._fingerprints[event.event_id] = fingerprint
        self._sequence_ids[sequence_key] = event.event_id
        events = self._events.setdefault(event.task_id, [])
        events.append(event)
        events.sort(key=lambda item: (item.sequence, item.occurred_at))
        self._gaps[event.task_id] = _compute_gaps(events)

    def has(self, task_id: str) -> bool:
        return task_id in self._events

    def events_for(self, task_id: str) -> tuple[EventView, ...]:
        return tuple(self._events.get(task_id, ()))

    def gaps_for(self, task_id: str) -> tuple[int, ...]:
        return self._gaps.get(task_id, ())

    def task_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._events))

    def counts(self) -> dict[str, int]:
        return {
            task_id: len(events) for task_id, events in sorted(self._events.items())
        }


def _compute_gaps(events: list[EventView]) -> tuple[int, ...]:
    sequences = sorted({event.sequence for event in events})
    if not sequences:
        return ()
    expected = set(range(1, max(sequences) + 1))
    return tuple(sorted(expected - set(sequences)))


def _event_fingerprint(event: EventView) -> str:
    value = {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "tenant_id": event.tenant_id,
        "task_id": event.task_id,
        "thread_id": event.thread_id,
        "task_version": event.task_version,
        "sequence": event.sequence,
        "trace_id": event.trace_id,
        "run_id": event.run_id,
        "producer": event.producer,
        "correlation_id": event.correlation_id,
        "data_classification": event.data_classification,
        "payload": event.payload,
        "occurred_at": event.occurred_at.isoformat(),
    }
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ShellContractError("SSE event is not JSON-safe") from exc
