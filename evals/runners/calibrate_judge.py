"""Fail-closed offline calibration for semantic LLM-as-Judge (FP-EVAL-004)."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MIN_BLIND_SAMPLE_SIZE = 30
KAPPA_GATE = 0.75
HUMAN_KAPPA_GATE = 0.75
BLIND_SET_PROFILE = "flowpilot.judge-blind-set.v2"
CALIBRATION_PROFILE = "flowpilot.judge-calibration.v2"
PLACEHOLDER_PROFILES = {
    "flowpilot.judge-blind-set.v1",
    "flowpilot.judge-calibration.v1",
}


def _digest_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _digest_text(value: str) -> str:
    return _digest_bytes(value.encode("utf-8"))


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass(frozen=True, slots=True)
class BlindSample:
    blind_id: str
    case_id: str
    category: str
    rubric_ids: tuple[str, ...]
    candidate_output: str
    output_digest: str
    evidence_hashes: tuple[tuple[str, str], ...]

    def anonymous(self) -> dict[str, Any]:
        return {
            "blind_id": self.blind_id,
            "category": self.category,
            "rubric_ids": list(self.rubric_ids),
            "candidate_output": self.candidate_output,
        }

    def binding(self) -> dict[str, Any]:
        return {
            "blind_id": self.blind_id,
            "case_id": self.case_id,
            "output_digest": self.output_digest,
            "evidence_hashes": dict(self.evidence_hashes),
        }


def cohens_kappa(a: Iterable[int], b: Iterable[int]) -> float | None:
    left, right = list(a), list(b)
    if not left or len(left) != len(right):
        return None
    observed = sum(x == y for x, y in zip(left, right, strict=True)) / len(left)
    lp, rp = sum(left) / len(left), sum(right) / len(right)
    expected = lp * rp + (1 - lp) * (1 - rp)
    return None if expected == 1 else (observed - expected) / (1 - expected)


def build_blind_samples(
    observations_path: Path,
    *,
    evidence_root: Path,
    size: int = MIN_BLIND_SAMPLE_SIZE,
    seed: int = 0,
) -> list[BlindSample]:
    """Build only from hash-bound, deterministic-gate-passing product observations."""
    document = _load(observations_path)
    if document.get("profile") != "flowpilot.acceptance-observations.v1":
        raise ValueError(
            "real Acceptance observation profile required; dataset/proxy input rejected"
        )
    eligible: list[Mapping[str, Any]] = []
    for item in document.get("observations", []):
        case = item.get("case") or {}
        execution = item.get("execution") or {}
        if case.get("suite") != "functional" or not case.get("judge_rubrics"):
            continue
        if execution.get("case_id") != case.get("case_id"):
            raise ValueError("case ID binding mismatch")
        output = item.get("candidate_output")
        if not isinstance(output, str) or not output:
            raise ValueError("real candidate output is required")
        if execution.get("output_digest") != _digest_text(output):
            raise ValueError("output digest mismatch")
        gates = execution.get("assertion_results")
        if (
            not isinstance(gates, dict)
            or not gates
            or not all(v is True for v in gates.values())
        ):
            continue
        hashes = item.get("evidence_hashes")
        refs = execution.get("evidence_refs")
        if not isinstance(hashes, dict) or not refs or set(hashes) != set(refs):
            raise ValueError("evidence hash binding mismatch")
        for ref, expected in hashes.items():
            path = (evidence_root / ref).resolve()
            if evidence_root.resolve() not in path.parents or not path.is_file():
                raise ValueError("evidence file missing or outside evidence root")
            if _digest_bytes(path.read_bytes()) != expected:
                raise ValueError("evidence hash mismatch")
        eligible.append(item)
    random.Random(seed).shuffle(eligible)
    if len(eligible) < size:
        raise ValueError(
            f"only {len(eligible)} trusted semantic observations; "
            f"at least {size} required"
        )
    result: list[BlindSample] = []
    for index, item in enumerate(eligible[:size], 1):
        case, execution = item["case"], item["execution"]
        rubrics = tuple(sorted(str(x["rubric_id"]) for x in case["judge_rubrics"]))
        if not all(value.startswith("judge.semantic.") for value in rubrics):
            raise ValueError("non-semantic Judge rubric rejected")
        result.append(
            BlindSample(
                f"blind.{index:03d}",
                str(case["case_id"]),
                str(case.get("category", "unknown")),
                rubrics,
                str(item["candidate_output"]),
                str(execution["output_digest"]),
                tuple(sorted(item["evidence_hashes"].items())),
            )
        )
    return result


def _labels(
    document: Mapping[str, Any], samples: list[BlindSample], name: str
) -> dict[str, int]:
    values = document.get("labels")
    expected = {sample.blind_id for sample in samples}
    if not isinstance(values, dict) or set(values) != expected:
        raise ValueError(f"{name} labels must cover the Blind Set exactly")
    parsed = {key: int(value) for key, value in values.items()}
    if any(value not in (0, 1) for value in parsed.values()):
        raise ValueError(f"{name} labels must be binary")
    return parsed


def compute_calibration(
    samples: list[BlindSample],
    human_round_1: Mapping[str, Any],
    human_round_2: Mapping[str, Any],
    adjudication: Mapping[str, Any],
    judge_predictions: Mapping[str, Any],
) -> dict[str, Any]:
    if len(samples) < MIN_BLIND_SAMPLE_SIZE:
        raise ValueError("insufficient trusted samples")
    first = _labels(human_round_1, samples, "first human round")
    second = _labels(human_round_2, samples, "second human round")
    if human_round_1.get("reviewer_round_id") == human_round_2.get("reviewer_round_id"):
        raise ValueError("two independent human rounds are required")
    disagreements = {key for key in first if first[key] != second[key]}
    decisions = adjudication.get("decisions")
    if not isinstance(decisions, dict) or set(decisions) != disagreements:
        raise ValueError("every and only human disagreement must be adjudicated")
    reference = {
        key: int(decisions[key]) if key in disagreements else first[key]
        for key in first
    }
    predictions = _labels(judge_predictions, samples, "Judge prediction")
    model_id, prompt_hash = (
        judge_predictions.get("model_id"),
        judge_predictions.get("prompt_hash"),
    )
    if (
        not model_id
        or not isinstance(prompt_hash, str)
        or not prompt_hash.startswith("sha256:")
    ):
        raise ValueError("Judge model identity and Prompt hash are required")
    human_kappa = cohens_kappa(first.values(), second.values())
    judge_kappa = cohens_kappa(predictions.values(), reference.values())
    calibrated = (
        human_kappa is not None
        and human_kappa >= HUMAN_KAPPA_GATE
        and judge_kappa is not None
        and judge_kappa >= KAPPA_GATE
        and judge_predictions.get("backend") != "proxy"
    )
    return {
        "profile": CALIBRATION_PROFILE,
        "status": "calibrated" if calibrated else "USER_GATE_REQUIRED",
        "aggregation_effect": "enabled" if calibrated else "no_effect",
        "sample_count": len(samples),
        "model_id": model_id,
        "prompt_hash": prompt_hash,
        "human_kappa": human_kappa,
        "judge_kappa": judge_kappa,
        "adjudicated_count": len(disagreements),
        "gate": {
            "human_kappa_gate": HUMAN_KAPPA_GATE,
            "judge_kappa_gate": KAPPA_GATE,
            "gate_met": calibrated,
        },
    }


def verify_artifacts(
    blind: Mapping[str, Any],
    bindings: Mapping[str, Any],
    calibration: Mapping[str, Any],
) -> list[str]:
    errors: list[str] = []
    for name, value, profile in (
        ("blind", blind, BLIND_SET_PROFILE),
        ("bindings", bindings, BLIND_SET_PROFILE),
        ("calibration", calibration, CALIBRATION_PROFILE),
    ):
        if value.get("profile") != profile:
            errors.append(f"{name} is legacy placeholder or has unsupported profile")
    if calibration.get("status") != "calibrated" or not calibration.get("gate", {}).get(
        "gate_met"
    ):
        errors.append("calibration has no aggregation effect")
    return errors


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-blind-set")
    build.add_argument("--observations", type=Path, required=True)
    build.add_argument("--evidence-root", type=Path, required=True)
    build.add_argument("--out-dir", type=Path, required=True)
    build.add_argument("--size", type=int, default=30)
    cal = sub.add_parser("calibrate")
    for flag in (
        "labels",
        "human-round-1",
        "human-round-2",
        "adjudication",
        "judge-predictions",
    ):
        cal.add_argument("--" + flag, type=Path, required=True)
    cal.add_argument("--out", type=Path, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--blind", type=Path, required=True)
    verify.add_argument("--bindings", type=Path, required=True)
    verify.add_argument("--calibration", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build-blind-set":
        samples = build_blind_samples(
            args.observations, evidence_root=args.evidence_root, size=args.size
        )
        _write(
            args.out_dir / "blind-set.v2.json",
            {"profile": BLIND_SET_PROFILE, "samples": [s.anonymous() for s in samples]},
        )
        _write(
            args.out_dir / "blind-set-bindings.v2.json",
            {"profile": BLIND_SET_PROFILE, "bindings": [s.binding() for s in samples]},
        )
    elif args.command == "calibrate":
        labels = _load(args.labels)
        samples = [
            BlindSample(
                x["blind_id"],
                x["case_id"],
                "",
                (),
                "",
                x["output_digest"],
                tuple(sorted(x["evidence_hashes"].items())),
            )
            for x in labels["bindings"]
        ]
        _write(
            args.out,
            compute_calibration(
                samples,
                _load(args.human_round_1),
                _load(args.human_round_2),
                _load(args.adjudication),
                _load(args.judge_predictions),
            ),
        )
    else:
        errors = verify_artifacts(
            _load(args.blind), _load(args.bindings), _load(args.calibration)
        )
        if errors:
            print("\n".join(errors))
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
