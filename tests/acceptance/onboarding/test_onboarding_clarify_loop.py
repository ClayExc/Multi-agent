"""M5-1 clarification loop — WAITING_USER multi-round field completion.

AC-E2E-002 steps 1-2: the onboarding request interrupts until the five
required fields (full_name / department / manager / location / start_date)
arrive, each round charges the M4-2 hard context budget, and budget
exhaustion terminates as FAILED instead of looping forever.
"""

from __future__ import annotations

from flowpilot_graph import GraphStatus
from flowpilot_graph.onboarding import ONBOARDING_REQUIRED_FIELDS

from .conftest import (
    MANAGER,
    build_harness,
    build_submit_command,
    execute,
    interrupt_card,
)


async def test_initial_create_interrupts_with_missing_fields() -> None:
    harness = await build_harness(task_id="task_onbclar001")
    create_ref = str(harness.create.payload["initial_message_ref"])
    harness.resolver.set_fields(
        create_ref,
        {"full_name": "Chen Yi", "department": "engineering"},
    )
    outcome = await execute(harness, harness.create, run_id="run_clar_01")

    assert outcome.state.status is GraphStatus.WAITING_USER
    assert outcome.state.pending_reason == "onboarding_clarification:fields"
    card = interrupt_card(harness)
    assert card["schema"] == "flowpilot.onboarding-clarification.v1"
    assert card["kind"] == "clarification"
    assert set(card["required_fields"]) == {
        "manager",
        "location",
        "start_date",
    }
    # The first round was charged against the hard budget (FP-CTX-004).
    assert outcome.state.conversation_round == 1
    assert outcome.state.cumulative_input_tokens > 0
    assert harness.graph.ledger.round_count == 1
    assert harness.graph.ledger.entries[0].turn_index == 0


async def test_multi_round_completion_then_proceeds_to_parallel_reads() -> None:
    harness = await build_harness(task_id="task_onbclar002")
    task_id = harness.create.task_id
    create_ref = str(harness.create.payload["initial_message_ref"])
    harness.resolver.set_fields(
        create_ref,
        {"full_name": "Chen Yi", "department": "engineering"},
    )
    outcome = await execute(harness, harness.create, run_id="run_clar_02a")
    assert outcome.state.status is GraphStatus.WAITING_USER

    # First submission still misses start_date -> a second clarification
    # round is charged and the graph pauses again.
    ref1 = f"message://tenant-a/onboarding/{task_id}/step1"
    harness.resolver.set_fields(
        ref1, {"manager": MANAGER, "location": "Shanghai"}
    )
    outcome = await execute(
        harness,
        build_submit_command(task_id, ref1),
        run_id="run_clar_02b",
    )
    assert outcome.state.status is GraphStatus.WAITING_USER
    assert outcome.state.conversation_round == 2
    card = interrupt_card(harness)
    assert set(card["required_fields"]) == {"start_date"}
    assert card["conversation_round"] == 1

    # Second submission completes the five fields; the graph leaves the
    # clarification loop and proceeds to the parallel reads, then plans the
    # sub-actions and pauses at the manager approval.
    ref2 = f"message://tenant-a/onboarding/{task_id}/step2"
    harness.resolver.set_fields(ref2, {"start_date": "2026-09-01"})
    outcome = await execute(
        harness,
        build_submit_command(task_id, ref2),
        run_id="run_clar_02c",
    )
    assert outcome.state.status is GraphStatus.WAITING_APPROVAL
    assert set(harness.probe.read_branches) == {
        "device_standard",
        "inventory",
        "permission_template",
    }
    assert harness.graph.ledger.round_count == 2


async def test_budget_rounds_exhaustion_terminates_failed() -> None:
    harness = await build_harness(
        task_id="task_onbclar003",
        maximum_rounds=2,
        token_budget=4096,
    )
    task_id = harness.create.task_id
    create_ref = str(harness.create.payload["initial_message_ref"])
    harness.resolver.set_fields(
        create_ref,
        {"full_name": "Chen Yi", "department": "engineering"},
    )
    outcome = await execute(harness, harness.create, run_id="run_clar_03a")
    assert outcome.state.status is GraphStatus.WAITING_USER

    ref1 = f"message://tenant-a/onboarding/{task_id}/step1"
    harness.resolver.set_fields(ref1, {"manager": MANAGER})
    outcome = await execute(
        harness,
        build_submit_command(task_id, ref1),
        run_id="run_clar_03b",
    )
    assert outcome.state.status is GraphStatus.WAITING_USER

    # Third round exceeds maximum_conversation_rounds=2: hard stop, no
    # endless loop, deterministic FAILED with the budget failure code.
    ref2 = f"message://tenant-a/onboarding/{task_id}/step2"
    harness.resolver.set_fields(ref2, {"location": "Shanghai"})
    outcome = await execute(
        harness,
        build_submit_command(task_id, ref2),
        run_id="run_clar_03c",
    )
    assert outcome.state.status is GraphStatus.FAILED
    assert outcome.state.failure_code == "CLARIFICATION_BUDGET_EXHAUSTED"


async def test_token_budget_exhaustion_terminates_failed() -> None:
    # A cumulative budget below the smallest envelope estimate makes the
    # very first clarification round fail closed (FP-CTX-004).
    harness = await build_harness(
        task_id="task_onbclar004",
        maximum_rounds=10,
        token_budget=1,
    )
    create_ref = str(harness.create.payload["initial_message_ref"])
    harness.resolver.set_fields(
        create_ref,
        {"full_name": "Chen Yi", "department": "engineering"},
    )
    outcome = await execute(harness, harness.create, run_id="run_clar_04")
    assert outcome.state.status is GraphStatus.FAILED
    assert outcome.state.failure_code == "CLARIFICATION_TOKEN_BUDGET_EXHAUSTED"


async def test_required_fields_contract_matches_domain_pack() -> None:
    """The graph's field set is exactly the onboarding domain pack's."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    text = (
        root / "domain-packs" / "onboarding" / "required-fields.yaml"
    ).read_text(encoding="utf-8")
    pack_fields = tuple(
        line.strip().lstrip("- ")
        for line in text.splitlines()
        if line.startswith("    - ")
    )
    assert pack_fields == ONBOARDING_REQUIRED_FIELDS == (
        "full_name",
        "department",
        "manager",
        "location",
        "start_date",
    )
