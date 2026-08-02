"""FP-EVAL-004: blind-test Judge calibration runner tests.

Covers the statistics (Wilson CI, Cohen's kappa, Youden threshold), the
anonymized stratified blind-set construction, the calibration computation,
and the committed artifacts (blind set reproducibility, calibration.json
three required elements, M6 hash freeze consistency with executor trail).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evals.runners.calibrate_judge import (
    BLIND_SET_PROFILE,
    CALIBRATION_PROFILE,
    EXECUTOR_IDENTITY,
    FREEZE_PROFILE,
    KAPPA_GATE,
    MIN_BLIND_SAMPLE_SIZE,
    BlindSample,
    ConfusionMatrix,
    build_blind_samples,
    build_freeze_record,
    cohens_kappa,
    compute_calibration,
    default_verdicts,
    iter_cases,
    reference_label,
    verify_freeze,
    wilson_interval,
    youden_threshold,
)

ROOT = Path(__file__).resolve().parents[3]
DATASETS = ROOT / "evals" / "datasets"
RUNNERS = ROOT / "evals" / "runners"


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def test_wilson_interval_zero_and_full() -> None:
    # Wilson(0, 10) upper bound: p=0, n=10, z=1.96 -> ~0.2775.
    assert wilson_interval(0, 10) == (0.0, pytest.approx(0.2775, abs=1e-3))
    assert wilson_interval(10, 10)[0] == pytest.approx(0.7225, abs=1e-3)
    assert wilson_interval(0, 0) == (0.0, 0.0)
    lo, hi = wilson_interval(15, 30)
    assert 0.0 <= lo < 0.5 < hi <= 1.0


def test_wilson_interval_contains_sample_proportion() -> None:
    lo, hi = wilson_interval(3, 30)
    assert lo <= 0.1 <= hi


def test_cohens_kappa_perfect_and_negative() -> None:
    assert cohens_kappa([1, 1, 0, 0], [1, 1, 0, 0]) == pytest.approx(1.0)
    # Systematic disagreement cannot be chance: kappa must be < 0.
    kappa = cohens_kappa([1, 1, 0, 0], [0, 0, 1, 1])
    assert kappa is not None and kappa < 0
    assert cohens_kappa([], []) is None


def test_youden_threshold_perfect_separation() -> None:
    scores = [0.9, 0.8, 0.7, 0.2, 0.1, 0.05]
    labels = [1, 1, 1, 0, 0, 0]
    threshold, youden = youden_threshold(scores, labels)
    assert youden == pytest.approx(1.0)
    assert 0.2 <= threshold <= 0.7


def test_youden_threshold_degenerate_scores() -> None:
    threshold, youden = youden_threshold([0.5, 0.5, 0.5], [1, 0, 1])
    assert threshold == 0.5
    assert youden == 0.0


def test_confusion_matrix_from_labels() -> None:
    matrix = ConfusionMatrix.from_labels([1, 1, 0, 0, 1], [1, 0, 0, 0, 1])
    assert matrix.to_dict() == {"tp": 2, "fp": 1, "fn": 0, "tn": 2}


# ---------------------------------------------------------------------------
# Blind-set construction
# ---------------------------------------------------------------------------


def _make_case(
    case_id: str,
    suite: str,
    category: str,
    terminal_status: str,
    *,
    with_output: bool = True,
) -> dict[str, Any]:
    messages = [{"role": "user", "content": f"prompt for {case_id}"}]
    if with_output:
        messages.append({"role": "assistant", "content": f"answer for {case_id}"})
    return {
        "case_id": case_id,
        "suite": suite,
        "category": category,
        "input": messages,
        "expected": {"terminal_status": terminal_status},
        "dataset_ref": {
            "dataset_id": "synthetic-test",
            "dataset_hash": "sha256:0000",
        },
    }


def _write_synthetic_corpus(root: Path, count: int) -> None:
    cases = root / "m6-incremental-a" / "cases" / "functional"
    cases.mkdir(parents=True)
    for index in range(count):
        case = _make_case(
            f"syn.func.{index:03d}",
            "functional",
            "clarification",
            "COMPLETED" if index % 2 == 0 else "FAILED",
        )
        (cases / f"syn.func.{index:03d}.json").write_text(
            json.dumps(case, ensure_ascii=False),
            encoding="utf-8",
        )


def test_build_blind_samples_is_deterministic_and_anonymized() -> None:
    samples = build_blind_samples(DATASETS, size=MIN_BLIND_SAMPLE_SIZE)
    assert len(samples) == MIN_BLIND_SAMPLE_SIZE
    rebuilt = build_blind_samples(DATASETS, size=MIN_BLIND_SAMPLE_SIZE)
    assert [s.blind_id for s in samples] == [s.blind_id for s in rebuilt]
    assert [s.source_case_id for s in samples] == [
        s.source_case_id for s in rebuilt
    ]
    # Stratification: both suites must be represented.
    assert {s.suite for s in samples} == {"functional", "safety_fault"}
    # Anonymization: the Judge-visible projection leaks no identity.
    for sample in samples:
        projection = sample.anonymized()
        assert "source_case_id" not in projection
        assert "reference_label" not in projection
        assert "dataset_hash" not in projection
        assert "dataset_id" not in projection
        assert sample.blind_id.startswith("blind.")


def test_build_blind_samples_insufficient_corpus_raises(tmp_path: Path) -> None:
    _write_synthetic_corpus(tmp_path / "datasets", 4)
    with pytest.raises(ValueError, match="at least"):
        build_blind_samples(
            tmp_path / "datasets",
            size=MIN_BLIND_SAMPLE_SIZE,
        )


def test_reference_label_uses_terminal_status() -> None:
    assert reference_label(_make_case("a", "f", "c", "COMPLETED")) == 1
    assert reference_label(_make_case("b", "f", "c", "FAILED")) == 0


def test_iter_cases_covers_full_m6_corpus() -> None:
    cases = list(iter_cases(DATASETS))
    assert len(cases) >= 150  # 69 + 52 + 35 declared candidates


# ---------------------------------------------------------------------------
# Calibration computation
# ---------------------------------------------------------------------------


def test_compute_calibration_requires_min_samples(tmp_path: Path) -> None:
    samples = [BlindSample(
        blind_id="blind.001",
        source_case_id="x",
        suite="functional",
        category="clarification",
        input_messages=(("user", "q"),),
        candidate_output="a",
        reference_label=1,
        dataset_id="t",
        dataset_hash="h",
    )]
    with pytest.raises(ValueError, match="at least"):
        compute_calibration(samples, {"blind.001": {"verdict": 1, "score": 1.0}})


def test_compute_calibration_missing_verdicts_raises() -> None:
    samples = build_blind_samples(DATASETS, size=MIN_BLIND_SAMPLE_SIZE)
    verdicts = {s.blind_id: {"verdict": 1, "score": 1.0} for s in samples[:-1]}
    with pytest.raises(ValueError, match="missing verdicts"):
        compute_calibration(samples, verdicts)


def test_compute_calibration_proxy_pipeline_shape() -> None:
    samples = build_blind_samples(DATASETS, size=MIN_BLIND_SAMPLE_SIZE)
    verdicts = default_verdicts(samples)
    result = compute_calibration(samples, verdicts)
    matrix = result.matrix
    assert matrix.tp + matrix.fp + matrix.fn + matrix.tn == len(samples)
    assert 0.0 <= result.accuracy <= 1.0
    assert result.ci["accuracy"][0] <= result.accuracy <= result.ci["accuracy"][1]
    assert set(result.thresholds) == {
        "answer_relevance",
        "summary_faithfulness",
        "citation_support",
        "clarification_quality",
        "ticket_description_quality",
    }
    for _dimension, advice in result.thresholds.items():
        assert "recommended_threshold" in advice
        assert "youden_j" in advice
        assert advice["rubric_id"].startswith("judge.semantic.")


# ---------------------------------------------------------------------------
# Committed artifact gates (reproducibility + required elements + freeze)
# ---------------------------------------------------------------------------


def test_committed_blind_set_is_reproducible() -> None:
    labels_path = RUNNERS / "blind-set-labels.v1.json"
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    assert labels["profile"] == BLIND_SET_PROFILE
    assert len(labels["labels"]) == MIN_BLIND_SAMPLE_SIZE
    rebuilt = build_blind_samples(DATASETS, size=len(labels["labels"]))
    committed = [value for value in labels["labels"].values()]
    assert [s.to_dict() for s in rebuilt] == committed


def test_committed_calibration_has_three_required_elements() -> None:
    calibration = json.loads(
        (RUNNERS / "calibration.json").read_text(encoding="utf-8")
    )
    assert calibration["profile"] == CALIBRATION_PROFILE
    assert calibration["status"] == "placeholder_proxy"
    assert calibration["judge_backend"] == "deterministic_proxy"
    # 1) metrics, 2) threshold recommendations, 3) confidence intervals.
    metrics = calibration["metrics"]
    assert set(metrics) >= {
        "confusion_matrix",
        "accuracy",
        "kappa",
        "false_positive_rate",
        "false_negative_rate",
    }
    assert calibration["threshold_recommendations"]
    assert calibration["confidence_intervals"]["accuracy_95"]
    assert calibration["blind_set"]["sample_count"] >= MIN_BLIND_SAMPLE_SIZE
    # Uncalibrated placeholder must never claim the gate is met.
    assert calibration["gate"] == {
        "kappa_gate": KAPPA_GATE,
        "gate_met": False,
    }


def test_committed_freeze_is_consistent_with_datasets_and_calibration() -> None:
    freeze = json.loads(
        (RUNNERS / "m6-hash-freeze.v1.json").read_text(encoding="utf-8")
    )
    assert freeze["profile"] == FREEZE_PROFILE
    assert freeze["status"] == "frozen"
    # Dataset hashes still match the committed files.
    assert verify_freeze(freeze, DATASETS) == []
    # Calibration digest matches the committed calibration.json.
    baseline = freeze["judge_baseline"]
    assert baseline["calibration_ref"] == "evals/runners/calibration.json"
    calibration_path = RUNNERS / "calibration.json"
    from packages.evaluation.canonical import sha256_file

    assert baseline["calibration_sha256"] == sha256_file(calibration_path)
    assert baseline["kappa_gate"] == KAPPA_GATE
    assert baseline["calibration_status"] == "placeholder_proxy"


def test_freeze_record_carries_executor_registry_identity(
    tmp_path: Path,
) -> None:
    calibration = json.loads(
        (RUNNERS / "calibration.json").read_text(encoding="utf-8")
    )
    calibration_path = tmp_path / "calibration.json"
    calibration_path.write_text(
        json.dumps(calibration, ensure_ascii=False),
        encoding="utf-8",
    )
    freeze = build_freeze_record(
        DATASETS,
        calibration_path=calibration_path,
        calibration_status="placeholder_proxy",
    )
    assert freeze["executor"]["agent_id"] == EXECUTOR_IDENTITY["agent_id"]
    assert freeze["executor"]["agent_id"] == "g2"
    assert freeze["executor"]["role"] == "S4-QUALITY eval-freezer"
    assert freeze["executor"]["registered_by"] == "human:owner"
    assert freeze["executor"]["identity_source"] == (
        ".flow/agents.json (flow-lite registration registry)"
    )
    assert freeze["git"]["commit"]
    assert freeze["git"]["branch"] == "flow-lite/g2-5"
    assert set(freeze["datasets"]) == {
        "flowpilot-m6-incremental-a-local",
        "flowpilot-m6-incremental-b-local",
        "flowpilot-m6-incremental-c-local",
    }


def test_freeze_record_manifest_hash_roundtrip(tmp_path: Path) -> None:
    calibration = json.loads(
        (RUNNERS / "calibration.json").read_text(encoding="utf-8")
    )
    calibration_path = tmp_path / "calibration.json"
    calibration_path.write_text(
        json.dumps(calibration, ensure_ascii=False),
        encoding="utf-8",
    )
    freeze = build_freeze_record(
        DATASETS,
        calibration_path=calibration_path,
        calibration_status="placeholder_proxy",
    )
    # The freeze record itself is self-consistent: verifying it against the
    # live dataset tree must report zero violations.
    assert verify_freeze(freeze, DATASETS) == []
