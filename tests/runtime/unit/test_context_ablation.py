"""FP-CTX-005: Baseline/Optimized Context 消融（context-ablation.json）。

The ablation runner compares the full-transcript pipeline against the
summary + sliding-window + filtered-handoff pipeline over the same
synthetic conversation and reports the real measured token distribution.
The assertions here are relational (optimized must measure below baseline,
leak counts must drop to zero) — no conclusion number is pre-filled.
"""

from __future__ import annotations

from packages.evaluation.context_ablation import run_ablation


def test_ablation_report_has_real_schema_and_measurements() -> None:
    report = run_ablation(rounds=5)

    assert report["schema"] == "flowpilot.context-ablation.v1"
    assert report["rounds"] == 5
    assert len(report["baseline"]["turns"]) == 5
    assert len(report["optimized"]["turns"]) == 5
    # Numbers come from the run, not from a hard-coded table.
    assert report["baseline"]["total_tokens"] > 0
    assert report["optimized"]["total_tokens"] > 0
    assert report["optimized"]["ledger"]["round_count"] == 5
    assert report["optimized"]["ledger"]["used_total_tokens"] == report[
        "optimized"
    ]["total_tokens"]


def test_ablation_optimized_context_measures_below_baseline() -> None:
    report = run_ablation(rounds=5)

    baseline_final = report["baseline"]["final_round_input_tokens"]
    optimized_final = report["optimized"]["final_round_input_tokens"]
    # The transcript grows every round; the summary + window must flatten
    # the growth by the final round.
    assert optimized_final < baseline_final
    assert (
        report["optimized"]["total_input_tokens"]
        < report["baseline"]["total_input_tokens"]
    )
    assert report["measured_reduction_input_pct"] > 0


def test_ablation_handoff_leak_count_drops_to_zero() -> None:
    report = run_ablation(rounds=5)
    handoff = report["handoff"]

    # Baseline forwards forbidden fields (approval/session/credentials).
    assert handoff["baseline"]["leak_count"] >= 1
    assert "approval" in handoff["baseline"]["leaked_fields"]
    # Optimized rebuild filters them plus the tool allowlist intersection.
    assert handoff["optimized"]["leak_count"] == 0
    assert handoff["optimized"]["tools_before_filter"] == 2
    assert handoff["optimized"]["tools_after_filter"] == 1
    assert handoff["optimized"]["included_fields"] == 2
    assert handoff["optimized"]["input_tokens"] < handoff["baseline"][
        "input_tokens"
    ]


def test_ablation_report_is_json_serializable() -> None:
    import json

    report = run_ablation(rounds=3)

    # The report must be directly consumable as the acceptance artifact.
    encoded = json.dumps(report, ensure_ascii=False)
    assert '"total_tokens"' in encoded
