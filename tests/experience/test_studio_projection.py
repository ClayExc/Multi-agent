"""Safe five-stage Studio projection and product rendering."""

from __future__ import annotations

from copy import deepcopy

import pytest


def _frame(step: int, *, failure_code: str = "") -> dict[str, object]:
    phases = ("intake", "interrupt", "knowledge", "model", "terminal")
    nodes = (
        "prepare",
        "clarification_interrupt",
        "knowledge_read",
        "run_agent",
        "finalize",
    )
    return {
        "schema": "flowpilot.debug-projection.v1",
        "profile": "studio-safe",
        "frame_id": f"frame-{step}",
        "step": step,
        "node": nodes[step - 1],
        "route": "",
        "status": "FAILED" if failure_code else "RUNNING",
        "terminal_reason": failure_code,
        "failure_code": failure_code,
        "budget": {},
        "context": {"layers": {}, "token_budget": 0, "trim_reason_code": ""},
        "handoff": {},
        "interrupt": {
            "kind": "clarification" if step == 2 else "",
            "resolved": step > 2,
        },
        "knowledge": {},
        "tools": {},
        "recovery": {
            "task_ref": "task://sha256/opaque",
            "checkpoint_sequence": step - 1,
            "run_generation": 1,
            "lease_status": "synthetic",
            "resumed": step > 2,
        },
        "workflow": {
            "graph_id": "flowpilot_it_service",
            "graph_version": "flowpilot.enterprise-knowledge.m7.v1",
            "intent": "knowledge_question",
            "actor": "artifact_writer" if step == 5 else "orchestrator",
        },
        "progress": {"current_step": step, "total_steps": 5, "phase": phases[step - 1]},
        "model": {
            "call_count": 2 if step >= 4 else 0,
            "outcome": "failed_retryable" if failure_code else "completed",
        },
        "references": {
            "citation_count": 1 if step >= 3 else 0,
            "artifact_count": 1 if step == 5 and not failure_code else 0,
        },
    }


def test_five_stage_projection_is_monotonic_and_renderable() -> None:
    from flowpilot_shell.projection import StudioProgressView, validate_progression
    from flowpilot_shell.render import render_studio_progress

    views = [StudioProgressView.from_mapping(_frame(step)) for step in range(1, 6)]
    validated = validate_progression(views)
    html = render_studio_progress(validated[-1])

    assert [view.phase for view in validated] == [
        "intake",
        "interrupt",
        "knowledge",
        "model",
        "terminal",
    ]
    assert 'data-step="5"' in html
    assert "模型调用</dt><dd>2" in html
    assert "引用</dt><dd>1" in html


def test_projection_rejects_sensitive_or_unknown_browser_fields() -> None:
    from flowpilot_shell.models import ShellContractError
    from flowpilot_shell.projection import StudioProgressView

    sensitive = _frame(3)
    sensitive["context"] = {"reasoning": "hidden-chain"}
    with pytest.raises(ShellContractError, match="forbidden"):
        StudioProgressView.from_mapping(sensitive)

    forged = _frame(3)
    forged["tenant_id"] = "tenant-forged"
    with pytest.raises(ShellContractError, match="field set changed"):
        StudioProgressView.from_mapping(forged)


def test_projection_rejects_backwards_duplicate_and_incomplete_progress() -> None:
    from flowpilot_shell.models import ShellContractError
    from flowpilot_shell.projection import StudioProgressView, validate_progression

    views = [StudioProgressView.from_mapping(_frame(step)) for step in range(1, 6)]
    with pytest.raises(ShellContractError, match="backwards"):
        validate_progression([views[1], views[0], *views[2:]])
    duplicate = list(views)
    duplicate[4] = StudioProgressView.from_mapping(
        {**_frame(5), "frame_id": "frame-4"}
    )
    with pytest.raises(ShellContractError, match="duplicate"):
        validate_progression(duplicate)
    with pytest.raises(ShellContractError, match="five stages"):
        validate_progression(views[:-1])


@pytest.mark.parametrize(
    ("failure_code", "hint"),
    (
        ("PROVIDER_TIMEOUT", "模型服务超时"),
        ("GRAPH_CHECKPOINT_UNAVAILABLE", "恢复失败"),
    ),
)
def test_failure_projection_has_stable_actionable_hint(
    failure_code: str,
    hint: str,
) -> None:
    from flowpilot_shell.projection import StudioProgressView
    from flowpilot_shell.render import render_studio_progress

    view = StudioProgressView.from_mapping(_frame(5, failure_code=failure_code))
    html = render_studio_progress(view)
    assert hint in html
    assert 'role="alert"' in html


def test_projection_html_escapes_registered_identifiers() -> None:
    from flowpilot_shell.projection import StudioProgressView
    from flowpilot_shell.render import render_studio_progress

    frame = deepcopy(_frame(5))
    frame["node"] = "<script>alert(1)</script>"
    html = render_studio_progress(StudioProgressView.from_mapping(frame))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
