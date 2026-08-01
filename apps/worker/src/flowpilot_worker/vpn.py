from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, TypedDict, cast

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
    debug_projection,
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

KNOWLEDGE_TOOL_NAME = "knowledge.search.v1"
KNOWLEDGE_SCHEMA_PIN = (
    "sha256:b7679fde5be1187e8a36b4cd4dd95a95b63a50dc56532294174b0088f0e6600b"
)
VPN_GRAPH_VERSION = "flowpilot.vpn-readonly.p1.v1"
VPN_AGENT_ID = "vpn-support-agent"
VPN_AGENT_VERSION = "p1.0"
VPN_AGENT_PRINCIPAL = "workload://flowpilot/vpn-support/p1"

_SAFE_FIELD = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_CLASSIFICATION_RANK = {
    DataClassification.PUBLIC: 0,
    DataClassification.INTERNAL: 1,
    DataClassification.CONFIDENTIAL: 2,
    DataClassification.RESTRICTED: 3,
}


def _append_unique(
    left: Sequence[str] | None,
    right: Sequence[str] | None,
) -> list[str]:
    return list(dict.fromkeys([*(left or ()), *(right or ())]))


class VpnGraphState(TypedDict, total=False):
    task_ref: str
    status: str
    route: str
    current_node: str
    visited_nodes: Annotated[list[str], _append_unique]
    observation_ref: str
    missing_fields: list[str]
    input_complete: bool
    context_id: str
    context_layers: dict[str, bool]
    knowledge_read_complete: bool
    service_read_complete: bool
    service_read_skipped: bool
    reads_complete: bool
    knowledge_call_count: int
    citation_count: int
    citation_refs: list[dict[str, str]]
    result_ref: str
    context_rebuilt: bool
    tool_scope_rebuilt: bool
    runtime_outcome: str
    terminal_reason: str
    failure_code: str


@dataclass(frozen=True, slots=True)
class VpnGraphConfig:
    graph_version: str = VPN_GRAPH_VERSION
    knowledge_schema_pin: str = KNOWLEDGE_SCHEMA_PIN
    knowledge_limit: int = 5
    maximum_attempts: int = 2
    policy_version: str = "policy-p1.0"
    system_policy_ref: str = "policy://vpn-readonly/p1"
    agent_id: str = VPN_AGENT_ID
    agent_version: str = VPN_AGENT_VERSION
    agent_principal_ref: str = VPN_AGENT_PRINCIPAL
    context_policy: ContextPolicy = ContextPolicy(
        context_policy_version="context-vpn-p1",
        data_classification_ceiling=DataClassification.CONFIDENTIAL,
        provider_allowlist=("deterministic-no-provider",),
        token_budget=1024,
    )

    def __post_init__(self) -> None:
        if self.knowledge_schema_pin != KNOWLEDGE_SCHEMA_PIN:
            raise ValueError("VPN graph must use the accepted Knowledge Schema Pin")
        if not 1 <= self.knowledge_limit <= 20:
            raise ValueError("knowledge_limit must be within the tool contract")
        if self.maximum_attempts < 1:
            raise ValueError("maximum_attempts must be positive")


@dataclass(frozen=True, slots=True)
class _Invocation:
    command: TaskCommand
    execution_ref: str
    lease: LeaseToken


class _VpnFailure(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        retryable: bool = False,
        knowledge_called: bool = False,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.knowledge_called = knowledge_called


_ACTIVE_INVOCATION: ContextVar[_Invocation | None] = ContextVar(
    "flowpilot_vpn_invocation",
    default=None,
)


class VpnReadOnlyGraph(GraphExecutionPort):
    """Deterministic VPN product graph composed only from trusted internal ports."""

    def __init__(
        self,
        *,
        requests: RequestObservationService,
        artifacts: ResultArtifactService,
        gateway: GatewayClientPort,
        checkpoints: CheckpointPort,
        context_builder: ContextBuilder,
        config: VpnGraphConfig | None = None,
        clock: Callable[[], datetime] | None = None,
        checkpointer: Any | None = None,
    ) -> None:
        self._requests = requests
        self._artifacts = artifacts
        self._gateway = gateway
        self._checkpoints = checkpoints
        self._context_builder = context_builder
        self._config = config or VpnGraphConfig()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._checkpointer = checkpointer or InMemorySaver()
        self.built_contexts: list[ContextEnvelope] = []
        self.last_safe_state: Mapping[str, Any] | None = None
        nodes = _VpnNodes(self)
        self._definition = build_flowpilot_it_service_graph(
            VpnGraphState,
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

        was_waiting = current.status is GraphStatus.WAITING_USER
        if was_waiting and command.command_type is not CommandType.SUBMIT_MESSAGE:
            raise GraphError(
                GraphErrorCode.COMMAND_UNSUPPORTED,
                "VPN clarification requires a submitted message reference",
            )
        current = current.transition(
            GraphStatus.RUNNING,
            node=GraphNode.INTAKE,
            command_id=command.command_id,
            command_digest=command.command_digest,
            run_id=lease.run_id,
            run_generation=lease.run_generation,
            security_context_ref=command.security_context.context_ref,
            security_context_hash=command.security_context.context_hash,
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
                graph_input = Command(resume={"confirmed": True})
            else:
                graph_input = {
                    "task_ref": self._opaque_task_ref(command),
                    "knowledge_call_count": current.knowledge_call_count,
                    "citation_count": current.citation_count,
                }
            result = await self._definition.graph.ainvoke(
                cast(Any, graph_input),
                config=cast(Any, graph_config),
            )
            self.last_safe_state = dict(result)
            if result.get("__interrupt__"):
                waiting = current.transition(
                    GraphStatus.WAITING_USER,
                    node=GraphNode.INTERRUPT,
                    pending_reason="vpn_clarification:environment",
                    observation_ref=self._optional_text(result.get("observation_ref")),
                    knowledge_call_count=self._count(
                        result.get("knowledge_call_count")
                    ),
                    citation_count=self._count(result.get("citation_count")),
                    service_read_skipped=(result.get("service_read_skipped") is True),
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
                    "VPN graph ended without a deterministic terminal state",
                )
            result_ref = self._required_text(result.get("result_ref"))
            completed = current.transition(
                GraphStatus.COMPLETED,
                node=GraphNode.FINALIZE,
                context_id=self._optional_text(result.get("context_id")),
                result_ref=result_ref,
                observation_ref=self._optional_text(result.get("observation_ref")),
                knowledge_call_count=self._count(result.get("knowledge_call_count")),
                citation_count=self._count(result.get("citation_count")),
                reference_refs=tuple(
                    item["source_ref"] for item in self._citation_refs(result)
                ),
                service_read_skipped=(result.get("service_read_skipped") is True),
                failure_code=None,
            )
            completed = await self._save(completed, lease)
            return GraphRunOutcome(
                state=completed,
                runtime_result=None,
                should_retry=False,
            )
        except _VpnFailure as failure:
            knowledge_count = max(
                current.knowledge_call_count,
                1 if failure.knowledge_called else 0,
            )
            should_retry = (
                failure.retryable
                and current.attempt_count < self._config.maximum_attempts
            )
            failed = current.transition(
                (GraphStatus.RETRY_PENDING if should_retry else GraphStatus.FAILED),
                node=(GraphNode.KNOWLEDGE_READ if should_retry else GraphNode.FINALIZE),
                failure_code=failure.code,
                knowledge_call_count=knowledge_count,
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
            raise _VpnFailure(
                exc.code.value,
                retryable=exc.retryable,
            ) from exc

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
                    context_id=self._stable_id(
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

    async def _knowledge_read(
        self,
        observation: RequestObservation,
    ) -> tuple[str, tuple[ResultCitation, ...]]:
        call = build_vpn_gateway_call(
            config=self._config,
            command=self._invocation().command,
            observation=observation,
            run_id=self._invocation().lease.run_id,
        )
        try:
            result = await self._gateway.execute(call)
        except GatewayPortError as exc:
            raise _VpnFailure(
                exc.code.value,
                knowledge_called=True,
            ) from exc
        except Exception as exc:
            raise _VpnFailure(
                "RUNTIME_KNOWLEDGE_GATEWAY_UNAVAILABLE",
                retryable=True,
                knowledge_called=True,
            ) from exc
        records = self._verified_records(result, call)
        if not records:
            raise _VpnFailure(
                "RUNTIME_KNOWLEDGE_NO_RESULT",
                knowledge_called=True,
            )
        citations = tuple(
            ResultCitation(
                source_ref=record["source_ref"],
                document_version=record["document_version"],
                section=record["section"],
                content_hash=record["content_hash"],
            )
            for record in records
        )
        content = self._compose_result(records)
        command = self._invocation().command
        projection = {
            "tenant_id": command.tenant_id,
            "task_id": command.task_id,
            "media_type": "text/markdown",
            "content": content,
            "citations": [citation.to_mapping() for citation in citations],
        }
        draft = ResultArtifactDraft(
            tenant_id=command.tenant_id,
            task_id=command.task_id,
            idempotency_key=canonical_sha256(
                {
                    "tenant_id": command.tenant_id,
                    "task_id": command.task_id,
                    "knowledge_request_id": call.request.request_id,
                }
            ),
            media_type="text/markdown",
            content=content,
            citations=citations,
            result_digest=canonical_sha256(projection),
        )
        try:
            receipt = await self._artifacts.save(draft)
        except ApplicationError as exc:
            raise _VpnFailure(
                exc.code.value,
                retryable=exc.retryable,
                knowledge_called=True,
            ) from exc
        if receipt.result_ref is None:
            raise _VpnFailure(
                "RUNTIME_RESULT_REFERENCE_MISSING",
                knowledge_called=True,
            )
        return receipt.result_ref, citations

    def _verified_records(
        self,
        result: ToolResult,
        call: GatewayCall,
    ) -> tuple[dict[str, str], ...]:
        if (
            result.request_id != call.request.request_id
            or result.policy_decision_id != call.request.policy_decision_id
            or result.operation is not ToolOperation.READ
        ):
            raise _VpnFailure(
                "RUNTIME_KNOWLEDGE_RESULT_BINDING_MISMATCH",
                knowledge_called=True,
            )
        if result.status is ToolResultStatus.FAILED_RETRYABLE:
            raise _VpnFailure(
                result.error_code or "RUNTIME_KNOWLEDGE_RETRYABLE",
                retryable=True,
                knowledge_called=True,
            )
        if result.status is ToolResultStatus.UNKNOWN:
            raise _VpnFailure(
                "RUNTIME_KNOWLEDGE_OUTCOME_UNKNOWN",
                knowledge_called=True,
            )
        if result.status is ToolResultStatus.FAILED_FINAL:
            raise _VpnFailure(
                result.error_code or "RUNTIME_KNOWLEDGE_FAILED",
                knowledge_called=True,
            )
        if result.status is not ToolResultStatus.VERIFIED or result.data is None:
            raise _VpnFailure(
                "RUNTIME_KNOWLEDGE_RESULT_INVALID",
                knowledge_called=True,
            )
        try:
            output_classification = DataClassification(result.output_classification)
        except ValueError as exc:
            raise _VpnFailure(
                "RUNTIME_KNOWLEDGE_RESULT_INVALID",
                knowledge_called=True,
            ) from exc
        ceiling = (
            self._invocation().command.security_context.data_classification_ceiling
        )
        if _CLASSIFICATION_RANK[output_classification] > _CLASSIFICATION_RANK[ceiling]:
            raise _VpnFailure(
                "RUNTIME_KNOWLEDGE_CLASSIFICATION_DENIED",
                knowledge_called=True,
            )
        data = result.data
        raw_records = data.get("records")
        returned_count = data.get("returned_count")
        if (
            not isinstance(raw_records, (tuple, list))
            or isinstance(returned_count, bool)
            or not isinstance(returned_count, int)
            or returned_count != len(raw_records)
        ):
            raise _VpnFailure(
                "RUNTIME_KNOWLEDGE_RESULT_INVALID",
                knowledge_called=True,
            )
        allowed = {
            "source_ref",
            "document_version",
            "section",
            "redacted_summary",
            "content_hash",
            "classification",
        }
        records: list[dict[str, str]] = []
        seen: set[str] = set()
        for raw in raw_records:
            if not isinstance(raw, Mapping) or set(raw) != allowed:
                raise _VpnFailure(
                    "RUNTIME_KNOWLEDGE_RESULT_INVALID",
                    knowledge_called=True,
                )
            if any(not isinstance(raw[key], str) or not raw[key] for key in allowed):
                raise _VpnFailure(
                    "RUNTIME_KNOWLEDGE_RESULT_INVALID",
                    knowledge_called=True,
                )
            record = {key: cast(str, raw[key]) for key in allowed}
            try:
                classification = DataClassification(record["classification"])
            except ValueError as exc:
                raise _VpnFailure(
                    "RUNTIME_KNOWLEDGE_RESULT_INVALID",
                    knowledge_called=True,
                ) from exc
            if _CLASSIFICATION_RANK[classification] > _CLASSIFICATION_RANK[ceiling]:
                raise _VpnFailure(
                    "RUNTIME_KNOWLEDGE_CLASSIFICATION_DENIED",
                    knowledge_called=True,
                )
            if (
                not re.fullmatch(r"sha256:[a-f0-9]{64}", record["content_hash"])
                or record["source_ref"] in seen
            ):
                raise _VpnFailure(
                    "RUNTIME_KNOWLEDGE_RESULT_INVALID",
                    knowledge_called=True,
                )
            seen.add(record["source_ref"])
            records.append(record)
        return tuple(records)

    @staticmethod
    def _compose_result(records: tuple[dict[str, str], ...]) -> str:
        steps = "\n".join(
            f"{index}. {record['redacted_summary']}"
            for index, record in enumerate(records, start=1)
        )
        references = "\n".join(
            "- "
            f"{record['section']} (version {record['document_version']}; "
            f"{record['source_ref']})"
            for record in records
        )
        return f"## Recommended steps\n\n{steps}\n\n## References\n\n{references}"

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
                "VPN graph checkpoint requires an explicit migration",
            )
        if (
            current.tenant_id != command.tenant_id
            or current.task_id != command.task_id
            or current.purpose != command.security_context.purpose
            or current.security_context_ref != command.security_context.context_ref
            or current.security_context_hash != command.security_context.context_hash
        ):
            raise GraphError(
                GraphErrorCode.SECURITY_BINDING_MISMATCH,
                "command does not match the VPN checkpoint security binding",
            )
        same_command = current.command_id == command.command_id
        if same_command and current.command_digest != command.command_digest:
            raise GraphError(
                GraphErrorCode.SECURITY_BINDING_MISMATCH,
                "replayed command does not match the VPN checkpoint digest",
            )
        if current.status is GraphStatus.RUNNING and not same_command:
            raise GraphError(
                GraphErrorCode.COMMAND_MISMATCH,
                "an in-flight VPN graph cannot switch commands",
            )
        if lease.run_generation < current.run_generation:
            raise GraphError(
                GraphErrorCode.LEASE_LOST,
                "worker lease generation is older than the VPN checkpoint",
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
            CommandType.SUBMIT_MESSAGE,
        }:
            raise GraphError(
                GraphErrorCode.COMMAND_UNSUPPORTED,
                "VPN graph accepts only request-reference commands",
            )
        try:
            command.assert_digest()
            command.assert_security_binding()
        except DomainViolation as exc:
            raise GraphError(
                GraphErrorCode.SECURITY_BINDING_MISMATCH,
                "command failed deterministic VPN security binding",
            ) from exc

    @staticmethod
    def _thread_id(command: TaskCommand) -> str:
        identity = f"{command.tenant_id}:{command.task_id}"
        return "vpn-thread-" + hashlib.sha256(identity.encode()).hexdigest()[:20]

    @staticmethod
    def _opaque_task_ref(command: TaskCommand) -> str:
        suffix = hashlib.sha256(
            f"{command.tenant_id}:{command.task_id}".encode()
        ).hexdigest()[:20]
        return f"task://sha256/{suffix}"

    @staticmethod
    def _stable_id(prefix: str, value: str) -> str:
        return f"{prefix}_{hashlib.sha256(value.encode()).hexdigest()[:20]}"

    @staticmethod
    def _required_text(value: object) -> str:
        if not isinstance(value, str) or not value:
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "VPN graph result is missing a required reference",
            )
        return value

    @staticmethod
    def _optional_text(value: object) -> str | None:
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _count(value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return 0
        return value

    @staticmethod
    def _citation_refs(state: Mapping[str, Any]) -> tuple[dict[str, str], ...]:
        value = state.get("citation_refs", ())
        if not isinstance(value, (tuple, list)):
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "VPN graph citation references are invalid",
            )
        result: list[dict[str, str]] = []
        required = {"source_ref", "document_version", "section", "content_hash"}
        for item in value:
            if not isinstance(item, Mapping) or set(item) != required:
                raise GraphError(
                    GraphErrorCode.STATE_INVALID,
                    "VPN graph citation references are invalid",
                )
            result.append({key: str(item[key]) for key in required})
        return tuple(result)

    @staticmethod
    def _invocation() -> _Invocation:
        invocation = _ACTIVE_INVOCATION.get()
        if invocation is None:
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "VPN graph node is outside an execution boundary",
            )
        return invocation


class _VpnNodes:
    def __init__(self, runtime: VpnReadOnlyGraph) -> None:
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
                "knowledge_read_complete": False,
                "service_read_complete": False,
                "service_read_skipped": False,
                "reads_complete": False,
                "knowledge_call_count": 0,
                "citation_count": 0,
                "citation_refs": [],
            },
        )

    async def build_context(self, _state: Mapping[str, Any]) -> Mapping[str, Any]:
        observation = await self._runtime._resolve()
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
                "missing_fields": list(observation.missing_fields),
                "input_complete": not observation.missing_fields,
                "context_id": context.context_id,
                "context_layers": {"L0": True, "L1": True, "L2": True},
            },
        )

    async def route_request(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        if state.get("input_complete") is not True:
            route = "clarification"
        elif state.get("reads_complete") is not True:
            route = "parallel_reads"
        elif state.get("status") in {
            GraphStatus.COMPLETED.value,
            GraphStatus.FAILED.value,
        }:
            route = "terminate"
        else:
            route = "run_agent"
        return self._advance("route_request", {"route": route})

    @staticmethod
    def route_after_request(state: Mapping[str, Any]) -> str | Sequence[str]:
        route = state.get("route")
        if route == "parallel_reads":
            return ("knowledge_read", "service_read")
        if route in {"clarification", "run_agent", "terminate"}:
            return str(route)
        raise GraphError(GraphErrorCode.STATE_INVALID, "VPN request route is invalid")

    async def clarification_interrupt(
        self, state: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        required = state.get("missing_fields", [])
        resume = interrupt(
            {
                "schema": "flowpilot.vpn-clarification.v1",
                "kind": "clarification",
                "observation_ref": state.get("observation_ref"),
                "required_fields": list(required) if isinstance(required, list) else [],
            }
        )
        if not isinstance(resume, Mapping) or resume.get("confirmed") is not True:
            raise _VpnFailure("RUNTIME_CLARIFICATION_INVALID")
        observation = await self._runtime._resolve()
        if observation.missing_fields:
            raise _VpnFailure("RUNTIME_CLARIFICATION_INCOMPLETE")
        return self._advance(
            "clarification_interrupt",
            {
                "observation_ref": observation.observation_ref,
                "missing_fields": [],
                "input_complete": True,
            },
        )

    async def knowledge_read(self, _state: Mapping[str, Any]) -> Mapping[str, Any]:
        observation = await self._runtime._resolve()
        if observation.missing_fields:
            raise _VpnFailure("RUNTIME_CLARIFICATION_REQUIRED")
        result_ref, citations = await self._runtime._knowledge_read(observation)
        return self._advance(
            "knowledge_read",
            {
                "knowledge_read_complete": True,
                "knowledge_call_count": 1,
                "citation_count": len(citations),
                "citation_refs": [citation.to_mapping() for citation in citations],
                "result_ref": result_ref,
            },
            record_current=False,
        )

    async def service_read(self, _state: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._advance(
            "service_read",
            {
                "service_read_complete": True,
                "service_read_skipped": True,
            },
            record_current=False,
        )

    async def join_reads(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        if (
            state.get("knowledge_read_complete") is not True
            or state.get("service_read_complete") is not True
            or state.get("service_read_skipped") is not True
        ):
            raise GraphError(
                GraphErrorCode.PARALLEL_REDUCER_CONFLICT,
                "VPN read branches did not converge safely",
            )
        return self._advance("join_reads", {"reads_complete": True})

    async def handoff(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        observation = await self._runtime._resolve()
        citations = self._runtime._citation_refs(state)
        context = self._runtime._build_context(
            observation,
            task_state={
                "status": GraphStatus.RUNNING.value,
                "observation_ref": observation.observation_ref,
                "result_ref": state.get("result_ref"),
                "citation_refs": [dict(item) for item in citations],
            },
            context_kind="result",
        )
        return self._advance(
            "handoff",
            {
                "context_id": context.context_id,
                "context_rebuilt": True,
                "tool_scope_rebuilt": True,
            },
        )

    async def approval_interrupt(self, _state: Mapping[str, Any]) -> Mapping[str, Any]:
        raise GraphError(
            GraphErrorCode.STATE_INVALID,
            "read-only VPN flow cannot route to approval",
        )

    async def run_agent(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        if not state.get("result_ref") or int(state.get("citation_count", 0)) < 1:
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "VPN response requires an opaque result and citation",
            )
        return self._advance("run_agent", {"runtime_outcome": "completed"})

    async def route_result(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        if state.get("runtime_outcome") != "completed":
            raise GraphError(
                GraphErrorCode.STATE_INVALID, "VPN result route is invalid"
            )
        return self._advance("route_result", {"route": "finalize"})

    @staticmethod
    def route_after_result(state: Mapping[str, Any]) -> str | Sequence[str]:
        if state.get("route") == "finalize":
            return "finalize"
        raise GraphError(GraphErrorCode.STATE_INVALID, "VPN result route is invalid")

    async def retry(self, _state: Mapping[str, Any]) -> Mapping[str, Any]:
        raise GraphError(
            GraphErrorCode.STATE_INVALID, "VPN retry crosses the Worker boundary"
        )

    async def compensate(self, _state: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._advance("compensate", {})

    async def finalize(self, _state: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._advance(
            "finalize",
            {
                "status": GraphStatus.COMPLETED.value,
                "terminal_reason": "VPN_READONLY_COMPLETED",
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


def build_vpn_gateway_call(
    *,
    config: VpnGraphConfig,
    command: TaskCommand,
    observation: RequestObservation,
    run_id: str | None = None,
) -> GatewayCall:
    """Build the stable, tenant-bound read request consumed by GatewayClientPort."""

    if (
        observation.tenant_id != command.tenant_id
        or observation.task_id != command.task_id
    ):
        raise _VpnFailure("RUNTIME_OBSERVATION_BINDING_MISMATCH")
    symptom = observation.fields.get("symptom_code")
    platform = observation.fields.get("platform")
    environment = observation.fields.get("environment")
    for value in (symptom, platform, environment):
        if not isinstance(value, str) or _SAFE_FIELD.fullmatch(value) is None:
            raise _VpnFailure("RUNTIME_OBSERVATION_FIELD_INVALID")
    query = f"error {symptom}"
    expires_at = min(
        command.issued_at + timedelta(minutes=15),
        command.security_context.expires_at,
    )
    action = PlannedAction(
        action_id=VpnReadOnlyGraph._stable_id(
            "act",
            f"{command.tenant_id}:{command.task_id}:{observation.source_digest}",
        ),
        tenant_id=command.tenant_id,
        task_id=command.task_id,
        requester_id=command.actor.id,
        agent=ActionAgent(id=config.agent_id, version=config.agent_version),
        tool=ActionTool(
            name=KNOWLEDGE_TOOL_NAME,
            schema_hash=config.knowledge_schema_pin,
            operation=ToolOperation.READ,
        ),
        arguments={"query": query, "limit": config.knowledge_limit},
        resource=ActionResource(type="knowledge_record", owner_id=command.tenant_id),
        purpose=command.security_context.purpose,
        data_classification=observation.data_classification,
        policy_version=config.policy_version,
        expires_at=expires_at,
    )
    request_id = VpnReadOnlyGraph._stable_id(
        "treq",
        f"{command.tenant_id}:{command.task_id}:{observation.source_digest}",
    )
    policy_decision_id = VpnReadOnlyGraph._stable_id(
        "pd",
        f"{command.tenant_id}:{command.task_id}:{action.digest()}",
    )
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
        action_digest=action.digest(),
        policy_decision_id=policy_decision_id,
        idempotency_key=canonical_sha256(
            {
                "tenant_id": command.tenant_id,
                "task_id": command.task_id,
                "tool": KNOWLEDGE_TOOL_NAME,
                "source_digest": observation.source_digest,
            }
        ),
        requested_at=command.issued_at,
    )
    return GatewayCall(
        request=request,
        thread_id=VpnReadOnlyGraph._stable_id(
            "thread",
            f"{command.tenant_id}:{command.task_id}",
        ),
        run_id=run_id or VpnReadOnlyGraph._stable_id("run", command.task_id),
        correlation_id=command.correlation_id or command.command_id,
    )


def vpn_debug_projection(state: Mapping[str, Any]) -> dict[str, Any]:
    """Expose the safe VPN counters without exposing request or answer content."""

    return debug_projection(state)


__all__ = [
    "KNOWLEDGE_SCHEMA_PIN",
    "KNOWLEDGE_TOOL_NAME",
    "VPN_GRAPH_VERSION",
    "VpnGraphConfig",
    "VpnGraphState",
    "VpnReadOnlyGraph",
    "build_vpn_gateway_call",
    "vpn_debug_projection",
]
