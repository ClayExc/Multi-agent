from __future__ import annotations

from pathlib import Path

import pytest

from packages.evaluation.canonical import load_json_strict
from packages.evaluation.reporting import CaseStatus
from packages.evaluation.scoring import DeterministicScorer


ROOT = Path(__file__).resolve().parents[3]
REGISTRY = load_json_strict(
    ROOT / "contracts" / "registries" / "evaluation-registry.v1.json"
)


def test_judge_high_score_cannot_override_deterministic_failure() -> None:
    scorer = DeterministicScorer.from_registry(REGISTRY)

    result = scorer.score(
        case_id="offline.functional.knowledge-qa.v1",
        suite="functional",
        category="knowledge_qa_citation",
        assertion_results={
            "assert.task.terminal_status.v1": False,
            "assert.citation.valid.v1": True,
        },
        judge_scores={"judge.semantic.answer_relevance.v1": 1.0},
    )

    assert result.status is CaseStatus.FAILED
    assert result.judge_scores["judge.semantic.answer_relevance.v1"] == 1.0


def test_safety_suite_cannot_use_semantic_judge_rubric() -> None:
    scorer = DeterministicScorer.from_registry(REGISTRY)

    with pytest.raises(ValueError, match="not allowed for safety_fault"):
        scorer.score(
            case_id="offline.safety.tenant-isolation.v1",
            suite="safety_fault",
            category="tenant_isolation",
            assertion_results={
                "assert.tenant.cross_access_zero.v1": True,
                "assert.audit.complete.v1": True,
            },
            judge_scores={"judge.semantic.answer_relevance.v1": 1.0},
        )


def test_missing_optional_judge_does_not_block_deterministic_pass() -> None:
    scorer = DeterministicScorer.from_registry(REGISTRY)

    result = scorer.score(
        case_id="offline.functional.knowledge-qa.v1",
        suite="functional",
        category="knowledge_qa_citation",
        assertion_results={
            "assert.task.terminal_status.v1": True,
            "assert.citation.valid.v1": True,
        },
    )

    assert result.status is CaseStatus.PASSED
    assert result.judge_scores == {}


def test_quarantined_execution_cannot_be_promoted_by_passing_assertions() -> None:
    scorer = DeterministicScorer.from_registry(REGISTRY)

    result = scorer.score(
        case_id="offline.functional.knowledge-qa.v1",
        suite="functional",
        category="knowledge_qa_citation",
        assertion_results={
            "assert.task.terminal_status.v1": True,
            "assert.citation.valid.v1": True,
        },
        execution_status=CaseStatus.QUARANTINED,
    )

    assert result.status is CaseStatus.QUARANTINED
