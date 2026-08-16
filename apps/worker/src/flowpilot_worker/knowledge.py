from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, TypedDict, cast
from urllib.parse import quote, unquote, urlsplit

from flowpilot_agent_runtime import (
    CLAUDE_AGENT_PROVIDER,
    OPENAI_AGENTS_PROVIDER,
    AgentMode,
    AgentProfile,
    AgentRunRequest,
    AgentRunResult,
    AgentRuntimePort,
    ContentSafetyError,
    OutputSchemaRef,
    ProviderSelection,
    RunStatus,
    RuntimeBudget,
    validate_runtime_output,
)
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
    SecurityContextValidationPort,
    build_flowpilot_it_service_graph,
)
from flowpilot_model_gateway import PRIMARY_FAST_MODEL
from flowpilot_security import ContentSurface, SecurityError, assert_content_safe
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

from .durable import DurableGraphFactory

KNOWLEDGE_TOOL_NAME = "knowledge.search.v1"
KNOWLEDGE_SCHEMA_PIN = (
    "sha256:b7679fde5be1187e8a36b4cd4dd95a95b63a50dc56532294174b0088f0e6600b"
)
KNOWLEDGE_GRAPH_VERSION = "flowpilot.enterprise-knowledge.m7.v1"
KNOWLEDGE_INTENT = "knowledge_question"
KNOWLEDGE_QUESTION_FIELD = "question"
KNOWLEDGE_AGENT_ID = "enterprise-knowledge-agent"
KNOWLEDGE_AGENT_VERSION = "m7.0"
KNOWLEDGE_AGENT_PRINCIPAL = "workload://flowpilot/enterprise-knowledge/m7"
_OUTPUT_SCHEMA_ID = "schema://flowpilot/enterprise-knowledge-answer/v1"
_OUTPUT_SCHEMA_HASH = canonical_sha256(
    {
        "type": "object",
        "required": ["answer_markdown", "citation_source_refs"],
        "properties": {
            "answer_markdown": {"type": "string"},
            "citation_source_refs": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "additionalProperties": False,
    }
)
_SHA256 = re.compile(r"^sha256:[a-f0-9]{64}$")
_DOCUMENT_VERSION = re.compile(r"^[1-9][0-9]*$")
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


def _default_agent() -> AgentProfile:
    return AgentProfile(
        id=KNOWLEDGE_AGENT_ID,
        version=KNOWLEDGE_AGENT_VERSION,
        prompt_version="enterprise-knowledge-m7-v1",
        mode=AgentMode.STRUCTURED,
        output_schema=OutputSchemaRef(
            id=_OUTPUT_SCHEMA_ID,
            hash=_OUTPUT_SCHEMA_HASH,
        ),
        allowed_tools=(),
        maximum_handoffs=0,
    )


def _default_provider() -> ProviderSelection:
    return ProviderSelection(
        provider=OPENAI_AGENTS_PROVIDER,
        model=PRIMARY_FAST_MODEL,
        data_policy_id="enterprise-knowledge-m7",
        routing_reason_code="ENTERPRISE_KNOWLEDGE_FAST",
    )


def _default_budget() -> RuntimeBudget:
    return RuntimeBudget(
        maximum_turns=1,
        maximum_tool_calls=0,
        maximum_input_tokens=4096,
        maximum_output_tokens=1024,
        maximum_total_tokens=5120,
        maximum_cost_microunits=10_000,
        timeout_ms=30_000,
    )


def _default_context_policy() -> ContextPolicy:
    return ContextPolicy(
        context_policy_version="context-enterprise-knowledge-m7",
        data_classification_ceiling=DataClassification.CONFIDENTIAL,
        provider_allowlist=(OPENAI_AGENTS_PROVIDER,),
        token_budget=4096,
    )


class KnowledgeGraphState(TypedDict, total=False):
    task_ref: str
    status: str
    route: str
    current_node: str
    visited_nodes: Annotated[list[str], _append_unique]
    observation_ref: str
    missing_fields: list[str]
    input_complete: bool
    context_id: str
    knowledge_read_complete: bool
    service_read_complete: bool
    service_read_skipped: bool
    reads_complete: bool
    knowledge_call_count: int
    knowledge_result_digest: str
    model_call_count: int
    citation_count: int
    citation_refs: list[dict[str, str]]
    result_ref: str
    context_rebuilt: bool
    tool_scope_rebuilt: bool
    runtime_outcome: str
    terminal_reason: str
    failure_code: str


@dataclass(frozen=True, slots=True)
class KnowledgeGraphConfig:
    graph_version: str = KNOWLEDGE_GRAPH_VERSION
    intent: str = KNOWLEDGE_INTENT
    question_field: str = KNOWLEDGE_QUESTION_FIELD
    knowledge_schema_pin: str = KNOWLEDGE_SCHEMA_PIN
    knowledge_limit: int = 5
    maximum_attempts: int = 2
    policy_version: str = "policy-m7.0"
    domain_pack_version: str = "it-service-m7.0"
    tool_schema_set: str = "knowledge-search-p1"
    system_policy_ref: str = "policy://enterprise-knowledge/m7"
    agent_principal_ref: str = KNOWLEDGE_AGENT_PRINCIPAL
    agent: AgentProfile = field(default_factory=_default_agent)
    provider: ProviderSelection = field(default_factory=_default_provider)
    budget: RuntimeBudget = field(default_factory=_default_budget)
    context_policy: ContextPolicy = field(default_factory=_default_context_policy)

    def __post_init__(self) -> None:
        if self.graph_version != KNOWLEDGE_GRAPH_VERSION:
            raise ValueError("knowledge graph version is not accepted")
        if self.intent != KNOWLEDGE_INTENT:
            raise ValueError("knowledge graph intent is not accepted")
        if self.question_field != KNOWLEDGE_QUESTION_FIELD:
            raise ValueError("knowledge question field is not accepted")
        if self.knowledge_schema_pin != KNOWLEDGE_SCHEMA_PIN:
            raise ValueError("knowledge schema pin is not accepted")
        if not 1 <= self.knowledge_limit <= 20:
            raise ValueError("knowledge_limit is outside the tool contract")
        if self.maximum_attempts < 1:
            raise ValueError("maximum_attempts must be positive")
        if not self.domain_pack_version or not self.tool_schema_set:
            raise ValueError("knowledge release identifiers must be configured")
        if self.agent.id != KNOWLEDGE_AGENT_ID:
            raise ValueError("knowledge graph requires the accepted agent identity")
        if self.agent.allowed_tools or self.agent.maximum_handoffs != 0:
            raise ValueError("model runtime must not receive tools or handoffs")
        if self.agent.output_schema != OutputSchemaRef(
            id=_OUTPUT_SCHEMA_ID,
            hash=_OUTPUT_SCHEMA_HASH,
        ):
            raise ValueError("knowledge output schema is not accepted")
        if self.provider.model != PRIMARY_FAST_MODEL:
            raise ValueError("knowledge graph must use flowpilot.primary.fast")
        if self.provider.provider not in {
            OPENAI_AGENTS_PROVIDER,
            CLAUDE_AGENT_PROVIDER,
        }:
            raise ValueError("knowledge graph provider is not accepted")
        if self.provider.provider not in self.context_policy.provider_allowlist:
            raise ValueError("selected provider is not allowed by context policy")
        if self.budget.maximum_tool_calls != 0:
            raise ValueError("knowledge model budget must prohibit tool calls")


@dataclass(slots=True)
class _Invocation:
    command: TaskCommand
    execution_ref: str
    lease: LeaseToken
    records: tuple[dict[str, str], ...] = ()
    records_digest: str | None = None
    context: ContextEnvelope | None = None
    runtime_result: AgentRunResult | None = None


class _KnowledgeFailure(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        retryable: bool = False,
        knowledge_called: bool = False,
        model_called: bool = False,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.knowledge_called = knowledge_called
        self.model_called = model_called


_ACTIVE_INVOCATION: ContextVar[_Invocation | None] = ContextVar(
    "flowpilot_enterprise_knowledge_invocation",
    default=None,
)


class EnterpriseKnowledgeGraph(GraphExecutionPort):
    """Recoverable enterprise knowledge Q&A over approved internal ports."""

    def __init__(
        self,
        *,
        requests: RequestObservationService,
        artifacts: ResultArtifactService,
        gateway: GatewayClientPort,
        runtime: AgentRuntimePort,
        security_contexts: SecurityContextValidationPort,
        checkpoints: CheckpointPort,
        context_builder: ContextBuilder,
        config: KnowledgeGraphConfig | None = None,
        clock: Callable[[], datetime] | None = None,
        checkpointer: Any | None = None,
    ) -> None:
        self._requests = requests
        self._artifacts = artifacts
        self._gateway = gateway
        self._runtime = runtime
        self._security_contexts = security_contexts
        self._checkpoints = checkpoints
        self._context_builder = context_builder
        self._config = config or KnowledgeGraphConfig()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._checkpointer = checkpointer or InMemorySaver()
        self.last_safe_state: Mapping[str, Any] | None = None
        self.built_contexts: list[ContextEnvelope] = []
        nodes = _KnowledgeNodes(self)
        self._definition = build_flowpilot_it_service_graph(
            KnowledgeGraphState,
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
        await self._validate_current_context(command)
        current = await self._load_or_initialize(command, lease)
        if current.status in {GraphStatus.COMPLETED, GraphStatus.FAILED}:
            return GraphRunOutcome(current, None, False)

        was_waiting = current.status is GraphStatus.WAITING_USER
        if was_waiting and command.command_type is not CommandType.SUBMIT_MESSAGE:
            raise GraphError(
                GraphErrorCode.COMMAND_UNSUPPORTED,
                "knowledge clarification requires a submitted message reference",
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
            command,
            execution_ref,
            lease,
            records_digest=current.knowledge_result_digest,
        )
        token = _ACTIVE_INVOCATION.set(invocation)
        graph_config = {"configurable": {"thread_id": self._graph_thread_id(command)}}
        try:
            graph_input: Mapping[str, Any] | Command[Any]
            if was_waiting and await self._has_graph_checkpoint(graph_config):
                graph_input = Command(resume={"confirmed": True})
            else:
                graph_input = {
                    "task_ref": self._opaque_task_ref(command),
                    "knowledge_call_count": current.knowledge_call_count,
                    "knowledge_result_digest": current.knowledge_result_digest,
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
                    pending_reason="user_input:question",
                    observation_ref=self._optional_text(result.get("observation_ref")),
                    knowledge_call_count=self._count(
                        result.get("knowledge_call_count")
                    ),
                    knowledge_result_digest=self._optional_text(
                        result.get("knowledge_result_digest")
                    ),
                    citation_count=self._count(result.get("citation_count")),
                    service_read_skipped=result.get("service_read_skipped") is True,
                )
                waiting = await self._save(waiting, lease)
                return GraphRunOutcome(waiting, None, False)
            if result.get("status") != GraphStatus.COMPLETED.value:
                raise GraphError(
                    GraphErrorCode.STATE_INVALID,
                    "knowledge graph ended without an authoritative terminal state",
                )
            result_ref = self._required_text(result.get("result_ref"))
            citations = self._citation_refs(result)
            completed = current.transition(
                GraphStatus.COMPLETED,
                node=GraphNode.FINALIZE,
                context_id=self._optional_text(result.get("context_id")),
                result_ref=result_ref,
                observation_ref=self._optional_text(result.get("observation_ref")),
                knowledge_call_count=self._count(result.get("knowledge_call_count")),
                knowledge_result_digest=self._required_digest(
                    result.get("knowledge_result_digest")
                ),
                citation_count=len(citations),
                reference_refs=tuple(item["source_ref"] for item in citations),
                citation_bindings=tuple(dict(item) for item in citations),
                service_read_skipped=result.get("service_read_skipped") is True,
                failure_code=None,
            )
            completed = await self._save(completed, lease)
            return GraphRunOutcome(
                completed,
                invocation.runtime_result,
                False,
            )
        except _KnowledgeFailure as failure:
            knowledge_count = max(
                current.knowledge_call_count,
                1 if failure.knowledge_called else 0,
            )
            should_retry = (
                failure.retryable
                and current.attempt_count < self._config.maximum_attempts
            )
            failed = current.transition(
                GraphStatus.RETRY_PENDING if should_retry else GraphStatus.FAILED,
                node=GraphNode.RUN_AGENT if should_retry else GraphNode.FINALIZE,
                failure_code=failure.code,
                knowledge_call_count=knowledge_count,
                knowledge_result_digest=(
                    invocation.records_digest or current.knowledge_result_digest
                ),
            )
            failed = await self._save(failed, lease)
            return GraphRunOutcome(failed, invocation.runtime_result, should_retry)
        finally:
            _ACTIVE_INVOCATION.reset(token)

    async def _validate_current_context(
        self,
        command: TaskCommand | None = None,
    ) -> None:
        presented = (command or self._invocation().command).security_context
        current = await self._security_contexts.validate_current(presented)
        if current.to_mapping() != presented.to_mapping():
            raise GraphError(
                GraphErrorCode.SECURITY_BINDING_MISMATCH,
                "resolved security context does not match the graph command",
            )

    async def _resolve(self) -> RequestObservation:
        try:
            observation = await self._requests.resolve(self._invocation().command)
        except ApplicationError as exc:
            raise _KnowledgeFailure(
                exc.code.value,
                retryable=exc.retryable,
            ) from exc
        if observation.intent != self._config.intent:
            raise _KnowledgeFailure("RUNTIME_KNOWLEDGE_INTENT_UNSUPPORTED")
        return observation

    async def _fetch_records(
        self,
        observation: RequestObservation,
    ) -> tuple[dict[str, str], ...]:
        invocation = self._invocation()
        if invocation.records:
            return invocation.records
        records = await self._query_records(observation)
        invocation.records = records
        invocation.records_digest = self._records_digest(records)
        return records

    async def _query_records(
        self,
        observation: RequestObservation,
    ) -> tuple[dict[str, str], ...]:
        await self._validate_current_context()
        invocation = self._invocation()
        call = build_knowledge_gateway_call(
            config=self._config,
            command=invocation.command,
            observation=observation,
            run_id=invocation.lease.run_id,
        )
        try:
            result = await self._gateway.execute(call)
        except GatewayPortError as exc:
            raise _KnowledgeFailure(
                exc.code.value,
                knowledge_called=True,
            ) from exc
        except SecurityError as exc:
            raise _KnowledgeFailure(
                exc.code.value,
                knowledge_called=True,
            ) from exc
        except Exception as exc:
            raise _KnowledgeFailure(
                "RUNTIME_KNOWLEDGE_GATEWAY_UNAVAILABLE",
                retryable=True,
                knowledge_called=True,
            ) from exc
        records = self._verified_records(result, call)
        if not records:
            raise _KnowledgeFailure(
                "RUNTIME_KNOWLEDGE_NO_RESULT",
                knowledge_called=True,
            )
        return records

    async def _revalidate_records(
        self,
        observation: RequestObservation,
        *,
        expected_digest: str,
    ) -> tuple[dict[str, str], ...]:
        records = await self._query_records(observation)
        current_digest = self._records_digest(records)
        if current_digest != expected_digest:
            raise _KnowledgeFailure(
                "RUNTIME_KNOWLEDGE_REFERENCE_DRIFT",
                knowledge_called=True,
            )
        invocation = self._invocation()
        invocation.records = records
        invocation.records_digest = current_digest
        return records

    def _build_context(
        self,
        observation: RequestObservation,
        records: tuple[dict[str, str], ...],
    ) -> ContextEnvelope:
        invocation = self._invocation()
        command = invocation.command
        question = _knowledge_question(self._config, observation)
        policy = replace(
            self._config.context_policy,
            data_classification_ceiling=self._effective_ceiling(command),
        )
        try:
            context = self._context_builder.build(
                ContextBuildRequest(
                    context_id=self._stable_id(
                        "ctx",
                        f"{command.task_id}:{command.command_id}:{observation.source_digest}",
                    ),
                    task_id=command.task_id,
                    agent_id=self._config.agent.id,
                    purpose=command.security_context.purpose,
                    security_context=command.security_context,
                    task_state={
                        "status": GraphStatus.RUNNING.value,
                        "intent": observation.intent,
                        "observation_ref": observation.observation_ref,
                        "question": question,
                        "knowledge_sources": [dict(record) for record in records],
                    },
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
            raise _KnowledgeFailure(str(code or "RUNTIME_CONTEXT_INVALID")) from exc
        invocation.context = context
        self.built_contexts.append(context)
        return context

    async def _run_model(
        self,
        observation: RequestObservation,
        records: tuple[dict[str, str], ...],
    ) -> tuple[str, tuple[ResultCitation, ...]]:
        invocation = self._invocation()
        await self._validate_current_context()
        context = invocation.context or self._build_context(observation, records)
        command = invocation.command
        request = AgentRunRequest(
            request_id=self._stable_id(
                "arq",
                f"{command.task_id}:{command.command_id}:{observation.source_digest}",
            ),
            task_id=command.task_id,
            tenant_id=command.tenant_id,
            trace_id=hashlib.sha256(
                (command.correlation_id or command.command_id).encode()
            ).hexdigest()[:32],
            run_id=invocation.lease.run_id,
            agent=self._config.agent,
            context=context,
            security_context=command.security_context,
            provider_selection=self._config.provider,
            budget=self._config.budget,
            session_ref=None,
            issued_at=self._utc(self._clock(), "clock"),
        )
        try:
            result = await self._runtime.run(request)
        except Exception as exc:
            raise _KnowledgeFailure(
                "RUNTIME_PROVIDER_UNAVAILABLE",
                retryable=True,
                knowledge_called=True,
                model_called=True,
            ) from exc
        await self._validate_current_context()
        try:
            validate_runtime_output(
                structured_output=(
                    result.structured_output
                    if isinstance(result.structured_output, Mapping)
                    else {}
                ),
                public_reasoning_summary=result.public_reasoning_summary,
                tool_proposals=result.tool_proposals,
            )
        except ContentSafetyError as exc:
            raise _KnowledgeFailure(
                exc.code.value,
                knowledge_called=True,
                model_called=True,
            ) from None
        invocation.runtime_result = result
        if (
            result.request_id != request.request_id
            or result.trace_id != request.trace_id
            or result.provider_name != request.provider_selection.provider
            or result.provider_model != request.provider_selection.model
        ):
            raise _KnowledgeFailure(
                "RUNTIME_MODEL_RESULT_BINDING_MISMATCH",
                knowledge_called=True,
                model_called=True,
            )
        if result.status is RunStatus.FAILED_RETRYABLE:
            raise _KnowledgeFailure(
                (
                    result.error.code.value
                    if result.error
                    else "RUNTIME_PROVIDER_UNAVAILABLE"
                ),
                retryable=True,
                knowledge_called=True,
                model_called=True,
            )
        if result.status is not RunStatus.COMPLETED:
            raise _KnowledgeFailure(
                result.error.code.value if result.error else "RUNTIME_MODEL_FAILED",
                knowledge_called=True,
                model_called=True,
            )
        if (
            result.tool_proposals
            or result.tool_call_refs
            or result.handoff_proposal is not None
        ):
            raise _KnowledgeFailure(
                "RUNTIME_MODEL_AUTHORITY_VIOLATION",
                knowledge_called=True,
                model_called=True,
            )
        records = await self._revalidate_records(
            observation,
            expected_digest=self._records_digest(records),
        )
        answer, citations = self._validated_answer(result, records)
        projection = {
            "tenant_id": command.tenant_id,
            "task_id": command.task_id,
            "media_type": "text/markdown",
            "content": answer,
            "citations": [citation.to_mapping() for citation in citations],
        }
        draft = ResultArtifactDraft(
            tenant_id=command.tenant_id,
            task_id=command.task_id,
            idempotency_key=canonical_sha256(
                {
                    "tenant_id": command.tenant_id,
                    "task_id": command.task_id,
                    "runtime_request_id": request.request_id,
                }
            ),
            media_type="text/markdown",
            content=answer,
            citations=citations,
            result_digest=canonical_sha256(projection),
        )
        try:
            receipt = await self._artifacts.save(draft)
        except ApplicationError as exc:
            raise _KnowledgeFailure(
                exc.code.value,
                retryable=exc.retryable,
                knowledge_called=True,
                model_called=True,
            ) from exc
        if receipt.result_ref is None:
            raise _KnowledgeFailure(
                "RUNTIME_RESULT_REFERENCE_MISSING",
                knowledge_called=True,
                model_called=True,
            )
        return receipt.result_ref, citations

    def _validated_answer(
        self,
        result: AgentRunResult,
        records: tuple[dict[str, str], ...],
    ) -> tuple[str, tuple[ResultCitation, ...]]:
        output = result.structured_output
        if not isinstance(output, Mapping) or set(output) != {
            "answer_markdown",
            "citation_source_refs",
        }:
            raise _KnowledgeFailure(
                "RUNTIME_MODEL_OUTPUT_INVALID",
                knowledge_called=True,
                model_called=True,
            )
        answer = output.get("answer_markdown")
        raw_refs = output.get("citation_source_refs")
        if (
            not isinstance(answer, str)
            or not answer.strip()
            or len(answer) > 64 * 1024
            or not isinstance(raw_refs, (tuple, list))
            or not raw_refs
            or any(not isinstance(item, str) for item in raw_refs)
            or len(raw_refs) != len(set(raw_refs))
        ):
            raise _KnowledgeFailure(
                "RUNTIME_MODEL_OUTPUT_INVALID",
                knowledge_called=True,
                model_called=True,
            )
        by_ref = {record["source_ref"]: record for record in records}
        if not set(raw_refs) <= set(by_ref):
            raise _KnowledgeFailure(
                "RUNTIME_MODEL_CITATION_INVALID",
                knowledge_called=True,
                model_called=True,
            )
        citations = tuple(
            ResultCitation(
                source_ref=by_ref[source_ref]["source_ref"],
                document_version=by_ref[source_ref]["document_version"],
                section=by_ref[source_ref]["section"],
                content_hash=by_ref[source_ref]["content_hash"],
            )
            for source_ref in cast(Sequence[str], raw_refs)
        )
        return answer, citations

    def _verified_records(
        self,
        result: ToolResult,
        call: GatewayCall,
    ) -> tuple[dict[str, str], ...]:
        try:
            assert_content_safe(
                result.to_mapping(),
                surface=ContentSurface.TOOL_RESULT,
                field="knowledge_tool_result",
            )
        except SecurityError as exc:
            raise _KnowledgeFailure(
                exc.code.value,
                knowledge_called=True,
            ) from None
        if (
            result.request_id != call.request.request_id
            or result.policy_decision_id != call.request.policy_decision_id
            or result.operation is not ToolOperation.READ
        ):
            raise _KnowledgeFailure(
                "RUNTIME_KNOWLEDGE_RESULT_BINDING_MISMATCH",
                knowledge_called=True,
            )
        if result.status is ToolResultStatus.FAILED_RETRYABLE:
            raise _KnowledgeFailure(
                result.error_code or "RUNTIME_KNOWLEDGE_RETRYABLE",
                retryable=True,
                knowledge_called=True,
            )
        if result.status is ToolResultStatus.UNKNOWN:
            raise _KnowledgeFailure(
                "RUNTIME_KNOWLEDGE_OUTCOME_UNKNOWN",
                knowledge_called=True,
            )
        if result.status is ToolResultStatus.FAILED_FINAL:
            raise _KnowledgeFailure(
                result.error_code or "RUNTIME_KNOWLEDGE_FAILED",
                knowledge_called=True,
            )
        if result.status is not ToolResultStatus.VERIFIED or result.data is None:
            raise _KnowledgeFailure(
                "RUNTIME_KNOWLEDGE_RESULT_INVALID",
                knowledge_called=True,
            )
        try:
            output_classification = DataClassification(result.output_classification)
        except (TypeError, ValueError) as exc:
            raise _KnowledgeFailure(
                "RUNTIME_KNOWLEDGE_RESULT_INVALID",
                knowledge_called=True,
            ) from exc
        ceiling = self._effective_ceiling(self._invocation().command)
        if _CLASSIFICATION_RANK[output_classification] > _CLASSIFICATION_RANK[ceiling]:
            raise _KnowledgeFailure(
                "RUNTIME_KNOWLEDGE_CLASSIFICATION_DENIED",
                knowledge_called=True,
            )
        if set(result.data) != {"records", "returned_count"}:
            raise _KnowledgeFailure(
                "RUNTIME_KNOWLEDGE_RESULT_INVALID",
                knowledge_called=True,
            )
        raw_records = result.data.get("records")
        returned_count = result.data.get("returned_count")
        if (
            not isinstance(raw_records, (tuple, list))
            or isinstance(returned_count, bool)
            or not isinstance(returned_count, int)
            or returned_count != len(raw_records)
            or returned_count > self._config.knowledge_limit
        ):
            raise _KnowledgeFailure(
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
                raise _KnowledgeFailure(
                    "RUNTIME_KNOWLEDGE_RESULT_INVALID",
                    knowledge_called=True,
                )
            if any(not isinstance(raw[key], str) or not raw[key] for key in allowed):
                raise _KnowledgeFailure(
                    "RUNTIME_KNOWLEDGE_RESULT_INVALID",
                    knowledge_called=True,
                )
            record = {key: cast(str, raw[key]) for key in allowed}
            try:
                classification = DataClassification(record["classification"])
            except ValueError as exc:
                raise _KnowledgeFailure(
                    "RUNTIME_KNOWLEDGE_RESULT_INVALID",
                    knowledge_called=True,
                ) from exc
            if _CLASSIFICATION_RANK[classification] > _CLASSIFICATION_RANK[ceiling]:
                raise _KnowledgeFailure(
                    "RUNTIME_KNOWLEDGE_CLASSIFICATION_DENIED",
                    knowledge_called=True,
                )
            if (
                _SHA256.fullmatch(record["content_hash"]) is None
                or _CLASSIFICATION_RANK[classification]
                > _CLASSIFICATION_RANK[output_classification]
                or len(record["redacted_summary"]) > 2048
                or any(
                    ord(character) < 32 and character not in "\n\r\t"
                    for character in record["redacted_summary"]
                )
                or not self._source_ref_matches(record)
                or record["source_ref"] in seen
            ):
                raise _KnowledgeFailure(
                    "RUNTIME_KNOWLEDGE_RESULT_INVALID",
                    knowledge_called=True,
                )
            seen.add(record["source_ref"])
            records.append(record)
        return tuple(records)

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
                "knowledge checkpoint requires an explicit migration",
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
                "command does not match the knowledge checkpoint binding",
            )
        same_command = current.command_id == command.command_id
        if same_command and current.command_digest != command.command_digest:
            raise GraphError(
                GraphErrorCode.SECURITY_BINDING_MISMATCH,
                "replayed command does not match the checkpoint digest",
            )
        if current.status is GraphStatus.RUNNING and not same_command:
            raise GraphError(
                GraphErrorCode.COMMAND_MISMATCH,
                "an in-flight knowledge graph cannot switch commands",
            )
        if lease.run_generation < current.run_generation:
            raise GraphError(
                GraphErrorCode.LEASE_LOST,
                "worker lease generation is older than the checkpoint",
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
        return getter is not None and await getter(config) is not None

    def _effective_ceiling(self, command: TaskCommand) -> DataClassification:
        return min(
            (
                command.security_context.data_classification_ceiling,
                self._config.context_policy.data_classification_ceiling,
            ),
            key=_CLASSIFICATION_RANK.__getitem__,
        )

    @staticmethod
    def _validate_command(command: TaskCommand) -> None:
        if command.command_type not in {CommandType.CREATE, CommandType.SUBMIT_MESSAGE}:
            raise GraphError(
                GraphErrorCode.COMMAND_UNSUPPORTED,
                "knowledge graph accepts only request-reference commands",
            )
        try:
            command.assert_digest()
            command.assert_security_binding()
        except DomainViolation as exc:
            raise GraphError(
                GraphErrorCode.SECURITY_BINDING_MISMATCH,
                "command failed deterministic knowledge security binding",
            ) from exc

    @staticmethod
    def _invocation() -> _Invocation:
        invocation = _ACTIVE_INVOCATION.get()
        if invocation is None:
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "knowledge node is outside an execution boundary",
            )
        return invocation

    @staticmethod
    def _stable_id(prefix: str, value: str) -> str:
        return f"{prefix}_{hashlib.sha256(value.encode()).hexdigest()[:20]}"

    @classmethod
    def _graph_thread_id(cls, command: TaskCommand) -> str:
        return cls._stable_id("thread", f"graph:{command.tenant_id}:{command.task_id}")

    @classmethod
    def _opaque_task_ref(cls, command: TaskCommand) -> str:
        return "task://sha256/" + hashlib.sha256(
            f"{command.tenant_id}:{command.task_id}".encode()
        ).hexdigest()[:20]

    @staticmethod
    def _required_text(value: object) -> str:
        if not isinstance(value, str) or not value:
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "knowledge graph result is missing a required reference",
            )
        return value

    @staticmethod
    def _required_digest(value: object) -> str:
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "knowledge graph result is missing a verified result digest",
            )
        return value

    @staticmethod
    def _optional_text(value: object) -> str | None:
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _count(value: object) -> int:
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        return 0

    def _citation_refs(
        self,
        state: Mapping[str, Any],
    ) -> tuple[dict[str, str], ...]:
        value = state.get("citation_refs", ())
        required = {
            "source_ref",
            "document_version",
            "section",
            "redacted_summary",
            "content_hash",
            "classification",
        }
        if not isinstance(value, (tuple, list)):
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "knowledge citation references are invalid",
            )
        result: list[dict[str, str]] = []
        for item in value:
            if not isinstance(item, Mapping) or set(item) != required:
                raise GraphError(
                    GraphErrorCode.STATE_INVALID,
                    "knowledge citation references are invalid",
                )
            binding = {key: str(item[key]) for key in required}
            if not self._source_ref_matches(binding):
                raise GraphError(
                    GraphErrorCode.STATE_INVALID,
                    "knowledge citation references are invalid",
                )
            result.append(binding)
        return tuple(result)

    @staticmethod
    def _records_digest(records: Sequence[Mapping[str, str]]) -> str:
        return canonical_sha256(
            [
                dict(record)
                for record in sorted(
                    records,
                    key=lambda item: item["source_ref"],
                )
            ]
        )

    def _source_ref_matches(self, record: Mapping[str, str]) -> bool:
        source_ref = record.get("source_ref", "")
        version = record.get("document_version", "")
        section = record.get("section", "")
        if (
            len(source_ref) > 512
            or _DOCUMENT_VERSION.fullmatch(version) is None
            or any(ord(character) < 33 for character in source_ref)
        ):
            return False
        parsed = urlsplit(source_ref)
        path_parts = parsed.path.removeprefix("/").split("/")
        document_id = unquote(path_parts[0]) if len(path_parts) == 2 else ""
        return (
            parsed.scheme == "knowledge"
            and parsed.netloc
            == quote(self._invocation().command.tenant_id, safe="")
            and parsed.query == ""
            and len(path_parts) == 2
            and bool(document_id)
            and document_id not in {".", ".."}
            and path_parts[0] == quote(document_id, safe="")
            and path_parts[1] == quote(version, safe="")
            and parsed.fragment == quote(section, safe="")
        )

    @staticmethod
    def _utc(value: datetime, field_name: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field_name} must be timezone-aware")
        return value.astimezone(UTC)


class _KnowledgeNodes:
    def __init__(self, runtime: EnterpriseKnowledgeGraph) -> None:
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
                "model_call_count": 0,
                "citation_count": 0,
                "citation_refs": [],
            },
        )

    async def build_context(self, _state: Mapping[str, Any]) -> Mapping[str, Any]:
        observation = await self._runtime._resolve()
        return self._advance(
            "build_context",
            {
                "observation_ref": observation.observation_ref,
                "missing_fields": list(observation.missing_fields),
                "input_complete": not observation.missing_fields,
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
        raise GraphError(GraphErrorCode.STATE_INVALID, "knowledge route is invalid")

    async def clarification_interrupt(
        self,
        state: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        required = state.get("missing_fields", [])
        resume = interrupt(
            {
                "schema": "flowpilot.knowledge-clarification.v1",
                "kind": "clarification",
                "observation_ref": state.get("observation_ref"),
                "required_fields": list(required) if isinstance(required, list) else [],
            }
        )
        if not isinstance(resume, Mapping) or resume.get("confirmed") is not True:
            raise _KnowledgeFailure("RUNTIME_CLARIFICATION_INVALID")
        observation = await self._runtime._resolve()
        if observation.missing_fields:
            raise _KnowledgeFailure("RUNTIME_CLARIFICATION_INCOMPLETE")
        return self._advance(
            "clarification_interrupt",
            {
                "observation_ref": observation.observation_ref,
                "missing_fields": [],
                "input_complete": True,
            },
        )

    async def knowledge_read(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        observation = await self._runtime._resolve()
        if observation.missing_fields:
            raise _KnowledgeFailure("RUNTIME_CLARIFICATION_REQUIRED")
        expected_digest = self._runtime._optional_text(
            state.get("knowledge_result_digest")
        )
        records = (
            await self._runtime._revalidate_records(
                observation,
                expected_digest=self._runtime._required_digest(expected_digest),
            )
            if expected_digest is not None
            else await self._runtime._fetch_records(observation)
        )
        return self._advance(
            "knowledge_read",
            {
                "knowledge_read_complete": True,
                "knowledge_call_count": 1,
                "knowledge_result_digest": self._runtime._records_digest(records),
                "citation_count": 0,
                "citation_refs": [],
            },
            record_current=False,
        )

    async def service_read(self, _state: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._advance(
            "service_read",
            {"service_read_complete": True, "service_read_skipped": True},
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
                "knowledge read branches did not converge safely",
            )
        return self._advance("join_reads", {"reads_complete": True})

    async def handoff(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        await self._runtime._validate_current_context()
        observation = await self._runtime._resolve()
        expected_digest = self._runtime._required_digest(
            state.get("knowledge_result_digest")
        )
        records = await self._runtime._revalidate_records(
            observation,
            expected_digest=expected_digest,
        )
        context = self._runtime._build_context(observation, records)
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
            "read-only knowledge flow cannot route to approval",
        )

    async def run_agent(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        observation = await self._runtime._resolve()
        expected_digest = self._runtime._required_digest(
            state.get("knowledge_result_digest")
        )
        records = await self._runtime._revalidate_records(
            observation,
            expected_digest=expected_digest,
        )
        result_ref, citations = await self._runtime._run_model(observation, records)
        by_ref = {record["source_ref"]: record for record in records}
        return self._advance(
            "run_agent",
            {
                "runtime_outcome": "completed",
                "model_call_count": 1,
                "result_ref": result_ref,
                "citation_count": len(citations),
                "citation_refs": [
                    dict(by_ref[citation.source_ref]) for citation in citations
                ],
            },
        )

    async def route_result(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        if state.get("runtime_outcome") != "completed":
            raise GraphError(GraphErrorCode.STATE_INVALID, "model result is invalid")
        return self._advance("route_result", {"route": "finalize"})

    @staticmethod
    def route_after_result(state: Mapping[str, Any]) -> str | Sequence[str]:
        if state.get("route") == "finalize":
            return "finalize"
        raise GraphError(GraphErrorCode.STATE_INVALID, "result route is invalid")

    async def retry(self, _state: Mapping[str, Any]) -> Mapping[str, Any]:
        raise GraphError(
            GraphErrorCode.STATE_INVALID,
            "knowledge retry must cross the Worker queue boundary",
        )

    async def compensate(self, _state: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._advance("compensate", {})

    async def finalize(self, _state: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._advance(
            "finalize",
            {
                "status": GraphStatus.COMPLETED.value,
                "terminal_reason": "ENTERPRISE_KNOWLEDGE_COMPLETED",
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


def build_knowledge_gateway_call(
    *,
    config: KnowledgeGraphConfig,
    command: TaskCommand,
    observation: RequestObservation,
    run_id: str | None = None,
) -> GatewayCall:
    if (
        observation.tenant_id != command.tenant_id
        or observation.task_id != command.task_id
        or observation.intent != config.intent
    ):
        raise _KnowledgeFailure("RUNTIME_OBSERVATION_BINDING_MISMATCH")
    question = _knowledge_question(config, observation)
    expires_at = min(
        command.issued_at + timedelta(minutes=15),
        command.security_context.expires_at,
    )
    action = PlannedAction(
        action_id=EnterpriseKnowledgeGraph._stable_id(
            "act",
            f"{command.tenant_id}:{command.task_id}:{observation.source_digest}",
        ),
        tenant_id=command.tenant_id,
        task_id=command.task_id,
        requester_id=command.actor.id,
        agent=ActionAgent(id=config.agent.id, version=config.agent.version),
        tool=ActionTool(
            name=KNOWLEDGE_TOOL_NAME,
            schema_hash=config.knowledge_schema_pin,
            operation=ToolOperation.READ,
        ),
        arguments={"query": question, "limit": config.knowledge_limit},
        resource=ActionResource(type="knowledge_record", owner_id=command.tenant_id),
        purpose=command.security_context.purpose,
        data_classification=observation.data_classification,
        policy_version=config.policy_version,
        expires_at=expires_at,
    )
    request_id = EnterpriseKnowledgeGraph._stable_id(
        "treq",
        f"{command.tenant_id}:{command.task_id}:{observation.source_digest}",
    )
    policy_decision_id = EnterpriseKnowledgeGraph._stable_id(
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
            id=config.agent.id,
            version=config.agent.version,
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
        thread_id=EnterpriseKnowledgeGraph._stable_id(
            "thread",
            f"{command.tenant_id}:{command.task_id}",
        ),
        run_id=run_id,
        correlation_id=command.correlation_id or command.command_id,
    )


def _knowledge_question(
    config: KnowledgeGraphConfig,
    observation: RequestObservation,
) -> str:
    raw_question = observation.fields.get(config.question_field)
    if not isinstance(raw_question, str):
        raise _KnowledgeFailure("RUNTIME_KNOWLEDGE_QUESTION_INVALID")
    question = raw_question.strip()
    if (
        not question
        or len(question) > 256
        or any(
            ord(character) < 32 and character not in "\t\n\r"
            for character in question
        )
    ):
        raise _KnowledgeFailure("RUNTIME_KNOWLEDGE_QUESTION_INVALID")
    return question


class EnterpriseKnowledgeDurableGraphFactory:
    def __init__(
        self,
        *,
        requests: RequestObservationService,
        artifacts: ResultArtifactService,
        gateway: GatewayClientPort,
        runtime: AgentRuntimePort,
        security_contexts: SecurityContextValidationPort,
        config: KnowledgeGraphConfig | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._requests = requests
        self._artifacts = artifacts
        self._gateway = gateway
        self._runtime = runtime
        self._security_contexts = security_contexts
        self._config = config
        self._clock = clock or (lambda: datetime.now(UTC))

    def __call__(
        self,
        *,
        checkpoints: CheckpointPort,
        control_checkpointer: object,
    ) -> GraphExecutionPort:
        return EnterpriseKnowledgeGraph(
            requests=self._requests,
            artifacts=self._artifacts,
            gateway=self._gateway,
            runtime=self._runtime,
            security_contexts=self._security_contexts,
            checkpoints=checkpoints,
            context_builder=ContextBuilder(clock=self._clock),
            config=self._config,
            clock=self._clock,
            checkpointer=control_checkpointer,
        )

    @staticmethod
    def as_durable_factory(
        factory: EnterpriseKnowledgeDurableGraphFactory,
    ) -> DurableGraphFactory:
        return factory


__all__ = [
    "KNOWLEDGE_AGENT_ID",
    "KNOWLEDGE_GRAPH_VERSION",
    "KNOWLEDGE_INTENT",
    "KNOWLEDGE_QUESTION_FIELD",
    "KNOWLEDGE_SCHEMA_PIN",
    "KNOWLEDGE_TOOL_NAME",
    "EnterpriseKnowledgeDurableGraphFactory",
    "EnterpriseKnowledgeGraph",
    "KnowledgeGraphConfig",
    "KnowledgeGraphState",
    "build_knowledge_gateway_call",
]
