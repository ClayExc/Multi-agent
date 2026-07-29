from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .errors import GraphError, GraphErrorCode


@dataclass(frozen=True, slots=True)
class BranchResult:
    branch_id: str
    facts: Mapping[str, Any]
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReducedBranches:
    facts: Mapping[str, Any]
    evidence_refs: tuple[str, ...]
    branch_order: tuple[str, ...]


def reduce_parallel(results: tuple[BranchResult, ...]) -> ReducedBranches:
    branch_ids = [item.branch_id for item in results]
    if len(branch_ids) != len(set(branch_ids)):
        raise GraphError(
            GraphErrorCode.PARALLEL_REDUCER_CONFLICT,
            "parallel branch identifiers must be unique",
        )
    facts: dict[str, Any] = {}
    evidence: list[str] = []
    ordered = sorted(results, key=lambda item: item.branch_id)
    for result in ordered:
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
    )
