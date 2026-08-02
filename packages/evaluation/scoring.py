"""Deterministic scoring and the hard boundary around LLM-as-Judge."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .reporting import AssertionOutcome, CaseResult, CaseStatus

OBJECTIVE_GATE_DOMAINS = {
    "approval",
    "context",
    "evaluation",
    "flow",
    "observability",
    "security",
    "tenant",
    "tool",
}


@dataclass(frozen=True, slots=True)
class JudgeBoundary:
    """Registry-backed authorization for semantic-only Judge dimensions."""

    rubrics: Mapping[str, Mapping[str, Any]]

    @classmethod
    def from_registry(cls, registry: Mapping[str, Any]) -> JudgeBoundary:
        rubrics = {
            item["rubric_id"]: item for item in registry.get("judge_rubrics", [])
        }
        return cls(rubrics=rubrics)

    def require_semantic_rubric(self, rubric_id: str, suite: str) -> None:
        rubric = self.rubrics.get(rubric_id)
        if rubric is None:
            raise ValueError(f"unknown Judge rubric: {rubric_id}")
        if rubric.get("gate_domain") != "semantic_only":
            raise ValueError(f"Judge rubric is not semantic_only: {rubric_id}")
        if suite not in rubric.get("allowed_suites", []):
            raise ValueError(f"Judge rubric {rubric_id} is not allowed for {suite}")

    def validate_scores(
        self,
        suite: str,
        scores: Mapping[str, float],
    ) -> dict[str, float]:
        validated: dict[str, float] = {}
        for rubric_id, score in scores.items():
            self.require_semantic_rubric(rubric_id, suite)
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                raise ValueError(f"Judge score must be numeric: {rubric_id}")
            if not 0 <= float(score) <= 1:
                raise ValueError(f"Judge score must be within [0, 1]: {rubric_id}")
            validated[rubric_id] = float(score)
        return validated


@dataclass(frozen=True, slots=True)
class DeterministicScorer:
    """Create a CaseResult with deterministic failure precedence."""

    assertion_domains: Mapping[str, str]
    judge_boundary: JudgeBoundary

    @classmethod
    def from_registry(cls, registry: Mapping[str, Any]) -> DeterministicScorer:
        assertion_domains = {
            item["assertion_id"]: item["gate_domain"]
            for item in registry.get("deterministic_assertions", [])
        }
        return cls(
            assertion_domains=assertion_domains,
            judge_boundary=JudgeBoundary.from_registry(registry),
        )

    def score(
        self,
        *,
        case_id: str,
        suite: str,
        category: str,
        assertion_results: Mapping[str, bool],
        execution_status: CaseStatus = CaseStatus.PASSED,
        judge_scores: Mapping[str, float] | None = None,
    ) -> CaseResult:
        if not assertion_results:
            raise ValueError("at least one deterministic assertion result is required")
        outcomes: list[AssertionOutcome] = []
        for assertion_id, passed in assertion_results.items():
            domain = self.assertion_domains.get(assertion_id)
            if domain is None:
                raise ValueError(f"unknown deterministic assertion: {assertion_id}")
            if domain not in OBJECTIVE_GATE_DOMAINS:
                raise ValueError(
                    f"deterministic assertion has unsupported domain: {assertion_id}"
                )
            if not isinstance(passed, bool):
                raise ValueError(
                    f"deterministic assertion outcome must be bool: {assertion_id}"
                )
            outcomes.append(
                AssertionOutcome(
                    assertion_id=assertion_id,
                    gate_domain=domain,
                    passed=passed,
                )
            )
        validated_judge = self.judge_boundary.validate_scores(
            suite,
            judge_scores or {},
        )
        if execution_status is CaseStatus.PASSED:
            status = (
                CaseStatus.PASSED
                if all(outcome.passed for outcome in outcomes)
                else CaseStatus.FAILED
            )
        else:
            status = execution_status
        return CaseResult(
            case_id=case_id,
            suite=suite,
            category=category,
            status=status,
            assertions=tuple(outcomes),
            judge_scores=validated_judge,
        )
