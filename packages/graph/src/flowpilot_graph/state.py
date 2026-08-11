from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from flowpilot_context import LayeredSummary

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
    "access_token",
    "api_key",
    "authorization",
    "bearer_token",
    "cookie",
    "client_secret",
    "credential",
    "credentials",
    "private_key",
    "password",
    "provider_session",
    "session_ref",
    "refresh_token",
    "secret",
    "session_token",
    "token",
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
    # M4-2 context engineering (FP-CTX-004 / FP-CTX-002): cross-turn budget
    # counters and the layered conversation summary ride the Checkpoint so
    # an interrupted or restarted run rebuilds them instead of re-charging.
    conversation_round: int = 0
    cumulative_input_tokens: int = 0
    cumulative_output_tokens: int = 0
    summary: LayeredSummary | None = None
    # M5-2 recovery (FP-FLOW-005 / AC-E2E-002 reliability face): parallel
    # read-branch completion marks, the reduced read facts, the sub-action
    # plan and per-sub-action execution progress ride the Checkpoint so a
    # Worker crash restart resumes from the last completed node instead of
    # re-running finished read branches or verified sub-actions.  All four
    # are additive (empty by default); the onboarding graph owns the
    # concrete projections.
    completed_read_branches: tuple[str, ...] = ()
    read_facts: tuple[tuple[str, Any], ...] = ()
    sub_action_plan: tuple[dict[str, Any], ...] = ()
    sub_action_progress: tuple[dict[str, Any], ...] = ()
    # M5-2 recovery: the intake fields and the original requester ride the
    # Checkpoint so a crash-restart replay never re-resolves the request
    # (the resolver may not serve approval-decision commands) and the
    # approval separation-of-duties check keeps the ORIGINAL requester.
    recovery_fields: tuple[tuple[str, str], ...] = ()
    recovery_requester_id: str | None = None

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
        if (
            self.conversation_round < 0
            or self.cumulative_input_tokens < 0
            or self.cumulative_output_tokens < 0
        ):
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "graph conversation budget counters cannot be negative",
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
            "conversation_round": self.conversation_round,
            "cumulative_input_tokens": self.cumulative_input_tokens,
            "cumulative_output_tokens": self.cumulative_output_tokens,
            "summary": (
                self.summary.to_mapping() if self.summary is not None else None
            ),
            "completed_read_branches": list(self.completed_read_branches),
            "read_facts": [list(item) for item in self.read_facts],
            "sub_action_plan": [dict(item) for item in self.sub_action_plan],
            "sub_action_progress": [
                dict(item) for item in self.sub_action_progress
            ],
            "recovery_fields": [list(item) for item in self.recovery_fields],
            "recovery_requester_id": self.recovery_requester_id,
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
                conversation_round=int(value.get("conversation_round", 0)),
                cumulative_input_tokens=int(
                    value.get("cumulative_input_tokens", 0)
                ),
                cumulative_output_tokens=int(
                    value.get("cumulative_output_tokens", 0)
                ),
                summary=(
                    LayeredSummary.from_mapping(value["summary"])
                    if value.get("summary") is not None
                    else None
                ),
                completed_read_branches=tuple(
                    str(item) for item in value.get("completed_read_branches", ())
                ),
                read_facts=tuple(
                    (str(item[0]), item[1])
                    for item in value.get("read_facts", ())
                ),
                sub_action_plan=tuple(
                    dict(item) for item in value.get("sub_action_plan", ())
                ),
                sub_action_progress=tuple(
                    dict(item) for item in value.get("sub_action_progress", ())
                ),
                recovery_fields=tuple(
                    (str(item[0]), str(item[1]))
                    for item in value.get("recovery_fields", ())
                ),
                recovery_requester_id=(
                    str(value["recovery_requester_id"])
                    if value.get("recovery_requester_id") is not None
                    else None
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
