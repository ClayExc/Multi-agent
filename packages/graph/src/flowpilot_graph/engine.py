from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol

from flowpilot_agent_runtime import (
    AgentProfile,
    AgentRunRequest,
    AgentRunResult,
    AgentRuntimePort,
    ProviderSelection,
    RunStatus,
    RuntimeBudget,
)
from flowpilot_context import ContextBuilder, ContextBuildRequest, ContextPolicy
from flowpilot_domain import CommandType, DomainViolation, TaskCommand

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

    def __post_init__(self) -> None:
        if self.maximum_attempts < 1:
            raise ValueError("maximum graph attempts must be positive")


@dataclass(frozen=True, slots=True)
class GraphRunOutcome:
    state: GraphState
    runtime_result: AgentRunResult | None
    should_retry: bool


@dataclass(frozen=True, slots=True)
class PreparedGraphRun:
    state: GraphState
    request: AgentRunRequest | None
    terminal_outcome: GraphRunOutcome | None


class GraphExecutionPort(Protocol):
    async def execute(
        self,
        command: TaskCommand,
        *,
        execution_ref: str,
        lease: LeaseToken,
    ) -> GraphRunOutcome: ...


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

    async def prepare(
        self,
        command: TaskCommand,
        *,
        execution_ref: str,
        lease: LeaseToken,
    ) -> PreparedGraphRun:
        self._validate_command(command)
        state = await self._load_or_initialize(command, lease)
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
                },
                task_state_ref=(
                    f"task://{command.task_id}/command/{command.command_id}"
                ),
                system_policy_ref=self._config.system_policy_ref,
                policy=self._config.context_policy,
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
        return await self._runtime.run(request)

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
