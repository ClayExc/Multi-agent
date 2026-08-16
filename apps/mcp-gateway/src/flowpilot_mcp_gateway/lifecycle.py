from __future__ import annotations

from collections import Counter
from typing import Any

from flowpilot_policy import PolicyErrorCode
from flowpilot_security import (
    ContentSurface,
    SecurityErrorCode,
    assert_content_safe,
    assert_safe_projection,
)
from flowpilot_tool_contracts import ToolContractErrorCode

from .errors import GatewayReason
from .models import (
    GatewayInvocation,
    LifecycleEvent,
    LifecycleOutcome,
    LifecycleStage,
)
from .signals import SignalSinkPort

LIFECYCLE_VERSION = "flowpilot.gateway-lifecycle.m0.v1"
COMPONENT_VERSION = "flowpilot-mcp-gateway/0.1.0"
STABLE_REASON_CODES = frozenset(
    {item.value for item in GatewayReason}
    | {item.value for item in PolicyErrorCode}
    | {item.value for item in SecurityErrorCode}
    | {item.value for item in ToolContractErrorCode}
)

DEBUG_PROJECTION_KEYS = frozenset(
    {
        "lifecycle_version",
        "request_id",
        "trace_id",
        "task_id",
        "correlation_id",
        "tool_name",
        "tool_schema_hash",
        "operation",
        "policy_decision_id",
        "approval_id",
        "execution_id",
        "result_status",
        "reason_code",
        "stages",
    }
)


class LifecycleRecorder:
    def __init__(
        self,
        *,
        invocation: GatewayInvocation,
        sink: SignalSinkPort,
        clock: Any,
    ) -> None:
        self._invocation = invocation
        self._sink = sink
        self._clock = clock
        self._events: list[LifecycleEvent] = []

    async def record(
        self,
        stage: LifecycleStage,
        outcome: LifecycleOutcome,
        reason_code: str,
        *,
        evidence_refs: tuple[str, ...] = (),
    ) -> None:
        if reason_code not in STABLE_REASON_CODES:
            raise ValueError("lifecycle reason code is not registered")
        event = LifecycleEvent(
            lifecycle_version=LIFECYCLE_VERSION,
            sequence=len(self._events) + 1,
            request_id=self._invocation.request.request_id,
            trace_id=self._invocation.request.trace_id,
            task_id=self._invocation.request.planned_action.task_id,
            correlation_id=self._invocation.correlation_id,
            stage=stage,
            outcome=outcome,
            reason_code=reason_code,
            component_version=COMPONENT_VERSION,
            recorded_at=self._clock(),
            evidence_refs=evidence_refs,
        )
        event_mapping = event.to_mapping()
        assert_content_safe(
            event_mapping,
            surface=ContentSurface.SIGNAL,
            field="lifecycle",
        )
        assert_safe_projection(event_mapping, field="lifecycle")
        self._events.append(event)
        try:
            await self._sink.emit_trace(event)
        except Exception:
            # Trace is diagnostic and must never become an authorization input.
            return

    @property
    def events(self) -> tuple[LifecycleEvent, ...]:
        return tuple(self._events)

    def metrics(self) -> dict[str, int]:
        counts = Counter(
            f"{event.stage.value}.{event.outcome.value}"
            for event in self._events
        )
        return dict(sorted(counts.items()))

    def debug_projection(
        self,
        *,
        execution_id: str,
        result_status: str,
        reason_code: str,
    ) -> dict[str, Any]:
        request = self._invocation.request
        projection = {
            "lifecycle_version": LIFECYCLE_VERSION,
            "request_id": request.request_id,
            "trace_id": request.trace_id,
            "task_id": request.planned_action.task_id,
            "correlation_id": self._invocation.correlation_id,
            "tool_name": request.planned_action.tool.name,
            "tool_schema_hash": request.planned_action.tool.schema_hash,
            "operation": request.planned_action.tool.operation.value,
            "policy_decision_id": request.policy_decision_id,
            "approval_id": request.approval_id,
            "execution_id": execution_id,
            "result_status": result_status,
            "reason_code": reason_code,
            "stages": [
                {
                    "sequence": event.sequence,
                    "stage": event.stage.value,
                    "outcome": event.outcome.value,
                    "reason_code": event.reason_code,
                }
                for event in self._events
            ],
        }
        if set(projection) != DEBUG_PROJECTION_KEYS:
            raise AssertionError("debug projection whitelist drifted")
        assert_content_safe(
            projection,
            surface=ContentSurface.SIGNAL,
            field="debug_projection",
        )
        assert_safe_projection(projection, field="debug_projection")
        return projection
