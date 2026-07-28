"""Offline evaluation and acceptance primitives for FlowPilot."""

from .evidence import EvidenceRecord, build_evidence_record
from .reporting import (
    AssertionOutcome,
    CaseResult,
    CaseStatus,
    aggregate_results,
    generate_acceptance_bundle,
)
from .scoring import DeterministicScorer, JudgeBoundary
from .validation import OfflineRepositoryValidator, ValidationFinding

__all__ = [
    "AssertionOutcome",
    "CaseResult",
    "CaseStatus",
    "DeterministicScorer",
    "EvidenceRecord",
    "JudgeBoundary",
    "OfflineRepositoryValidator",
    "ValidationFinding",
    "aggregate_results",
    "build_evidence_record",
    "generate_acceptance_bundle",
]
