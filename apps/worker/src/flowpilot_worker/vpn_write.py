"""VPN ticket write node — the approved-then-execute vertical slice.

This module is the minimal extraction of the write node from ``vpn.py``
(which remains read-only) to unlock deterministic testing of the approval →
Gateway write → readback → ledger vertical loop without a generalized
refactor. The graph reuses the stable FlowPilot topology and only the
trusted internal ports (request observation, result artifacts, Gateway
client, checkpoints).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Protocol, TypedDict, cast

from flowpilot_application import (
    ApplicationError,
    RequestObservation,
    RequestObservationService,
    ResultArtifactDraft,
    ResultArtifactService,
    ResultCitation,
)
from flowpilot_context import (
    ContextBuilder,
    ContextBuildRequest,
    ContextEnvelope,
    ContextPolicy,
)
from flowpilot_domain import (
    ActionAgent,
    ActionResource,
    ActionTool,
    Approval,
    ApprovalStatus,
    CommandType,
    DataClassification,
    DomainViolation,
    PlannedAction,
    TaskCommand,
    ToolOperation,
    canonical_sha256,
)
from flowpilot_graph import (
    CheckpointPort,
    FlowPilotGraphNodes,
    GraphDefinition,
    GraphError,
    GraphErrorCode,
    GraphExecutionPort,
    GraphNode,
    GraphRunOutcome,
    GraphState,
    GraphStatus,
    LeaseToken,
    build_flowpilot_it_service_graph,
)
from flowpilot_tool_contracts import (
    AgentPrincipal,
    GatewayCall,
    GatewayClientPort,
    GatewayPortError,
    ToolRequest,
    ToolResult,
    ToolResultStatus,
)
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, interrupt

from .vpn import (
    _ACTIVE_INVOCATION,
    _append_unique,
    _Invocation,
    _VpnFailure,
)

TICKET_TOOL_NAME = "ticket.update.v1"
TICKET_SCHEMA_PIN = (
    "sha256:1e68e4ae27bd8024d9b0e8864b5bc6a816848b9023ef5ed004b33c4880f1429d"
)
VPN_WRITE_GRAPH_VERSION = "flowpilot.vpn-ticket-write.p1.v1"
VPN_WRITE_AGENT_ID = "vpn-write-agent"
VPN_WRITE_AGENT_VERSION = "p1.0"
VPN_WRITE_AGENT_PRINCIPAL = "workload://flowpilot/vpn-write/p1"

_SAFE_FIELD = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_SAFE_TEXT = re.compile(r"^[^\x00-\x1f\x7f]{1,2048}$")
_CLASSIFICATION_RANK = {
    DataClassification.PUBLIC: 0,
    DataClassification.INTERNAL: 1,
    DataClassification.CONFIDENTIAL: 2,
    DataClassification.RESTRICTED: 3,
}


class ApprovalSourcePort(Protocol):
    """Minimal approval record boundary used by the write node on resume."""

    async def resolve(self, approval_id: str) -> Approval: ...


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}_{hashlib.sha256(value.encode()).hexdigest()[:20]}"


def _ticket_id(tenant_id: str, task_id: str) -> str:
    suffix = hashlib.sha256(f"{tenant_id}:{task_id}".encode()).hexdigest()[:10]
    return f"TCK-{suffix.upper()}"


class VpnTicketWriteState(TypedDict, total=False):
    task_ref: str
    status: str
    route: str
    current_node: str
    visited_nodes: Annotated[list[str], _append_unique]
    requester_id: str
    observation_ref: str
    source_digest: str
    input_complete: bool
    proposal: dict[str, Any]
    approval_id: str
    approval_action_digest: str
    approval_decision: str
    write_complete: bool
    ticket_ref: str
    result_ref: str
    runtime_outcome: str
    terminal_reason: str
    failure_code: str


@dataclass(frozen=True, slots=True)
class VpnTicketWriteConfig:
    graph_version: str = VPN_WRITE_GRAPH_VERSION
    ticket_schema_pin: str = TICKET_SCHEMA_PIN
    maximum_attempts: int = 2
    policy_version: str = "policy-p1.1"
    system_policy_ref: str = "policy://vpn-ticket-write/p1"
    agent_id: str = VPN_WRITE_AGENT_ID
    agent_version: str = VPN_WRITE_AGENT_VERSION
    agent_principal_ref: str = VPN_WRITE_AGENT_PRINCIPAL
    context_policy: ContextPolicy = ContextPolicy(
        context_policy_version="context-vpn-write-p1",
        data_classification_ceiling=DataClassification.CONFIDENTIAL,
        provider_allowlist=("deterministic-no-provider",),
        token_budget=1024,
    )

    def __post_init__(self) -> None:
        if self.ticket_schema_pin != TICKET_SCHEMA_PIN:
            raise ValueError("VPN write graph must use the accepted Ticket Schema Pin")
        if self.maximum_attempts < 1:
            raise ValueError("maximum_attempts must be positive")


class VpnTicketWriteGraph(GraphExecutionPort):
    """Deterministic approved-ticket-write graph over the stable topology.

    Flow: prepare → build_context (escalation observation + proposal) →
    approval_interrupt (WAITING_APPROVAL) → run_agent (Gateway write via
    ``ticket.update.v1``) → readback VERIFIED → finalize with a result
    artifact that carries the real ticket id.
    """

    def __init__(
        self,
        *,
        requests: RequestObservationService,
        artifacts: ResultArtifactService,
        gateway: GatewayClientPort,
        checkpoints: CheckpointPort,
        context_builder: ContextBuilder,
        config: VpnTicketWriteConfig | None = None,
        clock: Callable[[], datetime] | None = None,
        checkpointer: Any | None = None,
        approvals: ApprovalSourcePort | None = None,
    ) -> None:
        self._requests = requests
        self._artifacts = artifacts
        self._gateway = gateway
        self._checkpoints = checkpoints
        self._context_builder = context_builder
        self._config = config or VpnTicketWriteConfig()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._checkpointer = checkpointer or InMemorySaver()
        self._approvals = approvals
        self.built_contexts: list[ContextEnvelope] = []
        self.last_safe_state: Mapping[str, Any] | None = None
        nodes = _VpnWriteNodes(self)
        self._definition = build_flowpilot_it_service_graph(
            VpnTicketWriteState,
            nodes.as_graph_nodes(),
            checkpointer=self._checkpointer,
        )

    @property
    def definition(self) -> GraphDefinition:
        return self._definition

    async def execute(
        self,
        command: TaskCommand,
        *,
        execution_ref: str,
        lease: LeaseToken,
    ) -> GraphRunOutcome:
        self._validate_command(command)
        current = await self._load_or_initialize(command, lease)
        if current.status in {GraphStatus.COMPLETED, GraphStatus.FAILED}:
            return GraphRunOutcome(
                state=current,
                runtime_result=None,
                should_retry=False,
            )

        was_waiting = current.status is GraphStatus.WAITING_APPROVAL
        if was_waiting and command.command_type is not CommandType.DECIDE_APPROVAL:
            raise GraphError(
                GraphErrorCode.COMMAND_UNSUPPORTED,
                "VPN ticket write requires an approval decision command",
            )
        current = current.transition(
            GraphStatus.RUNNING,
            node=GraphNode.INTAKE,
            command_id=command.command_id,
            command_digest=command.command_digest,
            run_id=lease.run_id,
            run_generation=lease.run_generation,
            security_context_ref=(
                current.security_context_ref
                if was_waiting
                else command.security_context.context_ref
            ),
            security_context_hash=(
                current.security_context_hash
                if was_waiting
                else command.security_context.context_hash
            ),
            attempt_count=current.attempt_count + 1,
            pending_reason=None,
            failure_code=None,
        )
        current = await self._save(current, lease)

        invocation = _Invocation(
            command=command,
            execution_ref=execution_ref,
            lease=lease,
        )
        token = _ACTIVE_INVOCATION.set(invocation)
        graph_config = {"configurable": {"thread_id": self._thread_id(command)}}
        try:
            graph_input: Mapping[str, Any] | Command[Any]
            if was_waiting and await self._has_graph_checkpoint(graph_config):
                graph_input = Command(
                    resume={
                        "approval_id": str(command.payload["approval_id"]),
                        "action_digest": str(command.payload["action_digest"]),
                        "decision": (
                            "approved"
                            if command.payload["decision"] == "approve"
                            else "rejected"
                        ),
                        "approver_id": command.actor.id,
                    }
                )
            else:
                graph_input = {
                    "task_ref": self._opaque_task_ref(command),
                    "requester_id": command.actor.id,
                }
            result = await self._definition.graph.ainvoke(
                cast(Any, graph_input),
                config=cast(Any, graph_config),
            )
            self.last_safe_state = dict(result)
            if result.get("__interrupt__"):
                waiting = current.transition(
                    GraphStatus.WAITING_APPROVAL,
                    node=GraphNode.INTERRUPT,
                    pending_reason="vpn_approval:ticket_update",
                    observation_ref=self._optional_text(result.get("observation_ref")),
                )
                waiting = await self._save(waiting, lease)
                return GraphRunOutcome(
                    state=waiting,
                    runtime_result=None,
                    should_retry=False,
                )

            if result.get("status") != GraphStatus.COMPLETED.value:
                raise GraphError(
                    GraphErrorCode.STATE_INVALID,
                    "VPN ticket write graph ended without a deterministic "
                    "terminal state",
                )
            result_ref = self._required_text(result.get("result_ref"))
            completed = current.transition(
                GraphStatus.COMPLETED,
                node=GraphNode.FINALIZE,
                context_id=self._optional_text(result.get("context_id")),
                result_ref=result_ref,
                observation_ref=self._optional_text(result.get("observation_ref")),
                failure_code=None,
            )
            completed = await self._save(completed, lease)
            return GraphRunOutcome(
                state=completed,
                runtime_result=None,
                should_retry=False,
            )
        except _VpnFailure as failure:
            should_retry = (
                failure.retryable
                and current.attempt_count < self._config.maximum_attempts
            )
            failed = current.transition(
                (GraphStatus.RETRY_PENDING if should_retry else GraphStatus.FAILED),
                node=(GraphNode.RUN_AGENT if should_retry else GraphNode.FINALIZE),
                failure_code=failure.code,
            )
            failed = await self._save(failed, lease)
            return GraphRunOutcome(
                state=failed,
                runtime_result=None,
                should_retry=should_retry,
            )
        finally:
            _ACTIVE_INVOCATION.reset(token)

    async def _resolve(self) -> RequestObservation:
        try:
            return await self._requests.resolve(self._invocation().command)
        except ApplicationError as exc:
            raise _VpnFailure(exc.code.value, retryable=exc.retryable) from exc

    def _build_context(
        self,
        observation: RequestObservation,
        *,
        task_state: Mapping[str, Any],
        context_kind: str,
    ) -> ContextEnvelope:
        command = self._invocation().command
        policy = replace(
            self._config.context_policy,
            data_classification_ceiling=self._effective_ceiling(command),
        )
        try:
            context = self._context_builder.build(
                ContextBuildRequest(
                    context_id=_stable_id(
                        "ctx",
                        f"{command.task_id}:{command.command_id}:{context_kind}",
                    ),
                    task_id=command.task_id,
                    agent_id=self._config.agent_id,
                    purpose=command.security_context.purpose,
                    security_context=command.security_context,
                    task_state=dict(task_state),
                    task_state_ref=(
                        f"task://{command.task_id}/observation/"
                        f"{observation.source_digest.removeprefix('sha256:')[:16]}"
                    ),
                    system_policy_ref=self._config.system_policy_ref,
                    policy=policy,
                    excluded_fields=(
                        "original_message",
                        "request_body",
                        "internal_acl",
                        "credentials",
                        "tool_payload",
                    ),
                    redactions=("request_content", "knowledge_content"),
                )
            )
        except Exception as exc:
            code = getattr(getattr(exc, "code", None), "value", None)
            raise _VpnFailure(str(code or "RUNTIME_CONTEXT_INVALID")) from exc
        self.built_contexts.append(context)
        return context

    async def _load_or_initialize(
        self,
        command: TaskCommand,
        lease: LeaseToken,
    ) -> GraphState:
        current = await self._checkpoints.load(command.tenant_id, command.task_id)
        if current is None:
            return GraphState(
                task_id=command.task_id,
                tenant_id=command.tenant_id,
                command_id=command.command_id,
                command_digest=command.command_digest,
                run_id=lease.run_id,
                run_generation=lease.run_generation,
                graph_version=self._config.graph_version,
                status=GraphStatus.QUEUED,
                node=GraphNode.START,
                security_context_ref=command.security_context.context_ref,
                security_context_hash=command.security_context.context_hash,
                purpose=command.security_context.purpose,
            )
        if current.graph_version != self._config.graph_version:
            raise GraphError(
                GraphErrorCode.VERSION_MIGRATION_REQUIRED,
                "VPN ticket write checkpoint requires an explicit migration",
            )
        if (
            current.tenant_id != command.tenant_id
            or current.task_id != command.task_id
            or current.purpose != command.security_context.purpose
        ):
            raise GraphError(
                GraphErrorCode.SECURITY_BINDING_MISMATCH,
                "command does not match the VPN ticket write checkpoint "
                "security binding",
            )
        if (
            command.command_type is not CommandType.DECIDE_APPROVAL
            and (
                current.security_context_ref
                != command.security_context.context_ref
                or current.security_context_hash
                != command.security_context.context_hash
            )
        ):
            # An approval decision legitimately carries the approver's own
            # security context; the task checkpoint keeps the requester's.
            raise GraphError(
                GraphErrorCode.SECURITY_BINDING_MISMATCH,
                "command does not match the VPN ticket write checkpoint "
                "security binding",
            )
        same_command = current.command_id == command.command_id
        if same_command and current.command_digest != command.command_digest:
            raise GraphError(
                GraphErrorCode.SECURITY_BINDING_MISMATCH,
                "replayed command does not match the VPN ticket write "
                "checkpoint digest",
            )
        if current.status is GraphStatus.RUNNING and not same_command:
            raise GraphError(
                GraphErrorCode.COMMAND_MISMATCH,
                "an in-flight VPN ticket write graph cannot switch commands",
            )
        if lease.run_generation < current.run_generation:
            raise GraphError(
                GraphErrorCode.LEASE_LOST,
                "worker lease generation is older than the VPN ticket write "
                "checkpoint",
            )
        return replace(
            current,
            run_id=lease.run_id,
            run_generation=lease.run_generation,
        )

    async def _save(self, state: GraphState, lease: LeaseToken) -> GraphState:
        return await self._checkpoints.save(
            state,
            expected_sequence=state.checkpoint_sequence,
            lease=lease,
        )

    async def _has_graph_checkpoint(self, config: Mapping[str, Any]) -> bool:
        getter = getattr(self._checkpointer, "aget_tuple", None)
        if getter is None:
            return False
        return await getter(config) is not None

    def _effective_ceiling(self, command: TaskCommand) -> DataClassification:
        command_ceiling = command.security_context.data_classification_ceiling
        policy_ceiling = self._config.context_policy.data_classification_ceiling
        return min(
            (command_ceiling, policy_ceiling),
            key=_CLASSIFICATION_RANK.__getitem__,
        )

    @staticmethod
    def _validate_command(command: TaskCommand) -> None:
        if command.command_type not in {
            CommandType.CREATE,
            CommandType.DECIDE_APPROVAL,
        }:
            raise GraphError(
                GraphErrorCode.COMMAND_UNSUPPORTED,
                "VPN ticket write graph accepts create and approval decisions",
            )
        try:
            command.assert_digest()
            command.assert_security_binding()
        except DomainViolation as exc:
            raise GraphError(
                GraphErrorCode.SECURITY_BINDING_MISMATCH,
                "command failed deterministic VPN ticket write security binding",
            ) from exc

    @staticmethod
    def _thread_id(command: TaskCommand) -> str:
        identity = f"{command.tenant_id}:{command.task_id}"
        return "vpn-write-thread-" + hashlib.sha256(identity.encode()).hexdigest()[
            :12
        ]

    @staticmethod
    def _opaque_task_ref(command: TaskCommand) -> str:
        suffix = hashlib.sha256(
            f"{command.tenant_id}:{command.task_id}".encode()
        ).hexdigest()[:20]
        return f"task://sha256/{suffix}"

    @staticmethod
    def _required_text(value: object) -> str:
        if not isinstance(value, str) or not value:
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "VPN ticket write result is missing a required reference",
            )
        return value

    @staticmethod
    def _optional_text(value: object) -> str | None:
        return value if isinstance(value, str) and value else None

    async def _ticket_write(
        self,
        *,
        proposal: Mapping[str, Any],
        approval_id: str,
        source_digest: str,
    ) -> tuple[str, str]:
        """Execute the approved ticket write and verify the readback result."""
        command = self._invocation().command
        call = build_vpn_ticket_gateway_call(
            config=self._config,
            command=command,
            source_digest=source_digest,
            proposal=proposal,
            approval_id=approval_id,
            run_id=self._invocation().lease.run_id,
        )
        try:
            result = await self._gateway.execute(call)
        except GatewayPortError as exc:
            raise _VpnFailure(exc.code.value) from exc
        except Exception as exc:
            raise _VpnFailure(
                "RUNTIME_TICKET_GATEWAY_UNAVAILABLE",
                retryable=True,
            ) from exc
        self._assert_write_result_binding(result, call)
        if result.status is ToolResultStatus.FAILED_RETRYABLE:
            raise _VpnFailure(
                result.error_code or "RUNTIME_TICKET_RETRYABLE",
                retryable=True,
            )
        if result.status is ToolResultStatus.UNKNOWN:
            raise _VpnFailure(
                "RUNTIME_TICKET_OUTCOME_UNKNOWN",
                retryable=False,
            )
        if result.status is ToolResultStatus.FAILED_FINAL:
            raise _VpnFailure(
                result.error_code or "RUNTIME_TICKET_FAILED",
                retryable=False,
            )
        if (
            result.status is not ToolResultStatus.VERIFIED
            or result.data is None
            or result.verification is None
            or result.verification.matched is not True
        ):
            raise _VpnFailure("RUNTIME_TICKET_RESULT_INVALID")
        ticket_id = result.data.get("ticket_id")
        if ticket_id != proposal["arguments"].get("ticket_id"):
            raise _VpnFailure("RUNTIME_TICKET_RESULT_INVALID")
        ticket_ref = f"ticket://{command.tenant_id}/{ticket_id}"
        content = (
            f"## Ticket created\n\n"
            f"Ticket ID: {ticket_id}\n"
            f"Status: {result.data.get('status')}\n"
            f"Summary: {proposal['arguments'].get('summary')}"
        )
        projection = {
            "tenant_id": command.tenant_id,
            "task_id": command.task_id,
            "media_type": "text/markdown",
            "content": content,
            "citations": [
                {
                    "source_ref": ticket_ref,
                    "document_version": "1.0",
                    "section": "ticket",
                    "content_hash": canonical_sha256(
                        {
                            "ticket_id": ticket_id,
                            "status": result.data.get("status"),
                        }
                    ),
                }
            ],
        }
        draft = ResultArtifactDraft(
            tenant_id=command.tenant_id,
            task_id=command.task_id,
            idempotency_key=canonical_sha256(
                {
                    "tenant_id": command.tenant_id,
                    "task_id": command.task_id,
                    "ticket_request_id": call.request.request_id,
                }
            ),
            media_type="text/markdown",
            content=content,
            citations=(
                ResultCitation(
                    source_ref=ticket_ref,
                    document_version="1.0",
                    section="ticket",
                    content_hash=canonical_sha256(
                        {
                            "ticket_id": ticket_id,
                            "status": result.data.get("status"),
                        }
                    ),
                ),
            ),
            result_digest=canonical_sha256(projection),
        )
        try:
            receipt = await self._artifacts.save(draft)
        except ApplicationError as exc:
            raise _VpnFailure(
                exc.code.value,
                retryable=exc.retryable,
            ) from exc
        if receipt.result_ref is None:
            raise _VpnFailure("RUNTIME_RESULT_REFERENCE_MISSING")
        return receipt.result_ref, ticket_ref

    @staticmethod
    def _assert_write_result_binding(
        result: ToolResult,
        call: GatewayCall,
    ) -> None:
        if (
            result.request_id != call.request.request_id
            or result.policy_decision_id != call.request.policy_decision_id
            or result.operation is not ToolOperation.WRITE
        ):
            raise _VpnFailure("RUNTIME_TICKET_RESULT_BINDING_MISMATCH")

    @staticmethod
    def _invocation() -> _Invocation:
        invocation = _ACTIVE_INVOCATION.get()
        if invocation is None:
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "VPN ticket write node is outside an execution boundary",
            )
        return invocation


class _VpnWriteNodes:
    def __init__(self, runtime: VpnTicketWriteGraph) -> None:
        self._runtime = runtime

    def as_graph_nodes(self) -> FlowPilotGraphNodes:
        return FlowPilotGraphNodes(
            prepare=self.prepare,
            build_context=self.build_context,
            route_request=self.route_request,
            route_after_request=self.route_after_request,
            clarification_interrupt=self.clarification_interrupt,
            knowledge_read=self.knowledge_read,
            service_read=self.service_read,
            join_reads=self.join_reads,
            handoff=self.handoff,
            approval_interrupt=self.approval_interrupt,
            run_agent=self.run_agent,
            route_result=self.route_result,
            route_after_result=self.route_after_result,
            retry=self.retry,
            compensate=self.compensate,
            finalize=self.finalize,
        )

    async def prepare(self, _state: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._advance(
            "prepare",
            {
                "status": GraphStatus.RUNNING.value,
                "input_complete": False,
                "write_complete": False,
            },
        )

    async def build_context(self, _state: Mapping[str, Any]) -> Mapping[str, Any]:
        observation = await self._runtime._resolve()
        if observation.missing_fields:
            raise _VpnFailure("RUNTIME_TICKET_OBSERVATION_INCOMPLETE")
        proposal = _build_ticket_proposal(
            config=self._runtime._config,
            command=self._runtime._invocation().command,
            observation=observation,
        )
        context = self._runtime._build_context(
            observation,
            task_state={
                "status": GraphStatus.RUNNING.value,
                "intent": observation.intent,
                "observation_ref": observation.observation_ref,
                "missing_fields": list(observation.missing_fields),
            },
            context_kind="request",
        )
        return self._advance(
            "build_context",
            {
                "observation_ref": observation.observation_ref,
                "source_digest": observation.source_digest,
                "input_complete": True,
                "proposal": proposal,
                "context_id": context.context_id,
            },
        )

    async def route_request(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        if state.get("input_complete") is not True:
            raise _VpnFailure("RUNTIME_TICKET_OBSERVATION_INCOMPLETE")
        return self._advance("route_request", {"route": "approval"})

    @staticmethod
    def route_after_request(state: Mapping[str, Any]) -> str | Sequence[str]:
        route = state.get("route")
        if route == "approval":
            return "approval"
        raise GraphError(GraphErrorCode.STATE_INVALID, "VPN write route is invalid")

    async def clarification_interrupt(
        self, _state: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        raise GraphError(
            GraphErrorCode.STATE_INVALID,
            "VPN ticket write flow cannot route to clarification",
        )

    async def knowledge_read(self, _state: Mapping[str, Any]) -> Mapping[str, Any]:
        raise GraphError(
            GraphErrorCode.STATE_INVALID,
            "VPN ticket write flow cannot route to knowledge reads",
        )

    async def service_read(self, _state: Mapping[str, Any]) -> Mapping[str, Any]:
        raise GraphError(
            GraphErrorCode.STATE_INVALID,
            "VPN ticket write flow cannot route to service reads",
        )

    async def join_reads(self, _state: Mapping[str, Any]) -> Mapping[str, Any]:
        raise GraphError(
            GraphErrorCode.STATE_INVALID,
            "VPN ticket write flow cannot join read branches",
        )

    async def handoff(self, _state: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._advance("handoff", {})

    async def approval_interrupt(
        self, state: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        proposal = state.get("proposal")
        if not isinstance(proposal, Mapping) or not proposal.get("approval_id"):
            raise _VpnFailure("RUNTIME_APPROVAL_PROPOSAL_MISSING")
        card = {
            "schema": "flowpilot.vpn-approval.v1",
            "kind": "approval",
            "approval_id": proposal["approval_id"],
            "action_digest": proposal["action_digest"],
            "display_ref": proposal["display_ref"],
            "expires_at": proposal["expires_at"],
        }
        decision = interrupt(card)
        if not isinstance(decision, Mapping):
            raise _VpnFailure("RUNTIME_APPROVAL_DECISION_INVALID")
        if (
            decision.get("approval_id") != proposal["approval_id"]
            or decision.get("action_digest") != proposal["action_digest"]
        ):
            raise _VpnFailure("RUNTIME_APPROVAL_BINDING_MISMATCH")
        if decision.get("decision") != "approved":
            raise _VpnFailure("RUNTIME_APPROVAL_DECLINED")
        if decision.get("approver_id") == state.get("requester_id"):
            raise _VpnFailure("RUNTIME_APPROVAL_DUTIES_VIOLATION")
        await self._assert_approval_active(
            str(proposal["approval_id"]),
            str(proposal["action_digest"]),
        )
        return self._advance(
            "approval_interrupt",
            {
                "approval_id": proposal["approval_id"],
                "approval_action_digest": proposal["action_digest"],
                "approval_decision": "approved",
            },
        )

    async def _assert_approval_active(
        self, approval_id: str, action_digest: str
    ) -> None:
        source = self._runtime._approvals
        if source is None:
            return
        try:
            approval = await source.resolve(approval_id)
        except Exception as exc:
            raise _VpnFailure("RUNTIME_APPROVAL_UNAVAILABLE") from exc
        if (
            approval.approval_id != approval_id
            or approval.action_digest != action_digest
            or approval.status is not ApprovalStatus.APPROVED
            or self._runtime._clock() >= approval.expires_at
        ):
            raise _VpnFailure("RUNTIME_APPROVAL_INVALID")

    async def run_agent(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        proposal = state.get("proposal")
        if (
            not isinstance(proposal, Mapping)
            or state.get("approval_id") != proposal.get("approval_id")
            or state.get("approval_decision") != "approved"
        ):
            raise _VpnFailure("RUNTIME_APPROVAL_REQUIRED")
        result_ref, ticket_ref = await self._runtime._ticket_write(
            proposal=proposal,
            approval_id=str(state["approval_id"]),
            source_digest=str(state.get("source_digest") or ""),
        )
        return self._advance(
            "run_agent",
            {
                "write_complete": True,
                "ticket_ref": ticket_ref,
                "result_ref": result_ref,
                "runtime_outcome": "completed",
            },
        )

    async def route_result(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        if (
            state.get("write_complete") is not True
            or not state.get("result_ref")
            or not state.get("ticket_ref")
        ):
            raise _VpnFailure("RUNTIME_TICKET_RESULT_MISSING")
        return self._advance("route_result", {"route": "finalize"})

    @staticmethod
    def route_after_result(state: Mapping[str, Any]) -> str | Sequence[str]:
        if state.get("route") == "finalize":
            return "finalize"
        raise GraphError(
            GraphErrorCode.STATE_INVALID, "VPN write result route is invalid"
        )

    async def retry(self, _state: Mapping[str, Any]) -> Mapping[str, Any]:
        # Retry is reached only for retryable failures; the approval binding
        # in the checkpoint remains authoritative and run_agent re-executes.
        return self._advance("retry", {})

    async def compensate(self, _state: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._advance("compensate", {})

    async def finalize(self, _state: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._advance(
            "finalize",
            {
                "status": GraphStatus.COMPLETED.value,
                "terminal_reason": "VPN_TICKET_WRITE_COMPLETED",
            },
        )

    @staticmethod
    def _advance(
        node: str,
        update: Mapping[str, Any],
        *,
        record_current: bool = True,
    ) -> Mapping[str, Any]:
        result = {**update, "visited_nodes": [node]}
        if record_current:
            result["current_node"] = node
        return result


def _build_ticket_proposal(
    *,
    config: VpnTicketWriteConfig,
    command: TaskCommand,
    observation: RequestObservation,
) -> dict[str, Any]:
    """Deterministic ticket update proposal bound to the escalation observation."""
    if (
        observation.tenant_id != command.tenant_id
        or observation.task_id != command.task_id
    ):
        raise _VpnFailure("RUNTIME_OBSERVATION_BINDING_MISMATCH")
    tried_steps = observation.fields.get("tried_steps")
    symptom = observation.fields.get("symptom_code")
    if (
        not isinstance(tried_steps, str)
        or _SAFE_TEXT.fullmatch(tried_steps) is None
        or not isinstance(symptom, str)
        or _SAFE_FIELD.fullmatch(symptom) is None
    ):
        raise _VpnFailure("RUNTIME_TICKET_OBSERVATION_INVALID")
    ticket_id = _ticket_id(command.tenant_id, command.task_id)
    expires_at = min(
        command.issued_at + timedelta(minutes=15),
        command.security_context.expires_at,
    )
    action = PlannedAction(
        action_id=_stable_id(
            "act",
            f"{command.tenant_id}:{command.task_id}:{observation.source_digest}:write",
        ),
        tenant_id=command.tenant_id,
        task_id=command.task_id,
        requester_id=command.actor.id,
        agent=ActionAgent(id=config.agent_id, version=config.agent_version),
        tool=ActionTool(
            name=TICKET_TOOL_NAME,
            schema_hash=config.ticket_schema_pin,
            operation=ToolOperation.WRITE,
        ),
        arguments={
            "ticket_id": ticket_id,
            "status": "in_progress",
            "summary": tried_steps,
        },
        resource=ActionResource(type="ticket", id=ticket_id),
        purpose=command.security_context.purpose,
        data_classification=DataClassification.INTERNAL,
        policy_version=config.policy_version,
        expires_at=expires_at,
    )
    action_digest = action.digest()
    approval_id = _stable_id(
        "apr",
        f"{command.tenant_id}:{command.task_id}:{action_digest}",
    )
    return {
        "action_id": action.action_id,
        "approval_id": approval_id,
        "action_digest": action_digest,
        "requester_id": command.actor.id,
        "policy_decision_id": _stable_id(
            "pd",
            f"{command.tenant_id}:{command.task_id}:{action_digest}",
        ),
        "tool": TICKET_TOOL_NAME,
        "tool_schema_hash": config.ticket_schema_pin,
        "arguments": dict(action.arguments),
        "resource": action.resource.to_mapping(),
        "display_ref": f"proposal://{command.tenant_id}/{approval_id}",
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
    }


def build_vpn_ticket_gateway_call(
    *,
    config: VpnTicketWriteConfig,
    command: TaskCommand,
    source_digest: str,
    proposal: Mapping[str, Any],
    approval_id: str,
    run_id: str | None = None,
) -> GatewayCall:
    """Build the stable, tenant-bound write request consumed by the Gateway."""
    expires_at = datetime.fromisoformat(
        str(proposal["expires_at"]).replace("Z", "+00:00")
    )
    action = PlannedAction(
        action_id=str(proposal["action_id"]),
        tenant_id=command.tenant_id,
        task_id=command.task_id,
        requester_id=str(proposal["requester_id"]),
        agent=ActionAgent(id=config.agent_id, version=config.agent_version),
        tool=ActionTool(
            name=TICKET_TOOL_NAME,
            schema_hash=config.ticket_schema_pin,
            operation=ToolOperation.WRITE,
        ),
        arguments=dict(proposal["arguments"]),
        resource=ActionResource(
            type=str(proposal["resource"]["type"]),
            id=str(proposal["resource"]["id"]),
        ),
        purpose=command.security_context.purpose,
        data_classification=DataClassification.INTERNAL,
        policy_version=config.policy_version,
        expires_at=expires_at,
    )
    action_digest = action.digest()
    if action_digest != proposal["action_digest"]:
        raise _VpnFailure("RUNTIME_APPROVAL_BINDING_MISMATCH")
    request_id = _stable_id(
        "treq",
        f"{command.tenant_id}:{command.task_id}:{action_digest}",
    )
    policy_decision_id = str(proposal["policy_decision_id"])
    request = ToolRequest(
        request_id=request_id,
        trace_id=hashlib.sha256(
            (command.correlation_id or command.command_id).encode()
        ).hexdigest(),
        security_context=command.security_context,
        agent_principal=AgentPrincipal(
            id=config.agent_id,
            version=config.agent_version,
            principal_ref=config.agent_principal_ref,
        ),
        planned_action=action,
        action_digest=action_digest,
        policy_decision_id=policy_decision_id,
        idempotency_key=canonical_sha256(
            {
                "tenant_id": command.tenant_id,
                "task_id": command.task_id,
                "tool": TICKET_TOOL_NAME,
                "source_digest": source_digest,
            }
        ),
        requested_at=command.issued_at,
        approval_id=approval_id,
    )
    return GatewayCall(
        request=request,
        thread_id=_stable_id(
            "thread",
            f"{command.tenant_id}:{command.task_id}",
        ),
        run_id=run_id or _stable_id("run", command.task_id),
        correlation_id=command.correlation_id or command.command_id,
    )


__all__ = [
    "TICKET_SCHEMA_PIN",
    "TICKET_TOOL_NAME",
    "VPN_WRITE_GRAPH_VERSION",
    "VpnTicketWriteConfig",
    "VpnTicketWriteGraph",
    "VpnTicketWriteState",
    "build_vpn_ticket_gateway_call",
    "build_ticket_proposal",
]


def build_ticket_proposal(
    *,
    config: VpnTicketWriteConfig,
    command: TaskCommand,
    observation: RequestObservation,
) -> dict[str, Any]:
    """Public alias for the deterministic proposal builder."""
    return _build_ticket_proposal(
        config=config,
        command=command,
        observation=observation,
    )
