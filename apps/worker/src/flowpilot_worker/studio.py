from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, TypedDict

try:
    from flowpilot_graph import (
        FLOWPILOT_GRAPH_ID,
        DebugProjectionPolicy,
        FlowPilotGraphNodes,
        GraphDefinition,
        GraphError,
        GraphErrorCode,
        StudioProfile,
        assert_studio_input_safe,
        assert_studio_profile_allowed,
        build_flowpilot_it_service_graph,
        debug_projection,
    )
except ModuleNotFoundError:
    # The Studio Agent Server launches this module inside a langgraph_cli
    # subprocess whose environment has no PYTHONPATH and where the FlowPilot
    # workspace packages are not pip-installed.  Derive the repository root
    # from this file's location and expose every in-repo ``src`` root so the
    # server can import the graph packages; environments that already have
    # the packages importable never reach this branch.
    import sys
    from pathlib import Path

    _REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
    for _src_root in sorted((_REPOSITORY_ROOT / "packages").glob("*/src")):
        sys.path.insert(0, str(_src_root))
    for _src_root in sorted((_REPOSITORY_ROOT / "apps").glob("*/src")):
        sys.path.insert(0, str(_src_root))
    for _src_root in sorted((_REPOSITORY_ROOT / "mcp-servers").glob("*/src")):
        sys.path.insert(0, str(_src_root))
    from flowpilot_graph import (
        FLOWPILOT_GRAPH_ID,
        DebugProjectionPolicy,
        FlowPilotGraphNodes,
        GraphDefinition,
        GraphError,
        GraphErrorCode,
        StudioProfile,
        assert_studio_input_safe,
        assert_studio_profile_allowed,
        build_flowpilot_it_service_graph,
        debug_projection,
    )
from langgraph.types import interrupt

_DEFAULT_SCENARIO = "full_demo"
_SCENARIOS = frozenset(
    {
        "approval",
        "budget_exhausted",
        "clarification",
        "compensate",
        "full_demo",
        "happy_path",
        "retry_once",
    }
)
_PRODUCTION_ENV_KEYS = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "DATABASE_URL",
        "FLOWPILOT_PRODUCTION_ENV",
        "LANGSMITH_API_KEY",
        "MCP_GATEWAY_TOKEN",
        "OPENAI_API_KEY",
        "REDIS_URL",
    }
)


def _append_visits(
    left: Sequence[str] | None,
    right: Sequence[str] | None,
) -> list[str]:
    return [*(left or ()), *(right or ())]


def _merge_frames(
    left: Sequence[dict[str, Any]] | None,
    right: Sequence[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for frame in [*(left or ()), *(right or ())]:
        frame_id = frame.get("frame_id")
        if isinstance(frame_id, str):
            merged[frame_id] = frame
    return sorted(
        merged.values(),
        key=lambda frame: (
            int(frame.get("step") or 0),
            str(frame.get("frame_id")),
        ),
    )


def _maximum(left: int | None, right: int | None) -> int:
    return max(left or 0, right or 0)


class StudioSafeState(TypedDict, total=False):
    profile: str
    scenario: str
    task_ref: str
    status: str
    current_node: str
    route: str
    visited_nodes: Annotated[list[str], _append_visits]
    debug_projection: Annotated[
        list[dict[str, Any]],
        _merge_frames,
    ]
    step_count: Annotated[int, _maximum]
    budget_remaining: int
    maximum_retries: int
    retry_count: int
    checkpoint_sequence: Annotated[int, _maximum]
    run_generation: int
    lease_status: str
    input_complete: bool
    knowledge_read_complete: bool
    service_read_complete: bool
    service_read_skipped: bool
    reads_complete: bool
    knowledge_call_count: int
    citation_count: int
    approval_required: bool
    approval_granted: bool
    interrupt_kind: str
    interrupt_resolved: bool
    handoff_count: int
    handoff_reason: str
    context_rebuilt: bool
    tool_scope_rebuilt: bool
    context_layers: dict[str, bool]
    context_token_budget: int
    trim_reason_code: str
    tool_mode: str
    tool_stage: str
    runtime_outcome: str
    failure_code: str
    terminal_reason: str
    compensation_status: str


class _StudioSafeNodes:
    def __init__(self, profile: StudioProfile) -> None:
        self._profile = profile
        self._projection_policy = DebugProjectionPolicy(profile=profile)

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

    async def prepare(self, raw_state: Mapping[str, Any]) -> Mapping[str, Any]:
        assert_studio_input_safe(
            raw_state,
            expected_profile=self._profile,
        )
        scenario = raw_state.get("scenario", _DEFAULT_SCENARIO)
        if not isinstance(scenario, str) or scenario not in _SCENARIOS:
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "Studio scenario is not registered",
            )
        needs_clarification = scenario in {"clarification", "full_demo"}
        needs_approval = scenario in {"approval", "full_demo"}
        update: dict[str, Any] = {
            "profile": self._profile.value,
            "scenario": scenario,
            "task_ref": f"studio-safe://{FLOWPILOT_GRAPH_ID}/{scenario}",
            "status": "RUNNING",
            "step_count": 0,
            "budget_remaining": 8,
            "maximum_retries": 1,
            "retry_count": 0,
            "checkpoint_sequence": 0,
            "run_generation": 1,
            "lease_status": "synthetic",
            "input_complete": not needs_clarification,
            "knowledge_read_complete": False,
            "service_read_complete": False,
            "service_read_skipped": False,
            "reads_complete": False,
            "knowledge_call_count": 0,
            "citation_count": 0,
            "approval_required": needs_approval,
            "approval_granted": False,
            "interrupt_resolved": False,
            "handoff_count": 0,
            "context_rebuilt": False,
            "tool_scope_rebuilt": False,
            "tool_mode": "fake_readonly",
            "tool_stage": "proposal_only",
        }
        return self._advance(raw_state, "prepare", update)

    async def build_context(
        self,
        state: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self._assert_profile(state)
        return self._advance(
            state,
            "build_context",
            {
                "context_layers": {"L0": True, "L1": True, "L2": True},
                "context_token_budget": 512,
                "trim_reason_code": "SYNTHETIC_BUDGET",
            },
        )

    async def route_request(
        self,
        state: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self._assert_profile(state)
        if state.get("input_complete") is not True:
            route = "clarification"
        elif state.get("reads_complete") is not True:
            route = "parallel_reads"
        elif (
            state.get("approval_required") is True
            and state.get("approval_granted") is not True
        ):
            route = "approval"
        elif state.get("status") in {"COMPLETED", "FAILED"}:
            route = "terminate"
        else:
            route = "run_agent"
        return self._advance(state, "route_request", {"route": route})

    @staticmethod
    def route_after_request(
        state: Mapping[str, Any],
    ) -> str | Sequence[str]:
        route = state.get("route")
        if route == "parallel_reads":
            return ("knowledge_read", "service_read")
        if route in {
            "approval",
            "clarification",
            "run_agent",
            "terminate",
        }:
            return str(route)
        raise GraphError(
            GraphErrorCode.STATE_INVALID,
            "Studio request route is unknown",
        )

    async def clarification_interrupt(
        self,
        state: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self._assert_profile(state)
        resume = interrupt(
            {
                "schema": "flowpilot.studio-interrupt.v1",
                "kind": "clarification",
                "request_ref": "clarification://sha256/2a87392f28f68d4a",
                "required_fields": ["network_location"],
            }
        )
        if not isinstance(resume, Mapping) or resume.get("confirmed") is not True:
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "Studio clarification resume was not confirmed",
            )
        return self._advance(
            state,
            "clarification_interrupt",
            {
                "input_complete": True,
                "interrupt_kind": "clarification",
                "interrupt_resolved": True,
                "checkpoint_sequence": self._sequence(state) + 1,
            },
        )

    async def knowledge_read(
        self,
        state: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self._assert_profile(state)
        return self._advance(
            state,
            "knowledge_read",
            {
                "knowledge_read_complete": True,
                "knowledge_call_count": 1,
                "citation_count": 1,
            },
            record_current=False,
        )

    async def service_read(
        self,
        state: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self._assert_profile(state)
        return self._advance(
            state,
            "service_read",
            {
                "service_read_complete": True,
                "service_read_skipped": True,
            },
            record_current=False,
        )

    async def join_reads(
        self,
        state: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self._assert_profile(state)
        if (
            state.get("knowledge_read_complete") is not True
            or state.get("service_read_complete") is not True
        ):
            raise GraphError(
                GraphErrorCode.PARALLEL_REDUCER_CONFLICT,
                "Studio parallel reads did not both complete",
            )
        return self._advance(
            state,
            "join_reads",
            {
                "reads_complete": True,
                "tool_stage": "result_verified",
            },
        )

    async def handoff(
        self,
        state: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self._assert_profile(state)
        return self._advance(
            state,
            "handoff",
            {
                "handoff_count": int(state.get("handoff_count", 0)) + 1,
                "handoff_reason": "READS_READY",
                "context_rebuilt": True,
                "tool_scope_rebuilt": True,
            },
        )

    async def approval_interrupt(
        self,
        state: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self._assert_profile(state)
        resume = interrupt(
            {
                "schema": "flowpilot.studio-interrupt.v1",
                "kind": "approval",
                "action_digest_ref": "action://sha256/0a9f04d8fa0f1771",
                "expires": "synthetic",
            }
        )
        approved = isinstance(resume, Mapping) and resume.get("approved") is True
        update: dict[str, Any] = {
            "approval_granted": approved,
            "interrupt_kind": "approval",
            "interrupt_resolved": True,
            "checkpoint_sequence": self._sequence(state) + 1,
        }
        if not approved:
            update["failure_code"] = "STUDIO_APPROVAL_DENIED"
        return self._advance(state, "approval_interrupt", update)

    async def run_agent(
        self,
        state: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self._assert_profile(state)
        remaining = int(state.get("budget_remaining", 0))
        if remaining < 1:
            outcome = "budget_exhausted"
        elif (
            state.get("approval_required") is True
            and state.get("approval_granted") is not True
        ):
            outcome = "failed_final"
        elif (
            state.get("scenario") in {"full_demo", "retry_once"}
            and int(state.get("retry_count", 0)) == 0
        ):
            outcome = "failed_retryable"
        elif state.get("scenario") == "budget_exhausted":
            outcome = "budget_exhausted"
        elif state.get("scenario") == "compensate":
            outcome = "failed_final"
        else:
            outcome = "completed"
        return self._advance(
            state,
            "run_agent",
            {
                "budget_remaining": max(remaining - 1, 0),
                "runtime_outcome": outcome,
                "tool_stage": "proposal_only",
            },
        )

    async def route_result(
        self,
        state: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self._assert_profile(state)
        outcome = state.get("runtime_outcome")
        if (
            outcome == "failed_retryable"
            and int(state.get("retry_count", 0))
            < int(state.get("maximum_retries", 0))
        ):
            route = "retry"
        elif outcome == "failed_final":
            route = "compensate"
        elif outcome in {"budget_exhausted", "completed"}:
            route = "finalize"
        else:
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "Studio runtime outcome is unknown",
            )
        return self._advance(state, "route_result", {"route": route})

    @staticmethod
    def route_after_result(
        state: Mapping[str, Any],
    ) -> str | Sequence[str]:
        route = state.get("route")
        if route in {"retry", "compensate", "finalize"}:
            return str(route)
        raise GraphError(
            GraphErrorCode.STATE_INVALID,
            "Studio result route is unknown",
        )

    async def retry(
        self,
        state: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self._assert_profile(state)
        return self._advance(
            state,
            "retry",
            {
                "status": "RETRY_PENDING",
                "retry_count": int(state.get("retry_count", 0)) + 1,
                "checkpoint_sequence": self._sequence(state) + 1,
            },
        )

    async def compensate(
        self,
        state: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self._assert_profile(state)
        return self._advance(
            state,
            "compensate",
            {
                "compensation_status": "not_required_no_side_effect",
                "failure_code": str(
                    state.get("failure_code") or "STUDIO_RUNTIME_FAILED"
                ),
            },
        )

    async def finalize(
        self,
        state: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self._assert_profile(state)
        outcome = state.get("runtime_outcome")
        if outcome == "completed":
            status = "COMPLETED"
            terminal_reason = "SYNTHETIC_SUCCESS"
            failure_code: str | None = None
        elif outcome == "budget_exhausted":
            status = "FAILED"
            terminal_reason = "BUDGET_EXHAUSTED"
            failure_code = "STUDIO_BUDGET_EXHAUSTED"
        else:
            status = "FAILED"
            terminal_reason = "SYNTHETIC_FAILURE"
            failure_code = str(
                state.get("failure_code") or "STUDIO_RUNTIME_FAILED"
            )
        update: dict[str, Any] = {
            "status": status,
            "terminal_reason": terminal_reason,
            "checkpoint_sequence": self._sequence(state) + 1,
            "tool_stage": "no_authoritative_write",
        }
        if failure_code is not None:
            update["failure_code"] = failure_code
        return self._advance(state, "finalize", update)

    def _advance(
        self,
        state: Mapping[str, Any],
        node: str,
        updates: Mapping[str, Any],
        *,
        record_current: bool = True,
    ) -> Mapping[str, Any]:
        step_count = int(state.get("step_count", 0)) + 1
        if step_count > 24:
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "Studio graph exceeded its deterministic step budget",
            )
        combined = dict(state)
        combined.update(updates)
        combined["profile"] = self._profile.value
        combined["current_node"] = node
        combined["step_count"] = step_count
        frame = debug_projection(
            combined,
            policy=self._projection_policy,
        )
        frame["step"] = step_count
        frame["frame_id"] = (
            f"{node}:{step_count}:"
            f"{int(combined.get('retry_count', 0))}:"
            f"{self._sequence(combined)}"
        )
        result = dict(updates)
        result.update(
            {
                "step_count": step_count,
                "visited_nodes": [node],
                "debug_projection": [frame],
            }
        )
        if record_current:
            result["current_node"] = node
        return result

    def _assert_profile(self, state: Mapping[str, Any]) -> None:
        if state.get("profile") != self._profile.value:
            raise GraphError(
                GraphErrorCode.STUDIO_PROFILE_FORBIDDEN,
                "Studio state profile was edited or is invalid",
            )

    @staticmethod
    def _sequence(state: Mapping[str, Any]) -> int:
        value = state.get("checkpoint_sequence", 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "Studio checkpoint sequence is invalid",
            )
        return int(value)


def create_studio_graph_definition(
    *,
    checkpointer: Any = None,
    environment: Mapping[str, str] | None = None,
) -> GraphDefinition:
    effective_environment = environment or os.environ
    profile = _profile_from_environment(effective_environment)
    assert_studio_profile_allowed(profile)
    _assert_no_production_environment(effective_environment)
    nodes = _StudioSafeNodes(profile)
    return build_flowpilot_it_service_graph(
        StudioSafeState,
        nodes.as_graph_nodes(),
        checkpointer=checkpointer,
    )


def _profile_from_environment(
    environment: Mapping[str, str],
) -> StudioProfile:
    raw = environment.get(
        "FLOWPILOT_STUDIO_PROFILE",
        StudioProfile.SAFE.value,
    )
    try:
        return StudioProfile(raw)
    except ValueError as exc:
        raise GraphError(
            GraphErrorCode.STUDIO_PROFILE_FORBIDDEN,
            "Studio profile is not registered",
        ) from exc


def _assert_no_production_environment(
    environment: Mapping[str, str],
) -> None:
    if any(environment.get(key) for key in _PRODUCTION_ENV_KEYS):
        raise GraphError(
            GraphErrorCode.STUDIO_PROFILE_FORBIDDEN,
            "studio-safe refuses production credentials and endpoints",
        )
    external_network = environment.get(
        "FLOWPILOT_EXTERNAL_NETWORK",
        "disabled",
    )
    if external_network != "disabled":
        raise GraphError(
            GraphErrorCode.STUDIO_PROFILE_FORBIDDEN,
            "studio-safe external network must remain disabled",
        )


definition = create_studio_graph_definition()
graph = definition.graph

__all__ = [
    "StudioSafeState",
    "create_studio_graph_definition",
    "definition",
    "graph",
]
