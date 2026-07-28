"""Deterministic separation of sampled Trace and unsampled security evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from packages.evaluation.safety import require_safe_evidence


class SignalKind(StrEnum):
    TRACE = "trace"
    AUDIT = "audit"
    SECURITY = "security"


DESTINATIONS = {
    SignalKind.TRACE: "otel.trace",
    SignalKind.AUDIT: "audit.append_only",
    SignalKind.SECURITY: "security.append_only",
}


@dataclass(frozen=True, slots=True)
class SignalEnvelope:
    kind: SignalKind
    retained: bool
    tenant_id: str
    trace_id: str
    task_id: str
    correlation_id: str
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class RoutedSignal:
    kind: SignalKind
    destination: str
    retained: bool
    correlation: Mapping[str, str]


class SignalRouter:
    """Validate correlation and keep Audit/Security out of trace sampling."""

    def route(self, signal: SignalEnvelope) -> RoutedSignal:
        missing = [
            name
            for name in ("tenant_id", "trace_id", "task_id", "correlation_id")
            if not getattr(signal, name)
        ]
        if missing:
            raise ValueError(f"signal correlation fields missing: {missing}")
        if signal.kind in {SignalKind.AUDIT, SignalKind.SECURITY} and not signal.retained:
            raise ValueError(f"{signal.kind.value} signals cannot be sampled out")
        require_safe_evidence(signal.payload)
        return RoutedSignal(
            kind=signal.kind,
            destination=DESTINATIONS[signal.kind],
            retained=signal.retained,
            correlation={
                "tenant_id": signal.tenant_id,
                "trace_id": signal.trace_id,
                "task_id": signal.task_id,
                "correlation_id": signal.correlation_id,
            },
        )


def validate_linked_security_pair(
    audit_event: Mapping[str, Any],
    security_event: Mapping[str, Any],
) -> None:
    """Ensure a blocked Audit event and SecurityEvent are linked both ways."""

    if audit_event.get("result") != "blocked":
        raise ValueError("linked security pair requires a blocked Audit event")
    if audit_event.get("security_event_id") != security_event.get("event_id"):
        raise ValueError("Audit security_event_id does not match SecurityEvent")
    if security_event.get("audit_event_id") != audit_event.get("event_id"):
        raise ValueError("SecurityEvent audit_event_id does not match Audit event")
    for field in ("tenant_id", "trace_id", "task_id", "correlation_id"):
        if audit_event.get(field) != security_event.get(field):
            raise ValueError(f"linked signal correlation mismatch: {field}")
    require_safe_evidence(audit_event)
    require_safe_evidence(security_event)
