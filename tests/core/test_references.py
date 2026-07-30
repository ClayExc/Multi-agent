from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest
from flowpilot_application import (
    REFERENCE_PORT_VERSION,
    ApplicationError,
    ArtifactWriteDisposition,
    ErrorCode,
    RequestObservationService,
    RequestReferenceQuery,
    ResolvedRequestReference,
    ResultArtifactDraft,
    ResultArtifactService,
    ResultCitation,
    load_domain_pack,
)
from flowpilot_application.testing import (
    FakeRequestReferenceResolver,
    FakeResultArtifactPort,
)
from flowpilot_domain import DataClassification, TaskCommand

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
IT_SERVICE_PACK = REPOSITORY_ROOT / "domain-packs" / "it-service"


def test_reference_port_version_is_stable() -> None:
    assert REFERENCE_PORT_VERSION == "flowpilot.reference-ports.p1.v1"


def run[T](coroutine: object) -> T:
    return asyncio.run(coroutine)  # type: ignore[arg-type,return-value]


def _fixture(case_id: str) -> tuple[TaskCommand, ResolvedRequestReference]:
    definition = load_domain_pack(IT_SERVICE_PACK)
    fixture = next(item for item in definition.fixtures if item.case_id == case_id)
    assert fixture.resolved_request is not None
    return fixture.command, fixture.resolved_request


def _resolver_service(
    resolved: ResolvedRequestReference,
) -> tuple[RequestObservationService, FakeRequestReferenceResolver]:
    definition = load_domain_pack(IT_SERVICE_PACK)
    resolver = FakeRequestReferenceResolver(
        {resolved.query.message_ref: resolved}
    )
    return (
        RequestObservationService(
            resolver=resolver,
            required_fields=definition.required_fields,
        ),
        resolver,
    )


def _artifact_draft(
    *,
    content: str = "Use the current VPN credential reset procedure.",
    idempotency_character: str = "d",
) -> ResultArtifactDraft:
    citation = ResultCitation(
        source_ref=(
            "knowledge://tenant-a/vpn-sop/windows-691/3.2"
            "#credential-check"
        ),
        document_version="3.2",
        section="Windows / Error 691 / Credential reset",
        content_hash=(
            "sha256:"
            "cfc91ff3ba6a41fc3d7432f926c03cd6792397b2f15c72cb064dfe8e80314279"
        ),
    )
    unsigned = ResultArtifactDraft(
        tenant_id="tenant-a",
        task_id="task_vpnhome01",
        idempotency_key="sha256:" + idempotency_character * 64,
        media_type="text/markdown",
        content=content,
        citations=(citation,),
        result_digest="sha256:" + "0" * 64,
    )
    return replace(unsigned, result_digest=unsigned.recompute_digest())


def test_request_reference_resolves_redacted_observation_deterministically() -> None:
    command, resolved = _fixture("vpn_windows_691_home")
    service, resolver = _resolver_service(resolved)

    first = run(service.resolve(command))
    replay = run(service.resolve(command))

    assert first == replay
    assert first.intent == "vpn_support"
    assert first.fields == {
        "platform": "windows_11",
        "symptom_code": "691",
        "environment": "home_network",
    }
    assert first.missing_fields == ()
    assert first.observation_ref.startswith("observation://")
    assert not hasattr(first, "message_text")
    assert len(resolver.calls) == 2


def test_request_reference_computes_missing_environment_from_domain_pack() -> None:
    command, resolved = _fixture("vpn_windows_691_missing_environment")
    service, _resolver = _resolver_service(resolved)

    observation = run(service.resolve(command))

    assert observation.fields == {
        "platform": "windows_11",
        "symptom_code": "691",
    }
    assert observation.missing_fields == ("environment",)


def test_unknown_request_reference_has_stable_error() -> None:
    command, resolved = _fixture("vpn_windows_691_home")
    definition = load_domain_pack(IT_SERVICE_PACK)
    service = RequestObservationService(
        resolver=FakeRequestReferenceResolver(),
        required_fields=definition.required_fields,
    )

    with pytest.raises(ApplicationError) as captured:
        run(service.resolve(command))

    assert captured.value.code is ErrorCode.REQUEST_REFERENCE_NOT_FOUND
    assert captured.value.retryable is False
    assert command.payload["initial_message_ref"] not in captured.value.safe_message


def test_cross_tenant_resolved_reference_fails_closed() -> None:
    command, resolved = _fixture("vpn_windows_691_home")
    wrong_query = replace(resolved.query, tenant_id="tenant-other")
    wrong_tenant = replace(
        resolved,
        query=wrong_query,
        observation_digest="sha256:" + "0" * 64,
    )
    wrong_tenant = replace(
        wrong_tenant,
        observation_digest=wrong_tenant.recompute_digest(),
    )
    service, resolver = _resolver_service(wrong_tenant)
    resolver.records[resolved.query.message_ref] = wrong_tenant

    with pytest.raises(ApplicationError) as captured:
        run(service.resolve(command))

    assert captured.value.code is ErrorCode.REQUEST_REFERENCE_BINDING_MISMATCH


def test_tampered_resolved_reference_digest_is_rejected() -> None:
    command, resolved = _fixture("vpn_windows_691_home")
    tampered = replace(
        resolved,
        fields={**resolved.fields, "environment": "office_network"},
    )
    service, resolver = _resolver_service(tampered)
    resolver.records[resolved.query.message_ref] = tampered

    with pytest.raises(ApplicationError) as captured:
        run(service.resolve(command))

    assert captured.value.code is ErrorCode.REQUEST_REFERENCE_TAMPERED


def test_reference_resolver_failure_is_retryable_and_sanitized() -> None:
    command, resolved = _fixture("vpn_windows_691_home")
    service, resolver = _resolver_service(resolved)
    resolver.failure = RuntimeError("message body and credential must not escape")

    with pytest.raises(ApplicationError) as captured:
        run(service.resolve(command))

    assert captured.value.code is ErrorCode.REQUEST_REFERENCE_UNAVAILABLE
    assert captured.value.retryable is True
    assert "credential" not in captured.value.safe_message


def test_reference_classification_above_trusted_ceiling_is_rejected() -> None:
    command, resolved = _fixture("vpn_windows_691_home")
    restricted = replace(
        resolved,
        data_classification=DataClassification.RESTRICTED,
        observation_digest="sha256:" + "0" * 64,
    )
    restricted = replace(
        restricted,
        observation_digest=restricted.recompute_digest(),
    )
    service, resolver = _resolver_service(restricted)
    resolver.records[resolved.query.message_ref] = restricted

    with pytest.raises(ApplicationError) as captured:
        run(service.resolve(command))

    assert captured.value.code is ErrorCode.REQUEST_REFERENCE_BINDING_MISMATCH


def test_result_artifact_replay_returns_one_stable_reference() -> None:
    port = FakeResultArtifactPort()
    service = ResultArtifactService(port)
    draft = _artifact_draft()

    stored = run(service.save(draft))
    replay = run(service.save(draft))

    assert stored.disposition is ArtifactWriteDisposition.STORED
    assert replay.disposition is ArtifactWriteDisposition.DUPLICATE
    assert replay.result_ref == stored.result_ref
    assert len(port.artifacts_by_ref) == 1
    assert not hasattr(stored, "content")


def test_result_artifact_same_key_different_content_conflicts() -> None:
    port = FakeResultArtifactPort()
    service = ResultArtifactService(port)
    first = _artifact_draft()
    conflict = _artifact_draft(content="Different result body.")
    run(service.save(first))

    with pytest.raises(ApplicationError) as captured:
        run(service.save(conflict))

    assert captured.value.code is ErrorCode.RESULT_ARTIFACT_CONFLICT
    assert len(port.artifacts_by_ref) == 1


def test_result_artifact_tamper_and_invalid_receipt_fail_closed() -> None:
    port = FakeResultArtifactPort()
    service = ResultArtifactService(port)
    valid = _artifact_draft()
    tampered = replace(valid, content="Tampered after digest calculation.")

    with pytest.raises(ApplicationError) as digest_error:
        run(service.save(tampered))
    assert digest_error.value.code is ErrorCode.RESULT_ARTIFACT_TAMPERED
    assert port.calls == []

    port.invalid_receipt = True
    with pytest.raises(ApplicationError) as receipt_error:
        run(service.save(valid))
    assert receipt_error.value.code is ErrorCode.RESULT_ARTIFACT_PROTOCOL_ERROR


def test_result_artifact_requires_a_traceable_citation() -> None:
    valid = _artifact_draft()

    with pytest.raises(ValueError, match="citations must not be empty"):
        replace(valid, citations=())


def test_request_query_rejects_unbounded_or_untyped_references() -> None:
    with pytest.raises(ValueError):
        RequestReferenceQuery(
            tenant_id="tenant-a",
            task_id="task_vpnhome01",
            message_id="msg_vpnhome01",
            message_ref="",
            purpose="it_support",
            security_context_ref="security-context://tenant-a/context",
        )
