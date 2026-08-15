"""Deterministic engineering-control primitives."""

from flowpilot_engineering_control.capsule import (
    CapsuleBuilder,
    CapsuleRequest,
    ContextCapsule,
    ExpansionReason,
    ScopeExpansion,
)
from flowpilot_engineering_control.errors import EngineeringControlError, ErrorCode
from flowpilot_engineering_control.evidence import (
    CacheDecision,
    CacheKeyInput,
    CachePolicy,
    EnvironmentFingerprint,
    EvidenceCache,
    EvidenceKind,
)
from flowpilot_engineering_control.report import (
    AttemptReport,
    AttemptReportBuilder,
    ReadObservation,
)
from flowpilot_engineering_control.repository import (
    RepositoryMap,
    RepositoryMapBuilder,
)
from flowpilot_engineering_control.selection import (
    CommandSpec,
    SelectionRequest,
    SelectionSignal,
    TestPlan,
    TestSelector,
    TestTier,
)

__all__ = [
    "CapsuleBuilder",
    "CapsuleRequest",
    "CacheDecision",
    "CacheKeyInput",
    "CachePolicy",
    "CommandSpec",
    "ContextCapsule",
    "EngineeringControlError",
    "ErrorCode",
    "EnvironmentFingerprint",
    "EvidenceCache",
    "EvidenceKind",
    "ExpansionReason",
    "RepositoryMap",
    "RepositoryMapBuilder",
    "ReadObservation",
    "SelectionRequest",
    "SelectionSignal",
    "ScopeExpansion",
    "TestPlan",
    "TestSelector",
    "TestTier",
    "AttemptReport",
    "AttemptReportBuilder",
]
