from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from evals.runners.calibrate_judge import (
    ADJUDICATION_PROFILE,
    BINDINGS_PROFILE,
    BLIND_SET_PROFILE,
    CALIBRATION_PROFILE,
    FREEZE_PROFILE,
    HUMAN_REVIEW_PROFILE,
    PREDICTIONS_PROFILE,
    artifact_digests,
    blind_documents,
    build_blind_samples,
    cohens_kappa,
    compute_calibration,
    digest_text,
    digest_value,
    verify_artifacts,
    wilson_interval,
)


def corpus(tmp_path: Path, count: int = 34) -> tuple[Path, Path]:
    root = tmp_path / "evidence"
    root.mkdir()
    observations: list[dict[str, Any]] = []
    for index in range(count):
        output, ref = f"observed {index}", f"case-{index}.txt"
        (root / ref).write_text(output, encoding="utf-8")
        item: dict[str, Any] = {
            "observation_id": f"obs-{index}",
            "case": {
                "case_id": f"case-{index}",
                "suite": "functional",
                "category": "clarification" if index % 2 else "summary",
                "input": [{"role": "user", "content": "never candidate"}],
                "judge_rubrics": [{"rubric_id": "judge.semantic.answer_relevance.v1"}],
            },
            "candidate_output": output,
            "execution": {
                "case_id": f"case-{index}",
                "executor_id": "acceptance-executor",
                "executor_version": "1.0",
                "output_digest": digest_text(output),
                "assertion_results": {"functional": True},
                "evidence_refs": [ref],
            },
            "evidence_hashes": {ref: digest_text(output)},
        }
        item["observation_digest"] = digest_value(item)
        observations.append(item)
    path = tmp_path / "observations.json"
    path.write_text(
        json.dumps(
            {
                "profile": "flowpilot.acceptance-observations.v1",
                "observations": observations,
            }
        ),
        encoding="utf-8",
    )
    return path, root


def inputs(tmp_path: Path) -> tuple[Any, ...]:
    path, root = corpus(tmp_path)
    samples = build_blind_samples(path, evidence_root=root, size=30)
    blind, bindings = blind_documents(samples)
    base = {x.blind_id: i % 2 for i, x in enumerate(samples)}
    first = {
        "profile": HUMAN_REVIEW_PROFILE,
        "reviewer_id": "reviewer-a",
        "labels": base,
    }
    second = {
        "profile": HUMAN_REVIEW_PROFILE,
        "reviewer_id": "reviewer-b",
        "labels": dict(base),
    }
    adjudication = {
        "profile": ADJUDICATION_PROFILE,
        "adjudicator_id": "lead-reviewer",
        "decisions": {},
    }
    predictions = {
        "profile": PREDICTIONS_PROFILE,
        "prediction_run_id": "run-1",
        "model_id": "judge-model-v1",
        "backend": "trusted-provider",
        "prompt_hash": digest_text("prompt"),
        "labels": dict(base),
        "scores": {key: float(value) for key, value in base.items()},
    }
    digests = artifact_digests(
        blind, bindings, first, second, adjudication, predictions
    )
    calibration = compute_calibration(
        samples, first, second, adjudication, predictions, artifact_digests=digests
    )
    freeze = {
        "profile": FREEZE_PROFILE,
        "status": "approved",
        "approved_by_role": "S1-ARCH",
        "approval_id": "WP-035-S1-approval",
        "artifact_digests": digests,
        "calibration_digest": digest_value(calibration),
    }
    return (
        samples,
        blind,
        bindings,
        first,
        second,
        adjudication,
        predictions,
        calibration,
        freeze,
    )


def test_real_observations_are_stratified_and_input_is_not_output(
    tmp_path: Path,
) -> None:
    path, root = corpus(tmp_path)
    samples = build_blind_samples(path, evidence_root=root, size=30, seed=7)
    assert {x.category for x in samples} == {"clarification", "summary"}
    assert all(x.candidate_output.startswith("observed") for x in samples)
    assert [x.case_id for x in samples] == [
        x.case_id
        for x in build_blind_samples(path, evidence_root=root, size=30, seed=7)
    ]


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("observation_digest", "sha256:BAD", "lowercase hex"),
        ("candidate_output", "tampered", "output digest"),
        ("observation_id", "", "observation_id"),
    ],
)
def test_observation_identity_and_hashes_fail_closed(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    path, root = corpus(tmp_path)
    doc = json.loads(path.read_text())
    doc["observations"][0][field] = value
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match=message):
        build_blind_samples(path, evidence_root=root)


@pytest.mark.parametrize(
    "mutation,message",
    [
        ("duplicate_case", "duplicate case"),
        ("duplicate_ref", "unique list"),
        ("executor", "executor_id"),
        ("assertions", "assertion set"),
    ],
)
def test_provenance_duplicates_and_assertions_rejected(
    tmp_path: Path, mutation: str, message: str
) -> None:
    path, root = corpus(tmp_path)
    doc = json.loads(path.read_text())
    first = doc["observations"][0]
    if mutation == "duplicate_case":
        doc["observations"][1]["case"]["case_id"] = first["case"]["case_id"]
    elif mutation == "duplicate_ref":
        first["execution"]["evidence_refs"] *= 2
    elif mutation == "executor":
        first["execution"]["executor_id"] = "none"
    else:
        first["execution"]["assertion_results"] = []
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match=message):
        build_blind_samples(path, evidence_root=root)


def test_calibration_restores_enterprise_metrics_but_remains_candidate(
    tmp_path: Path,
) -> None:
    values = inputs(tmp_path)
    calibration = values[7]
    assert calibration["profile"] == CALIBRATION_PROFILE
    assert (
        calibration["status"] == "candidate"
        and calibration["aggregation_effect"] == "no_effect"
    )
    metrics = calibration["metrics"]
    assert set(metrics) >= {
        "confusion_matrix",
        "accuracy_95",
        "false_positive_rate",
        "false_negative_rate",
        "per_rubric",
    }
    rubric = metrics["per_rubric"]["judge.semantic.answer_relevance.v1"]
    assert "threshold_recommendation" in rubric and "confusion_matrix" in rubric


def test_review_identity_label_and_prediction_validation(tmp_path: Path) -> None:
    samples, _, _, first, second, adjudication, predictions, _, _ = inputs(tmp_path)
    second["reviewer_id"] = first["reviewer_id"]
    with pytest.raises(ValueError, match="distinct"):
        compute_calibration(samples, first, second, adjudication, predictions)
    second["reviewer_id"] = "reviewer-b"
    predictions["prompt_hash"] = "sha256:ABC"
    with pytest.raises(ValueError, match="lowercase hex"):
        compute_calibration(samples, first, second, adjudication, predictions)
    predictions["prompt_hash"] = digest_text("prompt")
    predictions.pop("backend")
    with pytest.raises(ValueError, match="backend"):
        compute_calibration(samples, first, second, adjudication, predictions)


def test_disagreements_require_binary_adjudication(tmp_path: Path) -> None:
    samples, _, _, first, second, adjudication, predictions, _, _ = inputs(tmp_path)
    key = samples[0].blind_id
    second["labels"][key] ^= 1
    with pytest.raises(ValueError, match="adjudication"):
        compute_calibration(samples, first, second, adjudication, predictions)
    adjudication["decisions"][key] = True
    with pytest.raises(ValueError, match="binary"):
        compute_calibration(samples, first, second, adjudication, predictions)


@pytest.mark.parametrize(
    "target",
    [
        "blind",
        "bindings",
        "round1",
        "round2",
        "adjudication",
        "predictions",
        "calibration",
        "freeze",
    ],
)
def test_verify_rejects_tampering_of_every_artifact(
    tmp_path: Path, target: str
) -> None:
    (
        _,
        blind,
        bindings,
        first,
        second,
        adjudication,
        predictions,
        calibration,
        freeze,
    ) = inputs(tmp_path)
    docs = [
        copy.deepcopy(x)
        for x in (
            blind,
            bindings,
            first,
            second,
            adjudication,
            predictions,
            calibration,
            freeze,
        )
    ]
    index = {
        "blind": 0,
        "bindings": 1,
        "round1": 2,
        "round2": 3,
        "adjudication": 4,
        "predictions": 5,
        "calibration": 6,
        "freeze": 7,
    }[target]
    docs[index]["tampered"] = True
    assert verify_artifacts(*docs)


def test_fabricated_calibrated_json_and_missing_freeze_fail(tmp_path: Path) -> None:
    _, blind, bindings, first, second, adjudication, predictions, calibration, _ = (
        inputs(tmp_path)
    )
    fabricated = dict(calibration)
    fabricated["status"] = "calibrated"
    fabricated["aggregation_effect"] = "enabled"
    assert verify_artifacts(
        blind, bindings, first, second, adjudication, predictions, fabricated, None
    )


def test_approved_freeze_verifies_full_chain(tmp_path: Path) -> None:
    (
        _,
        blind,
        bindings,
        first,
        second,
        adjudication,
        predictions,
        calibration,
        freeze,
    ) = inputs(tmp_path)
    assert (
        verify_artifacts(
            blind,
            bindings,
            first,
            second,
            adjudication,
            predictions,
            calibration,
            freeze,
        )
        == []
    )


def test_profiles_and_statistics() -> None:
    assert BINDINGS_PROFILE != BLIND_SET_PROFILE
    assert cohens_kappa([0, 1], [0, 1]) == 1.0
    low, high = wilson_interval(5, 10)
    assert low < 0.5 < high


def test_legacy_placeholder_stays_no_effect() -> None:
    root = Path(__file__).resolve().parents[3] / "evals" / "runners"
    old = json.loads((root / "calibration.json").read_text(encoding="utf-8"))
    assert old["status"] == "placeholder_proxy" and old["gate"]["gate_met"] is False
