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
from .vpn_readonly import (
    VPN_CANDIDATE_CASE_COUNT,
    VpnCaseDefinition,
    VpnCaseExpected,
    VpnCaseSet,
    load_vpn_case_set,
)

__all__ = [
    "AssertionOutcome",
    "CaseResult",
    "CaseStatus",
    "DeterministicScorer",
    "EvidenceRecord",
    "JudgeBoundary",
    "OfflineRepositoryValidator",
    "ValidationFinding",
    "VPN_CANDIDATE_CASE_COUNT",
    "VpnCaseDefinition",
    "VpnCaseExpected",
    "VpnCaseSet",
    "aggregate_results",
    "build_evidence_record",
    "generate_acceptance_bundle",
    "load_vpn_case_set",
]
