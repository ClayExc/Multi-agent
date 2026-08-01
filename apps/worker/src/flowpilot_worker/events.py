"""Publish task lifecycle events into the transactional outbox.

The publisher runs inside the worker's existing DataUnitOfWork, so the
outbox append commits or rolls back together with the checkpoint write
(transactional outbox pattern). Each graph checkpoint save maps to at most
one task-event.v1 event; the outbox sequence is the checkpoint sequence so
replays are deterministic and idempotent.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Mapping

from flowpilot_domain import TaskStatus
from flowpilot_graph import GraphState, GraphStatus
from flowpilot_persistence import DataUnitOfWork, OutboxEvent

Clock = Callable[[], datetime]

_TASK_REF = "task://{task_id}"
_INPUT_PROMPT_REF = "task://{task_id}/user-input/{request_id}"


def _to_task_status(status: GraphStatus) -> TaskStatus:
    return {
        GraphStatus.QUEUED: TaskStatus.RECEIVED,
        GraphStatus.RUNNING: TaskStatus.RUNNING,
        GraphStatus.WAITING_USER: TaskStatus.WAITING_USER,
        GraphStatus.WAITING_APPROVAL: TaskStatus.WAITING_APPROVAL,
        GraphStatus.RETRY_PENDING: TaskStatus.RUNNABLE,
        GraphStatus.COMPLETED: TaskStatus.COMPLETED,
        GraphStatus.FAILED: TaskStatus.FAILED,
    }[status]


class TaskEventPublisher:
    """Map graph checkpoint transitions onto task-event.v1 outbox events."""

    def __init__(
        self,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))

    async def publish(
        self,
        unit_of_work: DataUnitOfWork,
        *,
        tenant_id: str,
        task_id: str,
        thread_id: str,
        previous: GraphState | None,
        state: GraphState,
    ) -> None:
        """Append the event for this transition (at most one per save).

        The caller owns the transaction: the append only becomes durable
        when the surrounding unit of work commits.
        """
        event = self._build_event(
            tenant_id=tenant_id,
            task_id=task_id,
            thread_id=thread_id,
            previous=previous,
            state=state,
        )
        if event is not None:
            await unit_of_work.outbox.append(event)

    def _build_event(
        self,
        *,
        tenant_id: str,
        task_id: str,
        thread_id: str,
        previous: GraphState | None,
        state: GraphState,
    ) -> OutboxEvent | None:
        event_type, payload = self._map_transition(previous, state)
        if event_type is None or payload is None:
            return None
        occurred_at = self._utc(self._clock(), "clock")
        sequence = state.checkpoint_sequence
        if sequence < 1:
            raise ValueError(
                "checkpoint sequence must be positive for an outbox event"
            )
        return OutboxEvent(
            event_id=self._event_id(task_id, sequence),
            tenant_id=tenant_id,
            aggregate_type="task",
            aggregate_id=task_id,
            sequence=sequence,
            event_type=event_type,
            payload=payload,
            occurred_at=occurred_at,
            available_at=occurred_at,
        )

    def _map_transition(
        self,
        previous: GraphState | None,
        state: GraphState,
    ) -> tuple[str | None, Mapping[str, Any] | None]:
        if previous is None:
            return (
                "task.created.v1",
                {
                    "status": TaskStatus.RECEIVED.value,
                    "task_ref": _TASK_REF.format(task_id=state.task_id),
                },
            )
        previous_status = _to_task_status(previous.status)
        if state.status is not previous.status:
            return self._map_status_change(previous_status, state)
        # Status-unchanged saves announce an agent attempt when the graph
        # moves from BUILD_CONTEXT into RUN_AGENT with an incremented
        # attempt counter (the fresh intake save and every retry resume).
        if (
            state.status is GraphStatus.RUNNING
            and previous.status is GraphStatus.RUNNING
            and state.attempt_count > previous.attempt_count
        ):
            if previous.attempt_count == 0:
                return (
                    "task.status.changed.v1",
                    {
                        "from": TaskStatus.RECEIVED.value,
                        "to": TaskStatus.RUNNING.value,
                        "reason_code": "agent_attempt",
                    },
                )
            return (
                "task.status.changed.v1",
                {
                    "from": TaskStatus.RUNNING.value,
                    "to": TaskStatus.RUNNING.value,
                    "reason_code": "attempt",
                },
            )
        return None, None

    def _map_status_change(
        self,
        previous_status: TaskStatus,
        state: GraphState,
    ) -> tuple[str, Mapping[str, Any]]:
        if state.status is GraphStatus.RUNNING:
            return (
                "task.status.changed.v1",
                {
                    "from": previous_status.value,
                    "to": TaskStatus.RUNNING.value,
                    "reason_code": "resume",
                },
            )
        if state.status is GraphStatus.WAITING_USER:
            request_id = self._request_id(state)
            if request_id is None:
                return (
                    "task.status.changed.v1",
                    {
                        "from": previous_status.value,
                        "to": TaskStatus.WAITING_USER.value,
                        "reason_code": "user_input",
                    },
                )
            return (
                "task.input.required.v1",
                {
                    "request_id": request_id,
                    "prompt_ref": _INPUT_PROMPT_REF.format(
                        task_id=state.task_id,
                        request_id=request_id,
                    ),
                    "missing_fields": ["user_input"],
                },
            )
        if state.status is GraphStatus.WAITING_APPROVAL:
            return (
                "task.status.changed.v1",
                {
                    "from": previous_status.value,
                    "to": TaskStatus.WAITING_APPROVAL.value,
                    "reason_code": "approval",
                },
            )
        if state.status is GraphStatus.RETRY_PENDING:
            return (
                "task.status.changed.v1",
                {
                    "from": previous_status.value,
                    "to": TaskStatus.RUNNABLE.value,
                    "reason_code": "retry_pending",
                },
            )
        if state.status is GraphStatus.COMPLETED:
            if state.result_ref is None:
                raise ValueError(
                    "completed graph state requires a result reference"
                )
            return (
                "task.completed.v1",
                {"result_ref": state.result_ref},
            )
        if state.status is GraphStatus.FAILED:
            if state.failure_code is None:
                raise ValueError(
                    "failed graph state requires a stable failure code"
                )
            return (
                "task.failed.v1",
                {
                    "error_code": state.failure_code,
                    "retryable": False,
                },
            )
        raise ValueError(
            f"graph status {state.status.value} is not a task lifecycle status"
        )

    @staticmethod
    def _request_id(state: GraphState) -> str | None:
        reason = state.pending_reason
        if not isinstance(reason, str) or not reason.startswith("user_input:"):
            return None
        request_id = reason[len("user_input:") :]
        if not request_id:
            return None
        return request_id

    @staticmethod
    def _event_id(task_id: str, sequence: int) -> str:
        seed = f"{task_id}:{sequence}".encode()
        return "evt_" + hashlib.sha256(seed).hexdigest()[:16]

    @staticmethod
    def _utc(value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} must be timezone-aware")
        return value.astimezone(UTC)
