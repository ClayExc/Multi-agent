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


def test_checkpoint_round_trip_preserves_only_selected_citation_bindings() -> None:
    binding = {
        "source_ref": "knowledge://tenant-a/handbook/3#leave",
        "document_version": "3",
        "section": "leave",
        "redacted_summary": "Safe selected excerpt.",
        "content_hash": "sha256:" + "c" * 64,
        "classification": "internal",
    }
    state = _state().transition(GraphStatus.RUNNING, node=GraphNode.RUN_AGENT)
    state = state.transition(
        GraphStatus.COMPLETED,
        node=GraphNode.FINALIZE,
        result_ref="runtime-result://result",
        knowledge_result_digest="sha256:" + "d" * 64,
        citation_count=1,
        reference_refs=(binding["source_ref"],),
        citation_bindings=(binding,),
    )

    restored = GraphState.from_checkpoint(state.to_checkpoint())

    assert restored == state
    assert restored.citation_bindings == (binding,)
    assert "raw_document" not in repr(restored.to_checkpoint())


def test_checkpoint_rejects_citation_binding_with_extra_content() -> None:
    checkpoint = _state().to_checkpoint()
    checkpoint["citation_count"] = 1
    checkpoint["reference_refs"] = ["knowledge://tenant-a/handbook/3#leave"]
    checkpoint["citation_bindings"] = [
        {
            "source_ref": "knowledge://tenant-a/handbook/3#leave",
            "document_version": "3",
            "section": "leave",
            "redacted_summary": "Safe selected excerpt.",
            "content_hash": "sha256:" + "c" * 64,
            "classification": "internal",
            "raw_document": "forbidden",
        }
    ]

    with pytest.raises(GraphError) as captured:
        GraphState.from_checkpoint(checkpoint)

    assert captured.value.code is GraphErrorCode.STATE_INVALID


def test_checkpoint_rejects_credentials_and_provider_sessions() -> None:
    for forbidden in (
        "credential",
        "bearer_token",
        "provider_session",
        "original_message",
        "raw_document",
        "request_body",
        "tool_payload",
        "acl_subjects",
        "answer_body",
    ):
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
