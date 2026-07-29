from __future__ import annotations

from typing import Literal, TypedDict, cast

from flowpilot_agent_runtime import AgentRunResult
from flowpilot_domain import TaskCommand
from langgraph.graph import END, START, StateGraph

from .engine import (
    GraphRunOutcome,
    PreparedGraphRun,
    RuntimeGraphKernel,
)
from .errors import GraphError, GraphErrorCode
from .ports import LeaseToken
from .state import GraphState


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
        builder = StateGraph(_ExecutionState)
        builder.add_node("prepare", self._prepare)
        builder.add_node("run_agent", self._run_agent)
        builder.add_node("finalize", self._finalize)
        builder.add_edge(START, "prepare")
        builder.add_conditional_edges(
            "prepare",
            self._route_after_prepare,
            {
                "run_agent": "run_agent",
                "done": END,
            },
        )
        builder.add_edge("run_agent", "finalize")
        builder.add_edge("finalize", END)
        self._compiled = builder.compile()

    async def execute(
        self,
        command: TaskCommand,
        *,
        execution_ref: str,
        lease: LeaseToken,
    ) -> GraphRunOutcome:
        result = await self._compiled.ainvoke(
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

    async def _prepare(self, state: _ExecutionState) -> _ExecutionState:
        prepared = await self._kernel.prepare(
            state["command"],
            execution_ref=state["execution_ref"],
            lease=state["lease"],
        )
        update: _ExecutionState = {"prepared": prepared}
        if prepared.terminal_outcome is not None:
            update["outcome"] = prepared.terminal_outcome
        return update

    @staticmethod
    def _route_after_prepare(
        state: _ExecutionState,
    ) -> Literal["run_agent", "done"]:
        prepared = state["prepared"]
        if prepared.terminal_outcome is not None:
            return "done"
        return "run_agent"

    async def _run_agent(self, state: _ExecutionState) -> _ExecutionState:
        request = state["prepared"].request
        if request is None:
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "StateGraph runtime node received no prepared request",
            )
        return {"runtime_result": await self._kernel.invoke(request)}

    async def _finalize(self, state: _ExecutionState) -> _ExecutionState:
        outcome = await self._kernel.finalize(
            state["prepared"].state,
            state["runtime_result"],
            lease=state["lease"],
        )
        return cast(_ExecutionState, {"outcome": outcome})
