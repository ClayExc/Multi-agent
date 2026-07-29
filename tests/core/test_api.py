from __future__ import annotations

import asyncio
import copy
from dataclasses import replace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from flowpilot_api import TrustedRequestIdentity, create_app
from flowpilot_api.testing import StaticRequestSecurity
from flowpilot_application import CommandIntakeService, TaskQueryService
from flowpilot_application.testing import (
    FakeExecutionPort,
    FakeTaskRepository,
    FakeUnitOfWorkFactory,
)
from flowpilot_domain import ActorType, Task, TaskCommand


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
        task_query=TaskQueryService(FakeTaskRepository(unit_of_work.store)),
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
