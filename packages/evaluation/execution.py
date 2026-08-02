"""Fail-closed execution boundary for acceptance evaluation cases.

An evaluation case is data, not proof that the product performed the declared
scenario.  This module makes the product execution result an explicit input to
scoring.  Only a registered executor may produce a completed result, and every
completed result is rebound to the case input, deterministic assertion set,
output digest, and evidence artifacts before it can be considered for PASS.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from .canonical import canonical_digest, sha256_file
from .safety import require_safe_evidence

_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SCENARIO_PREFIX = "scenario:"


class ExecutionState(StrEnum):
    """Whether a product executor actually ran the case."""

    COMPLETED = "completed"
    FAILED = "failed"
    NOT_EXECUTED = "not_executed"


@dataclass(frozen=True, slots=True)
class CaseExecutionResult:
    """Auditable product observation returned by a registered executor."""

    case_id: str
    executor_id: str
    executor_version: str
    state: ExecutionState
    input_digest: str
    output_digest: str | None
    assertion_results: Mapping[str, bool]
    judge_scores: Mapping[str, float]
    evidence_refs: tuple[str, ...]
    failure_code: str | None = None
    failure_detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = {
            "case_id": self.case_id,
            "executor_id": self.executor_id,
            "executor_version": self.executor_version,
            "state": self.state.value,
            "input_digest": self.input_digest,
            "output_digest": self.output_digest,
            "assertion_results": dict(sorted(self.assertion_results.items())),
            "judge_scores": dict(sorted(self.judge_scores.items())),
            "evidence_refs": list(self.evidence_refs),
            "failure_code": self.failure_code,
            "failure_detail": self.failure_detail,
        }
        require_safe_evidence(value)
        return value


class CaseExecutor(Protocol):
    """A trusted adapter that invokes a product scenario and records evidence."""

    executor_id: str
    executor_version: str

    def supports(self, case: Mapping[str, Any]) -> bool:
        """Return whether this executor implements the case's scenario."""

    def execute(
        self,
        case: Mapping[str, Any],
        evidence_root: Path,
    ) -> CaseExecutionResult:
        """Run the product scenario and return observed, not expected, results."""


class CaseExecutorRegistry:
    """Select exactly one executor; ambiguity and absence fail closed."""

    def __init__(self, executors: Sequence[CaseExecutor] = ()) -> None:
        identities = [item.executor_id for item in executors]
        for executor in executors:
            if (
                not isinstance(executor.executor_id, str)
                or not executor.executor_id.strip()
                or executor.executor_id != executor.executor_id.strip()
                or executor.executor_id.lower() == "none"
            ):
                raise ValueError("executor ID must be non-empty and registered")
            if (
                not isinstance(executor.executor_version, str)
                or not executor.executor_version.strip()
                or executor.executor_version != executor.executor_version.strip()
                or executor.executor_version.lower() == "none"
            ):
                raise ValueError("executor version must be non-empty and registered")
        if len(identities) != len(set(identities)):
            raise ValueError("executor IDs must be unique")
        self._executors = tuple(executors)

    def dispatch(
        self,
        case: Mapping[str, Any],
        evidence_root: Path,
    ) -> CaseExecutionResult:
        try:
            matches = [item for item in self._executors if item.supports(case)]
        except Exception as exc:  # noqa: BLE001 - external executor boundary
            return failed_execution(
                case,
                failure_code="EXECUTOR_SELECTION_ERROR",
                failure_detail=f"executor support probe raised {type(exc).__name__}",
            )
        if not matches:
            return failed_execution(
                case,
                failure_code="EXECUTOR_NOT_REGISTERED",
                failure_detail=(
                    f"no registered product executor for scenario {_scenario(case)}"
                ),
            )
        if len(matches) > 1:
            return failed_execution(
                case,
                failure_code="EXECUTOR_AMBIGUOUS",
                failure_detail="multiple registered product executors matched the case",
            )
        executor = matches[0]
        try:
            result = executor.execute(case, evidence_root)
        except Exception as exc:  # noqa: BLE001 - external executor boundary
            return failed_execution(
                case,
                executor_id=executor.executor_id,
                executor_version=executor.executor_version,
                failure_code="EXECUTOR_ERROR",
                failure_detail=f"executor raised {type(exc).__name__}",
            )
        if not isinstance(result, CaseExecutionResult):
            return failed_execution(
                case,
                executor_id=executor.executor_id,
                executor_version=executor.executor_version,
                failure_code="EXECUTION_RESULT_INVALID",
                failure_detail="executor returned an unsupported result type",
            )
        if (
            result.executor_id != executor.executor_id
            or result.executor_version != executor.executor_version
        ):
            return failed_execution(
                case,
                executor_id=executor.executor_id,
                executor_version=executor.executor_version,
                assertion_results=result.assertion_results,
                judge_scores=result.judge_scores,
                failure_code="EXECUTOR_IDENTITY_MISMATCH",
                failure_detail=(
                    "execution result identity does not match selected executor; "
                    "untrusted evidence references discarded"
                ),
            )
        try:
            findings = validate_completed_execution(case, result, evidence_root)
        except Exception as exc:  # noqa: BLE001 - evidence validation boundary
            return failed_execution(
                case,
                executor_id=executor.executor_id,
                executor_version=executor.executor_version,
                failure_code="EXECUTION_RESULT_INVALID",
                failure_detail=f"result validation raised {type(exc).__name__}",
            )
        if findings:
            return failed_execution(
                case,
                executor_id=executor.executor_id,
                executor_version=executor.executor_version,
                assertion_results=result.assertion_results,
                judge_scores=result.judge_scores,
                failure_code="EXECUTION_RESULT_INVALID",
                failure_detail=(
                    "; ".join(findings)
                    + "; untrusted evidence references discarded"
                ),
            )
        return result


def case_input_digest(case: Mapping[str, Any]) -> str:
    """Bind an execution result to the exact canonical case input."""

    return str(canonical_digest(dict(case)))


def failed_execution(
    case: Mapping[str, Any],
    *,
    executor_id: str = "none",
    executor_version: str = "none",
    assertion_results: Mapping[str, bool] | None = None,
    judge_scores: Mapping[str, float] | None = None,
    evidence_refs: tuple[str, ...] = (),
    output_digest: str | None = None,
    failure_code: str,
    failure_detail: str,
) -> CaseExecutionResult:
    """Build a failure that cannot be mistaken for successful execution."""

    declared = _declared_assertion_ids(case)
    supplied = dict(assertion_results or {})
    outcomes = {
        assertion_id: bool(supplied.get(assertion_id, False))
        for assertion_id in declared
    }
    return CaseExecutionResult(
        case_id=str(case.get("case_id", "unknown")),
        executor_id=executor_id,
        executor_version=executor_version,
        state=(
            ExecutionState.FAILED
            if executor_id != "none"
            else ExecutionState.NOT_EXECUTED
        ),
        input_digest=case_input_digest(case),
        output_digest=output_digest,
        assertion_results=outcomes,
        judge_scores=dict(judge_scores or {}),
        evidence_refs=tuple(evidence_refs),
        failure_code=failure_code,
        failure_detail=failure_detail,
    )


def validate_completed_execution(
    case: Mapping[str, Any],
    result: CaseExecutionResult,
    evidence_root: Path,
) -> list[str]:
    """Validate executor identity, bindings, observations, and evidence files."""

    findings: list[str] = []
    if result.case_id != case.get("case_id"):
        findings.append("case ID binding mismatch")
    if not result.executor_id or result.executor_id == "none":
        findings.append("executor identity missing")
    if not result.executor_version or result.executor_version == "none":
        findings.append("executor version missing")
    if result.state is not ExecutionState.COMPLETED:
        findings.append(f"execution state is not completed: {result.state.value}")
    if result.input_digest != case_input_digest(case):
        findings.append("case input digest mismatch")
    if result.output_digest is None or not _SHA256_RE.fullmatch(result.output_digest):
        findings.append("output digest must be a single sha256:<64hex>")

    declared = set(_declared_assertion_ids(case))
    observed = set(result.assertion_results)
    if observed != declared:
        findings.append(
            "assertion result set mismatch: "
            f"missing={sorted(declared - observed)} "
            f"unknown={sorted(observed - declared)}"
        )
    for assertion_id, passed in result.assertion_results.items():
        if not isinstance(passed, bool):
            findings.append(f"assertion outcome must be bool: {assertion_id}")

    if not result.evidence_refs:
        findings.append("completed execution requires evidence references")
    root = evidence_root.resolve()
    resolved_evidence: list[Path] = []
    for reference in result.evidence_refs:
        relative = Path(reference)
        if relative.is_absolute() or ".." in relative.parts:
            findings.append(f"unsafe evidence reference: {reference}")
            continue
        resolved = (root / relative).resolve()
        if root not in resolved.parents:
            findings.append(f"evidence reference escapes root: {reference}")
        elif not resolved.is_file() or resolved.stat().st_size == 0:
            findings.append(f"execution evidence missing or empty: {reference}")
        else:
            resolved_evidence.append(resolved)

    if (
        result.output_digest is not None
        and resolved_evidence
        and sha256_file(resolved_evidence[0]) != result.output_digest
    ):
        findings.append("output digest does not bind the primary evidence artifact")

    for rubric_id, score in result.judge_scores.items():
        if not isinstance(rubric_id, str) or not rubric_id:
            findings.append("Judge rubric ID must be non-empty text")
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not 0 <= float(score) <= 1
        ):
            findings.append(f"Judge score must be numeric within [0, 1]: {rubric_id}")

    if result.failure_code is not None or result.failure_detail is not None:
        findings.append("completed execution cannot carry failure fields")
    try:
        require_safe_evidence(result.to_dict())
    except ValueError as exc:
        findings.append(str(exc))
    return findings


def collect_execution_evidence(
    results: Sequence[CaseExecutionResult],
    evidence_root: Path,
) -> dict[str, Path]:
    """Return a deterministic bundle map for every referenced evidence file.

    Relative references use canonical POSIX syntax below ``evidence_root``.
    Reusing a reference across cases is rejected instead of silently making
    multiple results share an ambiguously attributed artifact.
    """

    artifacts: dict[str, Path] = {}
    owners: dict[str, str] = {}
    resolved_owners: dict[str, str] = {}
    root = evidence_root.resolve()
    for result in sorted(results, key=lambda item: item.case_id):
        if result.state is not ExecutionState.COMPLETED:
            continue
        for reference in result.evidence_refs:
            canonical = _canonical_evidence_reference(reference)
            if canonical in owners:
                raise ValueError(
                    "duplicate execution evidence reference: "
                    f"{canonical} ({owners[canonical]}, {result.case_id})"
                )
            resolved = (root / Path(*canonical.split("/"))).resolve()
            if root not in resolved.parents:
                raise ValueError(f"execution evidence escapes root: {reference}")
            if not resolved.is_file() or resolved.stat().st_size == 0:
                raise ValueError(f"execution evidence missing or empty: {reference}")
            resolved_key = os.path.normcase(str(resolved))
            if resolved_key in resolved_owners:
                raise ValueError(
                    "execution evidence path aliases another reference: "
                    f"{canonical} ({resolved_owners[resolved_key]}, {result.case_id})"
                )
            owners[canonical] = result.case_id
            resolved_owners[resolved_key] = result.case_id
            artifacts[f"execution/{canonical}"] = resolved
    return artifacts


def merge_execution_evidence(
    artifacts: Mapping[str, Path],
    execution_artifacts: Mapping[str, Path],
) -> dict[str, Path]:
    """Merge bundle artifact maps without allowing evidence replacement."""

    conflicts = sorted(set(artifacts) & set(execution_artifacts))
    if conflicts:
        raise ValueError(f"execution evidence artifact conflict: {conflicts}")
    return {**artifacts, **execution_artifacts}


def _declared_assertion_ids(case: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(item["assertion_id"])
        for item in case.get("deterministic_assertions", [])
        if isinstance(item, Mapping) and "assertion_id" in item
    )


def _scenario(case: Mapping[str, Any]) -> str:
    for tag in case.get("tags", []):
        if isinstance(tag, str) and tag.startswith(_SCENARIO_PREFIX):
            return tag[len(_SCENARIO_PREFIX):]
    return "<missing>"


def _canonical_evidence_reference(reference: str) -> str:
    if not isinstance(reference, str) or not reference:
        raise ValueError("execution evidence reference must be non-empty text")
    if "\\" in reference:
        raise ValueError(
            f"execution evidence reference must use POSIX paths: {reference}"
        )
    path = PurePosixPath(reference)
    canonical = path.as_posix()
    if (
        path.is_absolute()
        or canonical != reference
        or ".." in path.parts
        or any(":" in part for part in path.parts)
        or canonical in {".", ""}
    ):
        raise ValueError(f"unsafe execution evidence reference: {reference}")
    return canonical
