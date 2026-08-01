from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from .errors import GraphError, GraphErrorCode


class GraphStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_USER = "WAITING_USER"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    RETRY_PENDING = "RETRY_PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class GraphNode(StrEnum):
    START = "start"
    INTAKE = "intake"
    BUILD_CONTEXT = "build_context"
    KNOWLEDGE_READ = "knowledge_read"
    SERVICE_READ = "service_read"
    RESPOND = "respond"
    RUN_AGENT = "run_agent"
    INTERRUPT = "interrupt"
    FINALIZE = "finalize"


_TRANSITIONS: dict[GraphStatus, frozenset[GraphStatus]] = {
    GraphStatus.QUEUED: frozenset({GraphStatus.RUNNING}),
    GraphStatus.RUNNING: frozenset(
        {
            GraphStatus.WAITING_USER,
            GraphStatus.WAITING_APPROVAL,
            GraphStatus.RETRY_PENDING,
            GraphStatus.COMPLETED,
            GraphStatus.FAILED,
        }
    ),
    GraphStatus.WAITING_USER: frozenset({GraphStatus.RUNNING, GraphStatus.FAILED}),
    GraphStatus.WAITING_APPROVAL: frozenset(
        {GraphStatus.RUNNING, GraphStatus.FAILED}
    ),
    GraphStatus.RETRY_PENDING: frozenset(
        {GraphStatus.RUNNING, GraphStatus.FAILED}
    ),
    GraphStatus.COMPLETED: frozenset(),
    GraphStatus.FAILED: frozenset(),
}

_FORBIDDEN_STATE_KEYS = {
    "api_key",
    "authorization",
    "bearer_token",
    "cookie",
    "credential",
    "credentials",
    "private_key",
    "provider_session",
    "session_ref",
    "acl",
    "acl_subjects",
    "answer_body",
    "original_message",
    "raw_document",
    "request_body",
    "tool_payload",
}


@dataclass(frozen=True, slots=True)
class GraphState:
    task_id: str
    tenant_id: str
    command_id: str
    command_digest: str
    run_id: str
    run_generation: int
    graph_version: str
    status: GraphStatus
    node: GraphNode
    security_context_ref: str
    security_context_hash: str
    purpose: str
    checkpoint_sequence: int = 0
    attempt_count: int = 0
    context_id: str | None = None
    result_ref: str | None = None
    failure_code: str | None = None
    pending_reason: str | None = None
    tool_proposal_refs: tuple[str, ...] = ()
    observation_ref: str | None = None
    knowledge_call_count: int = 0
    citation_count: int = 0
    reference_refs: tuple[str, ...] = ()
    service_read_skipped: bool = False

    def __post_init__(self) -> None:
        if self.run_generation < 1 or self.checkpoint_sequence < 0:
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "graph generation and checkpoint sequence must be valid",
            )
        if self.attempt_count < 0:
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "graph attempt count cannot be negative",
            )
        if self.knowledge_call_count < 0 or self.citation_count < 0:
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "graph knowledge counters cannot be negative",
            )
        if len(self.tool_proposal_refs) != len(set(self.tool_proposal_refs)):
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "tool proposal references must be unique",
            )
        if len(self.reference_refs) != len(set(self.reference_refs)):
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "graph knowledge references must be unique",
            )
        if self.citation_count != len(self.reference_refs) and self.reference_refs:
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "graph citation count must match its minimal references",
            )
        if (
            self.status in {GraphStatus.COMPLETED, GraphStatus.FAILED}
            and self.node is not GraphNode.FINALIZE
        ):
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "terminal graph state must be at the finalize node",
            )
        if self.status is GraphStatus.COMPLETED and self.result_ref is None:
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "completed graph state requires a result reference",
            )
        if self.status is GraphStatus.FAILED and self.failure_code is None:
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "failed graph state requires a stable failure code",
            )

    def transition(
        self,
        status: GraphStatus,
        *,
        node: GraphNode,
        **changes: Any,
    ) -> GraphState:
        if status is not self.status and status not in _TRANSITIONS[self.status]:
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                f"invalid graph transition {self.status.value}->{status.value}",
            )
        return replace(self, status=status, node=node, **changes)

    def to_checkpoint(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "task_id": self.task_id,
            "tenant_id": self.tenant_id,
            "command_id": self.command_id,
            "command_digest": self.command_digest,
            "run_id": self.run_id,
            "run_generation": self.run_generation,
            "graph_version": self.graph_version,
            "status": self.status.value,
            "node": self.node.value,
            "security_context_ref": self.security_context_ref,
            "security_context_hash": self.security_context_hash,
            "purpose": self.purpose,
            "checkpoint_sequence": self.checkpoint_sequence,
            "attempt_count": self.attempt_count,
            "context_id": self.context_id,
            "result_ref": self.result_ref,
            "failure_code": self.failure_code,
            "pending_reason": self.pending_reason,
            "tool_proposal_refs": list(self.tool_proposal_refs),
            "observation_ref": self.observation_ref,
            "knowledge_call_count": self.knowledge_call_count,
            "citation_count": self.citation_count,
            "reference_refs": list(self.reference_refs),
            "service_read_skipped": self.service_read_skipped,
        }
        assert_checkpoint_safe(value)
        return value

    @classmethod
    def from_checkpoint(cls, value: Mapping[str, Any]) -> GraphState:
        assert_checkpoint_safe(value)
        try:
            return cls(
                task_id=str(value["task_id"]),
                tenant_id=str(value["tenant_id"]),
                command_id=str(value["command_id"]),
                command_digest=str(value["command_digest"]),
                run_id=str(value["run_id"]),
                run_generation=int(value["run_generation"]),
                graph_version=str(value["graph_version"]),
                status=GraphStatus(str(value["status"])),
                node=GraphNode(str(value["node"])),
                security_context_ref=str(value["security_context_ref"]),
                security_context_hash=str(value["security_context_hash"]),
                purpose=str(value["purpose"]),
                checkpoint_sequence=int(value["checkpoint_sequence"]),
                attempt_count=int(value["attempt_count"]),
                context_id=(
                    str(value["context_id"])
                    if value.get("context_id") is not None
                    else None
                ),
                result_ref=(
                    str(value["result_ref"])
                    if value.get("result_ref") is not None
                    else None
                ),
                failure_code=(
                    str(value["failure_code"])
                    if value.get("failure_code") is not None
                    else None
                ),
                pending_reason=(
                    str(value["pending_reason"])
                    if value.get("pending_reason") is not None
                    else None
                ),
                tool_proposal_refs=tuple(
                    str(item) for item in value.get("tool_proposal_refs", ())
                ),
                observation_ref=(
                    str(value["observation_ref"])
                    if value.get("observation_ref") is not None
                    else None
                ),
                knowledge_call_count=int(value.get("knowledge_call_count", 0)),
                citation_count=int(value.get("citation_count", 0)),
                reference_refs=tuple(
                    str(item) for item in value.get("reference_refs", ())
                ),
                service_read_skipped=(
                    value.get("service_read_skipped", False) is True
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "checkpoint does not match the graph state contract",
            ) from exc


def assert_checkpoint_safe(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() in _FORBIDDEN_STATE_KEYS:
                raise GraphError(
                    GraphErrorCode.STATE_INVALID,
                    "checkpoint contains a forbidden sensitive or provider field",
                )
            assert_checkpoint_safe(child)
    elif isinstance(value, (tuple, list)):
        for child in value:
            assert_checkpoint_safe(child)
