from __future__ import annotations

import copy
from pathlib import Path

import pytest

from packages.evaluation.canonical import load_json_strict
from packages.evaluation.safety import UnsafeEvidenceError
from packages.observability.signals import (
    SignalEnvelope,
    SignalKind,
    SignalRouter,
    validate_linked_security_pair,
)

ROOT = Path(__file__).resolve().parents[3]


def _fixtures() -> tuple[dict, dict, dict]:
    routing = load_json_strict(
        ROOT
        / "evals"
        / "fixtures"
        / "observability"
        / "signal-routing.v1.json"
    )
    suite = load_json_strict(
        ROOT / "contracts" / "conformance" / "rc2-cases.json"
    )
    by_id = {item["case_id"]: item["instance"] for item in suite["cases"]}
    return (
        routing,
        by_id[routing["audit_case_id"]],
        by_id[routing["security_event_case_id"]],
    )


def _envelope(
    kind: SignalKind,
    payload: dict,
    *,
    retained: bool,
) -> SignalEnvelope:
    return SignalEnvelope(
        kind=kind,
        retained=retained,
        tenant_id=payload["tenant_id"],
        trace_id=payload["trace_id"],
        task_id=payload["task_id"],
        correlation_id=payload["correlation_id"],
        payload=payload,
    )


def test_trace_audit_and_security_route_to_distinct_destinations() -> None:
    routing, audit, security = _fixtures()
    router = SignalRouter()
    trace = routing["trace"]

    routed_trace = router.route(
        SignalEnvelope(
            kind=SignalKind.TRACE,
            retained=trace["retained"],
            tenant_id=trace["tenant_id"],
            trace_id=trace["trace_id"],
            task_id=trace["task_id"],
            correlation_id=trace["correlation_id"],
            payload=trace["payload"],
        )
    )
    routed_audit = router.route(
        _envelope(SignalKind.AUDIT, audit, retained=True)
    )
    routed_security = router.route(
        _envelope(SignalKind.SECURITY, security, retained=True)
    )

    assert routed_trace.destination == "otel.trace"
    assert routed_trace.retained is False
    assert routed_audit.destination == "audit.append_only"
    assert routed_security.destination == "security.append_only"
    assert len(
        {
            routed_trace.destination,
            routed_audit.destination,
            routed_security.destination,
        }
    ) == 3
    validate_linked_security_pair(audit, security)


@pytest.mark.parametrize("kind", [SignalKind.AUDIT, SignalKind.SECURITY])
def test_unsampled_durable_signal_is_rejected(kind: SignalKind) -> None:
    _, audit, security = _fixtures()
    payload = audit if kind is SignalKind.AUDIT else security

    with pytest.raises(ValueError, match="cannot be sampled out"):
        SignalRouter().route(_envelope(kind, payload, retained=False))


def test_cross_linked_security_pair_is_rejected() -> None:
    _, audit, security = _fixtures()
    tampered = copy.deepcopy(security)
    tampered["audit_event_id"] = "evt_wrong123"

    with pytest.raises(ValueError, match="does not match"):
        validate_linked_security_pair(audit, tampered)


def test_signal_payload_with_secret_is_rejected() -> None:
    routing, _, _ = _fixtures()
    trace = routing["trace"]
    payload = dict(trace["payload"])
    payload["message"] = "Bearer " + "x" * 24

    with pytest.raises(UnsafeEvidenceError):
        SignalRouter().route(
            SignalEnvelope(
                kind=SignalKind.TRACE,
                retained=True,
                tenant_id=trace["tenant_id"],
                trace_id=trace["trace_id"],
                task_id=trace["task_id"],
                correlation_id=trace["correlation_id"],
                payload=payload,
            )
        )
