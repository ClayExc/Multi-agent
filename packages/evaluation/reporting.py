"""Deterministic aggregation and acceptance bundle generation."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from .canonical import sha256_file, stable_json_bytes
from .safety import require_safe_evidence


class CaseStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    QUARANTINED = "quarantined"


@dataclass(frozen=True, slots=True)
class GateCheck:
    """A non-case acceptance gate, such as a required test suite."""

    check_id: str
    passed: bool
    evidence_ref: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "passed": self.passed,
            "evidence_ref": self.evidence_ref,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class AssertionOutcome:
    assertion_id: str
    gate_domain: str
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "assertion_id": self.assertion_id,
            "gate_domain": self.gate_domain,
            "passed": self.passed,
        }


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    suite: str
    category: str
    status: CaseStatus
    assertions: tuple[AssertionOutcome, ...]
    judge_scores: Mapping[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "suite": self.suite,
            "category": self.category,
            "status": self.status.value,
            "assertions": [item.to_dict() for item in self.assertions],
            "judge_scores": dict(sorted(self.judge_scores.items())),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CaseResult:
        assertions: list[AssertionOutcome] = []
        for item in value["assertions"]:
            if not isinstance(item.get("passed"), bool):
                raise ValueError(
                    f"assertion outcome must be bool: {item.get('assertion_id')}"
                )
            assertions.append(
                AssertionOutcome(
                    assertion_id=str(item["assertion_id"]),
                    gate_domain=str(item["gate_domain"]),
                    passed=item["passed"],
                )
            )
        return cls(
            case_id=str(value["case_id"]),
            suite=str(value["suite"]),
            category=str(value["category"]),
            status=CaseStatus(value["status"]),
            assertions=tuple(assertions),
            judge_scores={
                str(key): float(score)
                for key, score in value.get("judge_scores", {}).items()
            },
        )


@dataclass(frozen=True, slots=True)
class AggregateReport:
    denominator_policy: str
    declared_case_count: int
    result_count: int
    passed: int
    failed: int
    skipped: int
    quarantined: int
    failure_count: int
    success_rate: str | None
    gate_result: str
    report_state: str
    gate_checks: tuple[GateCheck, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "denominator_policy": self.denominator_policy,
            "declared_case_count": self.declared_case_count,
            "result_count": self.result_count,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "quarantined": self.quarantined,
            "failure_count": self.failure_count,
            "success_rate": self.success_rate,
            "gate_result": self.gate_result,
            "report_state": self.report_state,
            "gate_checks": [item.to_dict() for item in self.gate_checks],
        }


def aggregate_results(
    declared_case_ids: Iterable[str],
    results: Iterable[CaseResult],
    gate_checks: Iterable[GateCheck] = (),
) -> AggregateReport:
    declared = list(declared_case_ids)
    if len(declared) != len(set(declared)):
        raise ValueError("declared case IDs must be unique")
    result_list = list(results)
    result_ids = [item.case_id for item in result_list]
    if len(result_ids) != len(set(result_ids)):
        raise ValueError("case result IDs must be unique")
    unknown = set(result_ids) - set(declared)
    missing = set(declared) - set(result_ids)
    if unknown:
        raise ValueError(f"results contain undeclared cases: {sorted(unknown)}")
    if missing:
        raise ValueError(f"declared cases are missing results: {sorted(missing)}")

    counts = {status: 0 for status in CaseStatus}
    for result in result_list:
        if result.status == CaseStatus.PASSED and (
            not result.assertions or not all(item.passed for item in result.assertions)
        ):
            raise ValueError(
                f"passed case must have only passing deterministic assertions: "
                f"{result.case_id}"
            )
        counts[result.status] += 1
    declared_count = len(declared)
    check_list = tuple(gate_checks)
    check_ids = [item.check_id for item in check_list]
    if len(check_ids) != len(set(check_ids)):
        raise ValueError("gate check IDs must be unique")
    if any(not item.check_id or not item.evidence_ref for item in check_list):
        raise ValueError("gate checks require IDs and evidence references")
    failed_gate_checks = sum(not item.passed for item in check_list)
    failure_count = (
        counts[CaseStatus.FAILED]
        + counts[CaseStatus.SKIPPED]
        + counts[CaseStatus.QUARANTINED]
        + failed_gate_checks
    )
    if declared_count == 0:
        success_rate = None
        gate_result = "fail"
        report_state = "empty"
    else:
        success_rate = f"{counts[CaseStatus.PASSED] / declared_count:.6f}"
        gate_result = "pass" if failure_count == 0 else "fail"
        report_state = "complete"
    return AggregateReport(
        denominator_policy="all_declared_cases",
        declared_case_count=declared_count,
        result_count=len(result_list),
        passed=counts[CaseStatus.PASSED],
        failed=counts[CaseStatus.FAILED],
        skipped=counts[CaseStatus.SKIPPED],
        quarantined=counts[CaseStatus.QUARANTINED],
        failure_count=failure_count,
        success_rate=success_rate,
        gate_result=gate_result,
        report_state=report_state,
        gate_checks=check_list,
    )


def generate_acceptance_bundle(
    *,
    output_dir: Path,
    metadata: Mapping[str, Any],
    declared_case_ids: Iterable[str],
    results: Iterable[CaseResult],
    extra_artifacts: Mapping[str, Path] | None = None,
    gate_checks: Iterable[GateCheck] = (),
) -> dict[str, Any]:
    """Generate a deterministic offline bundle from explicit inputs.

    ``extra_artifacts`` maps manifest-relative names to already-written files
    (e.g. ``{"eval/verdicts.json": path}``); each entry is hashed into
    ``artifact_hashes`` so the manifest accounts for every bundle artifact.
    """

    declared = list(declared_case_ids)
    result_list = list(results)
    check_list = tuple(gate_checks)
    aggregate = aggregate_results(declared, result_list, check_list)
    artifact_inputs = dict(extra_artifacts or {})
    for check in check_list:
        if check.evidence_ref not in artifact_inputs:
            raise ValueError(
                f"gate check evidence is not an extra artifact: {check.evidence_ref}"
            )
    ordered_by_id = {item.case_id: item for item in result_list}
    ordered_results = [ordered_by_id[case_id] for case_id in declared]
    required_metadata = {
        "run_id",
        "started_at",
        "finished_at",
        "git_commit",
        "dirty_worktree",
        "contract_content_digest",
        "dataset_versions",
        "dataset_hashes",
        "dataset_manifest_hash",
        "fixture_manifest_hash",
        "traceability_hash",
        "evaluation_registry_hash",
    }
    missing = required_metadata - set(metadata)
    if missing:
        raise ValueError(f"acceptance metadata missing fields: {sorted(missing)}")
    _validate_metadata_hashes(metadata)
    require_safe_evidence(metadata)
    require_safe_evidence([item.to_dict() for item in ordered_results])
    require_safe_evidence([item.to_dict() for item in check_list])

    output_dir.mkdir(parents=True, exist_ok=True)
    eval_dir = output_dir / "eval"
    eval_dir.mkdir(parents=True, exist_ok=True)
    result_path = eval_dir / "case-results.jsonl"
    aggregate_path = eval_dir / "aggregate.json"
    report_path = output_dir / "REPORT.md"

    jsonl = b"".join(
        json.dumps(
            item.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
        for item in ordered_results
    )
    result_path.write_bytes(jsonl)
    aggregate_path.write_bytes(stable_json_bytes(aggregate.to_dict()))
    report_path.write_bytes(
        _render_report(metadata["run_id"], aggregate).encode("utf-8")
    )

    artifact_hashes = {
        "REPORT.md": sha256_file(report_path),
        "eval/aggregate.json": sha256_file(aggregate_path),
        "eval/case-results.jsonl": sha256_file(result_path),
    }
    for name, path in sorted(artifact_inputs.items()):
        resolved = Path(path)
        if not resolved.is_file():
            raise ValueError(f"extra artifact missing: {name} at {resolved}")
        artifact_hashes[name] = sha256_file(resolved)
    manifest = {
        **dict(metadata),
        "commands": list(metadata.get("commands", [])),
        "random_seeds": list(metadata.get("random_seeds", [])),
        "runtime_versions": dict(metadata.get("runtime_versions", {})),
        "models": dict(metadata.get("models", {})),
        "prompt_versions": dict(metadata.get("prompt_versions", {})),
        "artifact_hashes": artifact_hashes,
        "gate_result": aggregate.gate_result,
        "report_state": aggregate.report_state,
        "gate_checks": [item.to_dict() for item in check_list],
    }
    require_safe_evidence(manifest)
    (output_dir / "manifest.json").write_bytes(stable_json_bytes(manifest))
    return manifest


def _render_report(run_id: str, aggregate: AggregateReport) -> str:
    rate = (
        aggregate.success_rate
        if aggregate.success_rate is not None
        else "NOT_MEASURED"
    )
    checks = "".join(
        f"  - `{item.check_id}`: `{'PASS' if item.passed else 'FAIL'}` "
        f"(`{item.evidence_ref}`){f' — {item.detail}' if item.detail else ''}\n"
        for item in aggregate.gate_checks
    )
    if not checks:
        checks = "  - none\n"
    return (
        "# FlowPilot Offline Acceptance Report\n\n"
        f"- Run: `{run_id}`\n"
        f"- State: `{aggregate.report_state}`\n"
        f"- Gate: `{aggregate.gate_result}`\n"
        f"- Denominator: `{aggregate.denominator_policy}`\n"
        f"- Declared cases: `{aggregate.declared_case_count}`\n"
        f"- Passed: `{aggregate.passed}`\n"
        f"- Failed: `{aggregate.failed}`\n"
        f"- Skipped (failure): `{aggregate.skipped}`\n"
        f"- Quarantined (failure): `{aggregate.quarantined}`\n"
        f"- Total gate failures: `{aggregate.failure_count}`\n"
        f"- Success rate: `{rate}`\n"
        "- Required checks:\n"
        f"{checks}"
    )


_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _validate_metadata_hashes(metadata: Mapping[str, Any]) -> None:
    scalar_fields = (
        "contract_content_digest",
        "dataset_manifest_hash",
        "fixture_manifest_hash",
        "traceability_hash",
        "evaluation_registry_hash",
    )
    for field in scalar_fields:
        value = metadata.get(field)
        if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
            raise ValueError(f"acceptance metadata {field} must be sha256:<64hex>")
    dataset_hashes = metadata.get("dataset_hashes")
    if not isinstance(dataset_hashes, Mapping):
        raise ValueError("acceptance metadata dataset_hashes must be an object")
    for dataset_id, value in dataset_hashes.items():
        if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
            raise ValueError(
                "acceptance metadata dataset hash must be sha256:<64hex>: "
                f"{dataset_id}"
            )
