"""M5-2 recovery negative cases — AC-E2E-002 reliability face.

A composite-application recovery must REFUSE stale authority instead of
executing an old approval:

- permission revoked while the request waits  -> RUNTIME_APPROVAL_INVALID
- approval expired at recovery time           -> RUNTIME_APPROVAL_INVALID
- tampered approval command on the replay     -> RUNTIME_APPROVAL_BINDING_MISMATCH
- graph version changed under the Checkpoint  -> VERSION_MIGRATION_REQUIRED

Every case replays the decision against a fresh "worker process" whose
control-plane thread checkpoint was lost (crash restart), so the recovery
path (resume_decision injection + full re-validation) is the code under
test — never a silent skip of the interrupt.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from flowpilot_domain import Approval
from flowpilot_graph import GraphStatus, OnboardingCompositeGraph, OnboardingGraphConfig

from .conftest import (
    MANAGER,
    TENANT_A,
    build_approval_from_card,
    build_decide_command,
    build_harness,
    execute,
    run_until_approval,
)

ONBOARDING_GRAPH_V2 = "onboarding-composite-v2"


def _crash_restart_harness(previous):
    """A fresh "worker process": same durable state, NEW thread checkpointer.

    Mirrors the M5-1 restart pattern: the control-plane thread checkpoint
    is lost (process crash), so the recovery path replays the graph from
    its durable GraphState Checkpoint.
    """
    harness_b = _build_restarted(previous, graph_version=None)
    return harness_b


def _build_restarted(previous, *, graph_version: str | None):
    from flowpilot_context import ContextBuilder
    from langgraph.checkpoint.memory import InMemorySaver

    config = (
        OnboardingGraphConfig()
        if graph_version is None
        else OnboardingGraphConfig(graph_version=graph_version)
    )
    graph = OnboardingCompositeGraph(
        resolver=previous.resolver,
        gateway=previous.probe,
        checkpoints=previous.checkpoints,
        ledger=previous.ledger,
        artifacts=previous.artifacts,
        context_builder=ContextBuilder(),
        config=config,
        approvals=previous.graph._approvals,
        checkpointer=InMemorySaver(),
    )
    return _HarnessLike(previous, graph)


class _HarnessLike:
    """Duck-typed harness view over shared durable state for recovery tests."""

    def __init__(self, previous, graph) -> None:
        self.graph = graph
        self.create = previous.create
        self.checkpoints = previous.checkpoints
        self.leases = previous.leases
        self.probe = previous.probe
        self.ledger = previous.ledger
        self.artifacts = previous.artifacts
        self.approvals = previous.approvals
        self.resolver = previous.resolver
        self.config = graph._config


async def _prepare_approval(harness, card) -> None:
    approval = build_approval_from_card(
        card, create=harness.create, config=harness.config
    )
    harness.approvals.approvals[(TENANT_A, str(card["approval_id"]))] = approval
    await harness.approvals.approve(str(card["approval_id"]), MANAGER)


def _decide(harness, card, *, decision: str = "approve", actor_id: str = MANAGER):
    return build_decide_command(
        harness.create.task_id,
        approval_id=str(card["approval_id"]),
        action_digest=str(card["action_digest"]),
        decision=decision,
        actor_id=actor_id,
    )


async def test_recovery_rejects_revoked_approval() -> None:
    harness_a = await build_harness(task_id="task_onbrecneg001")
    _outcome, card = await run_until_approval(harness_a)
    approval_id = str(card["approval_id"])
    await _prepare_approval(harness_a, card)
    # Permission revoked while the composite waits.
    revoked = harness_a.approvals.approvals[(TENANT_A, approval_id)].to_mapping()
    revoked["status"] = "revoked"
    revoked["decided_at"] = harness_a.approvals.approvals[
        (TENANT_A, approval_id)
    ].decided_at.isoformat().replace("+00:00", "Z")
    harness_a.approvals.approvals[(TENANT_A, approval_id)] = Approval.from_mapping(
        revoked
    )

    harness_b = _crash_restart_harness(harness_a)
    outcome = await execute(
        harness_b, _decide(harness_b, card), run_id="run_onb_neg_revoked"
    )

    # The old approval is NOT executed: the recovery refuses.
    assert outcome.state.status is GraphStatus.FAILED
    assert outcome.state.failure_code == "RUNTIME_APPROVAL_INVALID"
    assert harness_a.probe.logical_counts.get("device.allocate.v1", 0) == 0
    assert harness_a.probe.logical_counts.get("permission.grant.v1", 0) == 0


async def test_recovery_rejects_expired_approval() -> None:
    harness_a = await build_harness(task_id="task_onbrecneg002")
    _outcome, card = await run_until_approval(harness_a)
    approval_id = str(card["approval_id"])
    await _prepare_approval(harness_a, card)
    # The approval expired while the worker was down: its validity window
    # ended long before the recovery clock (but still after request time,
    # which the Approval contract requires).
    stored = harness_a.approvals.approvals[(TENANT_A, approval_id)]
    expired = stored.to_mapping()
    expired["expires_at"] = (
        stored.requested_at + timedelta(seconds=1)
    ).isoformat().replace("+00:00", "Z")
    harness_a.approvals.approvals[(TENANT_A, approval_id)] = Approval.from_mapping(
        expired
    )

    harness_b = _crash_restart_harness(harness_a)
    outcome = await execute(
        harness_b, _decide(harness_b, card), run_id="run_onb_neg_expired"
    )

    assert outcome.state.status is GraphStatus.FAILED
    assert outcome.state.failure_code == "RUNTIME_APPROVAL_INVALID"
    assert harness_a.probe.logical_counts.get("device.allocate.v1", 0) == 0


async def test_recovery_rejects_tampered_approval_digest() -> None:
    harness_a = await build_harness(task_id="task_onbrecneg003")
    _outcome, card = await run_until_approval(harness_a)
    await _prepare_approval(harness_a, card)

    harness_b = _crash_restart_harness(harness_a)
    tampered = build_decide_command(
        harness_b.create.task_id,
        approval_id=str(card["approval_id"]),
        action_digest="sha256:" + "1" * 64,
        decision="approve",
        actor_id=MANAGER,
    )
    outcome = await execute(harness_b, tampered, run_id="run_onb_neg_tamper")

    # The tampered action digest is rejected on the recovery replay.
    assert outcome.state.status is GraphStatus.FAILED
    assert outcome.state.failure_code == "RUNTIME_APPROVAL_BINDING_MISMATCH"
    assert harness_a.probe.logical_counts.get("device.allocate.v1", 0) == 0


async def test_recovery_requires_explicit_graph_version_migration() -> None:
    from flowpilot_graph import GraphError, GraphErrorCode

    harness_a = await build_harness(task_id="task_onbrecneg004")
    _outcome, card = await run_until_approval(harness_a)

    # The graph implementation changed while the composite was waiting: the
    # Checkpoint carries the old graph_version and must NOT be replayed.
    harness_b = _build_restarted(harness_a, graph_version=ONBOARDING_GRAPH_V2)
    with pytest.raises(GraphError) as captured:
        await execute(harness_b, _decide(harness_b, card), run_id="run_onb_neg_version")

    assert captured.value.code is GraphErrorCode.VERSION_MIGRATION_REQUIRED
