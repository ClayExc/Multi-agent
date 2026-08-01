"""In-memory shell store: projections, timelines, cards and artifacts.

The store is session-scoped and never persisted (the shell does not save
business facts). The authoritative terminal state is the Task projection
fetched through the API adapter; events only build the timeline history.
After a reconnect/rebuild the shell converges by re-fetching the projection
and re-ingesting the event stream (TaskEventSubscriptionService gap
semantics simulated in the adapter).
"""

from __future__ import annotations

from .models import (
    ApprovalView,
    EventView,
    PlannedActionView,
    ResultArtifactView,
    ShellContractError,
    TaskView,
)
from .sse_client import TimelineReconstructor


class ShellStore:
    def __init__(self) -> None:
        self._tasks: dict[str, TaskView] = {}
        self._timeline = TimelineReconstructor()
        self._approvals: dict[str, ApprovalView] = {}
        self._actions: dict[str, PlannedActionView] = {}
        self._artifacts: dict[str, ResultArtifactView] = {}

    # -- ingestion -----------------------------------------------------

    def register_task(self, task: TaskView) -> None:
        self._tasks[task.task_id] = task

    def apply_event(self, event: EventView) -> tuple[str, tuple[int, ...]]:
        """Apply one event; returns (task_id, remaining gaps for that task)."""
        self._timeline.ingest(event)
        return event.task_id, self._timeline.gaps_for(event.task_id)

    def register_approval(self, approval: ApprovalView) -> None:
        self._approvals[approval.approval_id] = approval

    def register_action(self, action: PlannedActionView) -> None:
        self._actions[action.action_id] = action

    def register_artifact(self, artifact: ResultArtifactView) -> None:
        self._artifacts[artifact.result_ref] = artifact

    # -- convergence / recovery ----------------------------------------

    def rebuild_from_projection(self, task: TaskView) -> None:
        """Restore the authoritative state after reconnect (recovery entry).

        The projection replaces the task facts; the timeline keeps its event
        history (gaps remain visible until the stream fills them).
        """
        self._tasks[task.task_id] = task

    # -- reads ----------------------------------------------------------

    def task(self, task_id: str) -> TaskView | None:
        return self._tasks.get(task_id)

    def tasks(self) -> tuple[TaskView, ...]:
        return tuple(sorted(self._tasks.values(), key=lambda t: t.created_at))

    def timeline_events(self, task_id: str) -> tuple[EventView, ...]:
        return self._timeline.events_for(task_id)

    def timeline_gaps(self, task_id: str) -> tuple[int, ...]:
        return self._timeline.gaps_for(task_id)

    def approvals_for_task(self, task_id: str) -> tuple[ApprovalView, ...]:
        return tuple(
            sorted(
                (
                    approval
                    for approval in self._approvals.values()
                    if approval.task_id == task_id
                ),
                key=lambda approval: approval.requested_at,
            )
        )

    def actions_for_task(self, task_id: str) -> tuple[PlannedActionView, ...]:
        return tuple(
            sorted(
                (
                    action
                    for action in self._actions.values()
                    if action.task_id == task_id
                ),
                key=lambda action: action.action_id,
            )
        )

    def approval_card(self, approval_id: str) -> tuple[ApprovalView, PlannedActionView]:
        """Join an approval with its planned action (M5-1 isomorphic card input)."""
        approval = self._approvals.get(approval_id)
        if approval is None:
            raise ShellContractError(f"unknown approval {approval_id}")
        action = self._actions.get(approval.action_id)
        if action is None:
            raise ShellContractError(
                f"approval {approval_id} references unknown action {approval.action_id}"
            )
        return approval, action

    def artifact(self, result_ref: str) -> ResultArtifactView | None:
        return self._artifacts.get(result_ref)

    # -- evidence --------------------------------------------------------

    def snapshot(self) -> dict[str, object]:
        """Serializable evidence snapshot for demo artifacts."""
        return {
            "tasks": [task.task_id for task in self.tasks()],
            "timeline_counts": self._timeline.counts(),
            "gaps": {
                task_id: list(self._timeline.gaps_for(task_id))
                for task_id in self._timeline.task_ids()
                if self._timeline.gaps_for(task_id)
            },
            "approvals": sorted(self._approvals),
            "planned_actions": sorted(self._actions),
            "artifacts": sorted(self._artifacts),
        }
