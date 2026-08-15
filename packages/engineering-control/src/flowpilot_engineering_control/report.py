"""Deterministic Attempt reporting with explicit actual/estimated separation."""

from __future__ import annotations

import re
from dataclasses import dataclass

from flowpilot_engineering_control.capsule import ContextCapsule
from flowpilot_engineering_control.errors import EngineeringControlError, ErrorCode
from flowpilot_engineering_control.evidence import CacheDecision
from flowpilot_engineering_control.paths import normalize_repo_path
from flowpilot_engineering_control.selection import TestPlan
from flowpilot_engineering_control.serialization import (
    JsonValue,
    canonical_json_bytes,
    sha256_bytes,
)

SCHEMA_VERSION = "flowpilot.attempt-report.v1"
ESTIMATOR_ID = "utf8-bytes-div-4-ceil"
ESTIMATOR_VERSION = "1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ATTEMPT_ID = re.compile(r"^[A-Za-z0-9_.\-/]+$")


@dataclass(frozen=True, slots=True)
class ReadObservation:
    path: str
    sha256: str
    byte_count: int

    def __post_init__(self) -> None:
        if (
            normalize_repo_path(self.path) != self.path
            or not _SHA256.fullmatch(self.sha256)
            or self.byte_count < 0
        ):
            raise EngineeringControlError(ErrorCode.REPORT_INVALID)

    def to_record(self) -> dict[str, JsonValue]:
        return {
            "byte_count": self.byte_count,
            "path": self.path,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class ActualReadSummary:
    file_count: int
    byte_count: int
    observation_sha256: str

    def to_record(self) -> dict[str, JsonValue]:
        return {
            "byte_count": self.byte_count,
            "file_count": self.file_count,
            "observation_sha256": self.observation_sha256,
            "record_available": True,
        }


@dataclass(frozen=True, slots=True)
class AttemptReport:
    attempt_id: str
    capsule_sha256: str
    plan_sha256: str
    actual_read: ActualReadSummary | None
    estimated_input_bytes: int
    estimated_tokens: int
    selection_compute_ms: int
    cache_hits: int
    cache_misses: int
    cache_miss_reasons: tuple[str, ...]
    scope_expansion_count: int
    command_records: tuple[tuple[str, str], ...]

    def payload(self) -> dict[str, JsonValue]:
        return {
            "actual_read": (
                self.actual_read.to_record() if self.actual_read is not None else None
            ),
            "attempt_id": self.attempt_id,
            "cache": {
                "hits": self.cache_hits,
                "miss_reasons": list(self.cache_miss_reasons),
                "misses": self.cache_misses,
            },
            "capsule_sha256": self.capsule_sha256,
            "commands": [
                {"argv_sha256": digest, "command_id": command_id}
                for command_id, digest in self.command_records
            ],
            "estimated_usage": {
                "estimator_id": ESTIMATOR_ID,
                "estimator_version": ESTIMATOR_VERSION,
                "input_bytes": self.estimated_input_bytes,
                "tokens": self.estimated_tokens,
            },
            "plan_sha256": self.plan_sha256,
            "schema_version": SCHEMA_VERSION,
            "scope_expansion_count": self.scope_expansion_count,
            "selection_compute_ms": self.selection_compute_ms,
        }

    @property
    def digest(self) -> str:
        return sha256_bytes(canonical_json_bytes(self.payload()))

    def to_record(self) -> dict[str, JsonValue]:
        return {**self.payload(), "report_sha256": self.digest}

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_record())


class AttemptReportBuilder:
    @staticmethod
    def build(
        *,
        attempt_id: str,
        capsule: ContextCapsule,
        plan: TestPlan,
        actual_reads: tuple[ReadObservation, ...] | None,
        selection_compute_ms: int,
        cache_decisions: tuple[CacheDecision, ...] = (),
    ) -> AttemptReport:
        if selection_compute_ms < 0:
            raise EngineeringControlError(ErrorCode.REPORT_INVALID)
        if not _ATTEMPT_ID.fullmatch(attempt_id):
            raise EngineeringControlError(ErrorCode.REPORT_INVALID)
        actual_summary: ActualReadSummary | None = None
        if actual_reads is not None:
            observations = tuple(sorted(actual_reads, key=lambda item: item.path))
            if len({observation.path for observation in observations}) != len(
                observations
            ):
                raise EngineeringControlError(ErrorCode.REPORT_INVALID)
            observation_bytes = canonical_json_bytes(
                [observation.to_record() for observation in observations]
            )
            actual_summary = ActualReadSummary(
                file_count=len(observations),
                byte_count=sum(item.byte_count for item in observations),
                observation_sha256=sha256_bytes(observation_bytes),
            )
        estimated_bytes = capsule.counts["initial_read_bytes"]
        miss_reasons = tuple(
            sorted(
                {
                    reason.value
                    for decision in cache_decisions
                    if not decision.hit
                    for reason in decision.reasons
                }
            )
        )
        return AttemptReport(
            attempt_id=attempt_id,
            capsule_sha256=capsule.digest,
            plan_sha256=plan.digest,
            actual_read=actual_summary,
            estimated_input_bytes=estimated_bytes,
            estimated_tokens=(estimated_bytes + 3) // 4,
            selection_compute_ms=selection_compute_ms,
            cache_hits=sum(1 for decision in cache_decisions if decision.hit),
            cache_misses=sum(1 for decision in cache_decisions if not decision.hit),
            cache_miss_reasons=miss_reasons,
            scope_expansion_count=len(capsule.expansions),
            command_records=tuple(
                (command.command_id, command.argv_sha256) for command in plan.commands
            ),
        )
