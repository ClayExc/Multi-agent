from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from evals.runners.calibrate_judge import (
    BLIND_SET_PROFILE,
    MIN_BLIND_SAMPLE_SIZE,
    build_blind_samples,
    compute_calibration,
    verify_artifacts,
)


def digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def corpus(
    tmp_path: Path, *, count: int = 30, suite: str = "functional", rubric: bool = True
) -> tuple[Path, Path]:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    observations: list[dict[str, Any]] = []
    for i in range(count):
        output = f"observed answer {i}"
        ref = f"case-{i}.txt"
        (evidence / ref).write_text(output, encoding="utf-8")
        observations.append(
            {
                "case": {
                    "case_id": f"case-{i}",
                    "suite": suite,
                    "category": "clarification",
                    "input": [{"role": "user", "content": "must not become output"}],
                    "judge_rubrics": (
                        [{"rubric_id": "judge.semantic.answer_relevance.v1"}]
                        if rubric
                        else []
                    ),
                },
                "candidate_output": output,
                "execution": {
                    "case_id": f"case-{i}",
                    "output_digest": digest(output),
                    "assertion_results": {"deterministic": True},
                    "evidence_refs": [ref],
                },
                "evidence_hashes": {ref: digest(output)},
            }
        )
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
    return path, evidence


def test_case_input_cannot_be_candidate_output_and_real_observation_required(
    tmp_path: Path,
) -> None:
    path, root = corpus(tmp_path)
    samples = build_blind_samples(path, evidence_root=root)
    assert samples[0].candidate_output.startswith("observed answer")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"profile": "dataset", "observations": []}))
    with pytest.raises(ValueError, match="real Acceptance"):
        build_blind_samples(bad, evidence_root=root)


@pytest.mark.parametrize(
    "mutation,message",
    [("case", "case ID"), ("output", "output digest"), ("evidence", "evidence hash")],
)
def test_observation_bindings_fail_closed(
    tmp_path: Path, mutation: str, message: str
) -> None:
    path, root = corpus(tmp_path)
    doc = json.loads(path.read_text())
    item = doc["observations"][0]
    if mutation == "case":
        item["execution"]["case_id"] = "wrong"
    elif mutation == "output":
        item["execution"]["output_digest"] = digest("wrong")
    else:
        item["evidence_hashes"]["case-0.txt"] = digest("wrong")
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match=message):
        build_blind_samples(path, evidence_root=root)


def test_failed_gate_and_nonsemantic_cases_do_not_enter_denominator(
    tmp_path: Path,
) -> None:
    path, root = corpus(tmp_path, count=32)
    doc = json.loads(path.read_text())
    doc["observations"][0]["case"]["suite"] = "safety_fault"
    doc["observations"][1]["case"]["judge_rubrics"] = []
    doc["observations"][2]["execution"]["assertion_results"]["deterministic"] = False
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="only 29"):
        build_blind_samples(path, evidence_root=root)


def labels(
    samples: list[Any], value: int = 0, *, round_id: str = "r1"
) -> dict[str, Any]:
    return {
        "reviewer_round_id": round_id,
        "labels": {x.blind_id: (i + value) % 2 for i, x in enumerate(samples)},
    }


def test_missing_second_round_disagreement_or_prediction_identity_fails(
    tmp_path: Path,
) -> None:
    path, root = corpus(tmp_path)
    samples = build_blind_samples(path, evidence_root=root)
    first = labels(samples)
    second = labels(samples, round_id="r2")
    with pytest.raises(ValueError, match="second human"):
        compute_calibration(
            samples,
            first,
            {},
            {"decisions": {}},
            labels(samples, round_id="j")
            | {"model_id": "m", "prompt_hash": digest("p")},
        )
    second["labels"][samples[0].blind_id] ^= 1
    with pytest.raises(ValueError, match="adjudicated"):
        compute_calibration(
            samples,
            first,
            second,
            {"decisions": {}},
            labels(samples, round_id="j")
            | {"model_id": "m", "prompt_hash": digest("p")},
        )
    with pytest.raises(ValueError, match="identity"):
        compute_calibration(
            samples,
            first,
            first | {"reviewer_round_id": "r2"},
            {"decisions": {}},
            labels(samples, round_id="j"),
        )


def test_complete_synthetic_calibration_and_proxy_no_effect(tmp_path: Path) -> None:
    path, root = corpus(tmp_path)
    samples = build_blind_samples(path, evidence_root=root)
    first = labels(samples)
    second = labels(samples, round_id="r2")
    judge = labels(samples, round_id="judge") | {
        "model_id": "synthetic-model",
        "prompt_hash": digest("prompt"),
        "backend": "offline_fixture",
    }
    result = compute_calibration(samples, first, second, {"decisions": {}}, judge)
    assert result["status"] == "calibrated" and result["gate"]["gate_met"]
    judge["backend"] = "proxy"
    result = compute_calibration(samples, first, second, {"decisions": {}}, judge)
    assert (
        result["status"] == "USER_GATE_REQUIRED"
        and result["aggregation_effect"] == "no_effect"
    )


def test_legacy_committed_artifacts_are_explicit_placeholders() -> None:
    root = Path(__file__).resolve().parents[3] / "evals" / "runners"
    old_blind = json.loads((root / "blind-set.v1.json").read_text(encoding="utf-8"))
    old_labels = json.loads(
        (root / "blind-set-labels.v1.json").read_text(encoding="utf-8")
    )
    old_cal = json.loads((root / "calibration.json").read_text(encoding="utf-8"))
    errors = verify_artifacts(old_blind, old_labels, old_cal)
    assert errors and any("legacy placeholder" in item for item in errors)
    assert old_cal["status"] == "placeholder_proxy"


def test_sample_minimum() -> None:
    assert MIN_BLIND_SAMPLE_SIZE == 30 and BLIND_SET_PROFILE.endswith(".v2")
