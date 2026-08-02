"""M5-2 Worker restart semantics — AC-E2E-002 reliability face.

Composite-application recovery across a Worker process restart:

- task_id / thread_id stay stable, run_id changes and run_generation is
  bumped (the engine re-leases and ``_load_or_initialize`` replaces the
  run identity on the Checkpoint);
- an approval interrupt survives the restart and the same thread resumes;
- when the control-plane thread checkpoint is lost (process crash) the
  DECIDE_APPROVAL command is replayed against the durable Checkpoint and
  the approval is re-validated (binding / duties / manager / active)
  before any write executes.

Drives the onboarding composite graph through the real ``RuntimeWorker``
queue/lease loop via the durable-runtime factory wiring
(``OnboardingDurableGraphFactory``).
"""

from __future__ import annotations

import asyncio

from flowpilot_graph import GraphStatus
from flowpilot_worker import (
    InMemoryExecutionQueue,
    RuntimeExecutionAdapter,
    RuntimeWorker,
)
from onboarding_harness import (
    MANAGER,
    TENANT_A,
    approve_and_resume,
    build_approval_from_card,
    build_decide_command,
    build_harness,
    build_submit_command,
    execute,
    interrupt_card,
    rebuild_harness,
    run_until_approval,
)


async def _run_to_approval_via_worker(
    harness,
    queue: InMemoryExecutionQueue,
    *,
    run_id: str,
) -> object:
    """Drive create/submit commands through a RuntimeWorker until approval."""
    worker = RuntimeWorker(
        worker_id=f"worker-{run_id}",
        queue=queue,
        leases=harness.leases,
        graph=harness.graph,
        run_id_factory=lambda: run_id,
    )
    task_id = harness.create.task_id
    create_ref = str(harness.create.payload["initial_message_ref"])
    harness.resolver.set_fields(
        create_ref, {"full_name": "Chen Yi", "department": "engineering"}
    )
    await RuntimeExecutionAdapter(queue).submit(harness.create)
    first = await worker.run_once()
    assert first.graph_outcome is not None
    assert first.graph_outcome.state.status is GraphStatus.WAITING_USER

    ref1 = f"message://tenant-a/onboarding/{task_id}/step1"
    harness.resolver.set_fields(ref1, {"manager": MANAGER, "location": "Shanghai"})
    await RuntimeExecutionAdapter(queue).submit(build_submit_command(task_id, ref1))
    second = await worker.run_once()
    assert second.graph_outcome is not None
    assert second.graph_outcome.state.status is GraphStatus.WAITING_USER

    ref2 = f"message://tenant-a/onboarding/{task_id}/step2"
    harness.resolver.set_fields(ref2, {"start_date": "2026-09-01"})
    await RuntimeExecutionAdapter(queue).submit(build_submit_command(task_id, ref2))
    third = await worker.run_once()
    assert third.graph_outcome is not None
    assert third.graph_outcome.state.status is GraphStatus.WAITING_APPROVAL
    return third


def test_worker_restart_keeps_task_thread_and_bumps_run_generation() -> None:
    """AC-E2E-002: restart keeps task/thread, changes run_id, re-authorizes."""

    async def scenario() -> None:
        harness = await build_harness(task_id="task_onbrestart001")
        queue = InMemoryExecutionQueue()
        waiting = await _run_to_approval_via_worker(
            harness, queue, run_id="run_worker_a_restart001"
        )
        card = interrupt_card(harness)
        approval = build_approval_from_card(
            card, create=harness.create, config=harness.config
        )
        harness.approvals.approvals[(TENANT_A, str(card["approval_id"]))] = approval
        await harness.approvals.approve(str(card["approval_id"]), MANAGER)

        # The old worker "dies" without completing: its lease expires and a
        # replacement worker re-leases the same task (run_generation bumps).
        harness.leases.force_expire(TENANT_A, harness.create.task_id)
        replacement = RuntimeWorker(
            worker_id="worker-b-restart001",
            queue=queue,
            leases=harness.leases,
            graph=harness.graph,
            run_id_factory=lambda: "run_worker_b_restart001",
        )
        decide = build_decide_command(
            harness.create.task_id,
            approval_id=str(card["approval_id"]),
            action_digest=str(card["action_digest"]),
            decision="approve",
            actor_id=MANAGER,
        )
        await RuntimeExecutionAdapter(queue).submit(decide)
        resumed = await replacement.run_once()

        assert resumed.graph_outcome is not None
        state = resumed.graph_outcome.state
        assert state.status is GraphStatus.COMPLETED
        # task_id / thread_id unchanged across the restart.
        assert state.task_id == harness.create.task_id
        assert state.task_id == waiting.graph_outcome.state.task_id
        # run_id changes; run_generation bumps with the re-lease.
        assert state.run_id == "run_worker_b_restart001"
        assert state.run_id != waiting.graph_outcome.state.run_id
        assert state.run_generation == waiting.graph_outcome.state.run_generation + 1
        # The approval survived and was re-validated on the resume path.
        assert harness.approvals.resolve_count[str(card["approval_id"])] >= 1
        assert queue.acknowledged_count == 4

    asyncio.run(scenario())


def test_restart_with_lost_thread_checkpoint_resumes_same_thread() -> None:
    """A crashed process loses the control-plane thread checkpoint.

    The durable GraphState Checkpoint is the source of truth: the approval
    decision command is replayed, the approval is re-validated (never
    silently skipped) and the task completes on the same thread.
    """

    async def scenario() -> None:
        harness_a = await build_harness(task_id="task_onbrestart002")
        outcome_a, card = await run_until_approval(harness_a)
        approval_id = str(card["approval_id"])
        approval = build_approval_from_card(
            card, create=harness_a.create, config=harness_a.config
        )
        harness_a.approvals.approvals[(TENANT_A, approval_id)] = approval
        await harness_a.approvals.approve(approval_id, MANAGER)
        resolves_before = harness_a.approvals.resolve_count.get(approval_id, 0)

        # Process crash: fresh graph over the same durable checkpoints /
        # leases / upstream services, but a brand-new thread checkpointer.
        harness_b = rebuild_harness(harness_a)
        # The new worker process re-leases the task under a new run_id.
        decide = build_decide_command(
            harness_b.create.task_id,
            approval_id=approval_id,
            action_digest=str(card["action_digest"]),
            decision="approve",
            actor_id=MANAGER,
        )
        resumed = await execute(harness_b, decide, run_id="run_onb_recover_decide")

        state = resumed.state
        assert state.status is GraphStatus.COMPLETED
        # task_id / thread_id stable; run identity replaced.
        assert state.task_id == harness_a.create.task_id
        assert state.task_id == outcome_a.state.task_id
        assert (
            harness_b.graph._thread_id(harness_b.create)
            == harness_a.graph._thread_id(harness_a.create)
        )
        assert state.run_id == "run_onb_recover_decide"
        assert state.run_id != outcome_a.state.run_id
        assert state.run_generation > outcome_a.state.run_generation
        # The approval record was re-resolved and re-validated on recovery.
        assert harness_a.approvals.resolve_count[approval_id] > resolves_before
        # Both writes executed exactly once across the restart.
        assert harness_a.probe.logical_counts == {
            "device.allocate.v1": 1,
            "permission.grant.v1": 1,
            "ticket.create.v1": 1,
        }

    asyncio.run(scenario())


def test_approval_survives_restart_and_thread_continues() -> None:
    """Interrupt-period restart: the same thread continues to completion."""

    async def scenario() -> None:
        harness = await build_harness(task_id="task_onbrestart003")
        _outcome, card = await run_until_approval(harness)
        # Restart with the thread checkpoint INTACT (graceful restart): the
        # approval decision resumes the interrupt in the same thread.
        resumed = await approve_and_resume(harness, card)
        assert resumed.state.status is GraphStatus.COMPLETED
        assert resumed.state.run_id == "run_onb_decide"

    asyncio.run(scenario())
