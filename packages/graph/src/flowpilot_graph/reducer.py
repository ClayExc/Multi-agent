from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .errors import GraphError, GraphErrorCode


@dataclass(frozen=True, slots=True)
class BranchResult:
    branch_id: str
    facts: Mapping[str, Any]
    evidence_refs: tuple[str, ...] = ()
    # M5-1 (FP-FLOW-003): a branch that failed independently carries its own
    # stable failure code instead of aborting the whole parallel fan-out.
    # Failed branches contribute no facts; the reducer surfaces their codes
    # in ``ReducedBranches.failures`` so callers can localize the failure to
    # the exact branch (device standard / inventory / permission template).
    failure_code: str | None = None


@dataclass(frozen=True, slots=True)
class ReducedBranches:
    facts: Mapping[str, Any]
    evidence_refs: tuple[str, ...]
    branch_order: tuple[str, ...]
    # M5-1 (FP-FLOW-003): branch_id -> failure_code for every branch that
    # did not contribute facts.  Empty means every branch succeeded.
    failures: Mapping[str, str] = field(default_factory=dict)


def reduce_parallel(results: tuple[BranchResult, ...]) -> ReducedBranches:
    branch_ids = [item.branch_id for item in results]
    if len(branch_ids) != len(set(branch_ids)):
        raise GraphError(
            GraphErrorCode.PARALLEL_REDUCER_CONFLICT,
            "parallel branch identifiers must be unique",
        )
    facts: dict[str, Any] = {}
    evidence: list[str] = []
    failures: dict[str, str] = {}
    ordered = sorted(results, key=lambda item: item.branch_id)
    for result in ordered:
        if result.failure_code is not None:
            failures[result.branch_id] = result.failure_code
            continue
        for key, value in result.facts.items():
            if key in facts and facts[key] != value:
                raise GraphError(
                    GraphErrorCode.PARALLEL_REDUCER_CONFLICT,
                    "parallel branches produced conflicting facts",
                )
            facts[key] = value
        evidence.extend(result.evidence_refs)
    return ReducedBranches(
        facts=facts,
        evidence_refs=tuple(dict.fromkeys(evidence)),
        branch_order=tuple(item.branch_id for item in ordered),
        failures=failures,
    )
