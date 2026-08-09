"""Strict product view of the safe five-stage Studio projection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .models import ShellContractError

_FRAME_FIELDS = frozenset(
    {
        "budget",
        "context",
        "failure_code",
        "frame_id",
        "handoff",
        "interrupt",
        "knowledge",
        "model",
        "node",
        "profile",
        "progress",
        "recovery",
        "references",
        "route",
        "schema",
        "status",
        "step",
        "terminal_reason",
        "tools",
        "workflow",
    }
)
_PHASES = ("intake", "interrupt", "knowledge", "model", "terminal")
_FORBIDDEN_KEYS = frozenset(
    {
        "answer",
        "answer_markdown",
        "api_key",
        "authorization",
        "chain_of_thought",
        "credential",
        "prompt",
        "question",
        "reasoning",
        "security_context",
        "session_ref",
        "tenant_id",
        "token",
    }
)


@dataclass(frozen=True, slots=True)
class StudioProgressView:
    frame_id: str
    node: str
    status: str
    current_step: int
    total_steps: int
    phase: str
    actor: str
    model_call_count: int
    model_outcome: str
    citation_count: int
    artifact_count: int
    interrupt_kind: str
    recovery_resumed: bool
    failure_code: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> StudioProgressView:
        if frozenset(value) != _FRAME_FIELDS:
            raise ShellContractError("Studio projection field set changed")
        _assert_no_forbidden_keys(value)
        if value.get("schema") != "flowpilot.debug-projection.v1":
            raise ShellContractError("Studio projection schema changed")
        if value.get("profile") != "studio-safe":
            raise ShellContractError("Studio projection is not studio-safe")
        progress = _exact_mapping(
            value.get("progress"),
            {"current_step", "total_steps", "phase"},
            "progress",
        )
        workflow = _exact_mapping(
            value.get("workflow"),
            {"graph_id", "graph_version", "intent", "actor"},
            "workflow",
        )
        model = _exact_mapping(
            value.get("model"), {"call_count", "outcome"}, "model"
        )
        references = _exact_mapping(
            value.get("references"),
            {"citation_count", "artifact_count"},
            "references",
        )
        interrupt = _exact_mapping(
            value.get("interrupt"), {"kind", "resolved"}, "interrupt"
        )
        recovery = _exact_mapping(
            value.get("recovery"),
            {
                "task_ref",
                "checkpoint_sequence",
                "run_generation",
                "lease_status",
                "resumed",
            },
            "recovery",
        )
        current_step = _integer(progress["current_step"], "current_step", minimum=1)
        total_steps = _integer(progress["total_steps"], "total_steps", minimum=1)
        phase = _text(progress["phase"], "phase")
        if total_steps != 5 or current_step > total_steps:
            raise ShellContractError("Studio progress is outside the five-stage model")
        if phase != _PHASES[current_step - 1]:
            raise ShellContractError("Studio progress phase does not match its step")
        resumed = recovery["resumed"]
        if not isinstance(resumed, bool):
            raise ShellContractError("Studio recovery.resumed must be boolean")
        return cls(
            frame_id=_text(value["frame_id"], "frame_id"),
            node=_text(value["node"], "node"),
            status=_text(value["status"], "status"),
            current_step=current_step,
            total_steps=total_steps,
            phase=phase,
            actor=_text(workflow["actor"], "workflow.actor"),
            model_call_count=_integer(model["call_count"], "model.call_count"),
            model_outcome=_text(model["outcome"], "model.outcome", allow_empty=True),
            citation_count=_integer(
                references["citation_count"], "references.citation_count"
            ),
            artifact_count=_integer(
                references["artifact_count"], "references.artifact_count"
            ),
            interrupt_kind=_text(
                interrupt["kind"], "interrupt.kind", allow_empty=True
            ),
            recovery_resumed=resumed,
            failure_code=_text(
                value["failure_code"], "failure_code", allow_empty=True
            ),
        )


def validate_progression(
    frames: Sequence[StudioProgressView],
) -> tuple[StudioProgressView, ...]:
    if not frames:
        raise ShellContractError("Studio progression is empty")
    steps = [frame.current_step for frame in frames]
    if steps != sorted(steps):
        raise ShellContractError("Studio progression moved backwards")
    if set(steps) != {1, 2, 3, 4, 5}:
        raise ShellContractError("Studio progression does not cover five stages")
    if len({frame.frame_id for frame in frames}) != len(frames):
        raise ShellContractError("Studio progression contains duplicate frame_id")
    return tuple(frames)


def _exact_mapping(
    value: object,
    fields: set[str],
    label: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ShellContractError(f"Studio {label} field set changed")
    return value


def _assert_no_forbidden_keys(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if normalized in _FORBIDDEN_KEYS:
                raise ShellContractError("Studio projection contains a forbidden field")
            _assert_no_forbidden_keys(child)
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for child in value:
            _assert_no_forbidden_keys(child)


def _text(
    value: object,
    label: str,
    *,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise ShellContractError(f"Studio {label} must be a string")
    return value


def _integer(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ShellContractError(f"Studio {label} must be an integer")
    return value
