from __future__ import annotations

import asyncio
import copy
import json
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
        producer_principal_ref=f"workload://{producer}/test",
        correlation_id="correlation-security-0001",
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
        {
            "result_ref": "result://safe",
            "metadata": [
                {"provider_session": {"credential": {"access_token": "secret"}}}
            ],
        },
    ),
    ids=("session-ref", "reasoning", "nested-sensitive-key"),
)
def test_envelope_construction_recursively_rejects_sensitive_keys(
    payload: dict[str, Any],
) -> None:
    with pytest.raises(ValueError, match="sensitive key"):
        _envelope(payload=payload)


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
