from __future__ import annotations

import hashlib
import json
from collections import Counter
from copy import deepcopy
from dataclasses import replace

import pytest
from flowpilot_tool_contracts import ToolResultStatus

from artifacts.acceptance.generators.platform_security import (
    EvidenceValidationError,
    TimelineRequirements,
    build_timeline_evidence,
    write_evidence_bundle,
)

from .blackbox import AUDIENCE, make_blackbox

VERIFIED_WRITE_STAGES = (
    "ingress",
    "identity",
    "registry",
    "policy",
    "approval",
    "ledger",
    "upstream",
    "readback",
    "audit",
    "result",
)


def evidence_inputs(fixture, execution) -> dict:
    return {
        "case_id": "wp030a2.verified-write",
        "lifecycle": [
            event.to_mapping() for event in execution.lifecycle
        ],
        "debug_projection": dict(execution.debug_projection),
        "stage_metrics": dict(execution.stage_metrics),
        "emitted_traces": [
            event.to_mapping() for event in fixture.signals.traces
        ],
        "audits": [
            event.to_mapping() for event in fixture.signals.audits
        ],
        "security_events": [
            event.to_mapping()
            for event in fixture.signals.security_events
        ],
        "requirements": TimelineRequirements(
            required_stages=VERIFIED_WRITE_STAGES,
            expected_result_status="verified",
            trace_sampled=fixture.signals.trace_sampled,
        ),
    }


def recalculate_projection_and_metrics(inputs: dict) -> None:
    inputs["debug_projection"]["stages"] = [
        {
            "sequence": event["sequence"],
            "stage": event["stage"],
            "outcome": event["outcome"],
            "reason_code": event["reason_code"],
        }
        for event in inputs["lifecycle"]
    ]
    inputs["stage_metrics"] = dict(
        sorted(
            Counter(
                f"{event['stage']}.{event['outcome']}"
                for event in inputs["lifecycle"]
            ).items()
        )
    )
    if not inputs["requirements"].trace_sampled:
        inputs["emitted_traces"] = deepcopy(inputs["lifecycle"])


@pytest.mark.asyncio
async def test_trace_sampling_never_samples_audit_or_security() -> None:
    fixture = make_blackbox(trace_sampled=True)
    workload = replace(
        fixture.invocation.workload,
        audience=AUDIENCE + "/forged",
    )
    execution = await fixture.gateway.execute(
        fixture.request_for(workload=workload)
    )

    assert execution.result.status is ToolResultStatus.FAILED_FINAL
    assert fixture.signals.traces == []
    assert len(fixture.signals.audits) == 1
    assert len(fixture.signals.security_events) == 1
    evidence = build_timeline_evidence(
        case_id="wp030a2.sampled-denial",
        lifecycle=[
            event.to_mapping() for event in execution.lifecycle
        ],
        debug_projection=execution.debug_projection,
        stage_metrics=execution.stage_metrics,
        emitted_traces=[],
        audits=[
            event.to_mapping() for event in fixture.signals.audits
        ],
        security_events=[
            event.to_mapping()
            for event in fixture.signals.security_events
        ],
        requirements=TimelineRequirements(
            required_stages=("ingress", "identity", "result", "security"),
            expected_result_status="failed_final",
            trace_sampled=True,
            require_security=True,
        ),
    )

    assert evidence["trace_policy"] == {
        "sampled": True,
        "emitted_count": 0,
    }
    assert evidence["checks"]["unsampled_signals_retained"] is True


@pytest.mark.asyncio
async def test_verified_write_timeline_is_reconstructable() -> None:
    fixture = make_blackbox()
    execution = await fixture.gateway.execute(fixture.invocation)

    evidence = build_timeline_evidence(**evidence_inputs(fixture, execution))

    assert evidence["result_status"] == "verified"
    assert evidence["timeline"]["required_stages"] == list(
        VERIFIED_WRITE_STAGES
    )
    assert evidence["checks"] == {
        "closed_projection": True,
        "known_reason_codes": True,
        "sequence_complete": True,
        "correlations_match": True,
        "required_stages_present": True,
        "signals_sanitized": True,
        "unsampled_signals_retained": True,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        "missing_stage",
        "correlation_mismatch",
        "unknown_reason",
        "projection_escape",
        "secret_leak",
    ],
)
async def test_invalid_timeline_evidence_fails_closed(mutation: str) -> None:
    fixture = make_blackbox()
    execution = await fixture.gateway.execute(fixture.invocation)
    inputs = evidence_inputs(fixture, execution)

    if mutation == "missing_stage":
        inputs["lifecycle"] = [
            item for item in inputs["lifecycle"] if item["stage"] != "registry"
        ]
        for index, event in enumerate(inputs["lifecycle"], start=1):
            event["sequence"] = index
        recalculate_projection_and_metrics(inputs)
    elif mutation == "correlation_mismatch":
        inputs["lifecycle"][1]["correlation_id"] = "corr-forged"
        recalculate_projection_and_metrics(inputs)
    elif mutation == "unknown_reason":
        inputs["lifecycle"][0]["reason_code"] = "FREE_FORM_SUCCESS"
        recalculate_projection_and_metrics(inputs)
    elif mutation == "projection_escape":
        inputs["debug_projection"]["payload"] = {"model_authorized": True}
    else:
        inputs["audits"][0]["password"] = "password=acceptance-secret"

    with pytest.raises(EvidenceValidationError):
        build_timeline_evidence(**inputs)


@pytest.mark.asyncio
async def test_audit_security_link_mismatch_fails_closed() -> None:
    fixture = make_blackbox(trace_sampled=True)
    fixture.policy_source.available = False
    execution = await fixture.gateway.execute(fixture.invocation)
    security = [
        event.to_mapping() for event in fixture.signals.security_events
    ]
    security[0]["audit_event_id"] = "evt_forged_link"

    with pytest.raises(EvidenceValidationError, match="bidirectional"):
        build_timeline_evidence(
            case_id="wp030a2.broken-signal-link",
            lifecycle=[
                event.to_mapping() for event in execution.lifecycle
            ],
            debug_projection=execution.debug_projection,
            stage_metrics=execution.stage_metrics,
            emitted_traces=[],
            audits=[
                event.to_mapping() for event in fixture.signals.audits
            ],
            security_events=security,
            requirements=TimelineRequirements(
                required_stages=("ingress", "result", "security"),
                expected_result_status="failed_final",
                trace_sampled=True,
                require_security=True,
            ),
        )


@pytest.mark.asyncio
async def test_evidence_bundle_is_deterministic_and_non_release(
    tmp_path,
) -> None:
    fixture = make_blackbox()
    execution = await fixture.gateway.execute(fixture.invocation)
    evidence = build_timeline_evidence(**evidence_inputs(fixture, execution))
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_manifest = write_evidence_bundle(first, [evidence])
    second_manifest = write_evidence_bundle(second, [evidence])

    first_bytes = (first / "platform-security-evidence.json").read_bytes()
    second_bytes = (second / "platform-security-evidence.json").read_bytes()
    assert first_bytes == second_bytes
    assert first_manifest == second_manifest
    assert first_manifest["release_gate"] is False
    assert first_manifest["dataset_completion_claim"] is False
    expected_hash = "sha256:" + hashlib.sha256(first_bytes).hexdigest()
    assert first_manifest["artifacts"] == {
        "platform-security-evidence.json": expected_hash
    }
    assert not first_bytes.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in first_bytes
    parsed = json.loads(first_bytes)
    assert parsed["case_count"] == 1
    assert parsed["release_gate"] is False
