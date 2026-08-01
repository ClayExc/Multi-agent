"""M5-1 parallel read branches — FP-FLOW-003 with per-branch failure.

AC-E2E-002 steps 3: the three read-only branches (device standard,
inventory, permission template) fan out in parallel over the extended
factory topology, their Trace intervals overlap, and an independent branch
failure is localized to the exact branch without aborting the other reads
or producing a fake COMPLETED.
"""

from __future__ import annotations

from datetime import datetime

from flowpilot_graph import GraphStatus
from flowpilot_graph.errors import GraphError, GraphErrorCode
from flowpilot_graph.reducer import BranchResult, reduce_parallel

from .conftest import (
    OnboardingHarness,
    OnboardingProbeOptions,
    build_harness,
    build_submit_command,
    execute,
    interrupt_card,
)


def _intervals(harness: OnboardingHarness) -> dict[str, tuple[datetime, datetime]]:
    state = harness.graph.last_safe_state
    assert state is not None
    reads = state.get("reads") or {}
    return {
        branch: (
            datetime.fromisoformat(entry["started_at"].replace("Z", "+00:00")),
            datetime.fromisoformat(entry["finished_at"].replace("Z", "+00:00")),
        )
        for branch, entry in reads.items()
    }


async def _complete_inputs(harness: OnboardingHarness) -> None:
    task_id = harness.create.task_id
    create_ref = str(harness.create.payload["initial_message_ref"])
    harness.resolver.set_fields(
        create_ref,
        {"full_name": "Chen Yi", "department": "engineering"},
    )
    await execute(harness, harness.create, run_id="run_pr_reads_a")
    ref1 = f"message://tenant-a/onboarding/{task_id}/step1"
    harness.resolver.set_fields(
        ref1, {"manager": "manager-alice", "location": "Shanghai"}
    )
    await execute(harness, build_submit_command(task_id, ref1), run_id="run_pr_reads_b")
    ref2 = f"message://tenant-a/onboarding/{task_id}/step2"
    harness.resolver.set_fields(ref2, {"start_date": "2026-09-01"})
    await execute(harness, build_submit_command(task_id, ref2), run_id="run_pr_reads_c")


async def test_three_branches_run_in_parallel_with_overlapping_trace() -> None:
    harness = await build_harness(task_id="task_onbpar001")
    await _complete_inputs(harness)

    # The graph paused at the manager approval after the parallel fan-out.
    assert harness.graph.last_safe_state is not None
    card = interrupt_card(harness)
    assert card["kind"] == "approval"
    assert set(harness.probe.read_branches) == {
        "device_standard",
        "inventory",
        "permission_template",
    }
    intervals = _intervals(harness)
    assert set(intervals) == {"device_standard", "inventory", "permission_template"}
    # FP-FLOW-003: every branch interval overlaps every other branch
    # interval (all three started before the first one finished).
    for left in intervals.values():
        for right in intervals.values():
            assert left[0] < right[1], "branch trace intervals must overlap"
            assert right[0] < left[1], "branch trace intervals must overlap"

    # The planned sub-actions ground on the merged read facts.
    state = harness.graph.last_safe_state
    sub_actions = state.get("sub_actions") or []
    assert [item["tool"] for item in sub_actions] == [
        "device.allocate.v1",
        "permission.grant.v1",
    ]
    device = sub_actions[0]
    assert device["arguments"]["model"] == "ThinkPad-X1-Carbon-G11"
    permission = sub_actions[1]
    assert permission["arguments"]["template_id"] == "PT-BE-01"


async def test_branch_failure_is_isolated_and_localized() -> None:
    harness = await build_harness(
        task_id="task_onbpar002",
        probe_options=OnboardingProbeOptions(
            branch_failures={"inventory": "INVENTORY_UNAVAILABLE"}
        ),
    )
    await _complete_inputs(harness)

    # The other branches still executed (independent fan-out) but the
    # inventory failure is localized to its branch and the terminal state
    # is FAILED — never a fake COMPLETED.
    assert set(harness.probe.read_branches) == {
        "device_standard",
        "inventory",
        "permission_template",
    }
    outcome = harness.graph.last_safe_state
    assert outcome is not None
    assert outcome.get("status") == GraphStatus.FAILED.value
    assert outcome.get("failure_code") == "READ_FAILED:inventory:INVENTORY_UNAVAILABLE"


async def test_read_failure_localized_by_reducer_failures_map() -> None:
    harness = await build_harness(
        task_id="task_onbpar003",
        probe_options=OnboardingProbeOptions(
            branch_failures={"permission_template": "TEMPLATE_NOT_FOUND"}
        ),
    )
    await _complete_inputs(harness)
    outcome = harness.graph.last_safe_state
    assert outcome is not None
    assert outcome.get("status") == GraphStatus.FAILED.value
    assert (
        outcome.get("failure_code")
        == "READ_FAILED:permission_template:TEMPLATE_NOT_FOUND"
    )


async def test_reducer_surfaces_per_branch_failures_without_aborting() -> None:
    reduced = reduce_parallel(
        (
            BranchResult(branch_id="device_standard", facts={"model": "X1"}),
            BranchResult(
                branch_id="inventory",
                facts={},
                failure_code="INVENTORY_UNAVAILABLE",
            ),
            BranchResult(
                branch_id="permission_template",
                facts={},
                failure_code="TEMPLATE_NOT_FOUND",
            ),
        )
    )
    assert reduced.facts == {"model": "X1"}
    assert reduced.failures == {
        "inventory": "INVENTORY_UNAVAILABLE",
        "permission_template": "TEMPLATE_NOT_FOUND",
    }
    assert reduced.branch_order == (
        "device_standard",
        "inventory",
        "permission_template",
    )


async def test_reducer_rejects_conflicting_facts_still() -> None:
    try:
        reduce_parallel(
            (
                BranchResult(branch_id="a", facts={"status": "old"}),
                BranchResult(branch_id="b", facts={"status": "new"}),
            )
        )
        raise AssertionError("conflicting facts must raise")
    except GraphError as exc:
        assert exc.code is GraphErrorCode.PARALLEL_REDUCER_CONFLICT
