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
    "refresh_token",
    "secret",
    "session_ref",
)


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
        "terminal_reason": _stable_value(
            source.get("terminal_reason"),
            _STABLE_CODE,
        ),
        "failure_code": failure_code,
    }
    _assert_projection_safe(projection)
    return projection


def assert_studio_input_safe(
    state: Mapping[str, Any],
    *,
    expected_profile: StudioProfile,
) -> None:
    requested_profile = state.get("profile")
    if (
        requested_profile is not None
        and requested_profile != expected_profile.value
    ):
        raise GraphError(
            GraphErrorCode.STUDIO_PROFILE_FORBIDDEN,
            "Studio input cannot select another execution profile",
        )
    for key in state:
        normalized = str(key).lower()
        if normalized in _AUTHORITY_FIELDS or any(
            fragment in normalized for fragment in _SENSITIVE_NAME_FRAGMENTS
        ):
            raise GraphError(
                GraphErrorCode.STUDIO_STATE_EDIT_FORBIDDEN,
                "Studio input contains an authoritative or sensitive field",
            )


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
