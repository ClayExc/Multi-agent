"""Offline evaluation and acceptance primitives for FlowPilot."""

from .evidence import EvidenceRecord, build_evidence_record
from .execution import (
    CaseExecutionResult,
    CaseExecutor,
    CaseExecutorRegistry,
    ExecutionState,
    case_input_digest,
    collect_execution_evidence,
    failed_execution,
    merge_execution_evidence,
    validate_completed_execution,
)
from .incremental_a import (
    EXPECTED_CATEGORY_COUNTS,
    INCREMENTAL_A_DATASET_ID,
    generate_cases,
    load_cases,
    validate_candidates,
)
from .incremental_b import (
    EXPECTED_CATEGORY_COUNTS as EXPECTED_CATEGORY_COUNTS_B,
)
from .incremental_b import (
    INCREMENTAL_B_DATASET_ID,
)
from .incremental_b import (
    generate_cases as generate_cases_b,
)
from .incremental_b import (
    load_cases as load_cases_b,
)
from .incremental_b import (
    validate_candidates as validate_candidates_b,
)
from .reporting import (
    AssertionOutcome,
    CaseResult,
    CaseStatus,
    GateCheck,
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
    "CaseExecutionResult",
    "CaseExecutor",
    "CaseExecutorRegistry",
    "DeterministicScorer",
    "EvidenceRecord",
    "ExecutionState",
    "EXPECTED_CATEGORY_COUNTS",
    "EXPECTED_CATEGORY_COUNTS_B",
    "INCREMENTAL_A_DATASET_ID",
    "INCREMENTAL_B_DATASET_ID",
    "JudgeBoundary",
    "GateCheck",
    "OfflineRepositoryValidator",
    "ValidationFinding",
    "VPN_CANDIDATE_CASE_COUNT",
    "VpnCaseDefinition",
    "VpnCaseExpected",
    "VpnCaseSet",
    "aggregate_results",
    "build_evidence_record",
    "case_input_digest",
    "collect_execution_evidence",
    "failed_execution",
    "generate_acceptance_bundle",
    "generate_cases",
    "generate_cases_b",
    "load_cases",
    "load_cases_b",
    "load_vpn_case_set",
    "merge_execution_evidence",
    "validate_candidates",
    "validate_candidates_b",
    "validate_completed_execution",
]
