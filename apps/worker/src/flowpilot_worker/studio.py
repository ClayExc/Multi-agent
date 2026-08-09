from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from functools import wraps
from typing import Annotated, Any, NoReturn, TypedDict

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
        debug_projection_frame_fingerprint,
        product_debug_projection,
        topology_snapshot,
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
        debug_projection_frame_fingerprint,
        product_debug_projection,
        topology_snapshot,
    )
from langgraph.types import Command, interrupt

from flowpilot_worker.knowledge import KNOWLEDGE_GRAPH_VERSION, KNOWLEDGE_INTENT

_DEFAULT_SCENARIO = "knowledge_demo"
_PRODUCT_SCENARIOS = frozenset(
    {
        "knowledge_demo",
        "provider_timeout",
        "recovery_failed",
    }
)
_SCENARIOS = frozenset(
    {
        "approval",
        "budget_exhausted",
        "clarification",
        "compensate",
        "full_demo",
        "happy_path",
        *_PRODUCT_SCENARIOS,
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
_STUDIO_NODE_IDS = frozenset(str(node) for node in topology_snapshot()["nodes"])


def _append_visits(
    left: object,
    right: object,
) -> list[str]:
    return [*_validated_visits(left), *_validated_visits(right)]


def _merge_frames(
    left: object,
    right: object,
) -> list[dict[str, Any]]:
    merged: dict[str, tuple[str, dict[str, Any]]] = {}
    for frame in [*_validated_frames(left), *_validated_frames(right)]:
        frame_id = str(frame["frame_id"])
        fingerprint = debug_projection_frame_fingerprint(frame)
        existing = merged.get(frame_id)
        if existing is not None and existing[0] != fingerprint:
            raise GraphError(
                GraphErrorCode.DEBUG_PROJECTION_UNSAFE,
                "Studio frame identity was reused with different content",
            )
        if existing is None:
            merged[frame_id] = (fingerprint, frame)
    return sorted(
        (item[1] for item in merged.values()),
        key=lambda frame: (
            int(frame["step"]),
            str(frame["frame_id"]),
        ),
    )


def _validated_visits(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise GraphError(
            GraphErrorCode.DEBUG_PROJECTION_UNSAFE,
            "Studio visited-node state is not a sequence",
        )
    result: list[str] = []
    for node in value:
        if not isinstance(node, str) or node not in _STUDIO_NODE_IDS:
            raise GraphError(
                GraphErrorCode.DEBUG_PROJECTION_UNSAFE,
                "Studio visited-node state contains an unregistered node",
            )
        result.append(node)
    return result


def _validated_frames(value: object) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise GraphError(
            GraphErrorCode.DEBUG_PROJECTION_UNSAFE,
            "Studio debug-frame state is not a sequence",
        )
    result: list[dict[str, Any]] = []
    for raw_frame in value:
        if not isinstance(raw_frame, Mapping):
            raise GraphError(
                GraphErrorCode.DEBUG_PROJECTION_UNSAFE,
                "Studio debug-frame state contains a non-mapping frame",
            )
        frame = dict(raw_frame)
        debug_projection_frame_fingerprint(frame)
        if frame.get("node") not in _STUDIO_NODE_IDS:
            raise GraphError(
                GraphErrorCode.DEBUG_PROJECTION_UNSAFE,
                "Studio debug frame contains an unregistered node",
            )
        result.append(frame)
    return result


def _maximum(left: object, right: object) -> int:
    normalized: list[int] = []
    for value in (left, right):
        if value is None:
            normalized.append(0)
        elif not isinstance(value, bool) and isinstance(value, int) and value >= 0:
            normalized.append(value)
        else:
            raise GraphError(
                GraphErrorCode.DEBUG_PROJECTION_UNSAFE,
                "Studio counter state is invalid",
            )
    return max(normalized)


class StudioSafeState(TypedDict, total=False):
    profile: str
    scenario: str
    graph_id: str
    graph_version: str
    intent: str
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
    progress_step: int
    progress_total: int
    progress_phase: str
    active_actor: str
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
    model_call_count: int
    citation_count: int
    artifact_count: int
    approval_required: bool
    approval_granted: bool
    interrupt_kind: str
    interrupt_resolved: bool
    recovery_resumed: bool
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
        initial_input = (
            {"scenario": raw_state["scenario"]}
            if "scenario" in raw_state
            else {}
        )
        assert_studio_input_safe(initial_input, expected_profile=self._profile)
        scenario = raw_state.get("scenario", _DEFAULT_SCENARIO)
        if not isinstance(scenario, str) or scenario not in _SCENARIOS:
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "Studio scenario is not registered",
            )
        needs_clarification = scenario in {
            "clarification",
            "full_demo",
            "knowledge_demo",
        }
        needs_approval = scenario in {"approval", "full_demo"}
        update: dict[str, Any] = {
            "profile": self._profile.value,
            "scenario": scenario,
            "graph_id": FLOWPILOT_GRAPH_ID,
            "graph_version": KNOWLEDGE_GRAPH_VERSION,
            "intent": KNOWLEDGE_INTENT,
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
            "model_call_count": 0,
            "citation_count": 0,
            "artifact_count": 0,
            "approval_required": needs_approval,
            "approval_granted": False,
            "interrupt_resolved": False,
            "recovery_resumed": False,
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
        required_field = (
            "question"
            if state.get("scenario") in _PRODUCT_SCENARIOS
            else "network_location"
        )
        resume = interrupt(
            {
                "schema": "flowpilot.studio-interrupt.v1",
                "kind": "clarification",
                "request_ref": "clarification://sha256/2a87392f28f68d4a",
                "required_fields": [required_field],
            }
        )
        _validate_studio_interrupt_resume(
            resume,
            expected_kind="clarification",
        )
        return self._advance(
            state,
            "clarification_interrupt",
            {
                "input_complete": True,
                "interrupt_kind": "clarification",
                "interrupt_resolved": True,
                "recovery_resumed": True,
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
        approved = _validate_studio_interrupt_resume(
            resume,
            expected_kind="approval",
        )
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
        scenario = state.get("scenario")
        model_call_count = int(state.get("model_call_count", 0))
        failure_code: str | None = None
        if remaining < 1:
            outcome = "budget_exhausted"
        elif (
            state.get("approval_required") is True
            and state.get("approval_granted") is not True
        ):
            outcome = "failed_final"
        elif (
            scenario in {"full_demo", "knowledge_demo", "retry_once"}
            and int(state.get("retry_count", 0)) == 0
        ):
            outcome = "failed_retryable"
        elif scenario == "provider_timeout":
            failure_code = "PROVIDER_TIMEOUT"
            if int(state.get("retry_count", 0)) == 0:
                outcome = "failed_retryable"
            else:
                outcome = "failed_final"
        elif scenario == "recovery_failed":
            failure_code = "GRAPH_CHECKPOINT_UNAVAILABLE"
            outcome = "failed_final"
        elif scenario == "budget_exhausted":
            outcome = "budget_exhausted"
        elif scenario == "compensate":
            outcome = "failed_final"
        else:
            outcome = "completed"
        if scenario != "recovery_failed":
            model_call_count += 1
        update: dict[str, Any] = {
            "budget_remaining": max(remaining - 1, 0),
            "model_call_count": model_call_count,
            "runtime_outcome": outcome,
            "tool_stage": "proposal_only",
        }
        if failure_code is not None:
            update["failure_code"] = failure_code
        return self._advance(
            state,
            "run_agent",
            update,
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
                "recovery_resumed": True,
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
        scenario = state.get("scenario")
        if outcome == "completed":
            status = "COMPLETED"
            terminal_reason = (
                "ENTERPRISE_KNOWLEDGE_COMPLETED"
                if scenario in _PRODUCT_SCENARIOS
                else "SYNTHETIC_SUCCESS"
            )
            failure_code: str | None = None
        elif outcome == "budget_exhausted":
            status = "FAILED"
            terminal_reason = "BUDGET_EXHAUSTED"
            failure_code = "STUDIO_BUDGET_EXHAUSTED"
        else:
            status = "FAILED"
            failure_code = str(
                state.get("failure_code") or "STUDIO_RUNTIME_FAILED"
            )
            if scenario == "provider_timeout":
                terminal_reason = "PROVIDER_TIMEOUT"
            elif scenario == "recovery_failed":
                terminal_reason = "RECOVERY_FAILED"
            else:
                terminal_reason = "SYNTHETIC_FAILURE"
        update: dict[str, Any] = {
            "status": status,
            "terminal_reason": terminal_reason,
            "artifact_count": 1 if status == "COMPLETED" else 0,
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
        progress_step, progress_phase, active_actor = _product_progress(
            node,
            route=combined.get("route"),
            resumed=combined.get("recovery_resumed") is True,
        )
        combined.update(
            {
                "progress_step": progress_step,
                "progress_total": 5,
                "progress_phase": progress_phase,
                "active_actor": active_actor,
            }
        )
        if combined.get("scenario") in _PRODUCT_SCENARIOS:
            frame = product_debug_projection(
                combined,
                policy=self._projection_policy,
            )
        else:
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
            result.update(
                {
                    "current_node": node,
                    "progress_step": progress_step,
                    "progress_total": 5,
                    "progress_phase": progress_phase,
                    "active_actor": active_actor,
                }
            )
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


def _product_progress(
    node: str,
    *,
    route: object = None,
    resumed: bool = False,
) -> tuple[int, str, str]:
    if node == "route_request":
        if route in {"clarification", "approval"}:
            return (2, "interrupt", "human_gate")
        if route == "parallel_reads":
            return (3, "knowledge", "parallel_reads")
        if route == "run_agent":
            return (4, "model", "answer_agent")
        if route == "terminate":
            return (5, "terminal", "artifact_writer")
    if node == "build_context" and resumed:
        return (2, "interrupt", "orchestrator")
    if node in {"prepare", "build_context", "route_request"}:
        return (1, "intake", "orchestrator")
    if node in {"clarification_interrupt", "approval_interrupt"}:
        return (2, "interrupt", "human_gate")
    if node in {"knowledge_read", "service_read", "join_reads", "handoff"}:
        return (3, "knowledge", "parallel_reads")
    if node in {"run_agent", "route_result", "retry"}:
        return (4, "model", "answer_agent")
    return (5, "terminal", "artifact_writer")


def _assert_studio_invocation_input(value: object) -> None:
    if value is None:
        return
    if isinstance(value, Command):
        _assert_studio_resume_command_safe(value)
        return
    if not isinstance(value, Mapping):
        raise GraphError(
            GraphErrorCode.STUDIO_STATE_EDIT_FORBIDDEN,
            "Studio input must be a mapping or a resume command",
        )
    assert_studio_input_safe(value, expected_profile=StudioProfile.SAFE)
    scenario = value.get("scenario")
    if scenario is not None and scenario not in _SCENARIOS:
        raise GraphError(
            GraphErrorCode.STATE_INVALID,
            "Studio scenario is not registered",
        )


def _assert_studio_resume_command_safe(command: Command[Any]) -> None:
    if (
        command.graph is not None
        or command.update is not None
        or not _command_goto_is_empty(command.goto)
    ):
        raise GraphError(
            GraphErrorCode.STUDIO_STATE_EDIT_FORBIDDEN,
            "Studio command may only contain a resume decision",
        )
    resume = command.resume
    if not isinstance(resume, Mapping):
        raise GraphError(
            GraphErrorCode.STUDIO_STATE_EDIT_FORBIDDEN,
            "Studio command resume decision is not registered",
        )
    fields = frozenset(resume)
    if fields == {"confirmed"} and resume.get("confirmed") is True:
        return
    if fields == {"approved"} and isinstance(
        resume.get("approved"), bool
    ):
        return
    raise GraphError(
        GraphErrorCode.STUDIO_STATE_EDIT_FORBIDDEN,
        "Studio command resume decision is not registered",
    )


def _command_goto_is_empty(value: object) -> bool:
    return value is None or (
        isinstance(value, (list, tuple)) and len(value) == 0
    )


def _validate_studio_interrupt_resume(
    resume: object,
    *,
    expected_kind: str,
) -> bool:
    if isinstance(resume, Mapping):
        fields = frozenset(resume)
        if (
            expected_kind == "clarification"
            and fields == {"confirmed"}
            and resume.get("confirmed") is True
        ):
            return True
        if (
            expected_kind == "approval"
            and fields == {"approved"}
            and isinstance(resume.get("approved"), bool)
        ):
            return bool(resume["approved"])
    raise GraphError(
        GraphErrorCode.STUDIO_STATE_EDIT_FORBIDDEN,
        "Studio resume decision does not match the current interrupt",
    )


def _assert_studio_command_matches_snapshot(
    command: Command[Any],
    snapshot: Any,
) -> None:
    next_nodes = tuple(snapshot.next)
    if len(next_nodes) != 1 or next_nodes[0] not in {
        "clarification_interrupt",
        "approval_interrupt",
    }:
        _raise_studio_interrupt_binding_forbidden()
    expected_kind = next_nodes[0].removesuffix("_interrupt")
    tasks = tuple(snapshot.tasks)
    if len(tasks) != 1 or tasks[0].name != next_nodes[0]:
        _raise_studio_interrupt_binding_forbidden()
    interrupts = tuple(tasks[0].interrupts)
    if len(interrupts) != 1 or not isinstance(
        interrupts[0].value, Mapping
    ):
        _raise_studio_interrupt_binding_forbidden()
    if interrupts[0].value.get("kind") != expected_kind:
        _raise_studio_interrupt_binding_forbidden()
    _validate_studio_interrupt_resume(
        command.resume,
        expected_kind=expected_kind,
    )


def _latest_checkpoint_query_config(
    invocation_config: Mapping[str, Any],
) -> dict[str, Any]:
    configurable = invocation_config.get("configurable")
    if not isinstance(configurable, Mapping):
        _raise_studio_checkpoint_binding_forbidden()
    latest_configurable = dict(configurable)
    latest_configurable.pop("checkpoint_id", None)
    latest_config = dict(invocation_config)
    latest_config["configurable"] = latest_configurable
    return latest_config


def _assert_latest_checkpoint_binding(
    invocation_config: Mapping[str, Any],
    latest_snapshot: Any,
) -> None:
    requested = invocation_config.get("configurable")
    snapshot_config = latest_snapshot.config
    if not isinstance(snapshot_config, Mapping):
        _raise_studio_checkpoint_binding_forbidden()
    authoritative = snapshot_config.get("configurable")
    if not isinstance(requested, Mapping) or not isinstance(
        authoritative, Mapping
    ):
        _raise_studio_checkpoint_binding_forbidden()
    if requested.get("thread_id") != authoritative.get("thread_id"):
        _raise_studio_checkpoint_binding_forbidden()
    if requested.get("checkpoint_ns", "") != authoritative.get(
        "checkpoint_ns", ""
    ):
        _raise_studio_checkpoint_binding_forbidden()
    requested_checkpoint = requested.get("checkpoint_id")
    latest_checkpoint = authoritative.get("checkpoint_id")
    if not isinstance(latest_checkpoint, str) or not latest_checkpoint:
        _raise_studio_checkpoint_binding_forbidden()
    if requested_checkpoint is not None and (
        not isinstance(requested_checkpoint, str)
        or requested_checkpoint != latest_checkpoint
    ):
        _raise_studio_checkpoint_binding_forbidden()


def _raise_studio_checkpoint_binding_forbidden() -> NoReturn:
    raise GraphError(
        GraphErrorCode.STUDIO_STATE_EDIT_FORBIDDEN,
        "Studio resume must target the latest checkpoint",
    )


def _raise_studio_interrupt_binding_forbidden() -> NoReturn:
    raise GraphError(
        GraphErrorCode.STUDIO_STATE_EDIT_FORBIDDEN,
        "Studio resume decision does not match the current interrupt",
    )


def _invocation_config(
    args: tuple[Any, ...],
    kwargs: Mapping[str, Any],
) -> dict[str, Any]:
    config = args[0] if args else kwargs.get("config")
    if not isinstance(config, dict):
        _raise_studio_interrupt_binding_forbidden()
    return config


def _replace_invocation_config(
    args: tuple[Any, ...],
    kwargs: Mapping[str, Any],
    config: dict[str, Any],
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    updated_kwargs = dict(kwargs)
    if args:
        return (config, *args[1:]), updated_kwargs
    updated_kwargs["config"] = config
    return args, updated_kwargs


def _raise_studio_state_update_forbidden() -> NoReturn:
    raise GraphError(
        GraphErrorCode.STUDIO_STATE_EDIT_FORBIDDEN,
        "Studio state update entry points are forbidden",
    )


def _install_studio_ingress_guard(compiled_graph: Any) -> None:
    original_astream = compiled_graph.astream
    original_abulk_update_state = compiled_graph.abulk_update_state
    original_aupdate_state = compiled_graph.aupdate_state
    original_bulk_update_state = compiled_graph.bulk_update_state
    original_copy = compiled_graph.copy
    original_stream = compiled_graph.stream
    original_update_state = compiled_graph.update_state

    @wraps(original_astream)
    async def guarded_astream(
        value: Any,
        *args: Any,
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        _assert_studio_invocation_input(value)
        execution_args = args
        execution_kwargs = kwargs
        if isinstance(value, Command):
            invocation_config = _invocation_config(args, kwargs)
            latest_config = _latest_checkpoint_query_config(invocation_config)
            snapshot = await compiled_graph.aget_state(latest_config)
            _assert_latest_checkpoint_binding(invocation_config, snapshot)
            _assert_studio_command_matches_snapshot(value, snapshot)
            execution_args, execution_kwargs = _replace_invocation_config(
                args,
                kwargs,
                latest_config,
            )
        async for chunk in original_astream(
            value,
            *execution_args,
            **execution_kwargs,
        ):
            yield chunk

    @wraps(original_stream)
    def guarded_stream(
        value: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Iterator[Any]:
        _assert_studio_invocation_input(value)
        execution_args = args
        execution_kwargs = kwargs
        if isinstance(value, Command):
            invocation_config = _invocation_config(args, kwargs)
            latest_config = _latest_checkpoint_query_config(invocation_config)
            snapshot = compiled_graph.get_state(latest_config)
            _assert_latest_checkpoint_binding(invocation_config, snapshot)
            _assert_studio_command_matches_snapshot(value, snapshot)
            execution_args, execution_kwargs = _replace_invocation_config(
                args,
                kwargs,
                latest_config,
            )
        yield from original_stream(value, *execution_args, **execution_kwargs)

    @wraps(original_copy)
    def guarded_copy(*args: Any, **kwargs: Any) -> Any:
        copied_graph = original_copy(*args, **kwargs)
        _install_studio_ingress_guard(copied_graph)
        return copied_graph

    @wraps(original_update_state)
    def forbidden_update_state(*args: Any, **kwargs: Any) -> Any:
        _raise_studio_state_update_forbidden()

    @wraps(original_aupdate_state)
    async def forbidden_aupdate_state(*args: Any, **kwargs: Any) -> Any:
        _raise_studio_state_update_forbidden()

    @wraps(original_bulk_update_state)
    def forbidden_bulk_update_state(*args: Any, **kwargs: Any) -> Any:
        _raise_studio_state_update_forbidden()

    @wraps(original_abulk_update_state)
    async def forbidden_abulk_update_state(*args: Any, **kwargs: Any) -> Any:
        _raise_studio_state_update_forbidden()

    compiled_graph.abulk_update_state = forbidden_abulk_update_state
    compiled_graph.astream = guarded_astream
    compiled_graph.aupdate_state = forbidden_aupdate_state
    compiled_graph.bulk_update_state = forbidden_bulk_update_state
    compiled_graph.copy = guarded_copy
    compiled_graph.stream = guarded_stream
    compiled_graph.update_state = forbidden_update_state


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
    definition = build_flowpilot_it_service_graph(
        StudioSafeState,
        nodes.as_graph_nodes(),
        checkpointer=checkpointer,
    )
    _install_studio_ingress_guard(definition.graph)
    return definition


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
