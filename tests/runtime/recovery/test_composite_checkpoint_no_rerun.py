"""M5-2 Checkpoint resume without re-running completed work.

AC-E2E-002 reliability face:

- a crash restart skips the three already-completed parallel read branches
  (their completion marks + reduced facts ride the Checkpoint);
- a crash BETWEEN sub-actions (the device write committed upstream, its
  outcome was lost) replays the write under the SAME idempotency key and
  creates zero duplicates;
- a crash AFTER a sub-action was verified and its progress Checkpointed
  never re-executes that sub-action, and the related ticket is never
  duplicated (no double ticket refs either).
"""

from __future__ import annotations

import asyncio

import pytest
from flowpilot_graph import (
    DEVICE_ALLOCATE_TOOL,
    PERMISSION_GRANT_TOOL,
    TICKET_CREATE_TOOL,
    GraphStatus,
)
from onboarding_harness import (
    MANAGER,
    TENANT_A,
    OnboardingCrash,
    build_approval_from_card,
    build_decide_command,
    build_harness,
    execute,
    rebuild_harness,
    run_until_approval,
)


def test_restart_skips_completed_read_branches() -> None:
    """The three parallel reads ran once; the restart never re-runs them."""

    async def scenario() -> None:
        harness_a = await build_harness(task_id="task_onbnorerun001")
        _outcome, card = await run_until_approval(harness_a)
        reads_before = sorted(harness_a.probe.read_branches)
        assert reads_before == [
            "device_standard",
            "inventory",
            "permission_template",
        ]

        approval_id = str(card["approval_id"])
        approval = build_approval_from_card(
            card, create=harness_a.create, config=harness_a.config
        )
        harness_a.approvals.approvals[(TENANT_A, approval_id)] = approval
        await harness_a.approvals.approve(approval_id, MANAGER)

        # Crash + restart: brand-new control-plane thread checkpoint, same
        # durable Checkpoint.  The graph resumes from the approval node.
        harness_b = rebuild_harness(harness_a)
        decide = build_decide_command(
            harness_b.create.task_id,
            approval_id=approval_id,
            action_digest=str(card["action_digest"]),
            decision="approve",
            actor_id=MANAGER,
        )
        resumed = await execute(harness_b, decide, run_id="run_onb_norerun_decide")

        assert resumed.state.status is GraphStatus.COMPLETED
        # Zero additional read-branch executions after the restart.
        assert sorted(harness_a.probe.read_branches) == reads_before
        # The writes executed exactly once each.
        assert harness_a.probe.logical_counts == {
            DEVICE_ALLOCATE_TOOL: 1,
            PERMISSION_GRANT_TOOL: 1,
            TICKET_CREATE_TOOL: 1,
        }

    asyncio.run(scenario())


def test_crash_between_sub_actions_replays_idempotency_key_with_zero_duplicates() -> (
    None
):
    """The device write committed upstream, then the Worker died.

    Recovery replays the device write under the same idempotency key: zero
    duplicate resources, and the permission grant completes after the
    re-authorization.
    """

    async def scenario() -> None:
        from onboarding_harness import OnboardingProbeOptions

        harness_a = await build_harness(
            task_id="task_onbnorerun002",
            probe_options=OnboardingProbeOptions(
                crash_after_tool=DEVICE_ALLOCATE_TOOL
            ),
        )
        _outcome, card = await run_until_approval(harness_a)
        approval_id = str(card["approval_id"])
        approval = build_approval_from_card(
            card, create=harness_a.create, config=harness_a.config
        )
        harness_a.approvals.approvals[(TENANT_A, approval_id)] = approval
        await harness_a.approvals.approve(approval_id, MANAGER)

        decide = build_decide_command(
            harness_a.create.task_id,
            approval_id=approval_id,
            action_digest=str(card["action_digest"]),
            decision="approve",
            actor_id=MANAGER,
        )
        # The process dies right after the device allocation committed.
        with pytest.raises(OnboardingCrash):
            await execute(harness_a, decide, run_id="run_onb_crash_device")

        # The device write DID happen upstream (idempotent record exists).
        assert harness_a.probe.logical_counts.get(DEVICE_ALLOCATE_TOOL) == 1
        assert len(harness_a.probe._assignments) == 1

        # Restart: the approval is re-validated, the device write replays
        # under the same idempotency key (0 duplicates) and the permission
        # grant + ticket complete the composite.
        harness_b = rebuild_harness(harness_a)
        resumed = await execute(harness_b, decide, run_id="run_onb_recover_crash")

        assert resumed.state.status is GraphStatus.COMPLETED
        # Zero duplicate resource creation across the crash.
        assert harness_a.probe.logical_counts == {
            DEVICE_ALLOCATE_TOOL: 1,
            PERMISSION_GRANT_TOOL: 1,
            TICKET_CREATE_TOOL: 1,
        }
        assert len(harness_a.probe._assignments) == 1
        assert len(harness_a.probe._grants) == 1
        assert len(harness_a.probe._tickets) == 1
        # The crash-replay re-attempted the device write under the SAME
        # idempotency key (execute count 2) but the upstream deduplicated
        # it (logical write count stays 1, one assignment exists).
        assert harness_a.probe.execute_counts[DEVICE_ALLOCATE_TOOL] == 2
        device_calls = [
            call
            for call in harness_a.probe.write_calls
            if call.action.tool.name == DEVICE_ALLOCATE_TOOL
        ]
        assert len(device_calls) == 1
        assert len({call.idempotency_key for call in device_calls}) == 1

    asyncio.run(scenario())


def test_crash_after_verified_sub_action_skips_it_and_never_duplicates_ticket() -> None:
    """The device sub-action was verified AND its progress Checkpointed.

    The crash happens on the permission write; recovery must NOT re-run the
    verified device allocation (its progress rides the Checkpoint) and must
    not duplicate the related ticket or its refs.
    """

    async def scenario() -> None:
        from onboarding_harness import OnboardingProbeOptions

        harness_a = await build_harness(
            task_id="task_onbnorerun003",
            probe_options=OnboardingProbeOptions(
                crash_after_tool=PERMISSION_GRANT_TOOL
            ),
        )
        _outcome, card = await run_until_approval(harness_a)
        approval_id = str(card["approval_id"])
        approval = build_approval_from_card(
            card, create=harness_a.create, config=harness_a.config
        )
        harness_a.approvals.approvals[(TENANT_A, approval_id)] = approval
        await harness_a.approvals.approve(approval_id, MANAGER)

        decide = build_decide_command(
            harness_a.create.task_id,
            approval_id=approval_id,
            action_digest=str(card["action_digest"]),
            decision="approve",
            actor_id=MANAGER,
        )
        # Device verified + Checkpointed, then the process died on the
        # permission write.
        with pytest.raises(OnboardingCrash):
            await execute(
                harness_a, decide, run_id="run_onb_crash_permission"
            )

        checkpoint = await harness_a.checkpoints.load(
            TENANT_A, harness_a.create.task_id
        )
        assert checkpoint is not None
        assert {item["action_id"] for item in checkpoint.sub_action_progress} == {
            # Only the device progress was persisted before the crash.
            checkpoint.sub_action_progress[0]["action_id"]
        }
        assert checkpoint.sub_action_progress[0]["tool"] == DEVICE_ALLOCATE_TOOL

        harness_b = rebuild_harness(harness_a)
        resumed = await execute(harness_b, decide, run_id="run_onb_recover_perm")

        assert resumed.state.status is GraphStatus.COMPLETED
        assert harness_a.probe.logical_counts == {
            DEVICE_ALLOCATE_TOOL: 1,
            PERMISSION_GRANT_TOOL: 1,
            TICKET_CREATE_TOOL: 1,
        }
        # The verified device allocation was NEVER re-executed: not even a
        # re-attempt (execute count 1) — its progress Checkpoint skipped it.
        assert harness_a.probe.execute_counts[DEVICE_ALLOCATE_TOOL] == 1
        device_calls = [
            call
            for call in harness_a.probe.write_calls
            if call.action.tool.name == DEVICE_ALLOCATE_TOOL
        ]
        assert len(device_calls) == 1
        # The permission write re-attempted under the same key (execute
        # count 2) and the upstream deduplicated it (one grant); the ticket
        # is created exactly once.
        assert harness_a.probe.execute_counts[PERMISSION_GRANT_TOOL] == 2
        permission_calls = [
            call
            for call in harness_a.probe.write_calls
            if call.action.tool.name == PERMISSION_GRANT_TOOL
        ]
        assert len(permission_calls) == 1
        assert len({call.idempotency_key for call in permission_calls}) == 1
        ticket_calls = [
            call
            for call in harness_a.probe.write_calls
            if call.action.tool.name == TICKET_CREATE_TOOL
        ]
        assert len(ticket_calls) == 1
        # The summary lists the ticket exactly once.
        artifact = harness_a.artifacts.by_ref[resumed.state.result_ref]
        assert artifact.content.count("ticket://tenant-a/") == 1

    asyncio.run(scenario())
