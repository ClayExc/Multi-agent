"""Generate sanitized evidence for the WP-030 platform security black box.

This module intentionally consumes mappings exposed at the Gateway boundary.
It does not interpret authorization or tool outcomes; it only proves that the
deterministic outcome and its observable signals form a closed, correlated,
sanitized timeline.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flowpilot_mcp_gateway import (
    DEBUG_PROJECTION_KEYS,
    STABLE_REASON_CODES,
)
from flowpilot_security import SecurityError, assert_safe_projection

SCHEMA_VERSION = "flowpilot.platform-security-evidence.m1.v1"
_LIFECYCLE_KEYS = frozenset(
    {
        "lifecycle_version",
        "sequence",
        "request_id",
        "trace_id",
        "task_id",
        "correlation_id",
        "stage",
        "outcome",
        "reason_code",
        "component_version",
        "recorded_at",
        "evidence_refs",
    }
)
_PROJECTED_STAGE_KEYS = frozenset(
    {"sequence", "stage", "outcome", "reason_code"}
)
_IDENTIFIER_KEYS = (
    "request_id",
    "trace_id",
    "task_id",
    "correlation_id",
)


class EvidenceValidationError(ValueError):
    """Raised when observable evidence is incomplete or unsafe."""


@dataclass(frozen=True, slots=True)
class TimelineRequirements:
    """Deterministic requirements for one Gateway behavior case."""

    required_stages: tuple[str, ...]
    expected_result_status: str
    trace_sampled: bool
    require_audit: bool = True
    require_security: bool = False

    def __post_init__(self) -> None:
        if not self.required_stages:
            raise ValueError("required_stages cannot be empty")
        if len(self.required_stages) != len(set(self.required_stages)):
            raise ValueError("required_stages must be unique")
        if not self.expected_result_status:
            raise ValueError("expected_result_status cannot be empty")


def _plain_mapping(value: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    mapping = dict(value)
    try:
        assert_safe_projection(mapping, field=field)
    except SecurityError as exc:
        raise EvidenceValidationError(f"{field} is not sanitized") from exc
    return mapping


def _require_exact_keys(
    mapping: Mapping[str, Any],
    expected: frozenset[str],
    *,
    field: str,
) -> None:
    actual = frozenset(mapping)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise EvidenceValidationError(
            f"{field} keys differ: missing={missing} extra={extra}"
        )


def _require_correlated(
    mapping: Mapping[str, Any],
    expected: Mapping[str, Any],
    *,
    field: str,
) -> None:
    for key in _IDENTIFIER_KEYS:
        if mapping.get(key) != expected[key]:
            raise EvidenceValidationError(
                f"{field}.{key} does not match the Gateway projection"
            )


def _require_signal_correlated(
    mapping: Mapping[str, Any],
    expected: Mapping[str, Any],
    *,
    field: str,
) -> None:
    for key in ("trace_id", "task_id", "correlation_id"):
        if mapping.get(key) != expected[key]:
            raise EvidenceValidationError(
                f"{field}.{key} does not match the Gateway projection"
            )
    if mapping.get("causation_id") != expected["request_id"]:
        raise EvidenceValidationError(
            f"{field}.causation_id does not match request_id"
        )


def _validate_lifecycle(
    lifecycle: Sequence[Mapping[str, Any]],
    projection: Mapping[str, Any],
    stage_metrics: Mapping[str, int],
    requirements: TimelineRequirements,
) -> tuple[list[dict[str, Any]], list[str]]:
    if not lifecycle:
        raise EvidenceValidationError("lifecycle cannot be empty")

    events: list[dict[str, Any]] = []
    projected_stages: list[dict[str, Any]] = []
    for index, raw in enumerate(lifecycle, start=1):
        event = _plain_mapping(raw, field=f"lifecycle[{index - 1}]")
        _require_exact_keys(
            event,
            _LIFECYCLE_KEYS,
            field=f"lifecycle[{index - 1}]",
        )
        if event["sequence"] != index:
            raise EvidenceValidationError(
                "lifecycle sequence contains a gap, duplicate, or reordering"
            )
        _require_correlated(
            event,
            projection,
            field=f"lifecycle[{index - 1}]",
        )
        if event["lifecycle_version"] != projection["lifecycle_version"]:
            raise EvidenceValidationError("lifecycle version is inconsistent")
        reason_code = event["reason_code"]
        if reason_code not in STABLE_REASON_CODES:
            raise EvidenceValidationError(
                f"unknown lifecycle reason code: {reason_code}"
            )
        projected_stages.append(
            {
                "sequence": event["sequence"],
                "stage": event["stage"],
                "outcome": event["outcome"],
                "reason_code": reason_code,
            }
        )
        events.append(event)

    if projection["stages"] != projected_stages:
        raise EvidenceValidationError(
            "debug projection stages do not reproduce the lifecycle"
        )

    actual_metrics = dict(
        sorted(
            Counter(
                f"{event['stage']}.{event['outcome']}" for event in events
            ).items()
        )
    )
    if dict(stage_metrics) != actual_metrics:
        raise EvidenceValidationError(
            "stage metrics do not reproduce the lifecycle"
        )

    stage_names = [str(event["stage"]) for event in events]
    previous = -1
    for required in requirements.required_stages:
        try:
            current = stage_names.index(required, previous + 1)
        except ValueError as exc:
            raise EvidenceValidationError(
                f"required lifecycle stage is missing or out of order: {required}"
            ) from exc
        previous = current
    return events, stage_names


def _validate_traces(
    emitted_traces: Sequence[Mapping[str, Any]],
    lifecycle: Sequence[Mapping[str, Any]],
    projection: Mapping[str, Any],
    *,
    trace_sampled: bool,
) -> list[dict[str, Any]]:
    traces = [
        _plain_mapping(item, field=f"emitted_traces[{index}]")
        for index, item in enumerate(emitted_traces)
    ]
    if trace_sampled:
        if traces:
            raise EvidenceValidationError(
                "sampled trace fixture unexpectedly retained trace events"
            )
        return traces
    if traces != list(lifecycle):
        raise EvidenceValidationError(
            "unsampled trace fixture does not match the returned lifecycle"
        )
    for index, trace in enumerate(traces):
        _require_correlated(trace, projection, field=f"emitted_traces[{index}]")
    return traces


def _validate_unsampled_signals(
    audits: Sequence[Mapping[str, Any]],
    security_events: Sequence[Mapping[str, Any]],
    projection: Mapping[str, Any],
    requirements: TimelineRequirements,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    audit_values = [
        _plain_mapping(item, field=f"audits[{index}]")
        for index, item in enumerate(audits)
    ]
    security_values = [
        _plain_mapping(item, field=f"security_events[{index}]")
        for index, item in enumerate(security_events)
    ]
    if requirements.require_audit and not audit_values:
        raise EvidenceValidationError("required unsampled audit is missing")
    if requirements.require_security and not security_values:
        raise EvidenceValidationError(
            "required unsampled security event is missing"
        )
    if not requirements.require_security and security_values:
        raise EvidenceValidationError(
            "unexpected security event exists for a non-security outcome"
        )

    for index, audit in enumerate(audit_values):
        _require_signal_correlated(
            audit,
            projection,
            field=f"audits[{index}]",
        )
    for index, security in enumerate(security_values):
        _require_signal_correlated(
            security,
            projection,
            field=f"security_events[{index}]",
        )

    if requirements.require_security:
        audits_by_id = {
            str(audit.get("event_id")): audit for audit in audit_values
        }
        security_by_id = {
            str(event.get("event_id")): event for event in security_values
        }
        for event_id, security in security_by_id.items():
            audit_id = str(security.get("audit_event_id"))
            linked_audit = audits_by_id.get(audit_id)
            if (
                linked_audit is None
                or linked_audit.get("security_event_id") != event_id
            ):
                raise EvidenceValidationError(
                    "Audit/Security bidirectional link is incomplete"
                )
        for event_id, audit in audits_by_id.items():
            security_id = str(audit.get("security_event_id"))
            linked_security = security_by_id.get(security_id)
            if (
                linked_security is None
                or linked_security.get("audit_event_id") != event_id
            ):
                raise EvidenceValidationError(
                    "Security/Audit bidirectional link is incomplete"
                )
    return audit_values, security_values


def build_timeline_evidence(
    *,
    case_id: str,
    lifecycle: Sequence[Mapping[str, Any]],
    debug_projection: Mapping[str, Any],
    stage_metrics: Mapping[str, int],
    emitted_traces: Sequence[Mapping[str, Any]],
    audits: Sequence[Mapping[str, Any]],
    security_events: Sequence[Mapping[str, Any]],
    requirements: TimelineRequirements,
) -> dict[str, Any]:
    """Validate and project one Gateway timeline into sanitized evidence."""

    if not case_id.startswith("wp030a2."):
        raise EvidenceValidationError("case_id is outside the WP-030-a2 namespace")
    projection = _plain_mapping(debug_projection, field="debug_projection")
    _require_exact_keys(
        projection,
        DEBUG_PROJECTION_KEYS,
        field="debug_projection",
    )
    if projection["result_status"] != requirements.expected_result_status:
        raise EvidenceValidationError("Gateway result status is not expected")
    stages = projection.get("stages")
    if not isinstance(stages, list):
        raise EvidenceValidationError("debug_projection.stages must be a list")
    for index, stage in enumerate(stages):
        if not isinstance(stage, Mapping):
            raise EvidenceValidationError(
                f"debug_projection.stages[{index}] must be an object"
            )
        _require_exact_keys(
            stage,
            _PROJECTED_STAGE_KEYS,
            field=f"debug_projection.stages[{index}]",
        )

    events, stage_names = _validate_lifecycle(
        lifecycle,
        projection,
        stage_metrics,
        requirements,
    )
    traces = _validate_traces(
        emitted_traces,
        events,
        projection,
        trace_sampled=requirements.trace_sampled,
    )
    audit_values, security_values = _validate_unsampled_signals(
        audits,
        security_events,
        projection,
        requirements,
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "case_id": case_id,
        "result_status": projection["result_status"],
        "reason_code": projection["reason_code"],
        "identifiers": {
            key: projection[key] for key in _IDENTIFIER_KEYS
        },
        "execution_id": projection["execution_id"],
        "trace_policy": {
            "sampled": requirements.trace_sampled,
            "emitted_count": len(traces),
        },
        "timeline": {
            "event_count": len(events),
            "stages": stage_names,
            "required_stages": list(requirements.required_stages),
            "stage_metrics": dict(stage_metrics),
        },
        "audit_event_ids": [
            str(item["event_id"]) for item in audit_values
        ],
        "security_event_ids": [
            str(item["event_id"]) for item in security_values
        ],
        "checks": {
            "closed_projection": True,
            "known_reason_codes": True,
            "sequence_complete": True,
            "correlations_match": True,
            "required_stages_present": True,
            "signals_sanitized": True,
            "unsampled_signals_retained": True,
        },
    }


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def write_evidence_bundle(
    output_dir: Path,
    evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Write a deterministic, explicitly non-release evidence bundle."""

    records = sorted(
        (dict(item) for item in evidence),
        key=lambda item: str(item.get("case_id")),
    )
    case_ids = [str(item.get("case_id")) for item in records]
    if not records:
        raise EvidenceValidationError("evidence bundle cannot be empty")
    if len(case_ids) != len(set(case_ids)):
        raise EvidenceValidationError("evidence bundle contains duplicate case IDs")
    for index, item in enumerate(records):
        if item.get("schema_version") != SCHEMA_VERSION:
            raise EvidenceValidationError(
                f"evidence[{index}] has an unknown schema version"
            )
        _plain_mapping(item, field=f"evidence[{index}]")

    artifact = {
        "schema_version": SCHEMA_VERSION,
        "scope": "WP-030-a2 platform security black box",
        "release_gate": False,
        "dataset_completion_claim": False,
        "case_count": len(records),
        "cases": records,
    }
    artifact_bytes = _json_bytes(artifact)
    artifact_hash = "sha256:" + hashlib.sha256(artifact_bytes).hexdigest()
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "scope": artifact["scope"],
        "gate_result": "pass",
        "release_gate": False,
        "dataset_completion_claim": False,
        "artifacts": {
            "platform-security-evidence.json": artifact_hash,
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "platform-security-evidence.json").write_bytes(
        artifact_bytes
    )
    (output_dir / "manifest.json").write_bytes(_json_bytes(manifest))
    return manifest
