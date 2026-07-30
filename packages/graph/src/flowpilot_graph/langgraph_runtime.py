from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TypedDict, cast

from flowpilot_agent_runtime import AgentRunResult
from flowpilot_domain import TaskCommand

from .engine import (
    GraphRunOutcome,
    PreparedGraphRun,
    RuntimeGraphKernel,
)
from .errors import GraphError, GraphErrorCode
from .factory import (
    FlowPilotGraphNodes,
    GraphDefinition,
    build_flowpilot_it_service_graph,
)
from .ports import LeaseToken
from .state import GraphState, GraphStatus


class _ExecutionState(TypedDict, total=False):
    command: TaskCommand
    execution_ref: str
    lease: LeaseToken
    prepared: PreparedGraphRun
    runtime_result: AgentRunResult
    outcome: GraphRunOutcome


class LangGraphRuntime:
    """StateGraph-owned production topology backed by deterministic node logic."""

    def __init__(self, kernel: RuntimeGraphKernel) -> None:
        self._kernel = kernel
        callbacks = _KernelGraphNodes(kernel)
        self._definition = build_flowpilot_it_service_graph(
            _ExecutionState,
            callbacks.as_graph_nodes(),
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
        result = await self._definition.graph.ainvoke(
            {
                "command": command,
                "execution_ref": execution_ref,
                "lease": lease,
            }
        )
        outcome = result.get("outcome")
        if not isinstance(outcome, GraphRunOutcome):
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "StateGraph completed without an authoritative graph outcome",
            )
        return outcome

    async def interrupt_for_user_input(
        self,
        state: GraphState,
        *,
        request_id: str,
        lease: LeaseToken,
    ) -> GraphState:
        return await self._kernel.interrupt_for_user_input(
            state,
            request_id=request_id,
            lease=lease,
        )


class _KernelGraphNodes:
    """Bind production Kernel operations to the shared topology."""

    def __init__(self, kernel: RuntimeGraphKernel) -> None:
        self._kernel = kernel

    def as_graph_nodes(self) -> FlowPilotGraphNodes:
        return FlowPilotGraphNodes(
            prepare=self.prepare,
            build_context=self.build_context,
            route_request=self.route_request,
            route_after_request=self.route_after_request,
            clarification_interrupt=self.unsupported_boundary,
            knowledge_read=self.unsupported_boundary,
            service_read=self.unsupported_boundary,
            join_reads=self.unsupported_boundary,
            handoff=self.unsupported_boundary,
            approval_interrupt=self.unsupported_boundary,
            run_agent=self.run_agent,
            route_result=self.route_result,
            route_after_result=self.route_after_result,
            retry=self.retry,
            compensate=self.compensate,
            finalize=self.finalize,
        )

    async def prepare(self, raw_state: Mapping[str, Any]) -> Mapping[str, Any]:
        state = cast(_ExecutionState, raw_state)
        prepared = await self._kernel.prepare(
            state["command"],
            execution_ref=state["execution_ref"],
            lease=state["lease"],
        )
        update: _ExecutionState = {"prepared": prepared}
        if prepared.terminal_outcome is not None:
            update["outcome"] = prepared.terminal_outcome
        return update

    async def build_context(
        self,
        _state: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        # RuntimeGraphKernel.prepare owns Context construction today. This
        # explicit node preserves the stable topology while that operation is
        # incrementally split into a standalone replayable Kernel method.
        return {}

    async def route_request(
        self,
        _state: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return {}

    @staticmethod
    def route_after_request(
        raw_state: Mapping[str, Any],
    ) -> str | Sequence[str]:
        state = cast(_ExecutionState, raw_state)
        if state["prepared"].terminal_outcome is not None:
            return "terminate"
        return "run_agent"

    async def run_agent(
        self,
        raw_state: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        state = cast(_ExecutionState, raw_state)
        request = state["prepared"].request
        if request is None:
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "StateGraph runtime node received no prepared request",
            )
        result: _ExecutionState = {
            "runtime_result": await self._kernel.invoke(request)
        }
        return result

    async def route_result(
        self,
        raw_state: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        state = cast(_ExecutionState, raw_state)
        outcome = await self._kernel.finalize(
            state["prepared"].state,
            state["runtime_result"],
            lease=state["lease"],
        )
        return {"outcome": outcome}

    @staticmethod
    def route_after_result(
        raw_state: Mapping[str, Any],
    ) -> str | Sequence[str]:
        state = cast(_ExecutionState, raw_state)
        outcome = state["outcome"]
        if outcome.state.status is GraphStatus.FAILED:
            return "compensate"
        # Queue-level retry deliberately terminates this graph invocation so
        # the Worker releases the lease before the next attempt.
        return "finalize"

    async def retry(self, _state: Mapping[str, Any]) -> Mapping[str, Any]:
        raise GraphError(
            GraphErrorCode.STATE_INVALID,
            "production retries must cross the Worker queue boundary",
        )

    async def compensate(
        self,
        _state: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        # M0 has no committed side effect in the Runtime graph. The explicit
        # compensation node is therefore a deterministic no-op boundary.
        return {}

    @staticmethod
    async def finalize(
        raw_state: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        state = cast(_ExecutionState, raw_state)
        if not isinstance(state.get("outcome"), GraphRunOutcome):
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "finalize requires an authoritative graph outcome",
            )
        return {}

    @staticmethod
    async def unsupported_boundary(
        _state: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        raise GraphError(
            GraphErrorCode.STATE_INVALID,
            "production graph route reached an unconfigured application boundary",
        )
