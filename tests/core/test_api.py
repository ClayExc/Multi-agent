from __future__ import annotations

import asyncio
import copy
import json
import sys
from datetime import UTC, datetime, timedelta
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
for _package in ("domain", "application", "persistence"):
    _source = REPOSITORY_ROOT / "packages" / _package / "src"
    if str(_source) not in sys.path:
        sys.path.insert(0, str(_source))

from flowpilot_api import (  # noqa: E402
    InMemoryEventStream,
    TrustedRequestIdentity,
    create_app,
)
from flowpilot_api.errors import ApiError, ApiErrorCode  # noqa: E402
from flowpilot_api.testing import StaticRequestSecurity  # noqa: E402
from flowpilot_application import (  # noqa: E402
    CommandIntakeService,
    TaskEventStreamConfig,
    TaskEventSubscriptionService,
    TaskQueryService,
)
from flowpilot_application.testing import (  # noqa: E402
    FakeExecutionPort,
    FakeUnitOfWorkFactory,
)
from flowpilot_domain import ActorType, Task, TaskCommand  # noqa: E402
from flowpilot_persistence import (  # noqa: E402
    MemoryDataUnitOfWorkFactory,
    OutboxEvent,
)


class ApiClient:
    def __init__(self, app: FastAPI) -> None:
        self._app = app

    def get(self, path: str) -> httpx.Response:
        return self._request("GET", path)

    def post(self, path: str, *, json: object) -> httpx.Response:
        return self._request("POST", path, json=json)

    def _request(
        self, method: str, path: str, *, json: object | None = None
    ) -> httpx.Response:
        async def send() -> httpx.Response:
            transport = httpx.ASGITransport(app=self._app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://flowpilot.test",
            ) as client:
                return await client.request(method, path, json=json)

        return asyncio.run(send())


def _identity(command: dict[str, Any]) -> TrustedRequestIdentity:
    security = command["security_context"]
    return TrustedRequestIdentity(
        tenant_id=command["tenant_id"],
        subject_id=command["actor"]["id"],
        subject_type=ActorType(command["actor"]["type"]),
        purpose=security["purpose"],
        security_context_id=security["context_id"],
        security_context_ref=security["context_ref"],
        security_context_hash=security["context_hash"],
    )


def _task(command: dict[str, Any]) -> Task:
    return Task.from_mapping(
        {
            "task_id": command["task_id"],
            "thread_id": "thread_12345678",
            "tenant_id": command["tenant_id"],
            "status": "RECEIVED",
            "version": 0,
            "run_generation": 0,
            "domain": "it-service",
            "intent": "vpn_support",
            "risk_level": "low",
            "purpose": command["security_context"]["purpose"],
            "data_classification": "confidential",
            "security_context": command["security_context"],
            "release": {
                "graph_version": "graph-v1",
                "domain_pack_version": "0.1.0",
                "context_policy_version": "context-v1",
                "policy_version": "policy-v1",
                "tool_schema_set": "tools-v1",
            },
            "waiting_on": None,
            "result_ref": None,
            "error": None,
            "created_at": "2026-07-28T08:00:00Z",
            "updated_at": "2026-07-28T08:00:00Z",
            "completed_at": None,
        }
    )


def _configured_client(
    command: dict[str, Any],
) -> tuple[
    ApiClient,
    FakeUnitOfWorkFactory,
    FakeExecutionPort,
    StaticRequestSecurity,
]:
    unit_of_work = FakeUnitOfWorkFactory()
    execution = FakeExecutionPort()
    security = StaticRequestSecurity(_identity(command))
    app = create_app(
        command_intake=CommandIntakeService(
            unit_of_work=unit_of_work,
            execution=execution,
        ),
        task_query=TaskQueryService(unit_of_work),
        request_security=security,
    )
    return (
        ApiClient(app),
        unit_of_work,
        execution,
        security,
    )


def test_health_reports_whether_required_adapters_are_configured(
    valid_create_mapping: dict[str, Any],
) -> None:
    unconfigured = ApiClient(create_app())
    configured, _unit_of_work, _execution, _security = _configured_client(
        valid_create_mapping
    )

    assert unconfigured.get("/health").json() == {
        "status": "ok",
        "service": "flowpilot-api",
        "version": "0.1.0",
        "configured": False,
    }
    assert configured.get("/health").json()["configured"] is True


def test_command_intake_accepts_and_idempotently_replays(
    valid_create_mapping: dict[str, Any],
) -> None:
    client, unit_of_work, execution, security = _configured_client(valid_create_mapping)

    accepted = client.post("/v1/task-commands", json=valid_create_mapping)
    replay = client.post("/v1/task-commands", json=valid_create_mapping)

    assert accepted.status_code == 202
    assert accepted.json()["replayed"] is False
    assert accepted.json()["execution_receipt"]["disposition"] == "accepted"
    assert replay.status_code == 202
    assert replay.json()["replayed"] is True
    assert len(execution.calls) == 1
    assert len(security.command_calls) == 2
    assert (
        valid_create_mapping["tenant_id"],
        valid_create_mapping["command_id"],
    ) in unit_of_work.store.commands_by_id


def test_idempotency_conflict_has_a_stable_api_error(
    valid_create_mapping: dict[str, Any],
) -> None:
    client, _unit_of_work, execution, _security = _configured_client(
        valid_create_mapping
    )
    conflict = copy.deepcopy(valid_create_mapping)
    conflict["command_id"] = "cmd_conflict0"
    conflict["payload"]["initial_message_ref"] = "message://different"
    conflict["command_digest"] = "sha256:" + "0" * 64
    conflict["command_digest"] = TaskCommand.from_mapping(conflict).recompute_digest()

    assert (
        client.post("/v1/task-commands", json=valid_create_mapping).status_code == 202
    )
    response = client.post("/v1/task-commands", json=conflict)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CORE_IDEMPOTENCY_CONFLICT"
    assert len(execution.calls) == 1


def test_command_boundary_rejects_extra_fields_and_bad_digest(
    valid_create_mapping: dict[str, Any],
) -> None:
    client, _unit_of_work, execution, security = _configured_client(
        valid_create_mapping
    )
    widened = copy.deepcopy(valid_create_mapping)
    widened["authorization"] = {"allow": True}

    invalid_shape = client.post("/v1/task-commands", json=widened)
    bad_digest = copy.deepcopy(valid_create_mapping)
    bad_digest["command_digest"] = "sha256:" + "0" * 64
    invalid_digest = client.post("/v1/task-commands", json=bad_digest)

    assert invalid_shape.status_code == 422
    assert invalid_shape.json()["error"]["code"] == "CORE_CONTRACT_INVALID"
    assert invalid_digest.status_code == 400
    assert invalid_digest.json()["error"]["code"] == "CORE_COMMAND_DIGEST_MISMATCH"
    assert execution.calls == []
    assert security.command_calls == []


def test_security_binding_is_verified_before_authorization(
    valid_create_mapping: dict[str, Any],
) -> None:
    client, unit_of_work, execution, security = _configured_client(valid_create_mapping)
    mismatched = copy.deepcopy(valid_create_mapping)
    mismatched["payload"]["purpose"] = "unrelated_purpose"
    command = TaskCommand.from_mapping(
        {**mismatched, "command_digest": "sha256:" + "0" * 64}
    )
    mismatched["command_digest"] = command.recompute_digest()

    response = client.post("/v1/task-commands", json=mismatched)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CORE_SECURITY_BINDING_MISMATCH"
    assert security.command_calls == []
    assert execution.calls == []
    assert unit_of_work.store.commands_by_id == {}


@pytest.mark.parametrize(
    "identity_override",
    (
        {"tenant_id": "tenant-other"},
        {"subject_id": "user-other"},
        {"subject_type": ActorType.SERVICE},
        {"purpose": "unrelated-purpose"},
    ),
)
def test_trusted_identity_mismatch_fails_closed_before_authorization(
    valid_create_mapping: dict[str, Any],
    identity_override: dict[str, object],
) -> None:
    client, unit_of_work, execution, security = _configured_client(valid_create_mapping)
    security.identity = replace(security.identity, **identity_override)

    response = client.post("/v1/task-commands", json=valid_create_mapping)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "API_REQUEST_IDENTITY_MISMATCH"
    assert security.command_calls == []
    assert execution.calls == []
    assert unit_of_work.store.commands_by_id == {}


def test_runtime_failure_is_stable_retryable_and_sanitized(
    valid_create_mapping: dict[str, Any],
) -> None:
    client, _unit_of_work, execution, _security = _configured_client(
        valid_create_mapping
    )
    execution.failure = RuntimeError("credential=top-secret")

    response = client.post("/v1/task-commands", json=valid_create_mapping)

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "CORE_EXECUTION_UNAVAILABLE",
        "message": "runtime execution is unavailable",
        "retryable": True,
        "detail_ref": None,
    }
    assert "top-secret" not in response.text


def test_task_query_is_read_only_and_tenant_scoped(
    valid_create_mapping: dict[str, Any],
) -> None:
    client, unit_of_work, _execution, security = _configured_client(
        valid_create_mapping
    )
    task = _task(valid_create_mapping)
    unit_of_work.store.tasks_by_id[(task.tenant_id, task.task_id)] = task

    found = client.get(f"/v1/tasks/{task.task_id}")
    missing = client.get("/v1/tasks/task_missing00")
    malformed = client.get("/v1/tasks/not-a-task")

    assert found.status_code == 200
    assert Task.from_mapping(found.json()) == task
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "CORE_TASK_NOT_FOUND"
    assert malformed.status_code == 422
    assert security.task_read_calls == [task.task_id, "task_missing00"]
    assert unit_of_work.store.commands_by_id == {}


def test_task_query_does_not_disclose_another_tenant_projection(
    valid_create_mapping: dict[str, Any],
) -> None:
    client, unit_of_work, _execution, security = _configured_client(
        valid_create_mapping
    )
    task = _task(valid_create_mapping)
    unit_of_work.store.tasks_by_id[(task.tenant_id, task.task_id)] = task
    security.identity = TrustedRequestIdentity(
        tenant_id="tenant-other",
        subject_id=security.identity.subject_id,
        subject_type=security.identity.subject_type,
        purpose=security.identity.purpose,
        security_context_id=security.identity.security_context_id,
        security_context_ref=security.identity.security_context_ref,
        security_context_hash=security.identity.security_context_hash,
    )

    response = client.get(f"/v1/tasks/{task.task_id}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CORE_TASK_NOT_FOUND"
    assert task.tenant_id not in response.text


def test_openapi_exposes_only_versioned_strict_command_variants() -> None:
    schema = create_app().openapi()
    command_schema = schema["paths"]["/v1/task-commands"]["post"]["requestBody"][
        "content"
    ]["application/json"]["schema"]
    expected = {
        "task.create.v1",
        "task.message.submit.v1",
        "task.approval.decide.v1",
        "task.cancel.request.v1",
        "task.retry.request.v1",
    }

    assert command_schema["discriminator"]["propertyName"] == "command_type"
    assert set(command_schema["discriminator"]["mapping"]) == expected
    assert set(schema["paths"]["/v1/task-commands"]["post"]["responses"]) >= {
        "202",
        "400",
        "403",
        "409",
        "422",
        "500",
        "502",
        "503",
    }
    for reference in command_schema["oneOf"]:
        name = reference["$ref"].rsplit("/", maxsplit=1)[-1]
        assert schema["components"]["schemas"][name]["additionalProperties"] is False


def test_public_api_keeps_request_and_result_content_behind_references() -> None:
    schemas = create_app().openapi()["components"]["schemas"]
    create_payload = schemas["CreateTaskPayload"]["properties"]
    task_projection = schemas["TaskBody"]["properties"]

    assert "initial_message_ref" in create_payload
    assert {
        "initial_message",
        "message_text",
        "request_observation",
    }.isdisjoint(create_payload)
    assert "result_ref" in task_projection
    assert {
        "result",
        "answer",
        "content",
        "citations",
    }.isdisjoint(task_projection)


# --- Task event stream (SSE) endpoint ----------------------------------------

EVENT_STREAM_NOW = datetime(2026, 7, 28, 8, 0, tzinfo=UTC)


def _outbox_event(
    event_id: str,
    sequence: int,
    *,
    event_type: str = "task.status.changed.v1",
    task_id: str = "task_12345678",
    tenant_id: str = "tenant-a",
    payload: dict[str, Any] | None = None,
) -> OutboxEvent:
    return OutboxEvent(
        event_id=event_id,
        tenant_id=tenant_id,
        aggregate_type="task",
        aggregate_id=task_id,
        sequence=sequence,
        event_type=event_type,
        payload=payload
        or (
            {
                "from": "RUNNING",
                "to": "COMPLETED",
                "reason_code": None,
            }
            if event_type == "task.status.changed.v1"
            else {"status": "RECEIVED", "task_ref": f"task://{task_id}"}
        ),
        occurred_at=EVENT_STREAM_NOW + timedelta(seconds=sequence),
        available_at=EVENT_STREAM_NOW,
    )


def _stream_app(
    command: dict[str, Any],
    *,
    tenant_id: str | None = None,
) -> tuple[
    FastAPI,
    MemoryDataUnitOfWorkFactory,
    StaticRequestSecurity,
    InMemoryEventStream,
    TaskEventSubscriptionService,
]:
    identity = _identity(command)
    if tenant_id is not None:
        identity = replace(identity, tenant_id=tenant_id)
    unit_of_work = MemoryDataUnitOfWorkFactory()
    stream = InMemoryEventStream()
    subscription = TaskEventSubscriptionService(
        unit_of_work=unit_of_work,
        stream=stream,
        config=TaskEventStreamConfig(poll_interval=0.01),
        clock=lambda: EVENT_STREAM_NOW,
    )
    security = StaticRequestSecurity(identity)
    app = create_app(
        task_event_subscription=subscription,
        event_stream=stream,
        request_security=security,
    )
    return app, unit_of_work, security, stream, subscription


def _seed_stream_events(
    unit_of_work: MemoryDataUnitOfWorkFactory,
    command: dict[str, Any],
    *events: OutboxEvent,
) -> Any:
    """Return a coroutine that seeds task + outbox events."""
    task = _task(command)
    unit_of_work.database.seed_task(task)

    async def seed() -> None:
        async with unit_of_work() as uow:
            for event in events:
                await uow.outbox.append(event)
            await uow.commit()

    return seed()


async def _read_sse(
    app: FastAPI,
    path: str,
    *,
    expected: int,
    timeout: float = 5.0,
) -> list[dict[str, Any]]:
    """Read SSE frames until `expected` task events arrive.

    Uses a manual ASGI client because httpx.ASGITransport awaits the whole
    app and cannot observe long-lived streaming responses.

    expected=0 asserts the stream stays silent until the deadline.
    """
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("test", 123),
        "server": ("test", 80),
    }
    collected: list[dict[str, Any]] = []
    status_code = None
    content_type = b""
    data_buffer = b""
    receive_calls = 0

    async def receive() -> dict[str, Any]:
        nonlocal receive_calls
        receive_calls += 1
        if receive_calls == 1:
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.sleep(3600)
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        nonlocal status_code, content_type, data_buffer
        if message["type"] == "http.response.start":
            status_code = message["status"]
            content_type = dict(message.get("headers", [])).get(
                b"content-type", b""
            )
        elif message["type"] == "http.response.body":
            data_buffer += message.get("body", b"")
            text = data_buffer.decode(errors="replace")
            while "\n\n" in text:
                frame, text = text.split("\n\n", 1)
                data_buffer = text.encode()
                for line in frame.splitlines():
                    if line.startswith("data: "):
                        collected.append(json.loads(line[len("data: ") :]))

    app_task = asyncio.create_task(app(scope, receive, send))
    try:
        await asyncio.wait_for(app_task, timeout=timeout)
    except asyncio.TimeoutError:
        # SSE is an infinite stream: the app task never completes on its own.
        # If we have collected the expected events, that is success.
        if expected > 0 and len(collected) < expected:
            raise
        app_task.cancel()
        try:
            await app_task
        except (asyncio.CancelledError, Exception):
            pass

    assert status_code == 200
    assert content_type.startswith(b"text/event-stream")
    return collected


def test_event_stream_requires_configuration() -> None:
    client = ApiClient(create_app())
    assert client.get("/v1/tasks/events").status_code == 503


def test_event_stream_requires_authorization(
    valid_create_mapping: dict[str, Any],
) -> None:
    app, _unit_of_work, security, _stream, _subscription = _stream_app(
        valid_create_mapping
    )
    security.failure = ApiError(
        ApiErrorCode.REQUEST_IDENTITY_MISMATCH,
        "request identity was rejected",
        status_code=403,
    )

    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://flowpilot.test",
        ) as client:
            return await client.get("/v1/tasks/events")

    response = asyncio.run(request())
    assert response.status_code == 403


def test_event_stream_delivers_lifecycle_events_in_order(
    valid_create_mapping: dict[str, Any],
) -> None:
    app, unit_of_work, security, _stream, _subscription = _stream_app(
        valid_create_mapping
    )

    async def scenario() -> list[dict[str, Any]]:
        await _seed_stream_events(
            unit_of_work,
            valid_create_mapping,
            _outbox_event("evt_00000001", 1, event_type="task.created.v1"),
            _outbox_event("evt_00000002", 2),
            _outbox_event(
                "evt_00000003",
                3,
                event_type="task.completed.v1",
                payload={"result_ref": "runtime-result://abc"},
            ),
        )
        return await _read_sse(app, "/v1/tasks/events", expected=3)

    events = asyncio.run(scenario())

    assert security.event_stream_calls == ["tenant-a"]
    assert [event["sequence"] for event in events] == [1, 2, 3]
    assert [event["event_type"] for event in events] == [
        "task.created.v1",
        "task.status.changed.v1",
        "task.completed.v1",
    ]
    assert all(event["task_id"] == "task_12345678" for event in events)
    assert all(event["tenant_id"] == "tenant-a" for event in events)
    assert all(event["producer"] == "worker" for event in events)


def test_event_stream_is_isolated_per_tenant(
    valid_create_mapping: dict[str, Any],
) -> None:
    """FP-SEC-002: a tenant-b subscription reads zero tenant-a events."""
    app, unit_of_work, security, _stream, _subscription = _stream_app(
        valid_create_mapping,
        tenant_id="tenant-b",
    )

    async def scenario() -> list[dict[str, Any]]:
        await _seed_stream_events(
            unit_of_work,
            valid_create_mapping,
            _outbox_event("evt_00000001", 1, event_type="task.created.v1"),
            _outbox_event("evt_00000002", 2),
        )
        return await _read_sse(
            app, "/v1/tasks/events", expected=0, timeout=1.5
        )

    events = asyncio.run(asyncio.wait_for(scenario(), timeout=5.0))

    assert events == []
    assert security.event_stream_calls == ["tenant-b"]


def test_event_stream_contains_no_secret_material(
    valid_create_mapping: dict[str, Any],
) -> None:
    """FP-SEC-006: the wire format carries no plaintext secret fields."""
    app, unit_of_work, security, _stream, _subscription = _stream_app(
        valid_create_mapping
    )

    async def scenario() -> list[dict[str, Any]]:
        await _seed_stream_events(
            unit_of_work,
            valid_create_mapping,
            _outbox_event("evt_00000001", 1, event_type="task.created.v1"),
        )
        return await _read_sse(app, "/v1/tasks/events", expected=1)

    events = asyncio.run(scenario())
    serialized = json.dumps(events).casefold()
    for key in (
        "access_token",
        "api_key",
        "authorization",
        "password",
        "private_key",
        "secret",
    ):
        assert key not in serialized


def test_event_stream_replays_buffered_events_for_reconnects(
    valid_create_mapping: dict[str, Any],
) -> None:
    app, unit_of_work, security, _stream, _subscription = _stream_app(
        valid_create_mapping
    )

    async def scenario() -> tuple[
        list[dict[str, Any]], list[dict[str, Any]]
    ]:
        await _seed_stream_events(
            unit_of_work,
            valid_create_mapping,
            _outbox_event("evt_00000001", 1, event_type="task.created.v1"),
        )
        # First connection consumes the event, then disconnects.
        first = await _read_sse(app, "/v1/tasks/events", expected=1)
        # A second event arrives while the client is disconnected.
        await _seed_stream_events(
            unit_of_work,
            valid_create_mapping,
            _outbox_event("evt_00000002", 2),
        )
        # The reconnect replays both events from the stream buffer.
        second = await _read_sse(app, "/v1/tasks/events", expected=2)
        return first, second

    first, second = asyncio.run(scenario())
    assert [event["sequence"] for event in first] == [1]
    assert [event["sequence"] for event in second] == [1, 2]
