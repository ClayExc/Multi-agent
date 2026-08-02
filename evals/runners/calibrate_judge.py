"""FP-EVAL-004 blind-test calibration runner for the semantic Judge.

This runner turns the M6 evaluation corpora into a reproducible blind-test
calibration pipeline:

1. ``build-blind-set``  — stratified, deterministic sampling of >= 30
   EvaluationCase instances; every sample is *anonymized* (case id, hashes,
   expected labels and fixtures are stripped) so the Judge cannot infer the
   ground truth.  The anonymous samples and the reference labels are written
   to separate files so the labels never leak into the review sheet.
2. ``render-review-sheet`` — a human-readable sheet with one anonymous
   sample per row, ready for the two-round blind review required by
   ``docs/acceptance/ACCEPTANCE.md`` §12.3.
3. ``calibrate`` — reads the reviewer/Judge verdicts, computes the
   confusion matrix, agreement, Cohen's kappa and Wilson confidence
   intervals, searches per-rubric score thresholds (Youden's J) and writes
   ``calibration.json`` (metrics + threshold recommendations + confidence
   intervals).
4. ``freeze-hashes`` — freezes the M6 dataset file hashes together with the
   calibrated Judge baseline into ``m6-hash-freeze.v1.json`` (executor
   registry identity included for audit).
5. ``verify`` — rebuilds the blind set from the frozen inputs and re-checks
   that the committed artifacts are still reproducible and hash-consistent.

The Judge itself is intentionally NOT invoked here: this runner is the
offline, deterministic half of the calibration loop.  Reviewer verdicts are
supplied as JSON (``--verdicts``); a deterministic proxy verdict file can be
generated for pipeline dry-runs and is explicitly marked as
``judge_backend: deterministic_proxy`` so a placeholder calibration can never
be mistaken for human-reviewed calibration (aggregation keeps
``uncalibrated_judge_effect = no_effect`` until the kappa gate passes).
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.evaluation.canonical import (  # noqa: E402
    load_json_strict,
    sha256_file,
)

# ---------------------------------------------------------------------------
# Constants (aligned with ACCEPTANCE.md §12.3 and the frozen registry)
# ---------------------------------------------------------------------------

MIN_BLIND_SAMPLE_SIZE = 30  # §12.3: at least 30 samples per Judge/Prompt version
KAPPA_GATE = 0.75  # §12.3: suggested Cohen's kappa gate for aggregation use
RANDOM_SEED = 0  # dataset-card random_seed (deterministic rebuild)
Z_95 = 1.959963984540054  # two-sided 95% normal quantile (Wilson interval)

FREEZE_PROFILE = "flowpilot.m6-hash-freeze.v1"
BLIND_SET_PROFILE = "flowpilot.judge-blind-set.v1"
CALIBRATION_PROFILE = "flowpilot.judge-calibration.v1"

# M6 incremental corpora that feed the 120+36 release quota.
M6_DATASET_DIRS: tuple[str, ...] = (
    "m6-incremental-a",
    "m6-incremental-b",
    "m6-incremental-c",
)

# Semantic dimensions reviewed on the blind set.  They mirror the frozen
# registry rubrics so a calibrated threshold maps 1:1 onto a rubric_id.
DIMENSIONS: tuple[str, ...] = (
    "answer_relevance",
    "summary_faithfulness",
    "citation_support",
    "clarification_quality",
    "ticket_description_quality",
)

RUBRIC_BY_DIMENSION: Mapping[str, str] = {
    "answer_relevance": "judge.semantic.answer_relevance.v1",
    "summary_faithfulness": "judge.semantic.summary_faithfulness.v1",
    "citation_support": "judge.semantic.citation_support.v1",
    "clarification_quality": "judge.semantic.clarification_quality.v1",
    "ticket_description_quality": "judge.semantic.ticket_description_quality.v1",
}

EXECUTOR_IDENTITY = {
    "agent_id": "g2",
    "role": "S4-QUALITY eval-freezer",
    "capabilities": "hash冻结,judge校准,评测运行",
    "registered_by": "human:owner",
    "identity_source": ".flow/agents.json (flow-lite registration registry)",
}

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BlindSample:
    """An anonymized candidate output plus the hidden reference label."""

    blind_id: str
    source_case_id: str
    suite: str
    category: str
    input_messages: tuple[tuple[str, str], ...]  # (role, content)
    candidate_output: str
    reference_label: int  # 1 = expected PASS, 0 = expected FAIL
    dataset_id: str
    dataset_hash: str

    def anonymized(self) -> dict[str, Any]:
        """The Judge-visible projection: no ids, no hashes, no labels."""
        return {
            "blind_id": self.blind_id,
            "suite": self.suite,
            "category": self.category,
            "input_messages": [
                {"role": role, "content": content}
                for role, content in self.input_messages
            ],
            "candidate_output": self.candidate_output,
        }

    def to_dict(self) -> dict[str, Any]:
        value = self.anonymized()
        value["source_case_id"] = self.source_case_id
        value["reference_label"] = self.reference_label
        value["dataset_id"] = self.dataset_id
        value["dataset_hash"] = self.dataset_hash
        return value


@dataclass(frozen=True, slots=True)
class ConfusionMatrix:
    tp: int
    fp: int
    fn: int
    tn: int

    @classmethod
    def from_labels(
        cls,
        judge: Iterable[int],
        reference: Iterable[int],
    ) -> ConfusionMatrix:
        tp = fp = fn = tn = 0
        for j, r in zip(judge, reference, strict=True):
            if r == 1:
                if j == 1:
                    tp += 1
                else:
                    fn += 1
            elif j == 1:
                fp += 1
            else:
                tn += 1
        return cls(tp=tp, fp=fp, fn=fn, tn=tn)

    def to_dict(self) -> dict[str, int]:
        return {"tp": self.tp, "fp": self.fp, "fn": self.fn, "tn": self.tn}


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def wilson_interval(k: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (k/n)."""
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5 / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def cohens_kappa(a: Iterable[int], b: Iterable[int]) -> float | None:
    """Cohen's kappa between two raters; None when not computable."""
    a_list = list(a)
    b_list = list(b)
    if len(a_list) != len(b_list) or not a_list:
        return None
    n = len(a_list)
    agree = sum(1 for x, y in zip(a_list, b_list, strict=True) if x == y)
    p_o = agree / n
    p_a = (sum(a_list) / n) * (sum(b_list) / n)
    p_e = p_a + (1 - sum(a_list) / n) * (1 - sum(b_list) / n)
    if p_e == 1.0:
        return None  # degenerate marginal distributions
    return (p_o - p_e) / (1 - p_e)


def youden_threshold(
    scores: list[float],
    labels: list[int],
) -> tuple[float, float]:
    """Best binary threshold by Youden's J over the unique score grid.

    Returns (threshold, youden_j).  A verdict passes when score >= threshold.
    Falls back to 0.5 when every score is identical.
    """
    if len(scores) != len(labels) or not scores:
        raise ValueError("scores and labels must be non-empty and equal length")
    grid = sorted({round(s, 6) for s in scores})
    if len(grid) == 1:
        return (0.5, 0.0)
    best_t = grid[0]
    best_j = -1.0
    for t in grid:
        tp = sum(
            1 for s, label in zip(scores, labels, strict=True) if s >= t and label == 1
        )
        fp = sum(
            1 for s, label in zip(scores, labels, strict=True) if s >= t and label == 0
        )
        fn = sum(
            1 for s, label in zip(scores, labels, strict=True) if s < t and label == 1
        )
        tn = sum(
            1 for s, label in zip(scores, labels, strict=True) if s < t and label == 0
        )
        tpr = tp / (tp + fn) if tp + fn else 0.0
        tnr = tn / (tn + fp) if tn + fp else 0.0
        j = tpr + tnr - 1
        if j > best_j:
            best_j = j
            best_t = t
    return (best_t, best_j)


# ---------------------------------------------------------------------------
# Blind set construction (deterministic, anonymizing)
# ---------------------------------------------------------------------------


def _stable_shuffle(items: list[Any], seed: int) -> list[Any]:
    rng = random.Random(seed)
    rng.shuffle(items)
    return items


def iter_cases(dataset_root: Path) -> Iterable[tuple[Path, dict[str, Any]]]:
    """Yield (case_path, case) for every EvaluationCase in the M6 corpora."""
    for dataset_dir in M6_DATASET_DIRS:
        cases_dir = dataset_root / dataset_dir / "cases"
        if not cases_dir.is_dir():
            continue
        for case_path in sorted(cases_dir.rglob("*.json")):
            yield case_path, load_json_strict(case_path)


def reference_label(case: Mapping[str, Any]) -> int:
    """Deterministic ground truth from the frozen case: expected terminal
    status COMPLETED is the only positive label."""
    expected = case.get("expected") or {}
    status = expected.get("terminal_status")
    return 1 if status == "COMPLETED" else 0


def candidate_output(case: Mapping[str, Any]) -> str:
    """The candidate output the Judge reviews: the final assistant turn.

    Functional cases carry a message list; safety_fault cases carry a bare
    user instruction string with no assistant output, which is itself the
    candidate (the expected outcome is a blocked write).
    """
    messages = case.get("input") or []
    if isinstance(messages, str):
        return messages
    for message in reversed(messages):
        if isinstance(message, Mapping) and message.get("role") == "assistant":
            return str(message.get("content", ""))
    return ""


def build_blind_samples(
    dataset_root: Path,
    *,
    size: int = MIN_BLIND_SAMPLE_SIZE,
    seed: int = RANDOM_SEED,
) -> list[BlindSample]:
    """Stratified anonymized sampling across suites/categories.

    The sample is deterministic: case ids are sorted, then a seeded
    shuffle picks the requested count, preserving suite/category balance
    as far as the corpus allows.
    """
    by_category: dict[tuple[str, str], list[tuple[Path, dict[str, Any]]]] = {}
    for case_path, case in iter_cases(dataset_root):
        by_category.setdefault(
            (case.get("suite", "?"), case.get("category", "?")),
            [],
        ).append((case_path, case))

    selected: list[tuple[Path, dict[str, Any]]] = []
    categories = sorted(by_category)
    if not categories:
        raise ValueError(f"no EvaluationCase files found under {dataset_root}")
    # Round-robin quota so the total reaches exactly ``size`` without
    # dropping the remainder of the integer division.
    quota, remainder = divmod(size, len(categories))
    for index, category in enumerate(categories):
        take = quota + (1 if index < remainder else 0)
        pool = _stable_shuffle(by_category[category], seed + index)
        selected.extend(pool[:take])
    selected = _stable_shuffle(selected, seed)[:size]
    if len(selected) < size:
        raise ValueError(
            f"only {len(selected)} candidates available; at least {size} "
            f"required for a valid blind set"
        )

    samples: list[BlindSample] = []
    for index, (case_path, case) in enumerate(selected, start=1):
        case_id = str(case.get("case_id", case_path.stem))
        dataset_ref = case.get("dataset_ref") or {}
        samples.append(
            BlindSample(
                blind_id=f"blind.{index:03d}",
                source_case_id=case_id,
                suite=str(case.get("suite", "functional")),
                category=str(case.get("category", "?")),
                input_messages=tuple(
                    (
                        str(message.get("role", "user")),
                        str(message.get("content", "")),
                    )
                    for message in (case.get("input") or [])
                    if isinstance(message, Mapping)
                ),
                candidate_output=candidate_output(case),
                reference_label=reference_label(case),
                dataset_id=str(dataset_ref.get("dataset_id", "?")),
                dataset_hash=str(dataset_ref.get("dataset_hash", "")),
            )
        )
    return samples


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------


def default_verdicts(samples: list[BlindSample]) -> dict[str, dict[str, Any]]:
    """Deterministic proxy verdicts for pipeline dry-runs.

    The proxy labels the candidate output as acceptable when a final
    assistant answer exists.  This is a *placeholder* backend: it is a
    pipeline smoke-test, never human calibration, and the produced
    calibration.json is marked accordingly.
    """
    verdicts: dict[str, dict[str, Any]] = {}
    for sample in samples:
        verdicts[sample.blind_id] = {
            "verdict": 1 if sample.candidate_output.strip() else 0,
            "score": 1.0 if sample.candidate_output.strip() else 0.0,
        }
    return verdicts


def render_review_sheet(
    samples: list[BlindSample],
    *,
    dimension: str = "answer_relevance",
) -> str:
    """Human-readable two-round blind review sheet (labels hidden)."""
    rubric = RUBRIC_BY_DIMENSION.get(dimension, dimension)
    lines = [
        f"# Judge 盲测评审表（{dimension} / {rubric}）",
        "",
        "规则：对每个匿名样本判定 0（不合格）或 1（合格）；",
        "如有把握可给 0.0-1.0 的连续分（用于阈值建议）。",
        "两轮盲审：第一轮独立打分，第二轮复核分歧项。",
        "",
        "| blind_id | suite | category | candidate_output | verdict | score |",
        "|---|---|---|---|---|---|",
    ]
    for sample in samples:
        output = sample.candidate_output.replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {sample.blind_id} | {sample.suite} | {sample.category} "
            f"| {output[:100]} |  |  |"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Calibration computation
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CalibrationResult:
    matrix: ConfusionMatrix
    accuracy: float
    agreement: float
    kappa: float | None
    ci: dict[str, tuple[float, float]]
    thresholds: dict[str, dict[str, float]] = field(default_factory=dict)
    per_dimension: dict[str, dict[str, Any]] = field(default_factory=dict)


def compute_calibration(
    samples: list[BlindSample],
    verdicts: Mapping[str, Mapping[str, Any]],
) -> CalibrationResult:
    """Confusion matrix, metrics, CIs and per-dimension threshold advice."""
    if len(samples) < MIN_BLIND_SAMPLE_SIZE:
        raise ValueError(
            f"blind set has {len(samples)} samples; ACCEPTANCE.md §12.3 "
            f"requires at least {MIN_BLIND_SAMPLE_SIZE}"
        )
    missing = [s.blind_id for s in samples if s.blind_id not in verdicts]
    if missing:
        raise ValueError(
            f"missing verdicts for {len(missing)} samples: {missing[:5]}..."
        )

    judge = [int(verdicts[s.blind_id]["verdict"]) for s in samples]
    reference = [s.reference_label for s in samples]
    matrix = ConfusionMatrix.from_labels(judge, reference)

    n = len(samples)
    correct = matrix.tp + matrix.tn
    accuracy = correct / n
    agreement = correct / n
    kappa = cohens_kappa(judge, reference)

    ci = {
        "accuracy": wilson_interval(correct, n),
        "false_positive_rate": wilson_interval(matrix.fp, matrix.fp + matrix.tn),
        "false_negative_rate": wilson_interval(matrix.fn, matrix.fn + matrix.tp),
    }

    thresholds: dict[str, dict[str, float]] = {}
    per_dimension: dict[str, dict[str, Any]] = {}
    for dimension in DIMENSIONS:
        scores = [
            float(verdicts[s.blind_id].get("score", verdicts[s.blind_id]["verdict"]))
            for s in samples
        ]
        threshold, youden = youden_threshold(scores, reference)
        thresholds[dimension] = {
            "recommended_threshold": round(threshold, 4),
            "youden_j": round(youden, 4),
            "rubric_id": RUBRIC_BY_DIMENSION[dimension],
        }
        dim_judge = [1 if s >= threshold else 0 for s in scores]
        dim_matrix = ConfusionMatrix.from_labels(dim_judge, reference)
        dim_correct = dim_matrix.tp + dim_matrix.tn
        per_dimension[dimension] = {
            "confusion_matrix": dim_matrix.to_dict(),
            "accuracy": round(dim_correct / n, 4),
            "accuracy_ci": [round(v, 4) for v in wilson_interval(dim_correct, n)],
            "kappa": cohens_kappa(dim_judge, reference),
        }

    return CalibrationResult(
        matrix=matrix,
        accuracy=round(accuracy, 4),
        agreement=round(agreement, 4),
        kappa=None if kappa is None else round(kappa, 4),
        ci={key: tuple(round(v, 4) for v in value) for key, value in ci.items()},
        thresholds=thresholds,
        per_dimension=per_dimension,
    )


# ---------------------------------------------------------------------------
# Hash freezing
# ---------------------------------------------------------------------------


def dataset_file_hashes(dataset_root: Path, dataset_dir: str) -> dict[str, str]:
    """sha256 of every committed file under a dataset directory."""
    base = dataset_root / dataset_dir
    hashes: dict[str, str] = {}
    for path in sorted(base.rglob("*")):
        if path.is_file():
            hashes[str(path.relative_to(base)).replace("\\", "/")] = sha256_file(path)
    return hashes


def git_commit_sha(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


def build_freeze_record(
    dataset_root: Path,
    *,
    calibration_path: Path,
    calibration_status: str,
    agent_id: str = EXECUTOR_IDENTITY["agent_id"],
) -> dict[str, Any]:
    """M6 dataset hash baseline + calibrated Judge baseline + executor trail."""
    datasets: dict[str, dict[str, Any]] = {}
    for dataset_dir in M6_DATASET_DIRS:
        base = dataset_root / dataset_dir
        manifest_path = base / "manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = load_json_strict(manifest_path)
        datasets[str(manifest.get("dataset_id", dataset_dir))] = {
            "dataset_dir": dataset_dir,
            "manifest_sha256": sha256_file(manifest_path),
            "dataset_card_sha256": sha256_file(base / "dataset-card.yaml"),
            "case_count": manifest.get("case_count"),
            "files": dataset_file_hashes(dataset_root, dataset_dir),
        }

    calibration_hash = sha256_file(calibration_path)
    calibration = load_json_strict(calibration_path)
    def _repo_relative(path: Path) -> str:
        try:
            return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
        except ValueError:
            return str(path.resolve()).replace("\\", "/")

    freeze = {
        "$schema": FREEZE_PROFILE,
        "freeze_id": "flowpilot-m6-hash-freeze-v1",
        "profile": FREEZE_PROFILE,
        "status": "frozen",
        "frozen_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "executor": dict(EXECUTOR_IDENTITY),
        "git": {
            "commit": git_commit_sha(ROOT),
            "branch": "flow-lite/g2-5",
        },
        "datasets": datasets,
        "judge_baseline": {
            "calibration_ref": _repo_relative(calibration_path),
            "calibration_sha256": calibration_hash,
            "calibration_status": calibration_status,
            "kappa_gate": KAPPA_GATE,
            "kappa_observed": calibration.get("metrics", {}).get("kappa"),
            "thresholds": calibration.get("threshold_recommendations", {}),
        },
    }
    return freeze


def verify_freeze(freeze: Mapping[str, Any], dataset_root: Path) -> list[str]:
    """Recompute hashes against the freeze record; return violations."""
    violations: list[str] = []
    for dataset_id, record in (freeze.get("datasets") or {}).items():
        base = dataset_root / str(record["dataset_dir"])
        for rel_path, expected in (record.get("files") or {}).items():
            actual = sha256_file(base / rel_path)
            if actual != expected:
                violations.append(f"{dataset_id}:{rel_path} hash mismatch")
        manifest_actual = sha256_file(base / "manifest.json")
        if manifest_actual != record.get("manifest_sha256"):
            violations.append(f"{dataset_id}:manifest.json hash mismatch")
    return violations


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",  # ADR-0004 §2: portable bytes, LF only
    )


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def cmd_build_blind_set(args: argparse.Namespace) -> int:
    samples = build_blind_samples(args.dataset_root, size=args.size, seed=args.seed)
    if len(samples) < MIN_BLIND_SAMPLE_SIZE:
        raise SystemExit(
            f"only {len(samples)} candidates available; at least "
            f"{MIN_BLIND_SAMPLE_SIZE} required for a valid blind set"
        )
    labels = {
        "profile": BLIND_SET_PROFILE,
        "seed": args.seed,
        "sample_count": len(samples),
        "note": "labels are kept separate from the anonymous blind set",
        "labels": {s.blind_id: s.to_dict() for s in samples},
    }
    anonymous = {
        "profile": BLIND_SET_PROFILE,
        "seed": args.seed,
        "sample_count": len(samples),
        "dimensions": list(DIMENSIONS),
        "samples": [s.anonymized() for s in samples],
    }
    labels_path = args.out_dir / "blind-set-labels.v1.json"
    blind_path = args.out_dir / "blind-set.v1.json"
    _write_json(labels_path, labels)
    _write_json(blind_path, anonymous)
    _write_json(
        args.out_dir / "verdicts.template.v1.json",
        {s.blind_id: {"verdict": 0, "score": 0.0} for s in samples},
    )
    _write_text(args.out_dir / "review-sheet.v1.md", render_review_sheet(samples))
    print(f"blind set: {len(samples)} anonymized samples -> {blind_path}")
    print(f"labels (internal): {labels_path}")
    print(f"review sheet: {args.out_dir / 'review-sheet.v1.md'}")
    print(f"verdict template: {args.out_dir / 'verdicts.template.v1.json'}")
    return 0


def cmd_render_review_sheet(args: argparse.Namespace) -> int:
    labels = load_json_strict(args.labels)
    samples = [
        BlindSample(
            **{
                **value,
                "input_messages": tuple(
                    tuple(m) for m in value["input_messages"]
                ),
            }
        )
        for value in labels["labels"].values()
    ]
    _write_text(
        args.out_dir / "review-sheet.v1.md",
        render_review_sheet(samples, dimension=args.dimension),
    )
    print(f"review sheet written to {args.out_dir / 'review-sheet.v1.md'}")
    return 0


def _load_samples(args: argparse.Namespace) -> list[BlindSample]:
    labels = load_json_strict(args.labels)
    samples: list[BlindSample] = []
    for value in labels["labels"].values():
        messages = tuple(tuple(m) for m in value["input_messages"])
        samples.append(
            BlindSample(
                blind_id=value["blind_id"],
                source_case_id=value["source_case_id"],
                suite=value["suite"],
                category=value["category"],
                input_messages=messages,
                candidate_output=value["candidate_output"],
                reference_label=int(value["reference_label"]),
                dataset_id=value["dataset_id"],
                dataset_hash=value["dataset_hash"],
            )
        )
    return samples


def cmd_calibrate(args: argparse.Namespace) -> int:
    samples = _load_samples(args)
    if args.proxy:
        verdicts = default_verdicts(samples)
        judge_backend = "deterministic_proxy"
        status = "placeholder_proxy"
        note = (
            "placeholder calibration from the deterministic proxy verdict "
            "backend; human two-round blind review (ACCEPTANCE.md §12.3) is "
            "required before this calibration may gate aggregation"
        )
    else:
        verdicts = load_json_strict(args.verdicts)
        judge_backend = "human_review"
        status = "reviewed"
        note = ""
    result = compute_calibration(samples, verdicts)

    calibration = {
        "$schema": CALIBRATION_PROFILE,
        "calibration_id": "flowpilot-judge-calibration-v1",
        "profile": CALIBRATION_PROFILE,
        "status": status,
        "note": note,
        "judge_backend": judge_backend,
        "produced_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "blind_set": {
            "sample_count": len(samples),
            "min_required": MIN_BLIND_SAMPLE_SIZE,
            "labels_ref": str(
                args.labels.resolve().relative_to(ROOT.resolve())
            ).replace("\\", "/"),
            "seed": RANDOM_SEED,
        },
        "metrics": {
            "confusion_matrix": result.matrix.to_dict(),
            "accuracy": result.accuracy,
            "agreement": result.agreement,
            "kappa": result.kappa,
            "false_positive_rate": round(
                result.matrix.fp / (result.matrix.fp + result.matrix.tn), 4
            )
            if result.matrix.fp + result.matrix.tn
            else 0.0,
            "false_negative_rate": round(
                result.matrix.fn / (result.matrix.fn + result.matrix.tp), 4
            )
            if result.matrix.fn + result.matrix.tp
            else 0.0,
        },
        "confidence_intervals": {
            "accuracy_95": [result.ci["accuracy"][0], result.ci["accuracy"][1]],
            "false_positive_rate_95": [
                result.ci["false_positive_rate"][0],
                result.ci["false_positive_rate"][1],
            ],
            "false_negative_rate_95": [
                result.ci["false_negative_rate"][0],
                result.ci["false_negative_rate"][1],
            ],
        },
        "threshold_recommendations": result.thresholds,
        "per_dimension": result.per_dimension,
        "gate": {
            "kappa_gate": KAPPA_GATE,
            "gate_met": bool(result.kappa is not None and result.kappa >= KAPPA_GATE),
        },
    }
    _write_json(args.out, calibration)
    print(f"calibration written to {args.out}")
    print(f"  accuracy={calibration['metrics']['accuracy']} "
          f"kappa={calibration['metrics']['kappa']} "
          f"gate_met={calibration['gate']['gate_met']}")
    if calibration["gate"]["gate_met"]:
        print("  NOTE: calibration passed the kappa gate; aggregate effects "
              "still require registry approval (contracts/ is S1-owned).")
    return 0


def cmd_freeze_hashes(args: argparse.Namespace) -> int:
    freeze = build_freeze_record(
        args.dataset_root,
        calibration_path=args.calibration,
        calibration_status=args.status,
    )
    _write_json(args.out, freeze)
    print(f"freeze record written to {args.out}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    freeze = load_json_strict(args.freeze)
    violations = verify_freeze(freeze, args.dataset_root)
    if violations:
        print("FREEZE VIOLATIONS:")
        for violation in violations:
            print(f"  - {violation}")
        return 1

    # Blind-set reproducibility: rebuild and compare byte-for-byte.
    labels = load_json_strict(args.labels)
    rebuilt = build_blind_samples(args.dataset_root, size=len(labels["labels"]))
    rebuilt_serialized = json.dumps(
        [s.to_dict() for s in rebuilt],
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    )
    committed_serialized = json.dumps(
        [value for value in labels["labels"].values()],
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    )
    if rebuilt_serialized != committed_serialized:
        print(
            "BLIND SET REPRODUCIBILITY VIOLATION: "
            "rebuild differs from committed labels"
        )
        return 1

    calibration = load_json_strict(args.calibration)
    baseline = freeze.get("judge_baseline") or {}
    if baseline.get("calibration_sha256") != sha256_file(args.calibration):
        print("CALIBRATION HASH MISMATCH: calibration.json changed after freeze")
        return 1
    print("verify OK: dataset hashes consistent, blind set reproducible, "
          f"calibration {calibration.get('status')} matches freeze record")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="FP-EVAL-004 Judge blind-test calibration runner",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build-blind-set", help="sample + anonymize the blind set")
    p_build.add_argument("--dataset-root", type=Path, default=ROOT / "evals/datasets")
    p_build.add_argument("--out-dir", type=Path, default=ROOT / "evals/runners")
    p_build.add_argument("--size", type=int, default=MIN_BLIND_SAMPLE_SIZE)
    p_build.add_argument("--seed", type=int, default=RANDOM_SEED)
    p_build.set_defaults(func=cmd_build_blind_set)

    p_render = sub.add_parser(
        "render-review-sheet", help="render the human review sheet"
    )
    p_render.add_argument("--labels", type=Path, required=True)
    p_render.add_argument("--out-dir", type=Path, default=ROOT / "evals/runners")
    p_render.add_argument("--dimension", type=str, default="answer_relevance")
    p_render.set_defaults(func=cmd_render_review_sheet)

    p_cal = sub.add_parser("calibrate", help="compute calibration.json from verdicts")
    p_cal.add_argument("--labels", type=Path, required=True)
    p_cal.add_argument("--verdicts", type=Path, default=None)
    p_cal.add_argument(
        "--proxy", action="store_true", help="use deterministic proxy verdicts"
    )
    p_cal.add_argument(
        "--out", type=Path, default=ROOT / "evals/runners/calibration.json"
    )
    p_cal.set_defaults(func=cmd_calibrate)

    p_freeze = sub.add_parser(
        "freeze-hashes", help="freeze M6 dataset hashes + judge baseline"
    )
    p_freeze.add_argument("--dataset-root", type=Path, default=ROOT / "evals/datasets")
    p_freeze.add_argument("--calibration", type=Path, required=True)
    p_freeze.add_argument("--status", type=str, default="placeholder_proxy")
    p_freeze.add_argument(
        "--out",
        type=Path,
        default=ROOT / "evals/runners/m6-hash-freeze.v1.json",
    )
    p_freeze.set_defaults(func=cmd_freeze_hashes)

    p_verify = sub.add_parser(
        "verify", help="verify freeze + blind-set reproducibility"
    )
    p_verify.add_argument("--dataset-root", type=Path, default=ROOT / "evals/datasets")
    p_verify.add_argument("--freeze", type=Path, required=True)
    p_verify.add_argument("--labels", type=Path, required=True)
    p_verify.add_argument("--calibration", type=Path, required=True)
    p_verify.set_defaults(func=cmd_verify)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
