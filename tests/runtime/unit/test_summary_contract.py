"""FP-CTX-002: 分层摘要区分声称、验证与推断（摘要 Schema 结果）。

The layered summary is a strictly partitioned schema: ``claimed`` items
are statements not yet confirmed, ``verified`` items are confirmed by an
authoritative source or tool result, ``inferred`` items are derived by the
runtime.  A text may live in exactly one bucket; merging and Checkpoint
round-trips must preserve the partition.
"""

from __future__ import annotations

import pytest
from flowpilot_context import (
    ContextError,
    ContextErrorCode,
    ContextLayer,
    LayeredSummary,
    LayerName,
    SummaryItem,
    SummaryKind,
    TrustLevel,
    build_summary_layer,
)
from flowpilot_domain import DataClassification
from flowpilot_graph import GraphNode, GraphState, GraphStatus


def _summary() -> LayeredSummary:
    return LayeredSummary(
        items=(
            SummaryItem(
                kind=SummaryKind.CLAIMED,
                text="user claims VPN is flaky",
                source_refs=("message://t/1",),
            ),
            SummaryItem(
                kind=SummaryKind.VERIFIED,
                text="policy allows VPN for production",
                source_refs=("tool://policy/v1",),
            ),
            SummaryItem(
                kind=SummaryKind.INFERRED,
                text="ticket is likely network-zone related",
                source_refs=("message://t/3",),
            ),
        )
    )


def test_summary_schema_partitions_claim_verified_inferred() -> None:
    summary = _summary()
    sections = summary.sections()

    assert set(sections) == set(SummaryKind)
    assert [item.text for item in sections[SummaryKind.CLAIMED]] == [
        "user claims VPN is flaky"
    ]
    assert [item.text for item in sections[SummaryKind.VERIFIED]] == [
        "policy allows VPN for production"
    ]
    assert [item.text for item in sections[SummaryKind.INFERRED]] == [
        "ticket is likely network-zone related"
    ]
    # Strict partition: no text appears in two buckets.
    all_texts = [item.text for item in summary.items]
    assert len(all_texts) == len(set(all_texts))


def test_summary_rejects_duplicate_kind_text_pair() -> None:
    with pytest.raises(ContextError) as captured:
        LayeredSummary(
            items=(
                SummaryItem(
                    kind=SummaryKind.CLAIMED,
                    text="duplicate",
                    source_refs=("message://t/1",),
                ),
                SummaryItem(
                    kind=SummaryKind.CLAIMED,
                    text="duplicate",
                    source_refs=("message://t/2",),
                ),
            )
        )
    assert captured.value.code is ContextErrorCode.INVALID_CONTEXT


def test_summary_item_requires_non_empty_text_and_refs() -> None:
    with pytest.raises(ContextError):
        SummaryItem(
            kind=SummaryKind.CLAIMED,
            text="",
            source_refs=("message://t/1",),
        )
    with pytest.raises(ContextError):
        SummaryItem(
            kind=SummaryKind.CLAIMED,
            text="ok",
            source_refs=(),
        )


def test_summary_round_trip_through_mapping() -> None:
    summary = _summary()
    restored = LayeredSummary.from_mapping(summary.to_mapping())

    assert restored == summary
    sections = restored.sections()
    assert (
        len(sections[SummaryKind.VERIFIED]) == 1
        and sections[SummaryKind.VERIFIED][0].source_refs
        == ("tool://policy/v1",)
    )


def test_summary_merge_appends_without_duplication() -> None:
    summary = _summary()
    extra = LayeredSummary(
        items=(
            SummaryItem(
                kind=SummaryKind.VERIFIED,
                text="policy allows VPN for production",
                source_refs=("tool://policy/v1",),
            ),
            SummaryItem(
                kind=SummaryKind.CLAIMED,
                text="user also mentions office Wi-Fi",
                source_refs=("message://t/4",),
            ),
        )
    )
    merged = summary.merge(extra)

    assert len(merged.items) == 4
    assert (
        len(merged.sections()[SummaryKind.VERIFIED]) == 1
    ), "merge must not duplicate an existing (kind, text) pair"


def test_build_summary_layer_emits_l3_derived_data() -> None:
    layer = build_summary_layer(summary=_summary(), ref="summary://t/round/3")

    assert isinstance(layer, ContextLayer)
    assert layer.name is LayerName.CONVERSATION_SUMMARY
    assert layer.trust is TrustLevel.DERIVED_DATA
    assert layer.classification is DataClassification.INTERNAL
    assert layer.source_refs == ("summary://t/round/3",)
    assert layer.content["items"][0]["kind"] == SummaryKind.CLAIMED.value


def test_summary_rides_the_graph_checkpoint_without_loss() -> None:
    summary = _summary()
    state = GraphState(
        task_id="task_12345678",
        tenant_id="tenant-a",
        command_id="cmd_12345678",
        command_digest="sha256:" + "0" * 64,
        run_id="run_12345678",
        run_generation=1,
        graph_version="graph-v1",
        status=GraphStatus.WAITING_USER,
        node=GraphNode.INTERRUPT,
        security_context_ref="security-context://tenant-a/12345678",
        security_context_hash="sha256:" + "1" * 64,
        purpose="it_support",
        conversation_round=7,
        cumulative_input_tokens=224,
        cumulative_output_tokens=56,
        summary=summary,
    )

    restored = GraphState.from_checkpoint(state.to_checkpoint())

    assert restored.summary == summary
    assert restored.conversation_round == 7
    assert restored.cumulative_input_tokens == 224
    assert restored.cumulative_output_tokens == 56


def test_checkpoint_without_summary_round_trips_as_none() -> None:
    state = GraphState(
        task_id="task_12345678",
        tenant_id="tenant-a",
        command_id="cmd_12345678",
        command_digest="sha256:" + "0" * 64,
        run_id="run_12345678",
        run_generation=1,
        graph_version="graph-v1",
        status=GraphStatus.RUNNING,
        node=GraphNode.RUN_AGENT,
        security_context_ref="security-context://tenant-a/12345678",
        security_context_hash="sha256:" + "1" * 64,
        purpose="it_support",
    )

    restored = GraphState.from_checkpoint(state.to_checkpoint())

    assert restored.summary is None
    assert restored.conversation_round == 0
