from __future__ import annotations

import pytest
from flowpilot_graph import (
    BranchResult,
    GraphError,
    GraphErrorCode,
    GraphNode,
    GraphState,
    GraphStatus,
    assert_checkpoint_safe,
    reduce_parallel,
)


def _state() -> GraphState:
    return GraphState(
        task_id="task_12345678",
        tenant_id="tenant-a",
        command_id="cmd_12345678",
        command_digest="sha256:" + "a" * 64,
        run_id="run_12345678",
        run_generation=1,
        graph_version="graph-v1",
        status=GraphStatus.QUEUED,
        node=GraphNode.START,
        security_context_ref="security-context://tenant-a/12345678",
        security_context_hash="sha256:" + "b" * 64,
        purpose="it_support",
    )


def test_checkpoint_round_trip_contains_only_minimal_recovery_state() -> None:
    state = _state()

    restored = GraphState.from_checkpoint(state.to_checkpoint())

    assert restored == state
    checkpoint = restored.to_checkpoint()
    assert "session_ref" not in checkpoint
    assert "provider_session" not in checkpoint
    assert "security_context_ref" in checkpoint
    assert "security_context_hash" in checkpoint


def test_checkpoint_rejects_credentials_and_provider_sessions() -> None:
    for forbidden in ("credential", "bearer_token", "provider_session"):
        with pytest.raises(GraphError) as captured:
            assert_checkpoint_safe({forbidden: "secret"})
        assert captured.value.code is GraphErrorCode.STATE_INVALID


def test_terminal_state_is_owned_by_graph_transition_rules() -> None:
    running = _state().transition(
        GraphStatus.RUNNING,
        node=GraphNode.RUN_AGENT,
    )

    with pytest.raises(GraphError):
        running.transition(
            GraphStatus.COMPLETED,
            node=GraphNode.RUN_AGENT,
            result_ref="runtime-result://result",
        )

    completed = running.transition(
        GraphStatus.COMPLETED,
        node=GraphNode.FINALIZE,
        result_ref="runtime-result://result",
    )
    assert completed.status is GraphStatus.COMPLETED


def test_parallel_reducer_is_order_independent_and_deduplicates_evidence() -> None:
    left = BranchResult(
        branch_id="knowledge",
        facts={"vpn_version": "v2"},
        evidence_refs=("evidence://1",),
    )
    right = BranchResult(
        branch_id="data",
        facts={"asset_id": "asset-1"},
        evidence_refs=("evidence://1", "evidence://2"),
    )

    first = reduce_parallel((left, right))
    second = reduce_parallel((right, left))

    assert first == second
    assert first.branch_order == ("data", "knowledge")
    assert first.evidence_refs == ("evidence://1", "evidence://2")


def test_parallel_reducer_rejects_conflicting_facts() -> None:
    with pytest.raises(GraphError) as captured:
        reduce_parallel(
            (
                BranchResult(branch_id="a", facts={"status": "old"}),
                BranchResult(branch_id="b", facts={"status": "new"}),
            )
        )

    assert captured.value.code is GraphErrorCode.PARALLEL_REDUCER_CONFLICT
