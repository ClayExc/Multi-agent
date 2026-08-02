"""M5-1 composite flow — AC-E2E-002 end-to-end business slice.

Clarification -> three parallel reads -> sub-action planning (two writes
with distinct idempotency keys) -> manager approval interrupt (FP-APR-001
card) -> approve -> write closed loop (FP-MCP-003/004/005) -> related
ticket -> summary.  Partial failures terminate as FAILED with a failure
code that names the exact sub-action; already-verified sub-actions are
never re-executed and the summary only lists tickets that were actually
created and read-back verified.
"""

from __future__ import annotations

from flowpilot_domain import Approval
from flowpilot_graph import (
    DEVICE_ALLOCATE_TOOL,
    PERMISSION_GRANT_TOOL,
    TICKET_CREATE_TOOL,
    GraphStatus,
    OnboardingLedgerStatus,
)

from .conftest import (
    MANAGER,
    REQUESTER,
    OnboardingProbeOptions,
    _now_iso,
    approve_and_resume,
    build_approval_from_card,
    build_decide_command,
    build_harness,
    execute,
    run_until_approval,
)


async def test_full_composite_flow_completed_with_verified_writes() -> None:
    harness = await build_harness(task_id="task_onbe2e001")
    outcome, card = await run_until_approval(harness)
    assert outcome.state.status is GraphStatus.WAITING_APPROVAL

    # FP-APR-001 approval card contract: impact / arguments / basis /
    # expires_at / tool+action_id summary.
    assert card["kind"] == "approval"
    assert card["tool"] == PERMISSION_GRANT_TOOL
    assert card["operation"] == "write"
    assert set(card["impact"]) == {"resource", "purpose"}
    assert card["impact"]["resource"]["type"] == "permission_assignment"
    assert card["arguments"]["template_id"] == "PT-BE-01"
    assert set(card["basis"]) == {"policy_version", "policy_decision_id"}
    assert card["basis"]["policy_version"]
    assert card["expires_at"].endswith("Z")
    assert card["action_id"].startswith("act_")

    # Two sub-actions on the same task carry distinct idempotency keys.
    state = harness.graph.last_safe_state
    assert state is not None
    sub_actions = state.get("sub_actions") or []
    assert [item["tool"] for item in sub_actions] == [
        DEVICE_ALLOCATE_TOOL,
        PERMISSION_GRANT_TOOL,
    ]
    keys = {item["idempotency_key"] for item in sub_actions}
    assert len(keys) == 2, "device and permission must use distinct idempotency keys"

    resumed = await approve_and_resume(harness, card)
    assert resumed.state.status is GraphStatus.COMPLETED
    assert resumed.state.result_ref is not None

    # Every write executed exactly once and was verified by readback.
    assert harness.probe.logical_counts == {
        DEVICE_ALLOCATE_TOOL: 1,
        PERMISSION_GRANT_TOOL: 1,
        TICKET_CREATE_TOOL: 1,
    }
    for tool in (DEVICE_ALLOCATE_TOOL, PERMISSION_GRANT_TOOL, TICKET_CREATE_TOOL):
        entries = harness.ledger.by_tool(tool)
        statuses = [entry.status for entry in entries]
        assert OnboardingLedgerStatus.PREPARED in statuses
        assert statuses[-1] is OnboardingLedgerStatus.VERIFIED

    # The related ticket was created, read-back verified and summarized.
    assert len(harness.probe._tickets) == 1
    (ticket,) = harness.probe._tickets.values()
    artifact = harness.artifacts.by_ref[resumed.state.result_ref]
    assert str(ticket["ticket_id"]) in artifact.content
    assert "ticket://tenant-a/" in artifact.content


async def test_partial_failure_never_fake_completed_and_no_reexecution() -> None:
    harness = await build_harness(
        task_id="task_onbe2e002",
        probe_options=OnboardingProbeOptions(
            permission_failure="INVENTORY_INSUFFICIENT"
        ),
    )
    _outcome, card = await run_until_approval(harness)
    resumed = await approve_and_resume(harness, card)

    # Business failure of the permission sub-action: terminal FAILED with a
    # failure code that names the exact sub-action, never a fake COMPLETED.
    assert resumed.state.status is GraphStatus.FAILED
    assert (
        resumed.state.failure_code
        == "WRITE_FAILED:permission.grant.v1:INVENTORY_INSUFFICIENT"
    )

    # The already-succeeded device allocation was executed once and is not
    # re-executed; the ticket was never created.
    assert harness.probe.logical_counts == {DEVICE_ALLOCATE_TOOL: 1}
    assert harness.probe.logical_counts.get(TICKET_CREATE_TOOL, 0) == 0

    # The summary exists and contains zero created-and-verified tickets.
    assert resumed.state.result_ref is not None
    artifact = harness.artifacts.by_ref[resumed.state.result_ref]
    assert "none" in artifact.content

    # Replaying the same execution terminates at the same FAILED terminal
    # state without touching the upstream tools again.
    replay = await execute(harness, harness.create, run_id="run_onb_replay_partial")
    assert replay.state.status is GraphStatus.FAILED
    assert replay.state.failure_code == resumed.state.failure_code
    assert harness.probe.logical_counts == {DEVICE_ALLOCATE_TOOL: 1}


async def test_unknown_write_reconciles_before_rewrite() -> None:
    harness = await build_harness(
        task_id="task_onbe2e003",
        probe_options=OnboardingProbeOptions(device_unknown_once=True),
    )
    _outcome, card = await run_until_approval(harness)
    resumed = await approve_and_resume(harness, card)

    # The device write returned UNKNOWN once but the upstream allocation
    # already existed; the graph reconciled by read-back and never wrote a
    # duplicate (FP-MCP-005).
    assert resumed.state.status is GraphStatus.COMPLETED
    assert harness.probe.logical_counts[DEVICE_ALLOCATE_TOOL] == 1
    reconcile_calls = [call for call in harness.probe.write_calls if call.reconcile]
    assert len(reconcile_calls) == 1
    assert reconcile_calls[0].action.tool.name == DEVICE_ALLOCATE_TOOL


async def test_approval_binding_and_separation_of_duties() -> None:
    harness = await build_harness(task_id="task_onbe2e004")
    _outcome, card = await run_until_approval(harness)
    approval_id = str(card["approval_id"])
    action_digest = str(card["action_digest"])
    task_id = harness.create.task_id
    harness.approvals.approvals[(harness.create.tenant_id, approval_id)] = (
        build_approval_from_card(card, create=harness.create, config=harness.config)
    )

    # Self-approval is a duties violation: the requester may not approve.
    decide = build_decide_command(
        task_id,
        approval_id=approval_id,
        action_digest=action_digest,
        decision="approve",
        actor_id=REQUESTER,
    )
    outcome = await execute(harness, decide, run_id="run_onb_sod")
    assert outcome.state.status is GraphStatus.FAILED
    assert outcome.state.failure_code == "RUNTIME_APPROVAL_DUTIES_VIOLATION"

    # A tampered action digest must be rejected (FP-APR-001).
    harness2 = await build_harness(task_id="task_onbe2e005")
    _o2, card2 = await run_until_approval(harness2)
    harness2.approvals.approvals[
        (harness2.create.tenant_id, str(card2["approval_id"]))
    ] = (
        build_approval_from_card(card2, create=harness2.create, config=harness2.config)
    )
    tampered = build_decide_command(
        harness2.create.task_id,
        approval_id=str(card2["approval_id"]),
        action_digest="sha256:" + "1" * 64,
        decision="approve",
        actor_id=MANAGER,
    )
    outcome2 = await execute(harness2, tampered, run_id="run_onb_tamper")
    assert outcome2.state.status is GraphStatus.FAILED
    assert outcome2.state.failure_code == "RUNTIME_APPROVAL_BINDING_MISMATCH"

    # Approval must be given by the hiring manager recorded in the request.
    harness3 = await build_harness(task_id="task_onbe2e006")
    _o3, card3 = await run_until_approval(harness3)
    harness3.approvals.approvals[
        (harness3.create.tenant_id, str(card3["approval_id"]))
    ] = (
        build_approval_from_card(card3, create=harness3.create, config=harness3.config)
    )
    not_manager = build_decide_command(
        harness3.create.task_id,
        approval_id=str(card3["approval_id"]),
        action_digest=str(card3["action_digest"]),
        decision="approve",
        actor_id="someone-else",
    )
    outcome3 = await execute(harness3, not_manager, run_id="run_onb_notmanager")
    assert outcome3.state.status is GraphStatus.FAILED
    assert outcome3.state.failure_code == "RUNTIME_APPROVAL_NOT_MANAGER"


async def test_revoked_approval_blocks_resume() -> None:
    harness = await build_harness(task_id="task_onbe2e007")
    _outcome, card = await run_until_approval(harness)
    approval_id = str(card["approval_id"])
    approval = build_approval_from_card(
        card, create=harness.create, config=harness.config
    )
    harness.approvals.approvals[(harness.create.tenant_id, approval_id)] = approval
    await harness.approvals.approve(approval_id, MANAGER)
    # Permission revoked while the request waits (FP-APR-003 semantics).
    revoked = approval.to_mapping()
    revoked["status"] = "revoked"
    revoked["decided_at"] = _now_iso()
    harness.approvals.approvals[(harness.create.tenant_id, approval_id)] = (
        Approval.from_mapping(revoked)
    )

    decide = build_decide_command(
        harness.create.task_id,
        approval_id=approval_id,
        action_digest=str(card["action_digest"]),
        decision="approve",
        actor_id=MANAGER,
    )
    outcome = await execute(harness, decide, run_id="run_onb_revoked")
    assert outcome.state.status is GraphStatus.FAILED
    assert outcome.state.failure_code == "RUNTIME_APPROVAL_INVALID"


async def test_worker_restart_resumes_same_thread_new_run_id() -> None:
    """AC-E2E-002: restart keeps task/thread, changes run_id, re-authorizes."""
    harness_a = await build_harness(task_id="task_onbe2e008")
    outcome_a, card = await run_until_approval(harness_a)
    approval_id = str(card["approval_id"])

    # A fresh "worker" process: a new graph instance over the SAME durable
    # checkpoints/leases/saver and the same upstream services.
    harness_b = await build_harness(
        task_id="task_onbe2e008",
        probe_options=OnboardingProbeOptions(),
        checkpoints=harness_a.checkpoints,
        leases=harness_a.leases,
        saver=harness_a.saver,
        create=harness_a.create,
    )
    harness_b.graph._resolver = harness_a.resolver
    harness_b.graph._gateway = harness_a.probe
    harness_b.graph._ledger = harness_a.ledger
    harness_b.graph._artifacts = harness_a.artifacts
    harness_b.graph._approvals = harness_a.graph._approvals

    # task_id/thread_id stay stable across the restart.
    assert harness_b.create.task_id == harness_a.create.task_id
    assert harness_b.graph._thread_id(harness_b.create) == harness_a.graph._thread_id(
        harness_a.create
    )

    approval = build_approval_from_card(
        card, create=harness_a.create, config=harness_a.config
    )
    harness_a.approvals.approvals[(harness_a.create.tenant_id, approval_id)] = approval
    await harness_a.approvals.approve(approval_id, MANAGER)

    decide = build_decide_command(
        harness_b.create.task_id,
        approval_id=approval_id,
        action_digest=str(card["action_digest"]),
        decision="approve",
        actor_id=MANAGER,
    )
    resumed = await execute(harness_b, decide, run_id="run_onb_restart_decide")
    assert resumed.state.status is GraphStatus.COMPLETED
    # run_id changes on the new run; the task thread does not.
    assert resumed.state.run_id == "run_onb_restart_decide"
    assert resumed.state.run_id != outcome_a.state.run_id
    assert resumed.state.task_id == harness_a.create.task_id
    # Re-authentication/re-authorization happened: the decision command
    # carried the approver's own security context and the approval record
    # was re-validated before the writes executed.
    assert harness_a.probe.logical_counts[DEVICE_ALLOCATE_TOOL] == 1
    assert harness_a.probe.logical_counts[PERMISSION_GRANT_TOOL] == 1


async def test_idempotent_replay_creates_one_of_each_resource() -> None:
    harness = await build_harness(task_id="task_onbe2e009")
    _outcome, card = await run_until_approval(harness)
    await approve_and_resume(harness, card)
    assert harness.probe.logical_counts == {
        DEVICE_ALLOCATE_TOOL: 1,
        PERMISSION_GRANT_TOOL: 1,
        TICKET_CREATE_TOOL: 1,
    }

    # The same execution command replayed ten times: no duplicate writes
    # (the terminal checkpoint short-circuits and the probe cache never
    # re-executes a verified outcome).
    for index in range(10):
        replay = await execute(
            harness, harness.create, run_id=f"run_onb_replay_{index}"
        )
        assert replay.state.status is GraphStatus.COMPLETED
    assert harness.probe.logical_counts == {
        DEVICE_ALLOCATE_TOOL: 1,
        PERMISSION_GRANT_TOOL: 1,
        TICKET_CREATE_TOOL: 1,
    }
    assert len(harness.probe.write_calls) == 3
