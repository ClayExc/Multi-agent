"""Cryptographically bound, fail-closed Judge calibration (FP-EVAL-004)."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

MIN_BLIND_SAMPLE_SIZE = 30
KAPPA_GATE = 0.75
HUMAN_KAPPA_GATE = 0.75
BLIND_SET_PROFILE = "flowpilot.judge-blind-set.v2"
BINDINGS_PROFILE = "flowpilot.judge-blind-bindings.v2"
HUMAN_REVIEW_PROFILE = "flowpilot.judge-human-review.v2"
ADJUDICATION_PROFILE = "flowpilot.judge-adjudication.v2"
PREDICTIONS_PROFILE = "flowpilot.judge-predictions.v2"
CALIBRATION_PROFILE = "flowpilot.judge-calibration.v2"
FREEZE_PROFILE = "flowpilot.judge-calibration-freeze.v2"
OBSERVATIONS_PROFILE = "flowpilot.acceptance-observations.v1"
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def digest_value(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def digest_text(value: str) -> str:
    return digest_bytes(value.encode())


def _require_digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{name} must be sha256:64 lowercase hex")
    return value


def _require_identity(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{name} must be a nonempty trusted identity")
    if value.lower() in {"none", "unknown", "proxy"}:
        raise ValueError(f"{name} is not a trusted identity")
    return value


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


@dataclass(frozen=True, slots=True)
class BlindSample:
    blind_id: str
    case_id: str
    category: str
    rubric_ids: tuple[str, ...]
    candidate_output: str
    output_digest: str
    evidence_hashes: tuple[tuple[str, str], ...]
    executor_id: str
    executor_version: str
    assertion_results: tuple[tuple[str, bool], ...]
    observation_id: str
    observation_digest: str

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
            "executor_id": self.executor_id,
            "executor_version": self.executor_version,
            "assertion_results": dict(self.assertion_results),
            "observation_id": self.observation_id,
            "observation_digest": self.observation_digest,
        }


def cohens_kappa(a: Iterable[int], b: Iterable[int]) -> float | None:
    left, right = list(a), list(b)
    if not left or len(left) != len(right):
        return None
    observed = sum(x == y for x, y in zip(left, right, strict=True)) / len(left)
    lp, rp = sum(left) / len(left), sum(right) / len(right)
    expected = lp * rp + (1 - lp) * (1 - rp)
    return None if expected == 1 else (observed - expected) / (1 - expected)


def wilson_interval(
    successes: int, total: int, z: float = 1.959963984540054
) -> tuple[float, float]:
    if total <= 0:
        return (0.0, 0.0)
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * ((p * (1 - p) + z * z / (4 * total)) / total) ** 0.5 / denominator
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def _confusion(predicted: list[int], reference: list[int]) -> dict[str, int]:
    return {
        "tp": sum(p == r == 1 for p, r in zip(predicted, reference, strict=True)),
        "fp": sum(p == 1 and r == 0 for p, r in zip(predicted, reference, strict=True)),
        "fn": sum(p == 0 and r == 1 for p, r in zip(predicted, reference, strict=True)),
        "tn": sum(p == r == 0 for p, r in zip(predicted, reference, strict=True)),
    }


def _threshold(scores: list[float], labels: list[int]) -> dict[str, float]:
    best = (0.5, -2.0)
    for candidate in sorted(set(scores)):
        matrix = _confusion([int(score >= candidate) for score in scores], labels)
        sensitivity = (
            matrix["tp"] / (matrix["tp"] + matrix["fn"])
            if matrix["tp"] + matrix["fn"]
            else 0.0
        )
        specificity = (
            matrix["tn"] / (matrix["tn"] + matrix["fp"])
            if matrix["tn"] + matrix["fp"]
            else 0.0
        )
        youden = sensitivity + specificity - 1
        if youden > best[1]:
            best = (candidate, youden)
    return {"recommended_threshold": round(best[0], 4), "youden_j": round(best[1], 4)}


def build_blind_samples(
    observations_path: Path,
    *,
    evidence_root: Path,
    size: int = MIN_BLIND_SAMPLE_SIZE,
    seed: int = 0,
) -> list[BlindSample]:
    document = _load(observations_path)
    if document.get("profile") != OBSERVATIONS_PROFILE:
        raise ValueError("real Acceptance observation profile required")
    observations = document.get("observations")
    if not isinstance(observations, list):
        raise ValueError("observations must be a list")
    eligible: dict[tuple[str, tuple[str, ...]], list[BlindSample]] = {}
    seen_cases: set[str] = set()
    root = evidence_root.resolve()
    for item in observations:
        if not isinstance(item, dict):
            raise ValueError("each observation must be an object")
        case, execution = item.get("case"), item.get("execution")
        if not isinstance(case, dict) or not isinstance(execution, dict):
            raise ValueError("case and execution objects are required")
        case_id = _require_identity(case.get("case_id"), "case_id")
        if case_id in seen_cases:
            raise ValueError("duplicate case IDs")
        seen_cases.add(case_id)
        rubrics_raw = case.get("judge_rubrics")
        if case.get("suite") != "functional" or not rubrics_raw:
            continue
        if not isinstance(rubrics_raw, list) or any(
            not isinstance(x, dict) for x in rubrics_raw
        ):
            raise ValueError("judge_rubrics must be a list of objects")
        rubrics = tuple(
            sorted(
                _require_identity(x.get("rubric_id"), "rubric_id") for x in rubrics_raw
            )
        )
        if len(set(rubrics)) != len(rubrics) or not all(
            x.startswith("judge.semantic.") for x in rubrics
        ):
            raise ValueError("rubrics must be unique semantic Judge rubrics")
        if execution.get("case_id") != case_id:
            raise ValueError("case ID binding mismatch")
        output = item.get("candidate_output")
        if not isinstance(output, str) or not output:
            raise ValueError("real candidate output is required")
        output_digest = _require_digest(execution.get("output_digest"), "output_digest")
        if output_digest != digest_text(output):
            raise ValueError("output digest mismatch")
        assertions = execution.get("assertion_results")
        if (
            not isinstance(assertions, dict)
            or not assertions
            or any(
                not isinstance(k, str) or not isinstance(v, bool)
                for k, v in assertions.items()
            )
        ):
            raise ValueError("deterministic assertion set is invalid")
        if not all(assertions.values()):
            continue
        executor_id = _require_identity(execution.get("executor_id"), "executor_id")
        executor_version = _require_identity(
            execution.get("executor_version"), "executor_version"
        )
        refs, hashes = execution.get("evidence_refs"), item.get("evidence_hashes")
        if not isinstance(refs, list) or not refs or len(set(refs)) != len(refs):
            raise ValueError("evidence refs must be a nonempty unique list")
        if not isinstance(hashes, dict) or set(hashes) != set(refs):
            raise ValueError("evidence hash binding mismatch")
        for ref in refs:
            if (
                not isinstance(ref, str)
                or PurePosixPath(ref).is_absolute()
                or ".." in PurePosixPath(ref).parts
            ):
                raise ValueError("unsafe evidence reference")
            expected = _require_digest(hashes[ref], "evidence hash")
            path = (root / Path(ref)).resolve()
            if (
                root not in path.parents
                or not path.is_file()
                or digest_bytes(path.read_bytes()) != expected
            ):
                raise ValueError("evidence hash mismatch")
        observation_id = _require_identity(item.get("observation_id"), "observation_id")
        observation_digest = _require_digest(
            item.get("observation_digest"), "observation_digest"
        )
        payload = {
            key: value for key, value in item.items() if key != "observation_digest"
        }
        if observation_digest != digest_value(payload):
            raise ValueError("observation provenance digest mismatch")
        sample = BlindSample(
            "",
            case_id,
            str(case.get("category", "unknown")),
            rubrics,
            output,
            output_digest,
            tuple(sorted(hashes.items())),
            executor_id,
            executor_version,
            tuple(sorted(assertions.items())),
            observation_id,
            observation_digest,
        )
        eligible.setdefault((sample.category, rubrics), []).append(sample)
    groups = sorted(eligible)
    for index, key in enumerate(groups):
        random.Random(seed + index).shuffle(eligible[key])
    selected: list[BlindSample] = []
    while len(selected) < size and any(eligible.values()):
        for key in groups:
            if eligible[key] and len(selected) < size:
                selected.append(eligible[key].pop())
    if len(selected) < size:
        raise ValueError(
            f"only {len(selected)} trusted semantic observations; "
            f"at least {size} required"
        )
    return [
        BlindSample(
            f"blind.{i:03d}",
            sample.case_id,
            sample.category,
            sample.rubric_ids,
            sample.candidate_output,
            sample.output_digest,
            sample.evidence_hashes,
            sample.executor_id,
            sample.executor_version,
            sample.assertion_results,
            sample.observation_id,
            sample.observation_digest,
        )
        for i, sample in enumerate(selected, 1)
    ]


def blind_documents(
    samples: list[BlindSample], seed: int = 0
) -> tuple[dict[str, Any], dict[str, Any]]:
    blind = {
        "profile": BLIND_SET_PROFILE,
        "seed": seed,
        "samples": [x.anonymous() for x in samples],
    }
    bindings = {
        "profile": BINDINGS_PROFILE,
        "seed": seed,
        "bindings": [x.binding() for x in samples],
    }
    blind["bindings_digest"] = digest_value(bindings)
    bindings["blind_digest"] = digest_value(
        {k: v for k, v in blind.items() if k != "bindings_digest"}
    )
    return blind, bindings


def _labels(
    document: Mapping[str, Any],
    samples: list[BlindSample],
    name: str,
    profile: str,
    identity_field: str,
) -> tuple[dict[str, int], str]:
    if document.get("profile") != profile:
        raise ValueError(f"{name} profile mismatch")
    identity = _require_identity(document.get(identity_field), identity_field)
    values = document.get("labels")
    expected = {sample.blind_id for sample in samples}
    if not isinstance(values, dict) or set(values) != expected:
        raise ValueError(f"{name} labels must cover Blind Set exactly")
    if any(type(value) is not int or value not in (0, 1) for value in values.values()):
        raise ValueError(f"{name} labels must be binary integers")
    return dict(values), identity


def compute_calibration(
    samples: list[BlindSample],
    human_round_1: Mapping[str, Any],
    human_round_2: Mapping[str, Any],
    adjudication: Mapping[str, Any],
    judge_predictions: Mapping[str, Any],
    *,
    artifact_digests: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    if len(samples) < MIN_BLIND_SAMPLE_SIZE or len(
        {x.blind_id for x in samples}
    ) != len(samples):
        raise ValueError("insufficient or duplicate Blind Set samples")
    first, reviewer_1 = _labels(
        human_round_1, samples, "first human round", HUMAN_REVIEW_PROFILE, "reviewer_id"
    )
    second, reviewer_2 = _labels(
        human_round_2,
        samples,
        "second human round",
        HUMAN_REVIEW_PROFILE,
        "reviewer_id",
    )
    if reviewer_1 == reviewer_2:
        raise ValueError("distinct reviewer IDs are required")
    disagreements = {key for key in first if first[key] != second[key]}
    if adjudication.get("profile") != ADJUDICATION_PROFILE:
        raise ValueError("adjudication profile mismatch")
    _require_identity(adjudication.get("adjudicator_id"), "adjudicator_id")
    decisions = adjudication.get("decisions")
    if (
        not isinstance(decisions, dict)
        or set(decisions) != disagreements
        or any(type(v) is not int or v not in (0, 1) for v in decisions.values())
    ):
        raise ValueError("every disagreement requires one binary adjudication")
    reference = {key: decisions.get(key, first[key]) for key in first}
    predicted, _ = _labels(
        judge_predictions,
        samples,
        "Judge prediction",
        PREDICTIONS_PROFILE,
        "prediction_run_id",
    )
    model_id = _require_identity(judge_predictions.get("model_id"), "model_id")
    backend = _require_identity(judge_predictions.get("backend"), "backend")
    prompt_hash = _require_digest(judge_predictions.get("prompt_hash"), "prompt_hash")
    human_kappa = cohens_kappa(first.values(), second.values())
    judge_kappa = cohens_kappa(predicted.values(), reference.values())
    reference_values = [reference[x.blind_id] for x in samples]
    predicted_values = [predicted[x.blind_id] for x in samples]
    matrix = _confusion(predicted_values, reference_values)
    correct = matrix["tp"] + matrix["tn"]
    scores_doc = judge_predictions.get("scores", {})
    per_rubric: dict[str, Any] = {}
    for rubric in sorted({r for sample in samples for r in sample.rubric_ids}):
        indices = [i for i, sample in enumerate(samples) if rubric in sample.rubric_ids]
        labels = [reference_values[i] for i in indices]
        values = [
            float(scores_doc.get(samples[i].blind_id, predicted_values[i]))
            for i in indices
        ]
        threshold = _threshold(values, labels)
        rubric_matrix = _confusion(
            [int(x >= threshold["recommended_threshold"]) for x in values], labels
        )
        per_rubric[rubric] = {
            "sample_count": len(indices),
            "confusion_matrix": rubric_matrix,
            "kappa": cohens_kappa(
                [int(x >= threshold["recommended_threshold"]) for x in values], labels
            ),
            "threshold_recommendation": threshold,
        }
    gates_met = (
        human_kappa is not None
        and human_kappa >= HUMAN_KAPPA_GATE
        and judge_kappa is not None
        and judge_kappa >= KAPPA_GATE
    )
    total = len(samples)
    return {
        "profile": CALIBRATION_PROFILE,
        "status": "candidate" if gates_met else "USER_GATE_REQUIRED",
        "aggregation_effect": "no_effect",
        "sample_count": total,
        "model_id": model_id,
        "backend": backend,
        "prompt_hash": prompt_hash,
        "artifact_digests": dict(artifact_digests or {}),
        "metrics": {
            "confusion_matrix": matrix,
            "accuracy": correct / total,
            "accuracy_95": list(wilson_interval(correct, total)),
            "human_kappa": human_kappa,
            "judge_kappa": judge_kappa,
            "false_positive_rate": matrix["fp"] / (matrix["fp"] + matrix["tn"])
            if matrix["fp"] + matrix["tn"]
            else 0.0,
            "false_negative_rate": matrix["fn"] / (matrix["fn"] + matrix["tp"])
            if matrix["fn"] + matrix["tp"]
            else 0.0,
            "per_rubric": per_rubric,
        },
        "gate": {
            "human_kappa_gate": HUMAN_KAPPA_GATE,
            "judge_kappa_gate": KAPPA_GATE,
            "candidate_gate_met": gates_met,
            "release_gate_met": False,
            "requires_s1_freeze": True,
        },
    }


def samples_from_documents(
    blind: Mapping[str, Any], bindings: Mapping[str, Any]
) -> list[BlindSample]:
    if (
        blind.get("profile") != BLIND_SET_PROFILE
        or bindings.get("profile") != BINDINGS_PROFILE
    ):
        raise ValueError("Blind Set/bindings profile mismatch")
    anonymous, bound = blind.get("samples"), bindings.get("bindings")
    if (
        not isinstance(anonymous, list)
        or not isinstance(bound, list)
        or len(anonymous) != len(bound)
    ):
        raise ValueError("Blind Set and bindings must be equal-length lists")
    bindings_base = {k: v for k, v in bindings.items() if k != "blind_digest"}
    if blind.get("bindings_digest") != digest_value(bindings_base):
        raise ValueError("bindings digest mismatch")
    blind_base = {k: v for k, v in blind.items() if k != "bindings_digest"}
    if bindings.get("blind_digest") != digest_value(blind_base):
        raise ValueError("Blind Set digest mismatch")
    samples: list[BlindSample] = []
    for visible, binding in zip(anonymous, bound, strict=True):
        if (
            not isinstance(visible, dict)
            or not isinstance(binding, dict)
            or visible.get("blind_id") != binding.get("blind_id")
        ):
            raise ValueError("Blind ID binding mismatch")
        blind_id = _require_identity(visible.get("blind_id"), "blind_id")
        case_id = _require_identity(binding.get("case_id"), "case_id")
        output = visible.get("candidate_output")
        if not isinstance(output, str) or not output:
            raise ValueError("candidate output is required")
        output_digest = _require_digest(binding.get("output_digest"), "output_digest")
        if output_digest != digest_text(output):
            raise ValueError("candidate output digest mismatch")
        evidence_hashes = binding.get("evidence_hashes")
        if not isinstance(evidence_hashes, dict) or not evidence_hashes:
            raise ValueError("evidence hashes must be a nonempty object")
        for reference, evidence_digest in evidence_hashes.items():
            if not isinstance(reference, str) or not reference:
                raise ValueError("evidence reference must be nonempty")
            _require_digest(evidence_digest, "evidence hash")
        assertions = binding.get("assertion_results")
        if (
            not isinstance(assertions, dict)
            or not assertions
            or any(
                not isinstance(key, str) or type(value) is not bool
                for key, value in assertions.items()
            )
            or not all(assertions.values())
        ):
            raise ValueError("binding deterministic assertion set is invalid")
        rubrics = visible.get("rubric_ids")
        if (
            not isinstance(rubrics, list)
            or not rubrics
            or len(set(rubrics)) != len(rubrics)
            or not all(
                isinstance(value, str) and value.startswith("judge.semantic.")
                for value in rubrics
            )
        ):
            raise ValueError("binding semantic rubric set is invalid")
        samples.append(
            BlindSample(
                blind_id,
                case_id,
                str(visible["category"]),
                tuple(rubrics),
                output,
                output_digest,
                tuple(sorted(evidence_hashes.items())),
                _require_identity(binding.get("executor_id"), "executor_id"),
                _require_identity(binding.get("executor_version"), "executor_version"),
                tuple(sorted(assertions.items())),
                _require_identity(binding.get("observation_id"), "observation_id"),
                _require_digest(
                    binding.get("observation_digest"), "observation_digest"
                ),
            )
        )
    if len({x.blind_id for x in samples}) != len(samples) or len(
        {x.case_id for x in samples}
    ) != len(samples):
        raise ValueError("duplicate blind or case IDs")
    return samples


def artifact_digests(
    blind: Mapping[str, Any],
    bindings: Mapping[str, Any],
    first: Mapping[str, Any],
    second: Mapping[str, Any],
    adjudication: Mapping[str, Any],
    predictions: Mapping[str, Any],
) -> dict[str, str]:
    return {
        "blind": digest_value(blind),
        "bindings": digest_value(bindings),
        "human_round_1": digest_value(first),
        "human_round_2": digest_value(second),
        "adjudication": digest_value(adjudication),
        "judge_predictions": digest_value(predictions),
    }


def verify_artifacts(
    blind: Mapping[str, Any],
    bindings: Mapping[str, Any],
    first: Mapping[str, Any],
    second: Mapping[str, Any],
    adjudication: Mapping[str, Any],
    predictions: Mapping[str, Any],
    calibration: Mapping[str, Any],
    freeze: Mapping[str, Any] | None = None,
) -> list[str]:
    try:
        samples = samples_from_documents(blind, bindings)
        digests = artifact_digests(
            blind, bindings, first, second, adjudication, predictions
        )
        expected = compute_calibration(
            samples, first, second, adjudication, predictions, artifact_digests=digests
        )
        if calibration != expected:
            raise ValueError(
                "calibration output differs from deterministic recomputation"
            )
        if freeze is None:
            raise ValueError("S1-approved freeze is required")
        expected_freeze_keys = {
            "profile",
            "status",
            "approved_by_role",
            "approval_id",
            "artifact_digests",
            "calibration_digest",
        }
        if set(freeze) != expected_freeze_keys:
            raise ValueError("freeze has missing or unknown fields")
        if (
            freeze.get("profile") != FREEZE_PROFILE
            or freeze.get("status") != "approved"
        ):
            raise ValueError("freeze is not approved")
        if freeze.get("calibration_digest") != digest_value(calibration):
            raise ValueError("calibration freeze digest mismatch")
        if freeze.get("artifact_digests") != digests:
            raise ValueError("freeze input digests mismatch")
        if freeze.get("approved_by_role") != "S1-ARCH":
            raise ValueError("freeze lacks S1 approval")
        _require_identity(freeze.get("approval_id"), "approval_id")
        if not calibration["gate"]["candidate_gate_met"]:
            raise ValueError("candidate metric gate is not met")
    except (KeyError, TypeError, ValueError) as exc:
        return [str(exc)]
    return []


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
    build.add_argument("--seed", type=int, default=0)
    cal = sub.add_parser("calibrate")
    for flag in (
        "blind",
        "bindings",
        "human-round-1",
        "human-round-2",
        "adjudication",
        "judge-predictions",
    ):
        cal.add_argument("--" + flag, type=Path, required=True)
    cal.add_argument("--out", type=Path, required=True)
    verify = sub.add_parser("verify")
    for flag in (
        "blind",
        "bindings",
        "human-round-1",
        "human-round-2",
        "adjudication",
        "judge-predictions",
        "calibration",
        "freeze",
    ):
        verify.add_argument("--" + flag, type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build-blind-set":
        blind, bindings = blind_documents(
            build_blind_samples(
                args.observations,
                evidence_root=args.evidence_root,
                size=args.size,
                seed=args.seed,
            ),
            args.seed,
        )
        _write(args.out_dir / "blind-set.v2.json", blind)
        _write(args.out_dir / "blind-set-bindings.v2.json", bindings)
        return 0
    blind, bindings = _load(args.blind), _load(args.bindings)
    first, second = _load(args.human_round_1), _load(args.human_round_2)
    adjudication, predictions = _load(args.adjudication), _load(args.judge_predictions)
    if args.command == "calibrate":
        samples = samples_from_documents(blind, bindings)
        _write(
            args.out,
            compute_calibration(
                samples,
                first,
                second,
                adjudication,
                predictions,
                artifact_digests=artifact_digests(
                    blind, bindings, first, second, adjudication, predictions
                ),
            ),
        )
        return 0
    errors = verify_artifacts(
        blind,
        bindings,
        first,
        second,
        adjudication,
        predictions,
        _load(args.calibration),
        _load(args.freeze),
    )
    if errors:
        print("\n".join(errors))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
