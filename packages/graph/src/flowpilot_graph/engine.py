from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol

from flowpilot_agent_runtime import (
    AgentProfile,
    AgentRunRequest,
    AgentRunResult,
    AgentRuntimePort,
    ProviderSelection,
    RunStatus,
    RuntimeBudget,
)
from flowpilot_context import (
    ContextBudgetLedger,
    ContextBuilder,
    ContextBuildRequest,
    ContextEnvelope,
    ContextError,
    ContextErrorCode,
    ContextPolicy,
    HandoffBundle,
    LayeredSummary,
    build_summary_layer,
    estimate_tokens,
    forbidden_field_scan,
)
from flowpilot_domain import (
    CommandType,
    DomainViolation,
    SecurityContextRef,
    TaskCommand,
)

from .errors import GraphError, GraphErrorCode
from .ports import CheckpointPort, LeaseToken
from .state import GraphNode, GraphState, GraphStatus


@dataclass(frozen=True, slots=True)
class RuntimeGraphConfig:
    graph_version: str
    context_policy: ContextPolicy
    agent: AgentProfile
    provider: ProviderSelection
    budget: RuntimeBudget
    maximum_attempts: int = 2
    system_policy_ref: str = "policy://runtime/v1"
    # M4-2 (FP-CTX-004): hard cumulative conversation budget.  When unset
    # the single-call ceiling is reused as the whole-conversation ceiling.
    cumulative_token_budget: int | None = None
    maximum_conversation_rounds: int = 50
    # Optional escalation sink: fired for budget exhaustion and denied
    # boundary-crossing handoffs so callers can route audit events.
    on_escalation: Callable[[Mapping[str, Any]], None] | None = None

    def __post_init__(self) -> None:
        if self.maximum_attempts < 1:
            raise ValueError("maximum graph attempts must be positive")
        if (
            self.cumulative_token_budget is not None
            and self.cumulative_token_budget < 1
        ):
            raise ValueError("cumulative token budget must be positive")
        if self.maximum_conversation_rounds < 1:
            raise ValueError("maximum conversation rounds must be positive")


@dataclass(frozen=True, slots=True)
class GraphRunOutcome:
    state: GraphState
    runtime_result: AgentRunResult | None
    should_retry: bool


@dataclass(frozen=True, slots=True)
class ProviderSelectionTrace:
    """Trace-visible record of the provider used by one runtime node run."""

    trace_id: str
    run_id: str
    node: GraphNode
    provider: str
    model: str
    provider_run_ref: str | None


@dataclass(frozen=True, slots=True)
class PreparedGraphRun:
    state: GraphState
    request: AgentRunRequest | None
    terminal_outcome: GraphRunOutcome | None


@dataclass(frozen=True, slots=True)
class HandoffDecision:
    """Boundary verdict for a proposed handoff (FP-AGT-004)."""

    allowed: bool
    boundary: str | None = None
    reason: str | None = None
    audit_event: Mapping[str, Any] | None = None


class GraphExecutionPort(Protocol):
    async def execute(
        self,
        command: TaskCommand,
        *,
        execution_ref: str,
        lease: LeaseToken,
    ) -> GraphRunOutcome: ...


# Graph phases that own an approval or an execution step must never be
# bypassed by a handoff (FP-AGT-004): the approval card is bound to this
# task and the execution path has consumed authority that a target agent
# has not been vetted for.
_APPROVAL_BOUNDARY_STATUSES = frozenset({GraphStatus.WAITING_APPROVAL})
_EXECUTION_BOUNDARY_STATUSES = frozenset({GraphStatus.RETRY_PENDING})


class RuntimeGraphKernel:
    """Deterministic graph kernel used by StateGraph and conformance tests."""

    def __init__(
        self,
        *,
        config: RuntimeGraphConfig,
        context_builder: ContextBuilder,
        runtime: AgentRuntimePort,
        checkpoints: CheckpointPort,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._context_builder = context_builder
        self._runtime = runtime
        self._checkpoints = checkpoints
        self._clock = clock or (lambda: datetime.now(UTC))
        self._provider_traces: list[ProviderSelectionTrace] = []
        self._ledger = ContextBudgetLedger(
            cumulative_token_budget=(
                config.cumulative_token_budget
                if config.cumulative_token_budget is not None
                else config.context_policy.token_budget
            ),
            maximum_rounds=config.maximum_conversation_rounds,
        )
        # Append-only escalation/audit trail for budget exhaustion and
        # denied boundary-crossing handoffs (FP-FLOW-006 / FP-AGT-004).
        self.escalation_events: list[Mapping[str, Any]] = []

    @property
    def provider_selections(self) -> tuple[ProviderSelectionTrace, ...]:
        """Trace-visible provider selections recorded by runtime node runs."""
        return tuple(self._provider_traces)

    @property
    def ledger(self) -> ContextBudgetLedger:
        """Cross-turn token accounting for this kernel (FP-CTX-004)."""
        return self._ledger

    async def prepare(
        self,
        command: TaskCommand,
        *,
        execution_ref: str,
        lease: LeaseToken,
    ) -> PreparedGraphRun:
        self._validate_command(command)
        state = await self._load_or_initialize(command, lease)
        # Rebuild cross-turn budget counters from the Checkpoint before any
        # provider call; restore is idempotent, so replays never re-charge
        # turns that already ran (FP-CTX-004 / FP-FLOW-005).
        self._ledger.restore(
            round_count=state.conversation_round,
            input_tokens=state.cumulative_input_tokens,
            output_tokens=state.cumulative_output_tokens,
        )
        if self._ledger.is_exhausted:
            raise self._budget_exhausted(state)
        if state.status in {GraphStatus.COMPLETED, GraphStatus.FAILED}:
            return PreparedGraphRun(
                state=state,
                request=None,
                terminal_outcome=GraphRunOutcome(
                    state=state,
                    runtime_result=None,
                    should_retry=False,
                ),
            )
        resume_runtime_node = (
            state.status is GraphStatus.RUNNING
            and state.node is GraphNode.RUN_AGENT
        )
        if resume_runtime_node:
            state = await self._save(state, lease)
        elif state.status in {
            GraphStatus.RETRY_PENDING,
            GraphStatus.WAITING_USER,
            GraphStatus.WAITING_APPROVAL,
        }:
            state = state.transition(
                GraphStatus.RUNNING,
                node=GraphNode.BUILD_CONTEXT,
                command_id=command.command_id,
                command_digest=command.command_digest,
                security_context_ref=command.security_context.context_ref,
                security_context_hash=command.security_context.context_hash,
                purpose=command.security_context.purpose,
                pending_reason=None,
                failure_code=None,
            )
        else:
            state = state.transition(
                GraphStatus.RUNNING,
                node=GraphNode.BUILD_CONTEXT,
            )
        state = await self._save(state, lease)
        context_id = self._stable_id("ctx", command.command_id)
        optional_layers = (
            (
                build_summary_layer(
                    summary=state.summary,
                    ref=(
                        f"summary://{command.task_id}/round/"
                        f"{state.conversation_round}"
                    ),
                ),
            )
            if state.summary is not None
            else ()
        )
        context = self._context_builder.build(
            ContextBuildRequest(
                context_id=context_id,
                task_id=command.task_id,
                agent_id=self._config.agent.id,
                purpose=command.security_context.purpose,
                security_context=command.security_context,
                task_state={
                    "status": "RUNNING",
                    "command_id": command.command_id,
                    "execution_ref": execution_ref,
                    "conversation_round": state.conversation_round,
                },
                task_state_ref=(
                    f"task://{command.task_id}/command/{command.command_id}"
                ),
                system_policy_ref=self._config.system_policy_ref,
                policy=self._config.context_policy,
                optional_layers=optional_layers,
            )
        )
        state = replace(
            state,
            node=GraphNode.RUN_AGENT,
            context_id=context.context_id,
            attempt_count=(
                state.attempt_count
                if resume_runtime_node
                else state.attempt_count + 1
            ),
        )
        if not resume_runtime_node:
            state = await self._save(state, lease)
        request = AgentRunRequest(
            request_id=self._stable_id(
                "arq", f"{command.command_id}:{state.attempt_count}"
            ),
            task_id=command.task_id,
            tenant_id=command.tenant_id,
            trace_id=self._stable_trace_id(
                command.correlation_id or command.command_id
            ),
            run_id=state.run_id,
            agent=self._config.agent,
            context=context,
            security_context=command.security_context,
            provider_selection=self._config.provider,
            budget=self._config.budget,
            session_ref=None,
            issued_at=self._clock().astimezone(UTC),
        )
        return PreparedGraphRun(
            state=state,
            request=request,
            terminal_outcome=None,
        )

    async def invoke(self, request: AgentRunRequest) -> AgentRunResult:
        result = await self._runtime.run(request)
        # One trace record per runtime node run: the single provider actually
        # used for this node, taken from the runtime result (which the
        # adapter reports for failures too).
        self._provider_traces.append(
            ProviderSelectionTrace(
                trace_id=result.trace_id or request.trace_id,
                run_id=request.run_id,
                node=GraphNode.RUN_AGENT,
                provider=result.provider_name or request.provider_selection.provider,
                model=result.provider_model or request.provider_selection.model,
                provider_run_ref=result.provider_run_ref,
            )
        )
        self._charge_turn(request, result)
        return result

    def _charge_turn(
        self,
        request: AgentRunRequest,
        result: AgentRunResult,
    ) -> None:
        """Charge one model call against the conversation ledger.

        Real token numbers come from the runtime result usage (the fake
        runtime and every provider adapter report the same shape); the
        per-layer breakdown is the deterministic estimate over the actual
        envelope layers.  An over-budget call raises without recording and
        escalates, so the provider loop terminates (FP-CTX-004 /
        FP-FLOW-006).
        """
        layer_tokens = tuple(
            (layer.name.value, estimate_tokens(layer.to_mapping()))
            for layer in request.context.layers
        )
        try:
            self._ledger.charge(
                turn_index=self._ledger.round_count,
                request_id=request.request_id,
                context_id=request.context.context_id,
                agent_id=request.agent.id,
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                layer_tokens=layer_tokens,
            )
        except ContextError as exc:
            if exc.code is not ContextErrorCode.BUDGET_EXHAUSTED:
                raise
            reason = (
                "maximum_rounds"
                if self._ledger.round_count >= self._ledger.maximum_rounds
                else "cumulative_tokens"
            )
            raise self._budget_exhausted(
                request.context,
                request_id=request.request_id,
                reason_code=reason,
            ) from exc

    async def finalize(
        self,
        state: GraphState,
        runtime_result: AgentRunResult,
        *,
        lease: LeaseToken,
    ) -> GraphRunOutcome:
        proposal_refs = tuple(
            proposal.proposal_id for proposal in runtime_result.tool_proposals
        )
        if runtime_result.status is RunStatus.COMPLETED:
            completed = state.transition(
                GraphStatus.COMPLETED,
                node=GraphNode.FINALIZE,
                result_ref=f"runtime-result://{runtime_result.result_id}",
                failure_code=None,
                tool_proposal_refs=proposal_refs,
            )
            completed = self._carry_budget(completed)
            completed = await self._save(completed, lease)
            return GraphRunOutcome(
                state=completed,
                runtime_result=runtime_result,
                should_retry=False,
            )
        if (
            runtime_result.status is RunStatus.FAILED_RETRYABLE
            and state.attempt_count < self._config.maximum_attempts
        ):
            retry = state.transition(
                GraphStatus.RETRY_PENDING,
                node=GraphNode.RUN_AGENT,
                failure_code=runtime_result.error.code.value
                if runtime_result.error is not None
                else None,
                tool_proposal_refs=proposal_refs,
            )
            retry = self._carry_budget(retry)
            retry = await self._save(retry, lease)
            return GraphRunOutcome(
                state=retry,
                runtime_result=runtime_result,
                should_retry=True,
            )
        failed = state.transition(
            GraphStatus.FAILED,
            node=GraphNode.FINALIZE,
            failure_code=(
                runtime_result.error.code.value
                if runtime_result.error is not None
                else "RUNTIME_INTERNAL"
            ),
            tool_proposal_refs=proposal_refs,
        )
        failed = self._carry_budget(failed)
        failed = await self._save(failed, lease)
        return GraphRunOutcome(
            state=failed,
            runtime_result=runtime_result,
            should_retry=False,
        )

    async def interrupt_for_user_input(
        self,
        state: GraphState,
        *,
        request_id: str,
        lease: LeaseToken,
    ) -> GraphState:
        if state.status is not GraphStatus.RUNNING:
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "only a running graph may enter a user-input interrupt",
            )
        waiting = state.transition(
            GraphStatus.WAITING_USER,
            node=GraphNode.INTERRUPT,
            pending_reason=f"user_input:{request_id}",
        )
        # A conversation round ends here: persist the ledger counters so a
        # restart rebuilds the budget from this Checkpoint (FP-CTX-004).
        waiting = self._carry_budget(waiting)
        return await self._save(waiting, lease)

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
                "checkpoint graph version requires an explicit migration",
            )
        if (
            current.tenant_id != command.tenant_id
            or current.task_id != command.task_id
            or current.purpose != command.security_context.purpose
        ):
            raise GraphError(
                GraphErrorCode.SECURITY_BINDING_MISMATCH,
                "command does not match the checkpoint security binding",
            )
        same_command = current.command_id == command.command_id
        if same_command and (
            current.command_digest != command.command_digest
            or current.security_context_ref
            != command.security_context.context_ref
            or current.security_context_hash
            != command.security_context.context_hash
        ):
            raise GraphError(
                GraphErrorCode.SECURITY_BINDING_MISMATCH,
                "replayed command does not match its checkpoint binding",
            )
        if (
            current.status in {GraphStatus.QUEUED, GraphStatus.RUNNING}
            and not same_command
        ):
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "an in-flight graph cannot switch to another command",
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

    def _carry_budget(self, state: GraphState) -> GraphState:
        """Persist live ledger counters onto the state before a Checkpoint."""
        return replace(
            state,
            conversation_round=self._ledger.round_count,
            cumulative_input_tokens=self._ledger.used_input_tokens,
            cumulative_output_tokens=self._ledger.used_output_tokens,
        )

    def append_summary(
        self,
        state: GraphState,
        *,
        summary: LayeredSummary,
    ) -> GraphState:
        """Merge a new layered summary into the conversation summary.

        The merged summary rides the Checkpoint (``state.summary``) and is
        offered to the next model call as the L3 layer, so an interrupted
        run rebuilds it instead of losing the conversation (FP-CTX-002 /
        FP-FLOW-005).
        """
        merged = (
            state.summary.merge(summary) if state.summary is not None else summary
        )
        return replace(state, summary=merged)

    def evaluate_handoff(
        self,
        state: GraphState,
        *,
        target_agent_id: str,
    ) -> HandoffDecision:
        """Refuse handoffs that cross an approval or execution boundary.

        A task parked at ``WAITING_APPROVAL`` owns an approval card that
        cannot travel to another agent; a task that already consumed
        execution authority (an attempt ran, or a retry is pending) cannot
        hand the action off either.  Refusals are recorded as audit events
        (FP-AGT-004).
        """
        if target_agent_id == self._config.agent.id:
            return HandoffDecision(
                allowed=False,
                boundary="identity",
                reason="handoff target must differ from the source agent",
            )
        if state.status in _APPROVAL_BOUNDARY_STATUSES:
            return self._deny_handoff(
                state,
                boundary="approval",
                reason=(
                    "handoff is denied while the task owns an approval "
                    "card (WAITING_APPROVAL)"
                ),
                target_agent_id=target_agent_id,
            )
        if (
            state.status in _EXECUTION_BOUNDARY_STATUSES
            or state.attempt_count > 0
            or (
                state.status is GraphStatus.RUNNING
                and state.node is GraphNode.RUN_AGENT
            )
        ):
            return self._deny_handoff(
                state,
                boundary="execution",
                reason=(
                    "handoff is denied after the task entered its "
                    "execution path"
                ),
                target_agent_id=target_agent_id,
            )
        return HandoffDecision(allowed=True)

    def rebuild_handoff(
        self,
        *,
        state: GraphState,
        source: ContextEnvelope,
        security_context: SecurityContextRef,
        target_agent: AgentProfile,
        required_task_fields: Sequence[str],
        proposed_tools: Sequence[str],
    ) -> HandoffBundle:
        """Rebuild a minimal target context with allowlist-filtered tools.

        Gate order is fail-closed: boundary check first (FP-AGT-004), then
        field filtering (forbidden categories are rejected, FP-CTX-003),
        then tool allowlist intersection (FP-AGT-001), then a recursive
        leak scan over the serialized bundle as a defense-in-depth net.
        """
        decision = self.evaluate_handoff(
            state,
            target_agent_id=target_agent.id,
        )
        if not decision.allowed:
            raise ContextError(
                ContextErrorCode.HANDOFF_DENIED,
                decision.reason or "handoff denied at a task boundary",
            )
        bundle = self._context_builder.rebuild_for_handoff(
            source=source,
            security_context=security_context,
            target_agent_id=target_agent.id,
            new_context_id=self._stable_id(
                "ctx", f"{source.task_id}:{target_agent.id}"
            ),
            required_task_fields=required_task_fields,
            allowed_tools=proposed_tools,
            target_tool_allowlist=tuple(
                tool.name for tool in target_agent.allowed_tools
            ),
        )
        leaks = forbidden_field_scan(bundle.to_mapping())
        if leaks:
            self._escalate(
                state,
                event_type="handoff_denied",
                boundary="leak_scan",
                detail="handoff bundle carries forbidden fields",
            )
            raise ContextError(
                ContextErrorCode.HANDOFF_DENIED,
                "handoff bundle carries forbidden fields",
            ) from None
        return bundle

    def _deny_handoff(
        self,
        state: GraphState,
        *,
        boundary: str,
        reason: str,
        target_agent_id: str,
    ) -> HandoffDecision:
        event = self._escalate(
            state,
            event_type="handoff_denied",
            boundary=boundary,
            detail=reason,
            extra={"target_agent_id": target_agent_id},
        )
        return HandoffDecision(
            allowed=False,
            boundary=boundary,
            reason=reason,
            audit_event=event,
        )

    def _budget_exhausted(
        self,
        context: ContextEnvelope | None = None,
        *,
        request_id: str | None = None,
        reason_code: str | None = None,
    ) -> GraphError:
        exhaustion = self._ledger.exhaustion
        effective_reason = (
            reason_code
            or (exhaustion.reason_code if exhaustion is not None else None)
            or "cumulative_tokens"
        )
        detail = (
            exhaustion.detail
            if exhaustion is not None
            else f"hard conversation budget reached: {effective_reason}"
        )
        self._escalate(
            None,
            event_type="context_budget_exhausted",
            boundary="budget",
            detail=detail,
            extra={
                "context_id": context.context_id if context is not None else None,
                "request_id": request_id,
                "reason_code": effective_reason,
                **(
                    exhaustion.to_mapping()
                    if exhaustion is not None
                    else {}
                ),
            },
        )
        return GraphError(
            GraphErrorCode.BUDGET_EXHAUSTED,
            detail,
            retryable=False,
        )

    def _escalate(
        self,
        state: GraphState | None,
        *,
        event_type: str,
        boundary: str,
        detail: str,
        extra: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        """Append an escalation/audit event and fan it out to the sink."""
        payload: dict[str, Any] = {
            "event_type": event_type,
            "boundary": boundary,
            "result": "blocked",
            "detail": detail,
            "occurred_at": self._clock().astimezone(UTC).isoformat(),
        }
        if state is not None:
            payload["tenant_id"] = state.tenant_id
            payload["task_id"] = state.task_id
            payload["correlation_id"] = state.command_id
            payload["run_id"] = state.run_id
        if extra:
            payload.update(extra)
        identity = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        payload["event_id"] = "evt_" + hashlib.sha256(
            identity.encode()
        ).hexdigest()[:16]
        event: Mapping[str, Any] = payload
        self.escalation_events.append(event)
        if self._config.on_escalation is not None:
            self._config.on_escalation(event)
        return event

    @staticmethod
    def _validate_command(command: TaskCommand) -> None:
        if command.command_type not in {
            CommandType.CREATE,
            CommandType.SUBMIT_MESSAGE,
            CommandType.DECIDE_APPROVAL,
            CommandType.REQUEST_RETRY,
        }:
            raise GraphError(
                GraphErrorCode.COMMAND_UNSUPPORTED,
                "command is not supported by the runtime graph baseline",
            )
        try:
            command.assert_digest()
            command.assert_security_binding()
        except DomainViolation as exc:
            raise GraphError(
                GraphErrorCode.SECURITY_BINDING_MISMATCH,
                "command failed deterministic runtime binding",
            ) from exc

    @staticmethod
    def _stable_id(prefix: str, value: str) -> str:
        suffix = hashlib.sha256(value.encode()).hexdigest()[:16]
        return f"{prefix}_{suffix}"

    @staticmethod
    def _stable_trace_id(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()
