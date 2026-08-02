"""Onboarding composite graph durable-runtime wiring (M5-2, AC-E2E-002).

The M5-1 ``OnboardingCompositeGraph`` lives in ``packages/graph``; this
module is the Worker-side assembly point that exposes it as a
``DurableGraphFactory`` (same pattern the VPN vertical slice follows in
``vpn_write.py``).  The factory captures the trusted application ports and
injects the durable Checkpoint adapter plus the explicit control-plane
checkpointer on every (re)start, so a Worker crash restart resumes the
task from its durable GraphState Checkpoint — completed read branches,
the sub-action plan and per-sub-action progress survive, while the run_id
/ run_generation are re-leased by the new Worker generation.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from flowpilot_context import ContextBuilder
from flowpilot_graph import (
    CheckpointPort,
    GraphExecutionPort,
    OnboardingApprovalSourcePort,
    OnboardingArtifactPort,
    OnboardingCompositeGraph,
    OnboardingGatewayPort,
    OnboardingGraphConfig,
    OnboardingLedgerPort,
    OnboardingResolverPort,
)

from .durable import DurableGraphFactory


class OnboardingDurableGraphFactory:
    """Bound ``DurableGraphFactory`` for the onboarding composite graph.

    Every invocation constructs a fresh graph instance (a new "worker
    process") over the durable ports; the control checkpointer is passed
    explicitly so process-memory state is never silently assumed.
    """

    def __init__(
        self,
        *,
        resolver: OnboardingResolverPort,
        gateway: OnboardingGatewayPort,
        ledger: OnboardingLedgerPort,
        artifacts: OnboardingArtifactPort,
        approvals: OnboardingApprovalSourcePort | None = None,
        config: OnboardingGraphConfig | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._resolver = resolver
        self._gateway = gateway
        self._ledger = ledger
        self._artifacts = artifacts
        self._approvals = approvals
        self._config = config
        self._clock = clock or (lambda: datetime.now(UTC))

    def __call__(
        self,
        *,
        checkpoints: CheckpointPort,
        control_checkpointer: object,
    ) -> GraphExecutionPort:
        return OnboardingCompositeGraph(
            resolver=self._resolver,
            gateway=self._gateway,
            checkpoints=checkpoints,
            ledger=self._ledger,
            artifacts=self._artifacts,
            context_builder=ContextBuilder(clock=self._clock),
            config=self._config,
            approvals=self._approvals,
            clock=self._clock,
            checkpointer=control_checkpointer,
        )

    @staticmethod
    def as_durable_factory(
        factory: OnboardingDurableGraphFactory,
    ) -> DurableGraphFactory:
        """Narrow to the durable-runtime protocol (explicit typing aid)."""
        return factory


__all__ = ["OnboardingDurableGraphFactory"]
