from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .errors import GraphError, GraphErrorCode
from .state import GraphState

_STABLE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,127}$")
_STABLE_NODE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_STABLE_IDENTIFIER = re.compile(r"^[a-z][a-z0-9._-]{1,127}$")
_FRAME_ID = re.compile(
    r"^(?P<node>[a-z][a-z0-9_]{1,63}):"
    r"(?P<step>[1-9][0-9]*):"
    r"(?P<retry>[0-9]+):"
    r"(?P<sequence>[0-9]+)$"
)
_OPAQUE_TASK_REF = re.compile(r"^task://sha256/[0-9a-f]{16}$")
_STUDIO_INPUT_FIELDS = frozenset({"scenario"})
_AUTHORITY_FIELDS = frozenset(
    {
        "action",
        "approval",
        "approval_token",
        "checkpoint",
        "command",
        "ledger",
        "lease",
        "lease_token",
        "planned_action",
        "policy_decision",
        "production_profile",
        "security_context",
        "task",
        "task_id",
        "tenant_id",
        "thread_id",
        "tool_payload",
    }
)
_SENSITIVE_NAME_FRAGMENTS = (
    "access_token",
    "api_key",
    "authorization",
    "bearer_token",
    "cookie",
    "credential",
    "password",
    "private_key",
    "provider_session",
    "raw_context",
    "reasoning",
    "refresh_token",
    "secret",
    "session_ref",
    "chain_of_thought",
)
_STUDIO_SERVER_DERIVED_FIELDS = frozenset(
    {
        "active_actor",
        "approval_granted",
        "approval_required",
        "artifact_count",
        "budget_remaining",
        "checkpoint_sequence",
        "citation_count",
        "compensation_status",
        "context_layers",
        "context_rebuilt",
        "context_token_budget",
        "current_node",
        "debug_projection",
        "failure_code",
        "frame_id",
        "graph_id",
        "graph_version",
        "handoff_count",
        "handoff_reason",
        "input_complete",
        "intent",
        "interrupt_kind",
        "interrupt_resolved",
        "knowledge_call_count",
        "knowledge_read_complete",
        "lease_status",
        "maximum_retries",
        "model_call_count",
        "profile",
        "progress_phase",
        "progress_step",
        "progress_total",
        "reads_complete",
        "recovery_resumed",
        "retry_count",
        "route",
        "run_generation",
        "runtime_outcome",
        "service_read_complete",
        "service_read_skipped",
        "status",
        "step",
        "step_count",
        "studio_input_validated",
        "studio_input_error_code",
        "studio_input_error_message",
        "task_ref",
        "terminal_reason",
        "tool_mode",
        "tool_scope_rebuilt",
        "tool_stage",
        "trim_reason_code",
        "visited_nodes",
    }
)
_BASE_FRAME_FIELDS = frozenset(
    {
        "budget",
        "context",
        "failure_code",
        "frame_id",
        "handoff",
        "interrupt",
        "knowledge",
        "node",
        "profile",
        "recovery",
        "route",
        "schema",
        "status",
        "step",
        "terminal_reason",
        "tools",
    }
)
_PRODUCT_FRAME_FIELDS = frozenset(
    {"model", "progress", "references", "workflow"}
)
_FRAME_MAPPING_FIELDS = {
    "budget": frozenset(
        {"maximum_retries", "remaining_steps", "retry_count"}
    ),
    "context": frozenset({"layers", "token_budget", "trim_reason_code"}),
    "handoff": frozenset(
        {"context_rebuilt", "count", "reason_code", "tool_scope_rebuilt"}
    ),
    "interrupt": frozenset({"kind", "resolved"}),
    "knowledge": frozenset(
        {"call_count", "citation_count", "service_read_skipped"}
    ),
    "model": frozenset({"call_count", "outcome"}),
    "progress": frozenset({"current_step", "phase", "total_steps"}),
    "references": frozenset({"artifact_count", "citation_count"}),
    "tools": frozenset({"mode", "stage"}),
    "workflow": frozenset({"actor", "graph_id", "graph_version", "intent"}),
}
_RECOVERY_BASE_FIELDS = frozenset(
    {"checkpoint_sequence", "lease_status", "run_generation", "task_ref"}
)
_CONTEXT_LAYER_FIELDS = frozenset({"L0", "L1", "L2"})


class StudioProfile(StrEnum):
    SAFE = "studio-safe"
    INTEGRATION = "studio-integration"
    PRODUCTION = "production"


@dataclass(frozen=True, slots=True)
class DebugProjectionPolicy:
    profile: StudioProfile = StudioProfile.SAFE
    schema: str = "flowpilot.debug-projection.v1"


def debug_projection(
    state: GraphState | Mapping[str, Any],
    *,
    policy: DebugProjectionPolicy | None = None,
) -> dict[str, Any]:
    """Return a default-deny, JSON-safe view of graph execution state."""

    effective_policy = policy or DebugProjectionPolicy()
    source = (
        state.to_checkpoint()
        if isinstance(state, GraphState)
        else dict(state)
    )
    node = _stable_value(source.get("current_node") or source.get("node"), _STABLE_NODE)
    route = _stable_value(source.get("route"), _STABLE_NODE)
    status = _stable_value(source.get("status"), _STABLE_CODE)
    failure_code = _stable_value(source.get("failure_code"), _STABLE_CODE)
    interrupt_kind = _stable_value(
        source.get("interrupt_kind"),
        _STABLE_NODE,
    )
    handoff_reason = _stable_value(
        source.get("handoff_reason"),
        _STABLE_CODE,
    )

    projection: dict[str, Any] = {
        "schema": effective_policy.schema,
        "profile": effective_policy.profile.value,
        "node": node,
        "route": route,
        "status": status,
        "budget": {
            "remaining_steps": _non_negative_int(
                source.get("budget_remaining")
            ),
            "retry_count": _non_negative_int(source.get("retry_count")),
            "maximum_retries": _non_negative_int(
                source.get("maximum_retries")
            ),
        },
        "recovery": {
            "task_ref": _opaque_ref(
                "task",
                source.get("task_ref") or source.get("task_id"),
            ),
            "checkpoint_sequence": _non_negative_int(
                source.get("checkpoint_sequence")
            ),
            "run_generation": _positive_int(source.get("run_generation")),
            "lease_status": _stable_value(
                source.get("lease_status"),
                _STABLE_NODE,
            ),
        },
        "interrupt": {
            "kind": interrupt_kind,
            "resolved": _boolean(source.get("interrupt_resolved")),
        },
        "handoff": {
            "count": _non_negative_int(source.get("handoff_count")),
            "reason_code": handoff_reason,
            "context_rebuilt": _boolean(source.get("context_rebuilt")),
            "tool_scope_rebuilt": _boolean(
                source.get("tool_scope_rebuilt")
            ),
        },
        "context": {
            "layers": _context_layers(source.get("context_layers")),
            "token_budget": _non_negative_int(
                source.get("context_token_budget")
            ),
            "trim_reason_code": _stable_value(
                source.get("trim_reason_code"),
                _STABLE_CODE,
            ),
        },
        "tools": {
            "mode": _stable_value(source.get("tool_mode"), _STABLE_NODE),
            "stage": _stable_value(source.get("tool_stage"), _STABLE_NODE),
        },
        "knowledge": {
            "call_count": _non_negative_int(
                source.get("knowledge_call_count")
            ),
            "citation_count": _non_negative_int(source.get("citation_count")),
            "service_read_skipped": _boolean(
                source.get("service_read_skipped")
            ),
        },
        "terminal_reason": _stable_value(
            source.get("terminal_reason"),
            _STABLE_CODE,
        ),
        "failure_code": failure_code,
    }
    _assert_projection_safe(projection)
    return projection


def product_debug_projection(
    state: GraphState | Mapping[str, Any],
    *,
    policy: DebugProjectionPolicy | None = None,
) -> dict[str, Any]:
    """Add product progress to the safe projection without exposing content.

    Product-facing Studio runs need enough structure to show where a resumed
    graph is executing.  The extension deliberately exposes only registered
    identifiers, stable phase names, counters, and recovery booleans.  Prompt,
    answer, citation content, provider sessions, and authority-bearing state
    remain outside the projection.
    """

    source = (
        state.to_checkpoint()
        if isinstance(state, GraphState)
        else dict(state)
    )
    projection = debug_projection(source, policy=policy)
    projection["workflow"] = {
        "graph_id": _stable_value(source.get("graph_id"), _STABLE_IDENTIFIER),
        "graph_version": _stable_value(
            source.get("graph_version"),
            _STABLE_IDENTIFIER,
        ),
        "intent": _stable_value(source.get("intent"), _STABLE_NODE),
        "actor": _stable_value(source.get("active_actor"), _STABLE_NODE),
    }
    projection["progress"] = {
        "current_step": _positive_int(source.get("progress_step")),
        "total_steps": _positive_int(source.get("progress_total")),
        "phase": _stable_value(source.get("progress_phase"), _STABLE_NODE),
    }
    projection["model"] = {
        "call_count": _non_negative_int(source.get("model_call_count")),
        "outcome": _stable_value(source.get("runtime_outcome"), _STABLE_NODE),
    }
    projection["references"] = {
        "citation_count": _non_negative_int(source.get("citation_count")),
        "artifact_count": _non_negative_int(source.get("artifact_count")),
    }
    recovery = projection["recovery"]
    if isinstance(recovery, dict):
        recovery["resumed"] = _boolean(source.get("recovery_resumed"))
    _assert_projection_safe(projection)
    return projection


def assert_studio_input_safe(
    state: Mapping[str, Any],
    *,
    expected_profile: StudioProfile,
) -> None:
    del expected_profile
    if "profile" in state:
        raise GraphError(
            GraphErrorCode.STUDIO_STATE_EDIT_FORBIDDEN,
            "Studio input cannot select another execution profile",
        )
    _assert_studio_value_safe(state)
    if (
        any(not isinstance(key, str) for key in state)
        or set(state) - _STUDIO_INPUT_FIELDS
    ):
        raise GraphError(
            GraphErrorCode.STUDIO_STATE_EDIT_FORBIDDEN,
            "Studio input contains a field that is not registered",
        )
    scenario = state.get("scenario")
    if scenario is not None and not isinstance(scenario, str):
        raise GraphError(
            GraphErrorCode.STUDIO_STATE_EDIT_FORBIDDEN,
            "Studio scenario must be a registered string",
        )


def assert_debug_projection_frame_safe(frame: Mapping[str, Any]) -> None:
    """Validate a persisted Studio frame before any reducer accepts it."""

    _assert_projection_safe(frame)
    fields = frozenset(frame)
    is_product = bool(fields & _PRODUCT_FRAME_FIELDS)
    expected_fields = _BASE_FRAME_FIELDS | (
        _PRODUCT_FRAME_FIELDS if is_product else frozenset()
    )
    if fields != expected_fields or any(
        not isinstance(key, str) for key in frame
    ):
        raise _unsafe_frame("debug frame fields are not registered")
    if (
        frame.get("schema") != "flowpilot.debug-projection.v1"
        or frame.get("profile") != StudioProfile.SAFE.value
    ):
        raise _unsafe_frame("debug frame schema or profile is invalid")

    for field, expected_nested_fields in _FRAME_MAPPING_FIELDS.items():
        if field not in frame:
            continue
        nested = frame.get(field)
        if not isinstance(nested, Mapping) or frozenset(nested) != (
            expected_nested_fields
        ):
            raise _unsafe_frame("debug frame nested fields are invalid")
    recovery = frame.get("recovery")
    expected_recovery = _RECOVERY_BASE_FIELDS | (
        frozenset({"resumed"}) if is_product else frozenset()
    )
    if not isinstance(recovery, Mapping) or frozenset(recovery) != (
        expected_recovery
    ):
        raise _unsafe_frame("debug frame recovery fields are invalid")
    context = frame.get("context")
    layers = context.get("layers") if isinstance(context, Mapping) else None
    if not isinstance(layers, Mapping) or frozenset(layers) != (
        _CONTEXT_LAYER_FIELDS
    ) or any(not isinstance(value, bool) for value in layers.values()):
        raise _unsafe_frame("debug frame context layers are invalid")
    if not _frame_scalar_shapes_are_valid(frame, is_product=is_product):
        raise _unsafe_frame("debug frame scalar values are invalid")

    frame_id = frame.get("frame_id")
    node = frame.get("node")
    step = frame.get("step")
    budget = frame.get("budget")
    retry = budget.get("retry_count") if isinstance(budget, Mapping) else None
    sequence = (
        recovery.get("checkpoint_sequence")
        if isinstance(recovery, Mapping)
        else None
    )
    matched = _FRAME_ID.fullmatch(frame_id) if isinstance(frame_id, str) else None
    if (
        matched is None
        or not isinstance(node, str)
        or _STABLE_NODE.fullmatch(node) is None
        or isinstance(step, bool)
        or not isinstance(step, int)
        or step < 1
        or isinstance(retry, bool)
        or not isinstance(retry, int)
        or retry < 0
        or isinstance(sequence, bool)
        or not isinstance(sequence, int)
        or sequence < 0
        or matched.group("node") != node
        or int(matched.group("step")) != step
        or int(matched.group("retry")) != retry
        or int(matched.group("sequence")) != sequence
    ):
        raise _unsafe_frame("debug frame identity binding is invalid")
    try:
        encoded = json.dumps(
            frame,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError) as exc:
        raise _unsafe_frame("debug frame is not JSON-safe") from exc
    if len(encoded) > 16_384:
        raise _unsafe_frame("debug frame exceeds the safe size limit")


def debug_projection_frame_fingerprint(frame: Mapping[str, Any]) -> str:
    assert_debug_projection_frame_safe(frame)
    return projection_digest(frame)


def assert_studio_profile_allowed(profile: StudioProfile) -> None:
    if profile is StudioProfile.PRODUCTION:
        raise GraphError(
            GraphErrorCode.STUDIO_PROFILE_FORBIDDEN,
            "Production profile cannot be exposed through Studio",
        )
    if profile is StudioProfile.INTEGRATION:
        raise GraphError(
            GraphErrorCode.STUDIO_PROFILE_FORBIDDEN,
            "Studio integration requires separately configured trusted ports",
        )


def projection_digest(value: Mapping[str, Any]) -> str:
    _assert_projection_safe(value)
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _assert_studio_value_safe(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = _normalized_key(key)
            if (
                normalized in _AUTHORITY_FIELDS
                or normalized in _STUDIO_SERVER_DERIVED_FIELDS
                or any(
                    fragment in normalized
                    for fragment in _SENSITIVE_NAME_FRAGMENTS
                )
            ):
                raise GraphError(
                    GraphErrorCode.STUDIO_STATE_EDIT_FORBIDDEN,
                    "Studio input contains authoritative or sensitive state",
                )
            _assert_studio_value_safe(child)
    elif isinstance(value, (tuple, list)):
        for child in value:
            _assert_studio_value_safe(child)


def _normalized_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")


def _frame_scalar_shapes_are_valid(
    frame: Mapping[str, Any],
    *,
    is_product: bool,
) -> bool:
    budget = frame["budget"]
    recovery = frame["recovery"]
    interrupt_state = frame["interrupt"]
    handoff = frame["handoff"]
    context = frame["context"]
    tools = frame["tools"]
    knowledge = frame["knowledge"]
    if not all(
        isinstance(item, Mapping)
        for item in (
            budget,
            recovery,
            interrupt_state,
            handoff,
            context,
            tools,
            knowledge,
        )
    ):
        return False
    if not (
        _matches(frame.get("node"), _STABLE_NODE)
        and _matches_optional(frame.get("route"), _STABLE_NODE)
        and _matches(frame.get("status"), _STABLE_CODE)
        and _matches_optional(frame.get("terminal_reason"), _STABLE_CODE)
        and _matches_optional(frame.get("failure_code"), _STABLE_CODE)
        and all(
            _is_non_negative_int(budget.get(key))
            for key in ("remaining_steps", "retry_count", "maximum_retries")
        )
        and _matches_optional(recovery.get("task_ref"), _OPAQUE_TASK_REF)
        and _is_non_negative_int(recovery.get("checkpoint_sequence"))
        and _is_positive_int(recovery.get("run_generation"))
        and _matches_optional(recovery.get("lease_status"), _STABLE_NODE)
        and _matches_optional(interrupt_state.get("kind"), _STABLE_NODE)
        and isinstance(interrupt_state.get("resolved"), bool)
        and _is_non_negative_int(handoff.get("count"))
        and _matches_optional(handoff.get("reason_code"), _STABLE_CODE)
        and isinstance(handoff.get("context_rebuilt"), bool)
        and isinstance(handoff.get("tool_scope_rebuilt"), bool)
        and _is_optional_non_negative_int(context.get("token_budget"))
        and _matches_optional(context.get("trim_reason_code"), _STABLE_CODE)
        and _matches_optional(tools.get("mode"), _STABLE_NODE)
        and _matches_optional(tools.get("stage"), _STABLE_NODE)
        and _is_non_negative_int(knowledge.get("call_count"))
        and _is_non_negative_int(knowledge.get("citation_count"))
        and isinstance(knowledge.get("service_read_skipped"), bool)
    ):
        return False
    if not is_product:
        return True
    workflow = frame["workflow"]
    progress = frame["progress"]
    model = frame["model"]
    references = frame["references"]
    return (
        isinstance(workflow, Mapping)
        and isinstance(progress, Mapping)
        and isinstance(model, Mapping)
        and isinstance(references, Mapping)
        and _matches(workflow.get("graph_id"), _STABLE_IDENTIFIER)
        and _matches(workflow.get("graph_version"), _STABLE_IDENTIFIER)
        and _matches(workflow.get("intent"), _STABLE_NODE)
        and _matches(workflow.get("actor"), _STABLE_NODE)
        and _is_positive_int(progress.get("current_step"))
        and _is_positive_int(progress.get("total_steps"))
        and _matches(progress.get("phase"), _STABLE_NODE)
        and _is_non_negative_int(model.get("call_count"))
        and _matches_optional(model.get("outcome"), _STABLE_NODE)
        and _is_non_negative_int(references.get("citation_count"))
        and _is_non_negative_int(references.get("artifact_count"))
        and isinstance(recovery.get("resumed"), bool)
    )


def _matches(value: object, pattern: re.Pattern[str]) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _matches_optional(value: object, pattern: re.Pattern[str]) -> bool:
    return value is None or _matches(value, pattern)


def _is_non_negative_int(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value >= 0


def _is_positive_int(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, int)
        and value > 0
    )


def _is_optional_non_negative_int(value: object) -> bool:
    return value is None or _is_non_negative_int(value)


def _unsafe_frame(message: str) -> GraphError:
    return GraphError(GraphErrorCode.DEBUG_PROJECTION_UNSAFE, message)


def _opaque_ref(kind: str, value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    digest = hashlib.sha256(value.encode()).hexdigest()[:16]
    return f"{kind}://sha256/{digest}"


def _stable_value(value: object, pattern: re.Pattern[str]) -> str | None:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        return None
    return value


def _non_negative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _positive_int(value: object) -> int | None:
    normalized = _non_negative_int(value)
    return normalized if normalized is not None and normalized > 0 else None


def _boolean(value: object) -> bool:
    return value is True


def _context_layers(value: object) -> dict[str, bool]:
    if not isinstance(value, Mapping):
        return {"L0": False, "L1": False, "L2": False}
    return {layer: value.get(layer) is True for layer in ("L0", "L1", "L2")}


def _assert_projection_safe(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower()
            if normalized in _AUTHORITY_FIELDS or any(
                fragment in normalized
                for fragment in _SENSITIVE_NAME_FRAGMENTS
            ):
                raise GraphError(
                    GraphErrorCode.DEBUG_PROJECTION_UNSAFE,
                    "debug projection contains a forbidden field",
                )
            _assert_projection_safe(child)
    elif isinstance(value, (tuple, list)):
        for child in value:
            _assert_projection_safe(child)
