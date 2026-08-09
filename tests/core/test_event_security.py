from __future__ import annotations

import asyncio
import copy
import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from flowpilot_api.app import _sse_frame
from flowpilot_api.stream import InMemoryEventStream
from flowpilot_application import TaskEventEnvelope
from flowpilot_application.task_events import TASK_EVENT_PAYLOAD_RULES
from flowpilot_security import (
    CREDENTIAL_FAMILIES,
    SecurityError,
    SecurityErrorCode,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TASK_EVENT_SCHEMA = json.loads(
    (
        REPOSITORY_ROOT
        / "contracts"
        / "jsonschema"
        / "task-event.v1.schema.json"
    ).read_text(encoding="utf-8")
)
NOW = datetime(2026, 8, 9, 8, 0, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64
TOKEN_FAMILY_CASES: tuple[tuple[str, str], ...] = (
    ("openai_legacy", "sk-" + "Ab9" * 12),
    ("openai_project", "sk-" + "proj-" + "Ab9" * 12),
    ("openai_admin", "sk-" + "admin-" + "Ab9" * 12),
    ("openai_service_account", "sk-" + "svcacct-" + "Ab9" * 12),
    ("anthropic_secret_key", "sk-" + "ant-api03-" + "Ab9" * 12),
    (
        "slack_multisegment",
        "xoxb-" + "2-" + "1" * 12 + "-" + "Ab9" * 8,
    ),
    (
        "slack_xapp_token",
        "xapp-" + "1-2-" + "1" * 12 + "-" + "Ab9" * 8,
    ),
    ("github_classic", "ghp_" + "Ab9" * 12),
    ("github_fine_grained", "github_" + "pat_" + "Ab9_" * 8),
    ("authorization_bearer", "Bearer " + "Ab9" * 8),
    ("authorization_basic", "Basic " + "QWxhZGRpbjpvcGVuIHNlc2FtZQ=="),
    ("aws_access_key", "AKIA" + "A1" * 8),
    ("aws_session_key", "ASIA" + "A1" * 8),
    ("private_key_header", "-----BEGIN " + "PRIVATE KEY-----"),
    (
        "encrypted_private_key_header",
        "-----BEGIN " + "ENCRYPTED PRIVATE KEY-----",
    ),
    (
        "jwt",
        "eyJhbGciOiJIUzI1NiJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
        "Ab9_Ab9_Ab9_Ab9_",
    ),
    ("sensitive_assignment", "token=" + "Ab9" * 8),
    (
        "credential_uri",
        "postgresql://user:" + "credential-value@example.internal/database",
    ),
)
P0_CREDENTIAL_CASES = tuple(
    case
    for case in TOKEN_FAMILY_CASES
    if case[0]
    in {
        "aws_session_key",
        "openai_admin",
        "slack_xapp_token",
        "encrypted_private_key_header",
    }
)
OPAQUE_TOKEN_FAMILY_CASES = tuple(
    case
    for case in TOKEN_FAMILY_CASES
    if case[0]
    in {
        "openai_legacy",
        "openai_project",
        "openai_admin",
        "openai_service_account",
        "anthropic_secret_key",
        "slack_multisegment",
        "slack_xapp_token",
        "github_classic",
        "github_fine_grained",
        "aws_access_key",
        "aws_session_key",
        "jwt",
    }
)
CENTRAL_ASSIGNMENT_CASES: tuple[tuple[str, str], ...] = (
    ("authorization-assignment", "authorization=Basic-placeholder"),
    ("credential-assignment", "credential=placeholder"),
    ("password-assignment", "password=placeholder"),
    ("api-key-assignment", "api_key:placeholder"),
    ("secret-assignment", "secret=placeholder"),
)
PROJECTION_ASSIGNMENT_CASES: tuple[tuple[str, str], ...] = (
    ("cookie-assignment", "cookie=sessionid-placeholder"),
    ("session-ref-assignment", "session_ref=provider-session"),
    ("provider-session-assignment", "provider_session=provider-session"),
    ("reasoning-assignment", "reasoning=hidden-content"),
    ("chain-of-thought-assignment", "chain_of_thought=hidden-content"),
)

EVENT_CASES: tuple[tuple[str, str, dict[str, Any]], ...] = (
    (
        "task.created.v1",
        "worker",
        {"status": "RECEIVED", "task_ref": "task://task_12345678"},
    ),
    (
        "task.status.changed.v1",
        "worker",
        {"from": "RUNNING", "to": "COMPLETED", "reason_code": None},
    ),
    (
        "task.input.required.v1",
        "worker",
        {
            "request_id": "request-123",
            "prompt_ref": "prompt://request-123",
            "missing_fields": ["environment"],
        },
    ),
    (
        "task.approval.required.v1",
        "worker",
        {
            "approval_id": "apr_12345678",
            "action_digest": DIGEST,
            "display_ref": "display://approval/12345678",
            "expires_at": "2026-08-09T09:00:00Z",
        },
    ),
    (
        "task.approval.decided.v1",
        "approval_service",
        {
            "approval_id": "apr_12345678",
            "action_digest": DIGEST,
            "decision": "approved",
        },
    ),
    (
        "task.tool_execution.updated.v1",
        "mcp_gateway",
        {"execution_id": "tex_12345678", "status": "verified"},
    ),
    (
        "task.completed.v1",
        "worker",
        {"result_ref": "result://task/12345678"},
    ),
    (
        "task.failed.v1",
        "worker",
        {
            "error_code": "PROVIDER_TIMEOUT",
            "retryable": True,
            "detail_ref": None,
        },
    ),
    (
        "task.escalated.v1",
        "worker",
        {"reason_code": "HUMAN_REQUIRED", "handoff_ref": None},
    ),
)


def _envelope(
    event_type: str = "task.completed.v1",
    producer: str = "worker",
    payload: Mapping[str, Any] | None = None,
    *,
    tenant_id: str = "tenant-a",
    producer_principal_ref: str | None = None,
    correlation_id: str = "correlation-security-0001",
) -> TaskEventEnvelope:
    return TaskEventEnvelope(
        event_id="evt_security01",
        event_type=event_type,
        tenant_id=tenant_id,
        task_id="task_12345678",
        thread_id="thread_12345678",
        task_version=1,
        sequence=1,
        trace_id="trace-security-0001",
        run_id=None if producer == "approval_service" else "run_12345678",
        producer=producer,
        producer_principal_ref=(
            producer_principal_ref
            if producer_principal_ref is not None
            else f"workload://{producer}/test"
        ),
        correlation_id=correlation_id,
        causation_id=None,
        data_classification="internal",
        payload=(
            payload
            if payload is not None
            else {"result_ref": "result://task/12345678"}
        ),
        occurred_at=NOW,
    )


def _schema_branches() -> dict[str, tuple[frozenset[str], str]]:
    result: dict[str, tuple[frozenset[str], str]] = {}
    for branch in TASK_EVENT_SCHEMA["oneOf"]:
        properties = branch["properties"]
        event_type = properties["event_type"]["const"]
        producer_schema = properties["producer"]
        producers = frozenset(
            {producer_schema["const"]}
            if "const" in producer_schema
            else producer_schema["enum"]
        )
        payload_ref = properties["payload"]["$ref"].rsplit("/", 1)[-1]
        result[event_type] = (producers, payload_ref)
    return result


def _wrong_producer(allowed: frozenset[str]) -> str:
    return next(
        producer
        for producer in ("worker", "approval_service", "mcp_gateway", "reconciler")
        if producer not in allowed
    )


def test_application_rules_match_repository_schema_exactly() -> None:
    branches = _schema_branches()

    assert set(TASK_EVENT_PAYLOAD_RULES) == set(branches)
    for event_type, rule in TASK_EVENT_PAYLOAD_RULES.items():
        producers, payload_ref = branches[event_type]
        payload_schema = TASK_EVENT_SCHEMA["$defs"][payload_ref]
        assert rule.producers == producers
        assert rule.required == frozenset(payload_schema["required"])
        assert set(rule.fields) == set(payload_schema["properties"])
        assert payload_schema["additionalProperties"] is False


@pytest.mark.parametrize(
    ("event_type", "producer", "payload"),
    EVENT_CASES,
    ids=[case[0] for case in EVENT_CASES],
)
def test_each_task_event_type_matches_the_existing_schema(
    event_type: str,
    producer: str,
    payload: dict[str, Any],
) -> None:
    envelope = _envelope(event_type, producer, payload)

    jsonschema.validate(
        envelope.to_mapping(),
        TASK_EVENT_SCHEMA,
        format_checker=jsonschema.FormatChecker(),
    )


@pytest.mark.parametrize(
    ("event_type", "producer", "payload"),
    EVENT_CASES,
    ids=[case[0] for case in EVENT_CASES],
)
def test_each_task_event_rejects_additional_missing_and_wrong_producer(
    event_type: str,
    producer: str,
    payload: dict[str, Any],
) -> None:
    valid_wire = _envelope(event_type, producer, payload).to_mapping()
    additional = copy.deepcopy(payload)
    additional["unexpected_ref"] = "unexpected://value"
    additional_wire = copy.deepcopy(valid_wire)
    additional_wire["payload"] = additional
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(additional_wire, TASK_EVENT_SCHEMA)
    with pytest.raises(ValueError, match="additional task-event.v1"):
        _envelope(event_type, producer, additional)

    missing = copy.deepcopy(payload)
    missing.pop(next(iter(TASK_EVENT_PAYLOAD_RULES[event_type].required)))
    missing_wire = copy.deepcopy(valid_wire)
    missing_wire["payload"] = missing
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(missing_wire, TASK_EVENT_SCHEMA)
    with pytest.raises(ValueError, match="missing required task-event.v1"):
        _envelope(event_type, producer, missing)

    wrong_producer = _wrong_producer(
        TASK_EVENT_PAYLOAD_RULES[event_type].producers
    )
    producer_wire = copy.deepcopy(valid_wire)
    producer_wire["producer"] = wrong_producer
    producer_wire["run_id"] = (
        None if wrong_producer == "approval_service" else "run_12345678"
    )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(producer_wire, TASK_EVENT_SCHEMA)
    with pytest.raises(ValueError, match="producer is not allowed"):
        _envelope(event_type, wrong_producer, payload)


@pytest.mark.parametrize(
    ("event_type", "producer", "payload"),
    (
        ("task.created.v1", "worker", {"status": "RUNNING", "task_ref": "x"}),
        (
            "task.status.changed.v1",
            "worker",
            {"from": "UNKNOWN", "to": "COMPLETED", "reason_code": None},
        ),
        (
            "task.input.required.v1",
            "worker",
            {"request_id": "r", "prompt_ref": "p", "missing_fields": []},
        ),
        (
            "task.approval.required.v1",
            "worker",
            {
                "approval_id": "bad",
                "action_digest": DIGEST,
                "display_ref": "display://x",
                "expires_at": "not-a-date-time",
            },
        ),
        (
            "task.approval.decided.v1",
            "approval_service",
            {
                "approval_id": "apr_12345678",
                "action_digest": "sha256:BAD",
                "decision": "allow",
            },
        ),
        (
            "task.tool_execution.updated.v1",
            "mcp_gateway",
            {"execution_id": "bad", "status": "success"},
        ),
        ("task.completed.v1", "worker", {"result_ref": ""}),
        (
            "task.failed.v1",
            "worker",
            {"error_code": "E1", "retryable": "yes"},
        ),
        ("task.escalated.v1", "worker", {"reason_code": ""}),
    ),
    ids=[case[0] for case in EVENT_CASES],
)
def test_each_task_event_rejects_invalid_types_or_formats(
    event_type: str,
    producer: str,
    payload: dict[str, Any],
) -> None:
    valid_payload = next(
        candidate_payload
        for candidate_type, _candidate_producer, candidate_payload in EVENT_CASES
        if candidate_type == event_type
    )
    invalid_wire = _envelope(event_type, producer, valid_payload).to_mapping()
    invalid_wire["payload"] = payload
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            invalid_wire,
            TASK_EVENT_SCHEMA,
            format_checker=jsonschema.FormatChecker(),
        )
    with pytest.raises(ValueError):
        _envelope(event_type, producer, payload)


@pytest.mark.parametrize(
    "payload",
    (
        {"result_ref": "result://safe", "session_ref": "provider://private"},
        {"result_ref": "result://safe", "reasoning": "hidden reasoning"},
    ),
    ids=("session-ref", "reasoning"),
)
def test_envelope_construction_recursively_rejects_sensitive_keys(
    payload: dict[str, Any],
) -> None:
    with pytest.raises(ValueError, match="sensitive key"):
        _envelope(payload=payload)


def test_envelope_construction_uses_central_error_for_credential_keys() -> None:
    payload = {
        "result_ref": "result://safe",
        "metadata": [
            {"provider_session": {"credential": {"access_token": "secret"}}}
        ],
    }

    with pytest.raises(SecurityError) as captured:
        _envelope(payload=payload)

    assert captured.value.code is SecurityErrorCode.UNSAFE_PROJECTION


@pytest.mark.parametrize(
    ("event_type", "producer", "payload"),
    (
        (
            "task.created.v1",
            "worker",
            {"status": "RECEIVED", "task_ref": "task://task_12345678"},
        ),
        (
            "task.input.required.v1",
            "worker",
            {
                "request_id": "request-123",
                "prompt_ref": "prompt://request-123",
                "missing_fields": ["environment"],
            },
        ),
        (
            "task.approval.required.v1",
            "worker",
            {
                "approval_id": "apr_12345678",
                "action_digest": DIGEST,
                "display_ref": "display://approval/12345678",
                "expires_at": "2026-08-09T09:00:00Z",
            },
        ),
        (
            "task.approval.required.v1",
            "worker",
            {
                "approval_id": "apr_12345678",
                "action_digest": DIGEST,
                "display_ref": "proposal://approval/12345678",
                "expires_at": "2026-08-09T09:00:00Z",
            },
        ),
        (
            "task.completed.v1",
            "worker",
            {"result_ref": "result://task/12345678"},
        ),
        (
            "task.completed.v1",
            "worker",
            {"result_ref": "runtime-result://task/12345678"},
        ),
        (
            "task.failed.v1",
            "worker",
            {
                "error_code": "PROVIDER_TIMEOUT",
                "retryable": True,
                "detail_ref": "detail://task/12345678",
            },
        ),
        (
            "task.escalated.v1",
            "worker",
            {
                "reason_code": "HUMAN_REQUIRED",
                "handoff_ref": "handoff://task/12345678",
            },
        ),
    ),
    ids=(
        "task-ref",
        "prompt-ref",
        "display-ref",
        "proposal-ref",
        "result-ref",
        "runtime-result-ref",
        "detail-ref",
        "handoff-ref",
    ),
)
def test_task_event_reference_fields_accept_opaque_uris(
    event_type: str,
    producer: str,
    payload: dict[str, Any],
) -> None:
    envelope = _envelope(event_type, producer, payload)

    jsonschema.validate(
        envelope.to_mapping(),
        TASK_EVENT_SCHEMA,
        format_checker=jsonschema.FormatChecker(),
    )


@pytest.mark.parametrize(
    ("event_type", "producer", "payload"),
    (
        (
            "task.created.v1",
            "worker",
            {"status": "RECEIVED", "task_ref": "plain task reference"},
        ),
        (
            "task.input.required.v1",
            "worker",
            {
                "request_id": "request-123",
                "prompt_ref": "plain prompt reference",
                "missing_fields": ["environment"],
            },
        ),
        (
            "task.approval.required.v1",
            "worker",
            {
                "approval_id": "apr_12345678",
                "action_digest": DIGEST,
                "display_ref": "plain display reference",
                "expires_at": "2026-08-09T09:00:00Z",
            },
        ),
        (
            "task.completed.v1",
            "worker",
            {"result_ref": "plain result reference"},
        ),
        (
            "task.failed.v1",
            "worker",
            {
                "error_code": "PROVIDER_TIMEOUT",
                "retryable": True,
                "detail_ref": "plain detail reference",
            },
        ),
        (
            "task.escalated.v1",
            "worker",
            {
                "reason_code": "HUMAN_REQUIRED",
                "handoff_ref": "plain handoff reference",
            },
        ),
    ),
    ids=(
        "task-ref",
        "prompt-ref",
        "display-ref",
        "result-ref",
        "detail-ref",
        "handoff-ref",
    ),
)
def test_every_payload_reference_field_rejects_plaintext(
    event_type: str,
    producer: str,
    payload: dict[str, Any],
) -> None:
    with pytest.raises(ValueError, match="opaque URI reference"):
        _envelope(event_type, producer, payload)


@pytest.mark.parametrize(
    "reference",
    (
        "result://",
        "result://user@example/path",
        "result://safe?token=value",
        "result://safe#fragment",
        "result://safe\nnext-header",
        "result://safe path",
    ),
    ids=("empty", "userinfo", "query", "fragment", "control", "space"),
)
def test_opaque_reference_rejects_unsafe_uri_components(reference: str) -> None:
    with pytest.raises(ValueError):
        _envelope(payload={"result_ref": reference})


def test_optional_empty_refs_remain_contract_compatible() -> None:
    failed = _envelope(
        "task.failed.v1",
        "worker",
        {"error_code": "FAILED", "retryable": False, "detail_ref": ""},
    )
    escalated = _envelope(
        "task.escalated.v1",
        "worker",
        {"reason_code": "HUMAN_REQUIRED", "handoff_ref": ""},
    )

    jsonschema.validate(failed.to_mapping(), TASK_EVENT_SCHEMA)
    jsonschema.validate(escalated.to_mapping(), TASK_EVENT_SCHEMA)


def test_producer_principal_ref_must_be_an_opaque_uri() -> None:
    with pytest.raises(ValueError, match="opaque URI reference"):
        _envelope(producer_principal_ref="worker principal in plaintext")


@pytest.mark.parametrize(
    ("case_id", "sensitive_value"),
    TOKEN_FAMILY_CASES + CENTRAL_ASSIGNMENT_CASES,
    ids=[case_id for case_id, _value in TOKEN_FAMILY_CASES]
    + [case_id for case_id, _value in CENTRAL_ASSIGNMENT_CASES],
)
def test_envelope_top_level_strings_reject_sensitive_values(
    case_id: str,
    sensitive_value: str,
) -> None:
    assert case_id
    with pytest.raises(SecurityError) as captured:
        _envelope(correlation_id=sensitive_value)
    assert captured.value.code is SecurityErrorCode.UNSAFE_PROJECTION


@pytest.mark.parametrize(
    ("case_id", "sensitive_value"),
    PROJECTION_ASSIGNMENT_CASES,
    ids=[case_id for case_id, _value in PROJECTION_ASSIGNMENT_CASES],
)
def test_noncredential_projection_values_remain_forbidden(
    case_id: str,
    sensitive_value: str,
) -> None:
    assert case_id
    with pytest.raises(ValueError, match="sensitive value"):
        _envelope(correlation_id=sensitive_value)


def test_central_registry_contains_required_consumer_families() -> None:
    family_ids = {family.family_id for family in CREDENTIAL_FAMILIES}

    assert len(family_ids) == len(CREDENTIAL_FAMILIES)
    assert {
        "aws_access_key",
        "openai_admin",
        "slack_xapp_token",
        "private_key_header",
    } <= family_ids


@pytest.mark.parametrize("prefix", ("xoxb", "xoxa", "xoxp", "xoxr", "xoxs"))
def test_slack_token_family_covers_registered_prefixes(prefix: str) -> None:
    token = prefix + "-2-" + "1" * 12 + "-" + "Ab9" * 8

    with pytest.raises(SecurityError):
        _envelope(correlation_id=token)


@pytest.mark.parametrize("prefix", ("ghp_", "gho_", "ghu_", "ghs_", "ghr_"))
def test_github_classic_family_covers_registered_prefixes(prefix: str) -> None:
    token = prefix + "Ab9" * 12

    with pytest.raises(SecurityError):
        _envelope(correlation_id=token)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("event_id", "evt_" + "ASIA" + "A1" * 8),
        ("tenant_id", "ASIA" + "A1" * 8),
        ("task_id", "task_" + "ASIA" + "A1" * 8),
        ("thread_id", "thread_" + "ASIA" + "A1" * 8),
        ("trace_id", "ASIA" + "A1" * 8),
        ("run_id", "run_" + "ASIA" + "A1" * 8),
        (
            "producer_principal_ref",
            "workload://worker/" + "ASIA" + "A1" * 8,
        ),
        ("correlation_id", "ASIA" + "A1" * 8),
        ("causation_id", "ASIA" + "A1" * 8),
    ),
    ids=(
        "event-id",
        "tenant-id",
        "task-id",
        "thread-id",
        "trace-id",
        "run-id",
        "producer-principal-ref",
        "correlation-id",
        "causation-id",
    ),
)
def test_every_variable_envelope_string_scans_token_families(
    field: str,
    value: str,
) -> None:
    envelope = _envelope()
    object.__setattr__(envelope, field, value)

    with pytest.raises(SecurityError) as captured:
        envelope.assert_valid()
    assert captured.value.code is SecurityErrorCode.UNSAFE_PROJECTION


def test_hyphenated_business_identifiers_remain_valid() -> None:
    envelope = _envelope(
        tenant_id="tenant-west-business-12345678",
        producer_principal_ref="workload://worker/business-release-2026",
        correlation_id="correlation-business-release-2026",
    )
    object.__setattr__(envelope, "event_id", "evt_business-release-12345678")
    object.__setattr__(envelope, "task_id", "task_business-release-12345678")
    object.__setattr__(
        envelope,
        "thread_id",
        "thread_business-release-12345678",
    )
    object.__setattr__(envelope, "trace_id", "trace-business-release-2026")
    object.__setattr__(envelope, "run_id", "run_business-release-12345678")
    object.__setattr__(
        envelope,
        "causation_id",
        "cause-business-release-2026",
    )

    envelope.assert_valid()


@pytest.mark.parametrize(
    ("family", "sensitive_value"),
    TOKEN_FAMILY_CASES,
    ids=[family for family, _value in TOKEN_FAMILY_CASES],
)
def test_payload_nested_sequence_rejects_sensitive_string_value(
    family: str,
    sensitive_value: str,
) -> None:
    assert family
    with pytest.raises(SecurityError):
        _envelope(
            "task.input.required.v1",
            "worker",
            {
                "request_id": "request-123",
                "prompt_ref": "prompt://request-123",
                "missing_fields": [sensitive_value],
            },
        )


@pytest.mark.parametrize(
    ("family", "sensitive_value"),
    OPAQUE_TOKEN_FAMILY_CASES,
    ids=[family for family, _value in OPAQUE_TOKEN_FAMILY_CASES],
)
def test_opaque_reference_values_reject_token_families(
    family: str,
    sensitive_value: str,
) -> None:
    assert family
    with pytest.raises(SecurityError):
        _envelope(
            payload={"result_ref": "result://artifact/" + sensitive_value}
        )


def test_payload_nested_mapping_rejects_sensitive_string_before_schema_use() -> None:
    with pytest.raises(SecurityError):
        _envelope(
            payload={
                "result_ref": "result://safe",
                "metadata": [{"note": "password=customer-secret"}],
            }
        )


def test_cross_tenant_emit_writes_neither_subscriber_nor_replay() -> None:
    async def scenario() -> None:
        stream = InMemoryEventStream()
        subscriber = stream.subscribe("tenant-a")
        foreign = _envelope(tenant_id="tenant-b")

        with pytest.raises(ValueError, match="tenant does not match"):
            await stream.emit("tenant-a", foreign)

        assert subscriber.empty()
        replay = stream.subscribe("tenant-a")
        assert replay.empty()
        assert stream.subscribe("tenant-b").empty()

    asyncio.run(scenario())


def test_tampered_envelope_cannot_pollute_stream_or_produce_sse() -> None:
    envelope = _envelope()
    object.__setattr__(
        envelope,
        "payload",
        {
            "result_ref": "result://safe",
            "nested": [{"chain_of_thought": "hidden"}],
        },
    )

    async def scenario() -> None:
        stream = InMemoryEventStream()
        subscriber = stream.subscribe("tenant-a")
        with pytest.raises(ValueError, match="sensitive key"):
            await stream.emit("tenant-a", envelope)
        assert subscriber.empty()
        assert stream.subscribe("tenant-a").empty()

    asyncio.run(scenario())
    with pytest.raises(ValueError, match="sensitive key"):
        _sse_frame(envelope)


def test_tampered_reference_writes_no_stream_or_sse_output() -> None:
    envelope = _envelope()
    object.__setattr__(
        envelope,
        "payload",
        {"result_ref": "result://safe?view=full"},
    )

    async def scenario() -> None:
        stream = InMemoryEventStream()
        subscriber = stream.subscribe("tenant-a")
        with pytest.raises(ValueError, match="opaque URI reference"):
            await stream.emit("tenant-a", envelope)
        assert subscriber.empty()
        assert stream.subscribe("tenant-a").empty()

    asyncio.run(scenario())
    frames: list[str] = []
    with pytest.raises(ValueError, match="opaque URI reference"):
        frames.append(_sse_frame(envelope))
    assert frames == []


@pytest.mark.parametrize(
    ("family", "sensitive_value"),
    TOKEN_FAMILY_CASES,
    ids=[family for family, _value in TOKEN_FAMILY_CASES],
)
def test_tampered_sensitive_value_writes_no_stream_or_sse_output(
    family: str,
    sensitive_value: str,
) -> None:
    assert family
    envelope = _envelope()
    object.__setattr__(
        envelope,
        "correlation_id",
        sensitive_value,
    )

    async def scenario() -> None:
        stream = InMemoryEventStream()
        subscriber = stream.subscribe("tenant-a")
        with pytest.raises(SecurityError):
            await stream.emit("tenant-a", envelope)
        assert subscriber.empty()
        assert stream.subscribe("tenant-a").empty()

    asyncio.run(scenario())
    frames: list[str] = []
    with pytest.raises(SecurityError):
        frames.append(_sse_frame(envelope))
    assert frames == []


@pytest.mark.parametrize(
    ("family", "sensitive_value"),
    P0_CREDENTIAL_CASES,
    ids=[family for family, _value in P0_CREDENTIAL_CASES],
)
def test_tampered_replay_is_revalidated_before_subscriber_registration(
    family: str,
    sensitive_value: str,
) -> None:
    assert family

    async def scenario() -> None:
        stream = InMemoryEventStream()
        envelope = _envelope()
        await stream.emit("tenant-a", envelope)
        object.__setattr__(envelope, "correlation_id", sensitive_value)

        with pytest.raises(SecurityError):
            stream.subscribe("tenant-a")

        assert stream._subscribers.get("tenant-a") is None

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("family", "sensitive_value"),
    P0_CREDENTIAL_CASES,
    ids=[family for family, _value in P0_CREDENTIAL_CASES],
)
def test_credential_errors_and_logs_never_render_original_material(
    family: str,
    sensitive_value: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("flowpilot.tests.task-event-credentials")
    with pytest.raises(SecurityError) as captured:
        _envelope(correlation_id=sensitive_value)

    error = captured.value
    with caplog.at_level(logging.ERROR, logger=logger.name):
        logger.error("task event rejected: %s", error)

    assert family
    assert error.code is SecurityErrorCode.UNSAFE_PROJECTION
    assert sensitive_value not in str(error)
    assert sensitive_value not in repr(error)
    assert sensitive_value not in caplog.text


@pytest.mark.parametrize(
    ("family", "sensitive_value"),
    P0_CREDENTIAL_CASES,
    ids=[family for family, _value in P0_CREDENTIAL_CASES],
)
def test_credential_mapping_keys_are_rejected_before_projection_errors(
    family: str,
    sensitive_value: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("flowpilot.tests.task-event-credential-keys")
    with pytest.raises(SecurityError) as captured:
        _envelope(
            payload={
                "result_ref": "result://safe",
                sensitive_value: {"reasoning": "hidden-content"},
            }
        )

    error = captured.value
    with caplog.at_level(logging.ERROR, logger=logger.name):
        logger.error("task event rejected: %s", error)

    assert family
    assert error.code is SecurityErrorCode.UNSAFE_PROJECTION
    assert sensitive_value not in str(error)
    assert sensitive_value not in repr(error)
    assert sensitive_value not in caplog.text
