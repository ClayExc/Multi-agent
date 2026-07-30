from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from flowpilot_security import AuthenticatedWorkload
from flowpilot_tool_contracts import ToolRequest, ToolResult

_THREAD = re.compile(r"^thread_[A-Za-z0-9_-]{8,128}$")
_RUN = re.compile(r"^run_[A-Za-z0-9_-]{8,128}$")


class LifecycleStage(StrEnum):
    INGRESS = "ingress"
    IDENTITY = "identity"
    REGISTRY = "registry"
    POLICY = "policy"
    APPROVAL = "approval"
    LEDGER = "ledger"
    UPSTREAM = "upstream"
    READBACK = "readback"
    RESULT = "result"
    AUDIT = "audit"
    SECURITY = "security"
    RECONCILIATION = "reconciliation"


class LifecycleOutcome(StrEnum):
    STARTED = "started"
    PASSED = "passed"
    REJECTED = "rejected"
    SKIPPED = "skipped"
    REPLAYED = "replayed"
    UNKNOWN = "unknown"
    VERIFIED = "verified"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class GatewayInvocation:
    request: ToolRequest
    workload: AuthenticatedWorkload
    thread_id: str
    run_id: str | None
    correlation_id: str

    def __post_init__(self) -> None:
        if _THREAD.fullmatch(self.thread_id) is None:
            raise ValueError("thread_id must be a public v1 identifier")
        if self.run_id is not None and _RUN.fullmatch(self.run_id) is None:
            raise ValueError("run_id must be a public v1 identifier")
        if not self.correlation_id or len(self.correlation_id) > 128:
            raise ValueError("correlation_id must contain 1..128 characters")


@dataclass(frozen=True, slots=True)
class LifecycleEvent:
    lifecycle_version: str
    sequence: int
    request_id: str
    trace_id: str
    task_id: str
    correlation_id: str
    stage: LifecycleStage
    outcome: LifecycleOutcome
    reason_code: str
    component_version: str
    recorded_at: datetime
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("lifecycle sequence must be positive")
        if self.recorded_at.tzinfo is None or (
            self.recorded_at.utcoffset() is None
        ):
            raise ValueError("lifecycle timestamp must be timezone-aware")
        object.__setattr__(
            self, "recorded_at", self.recorded_at.astimezone(UTC)
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "lifecycle_version": self.lifecycle_version,
            "sequence": self.sequence,
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "correlation_id": self.correlation_id,
            "stage": self.stage.value,
            "outcome": self.outcome.value,
            "reason_code": self.reason_code,
            "component_version": self.component_version,
            "recorded_at": self.recorded_at.isoformat().replace("+00:00", "Z"),
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True, slots=True)
class GatewayExecution:
    result: ToolResult
    lifecycle: tuple[LifecycleEvent, ...]
    debug_projection: Mapping[str, Any]
    stage_metrics: Mapping[str, int]
