from __future__ import annotations

import asyncio
import copy
import inspect
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from flowpilot_api import (
    GovernanceAccessPolicy,
    TrustedRequestIdentity,
    create_product_app,
)
from flowpilot_api.testing import StaticRequestSecurity
from flowpilot_application import ErrorCode
from flowpilot_application.testing import (
    FAKE_TASK_INITIALIZATION,
    FakeExecutionPort,
    FakeThreadIdFactory,
    FakeUnitOfWorkFactory,
)
from flowpilot_domain import ActorType, TaskCommand
from flowpilot_persistence import MemoryDataUnitOfWorkFactory

NOW = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)


def _identity(command: dict[str, Any]) -> TrustedRequestIdentity:
    context = command["security_context"]
    return TrustedRequestIdentity(
        tenant_id=command["tenant_id"],
        subject_id=command["actor"]["id"],
        subject_type=ActorType(command["actor"]["type"]),
        purpose=context["purpose"],
        security_context_id=context["context_id"],
        security_context_ref=context["context_ref"],
        security_context_hash=context["context_hash"],
    )


def _with_digest(command: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(command)
    value["command_digest"] = "sha256:" + "0" * 64
    value["command_digest"] = TaskCommand.from_mapping(value).recompute_digest()
    return value


def _product_client(
    command: dict[str, Any],
) -> tuple[
    httpx.ASGITransport,
    FakeUnitOfWorkFactory,
    FakeExecutionPort,
    StaticRequestSecurity,
]:
    unit_of_work = FakeUnitOfWorkFactory()
    execution = FakeExecutionPort()
    security = StaticRequestSecurity(_identity(command))
    app = create_product_app(
        command_unit_of_work=unit_of_work,
        task_query_unit_of_work=unit_of_work,
        task_event_unit_of_work=MemoryDataUnitOfWorkFactory(),
        execution=execution,
        task_initialization=FAKE_TASK_INITIALIZATION,
        thread_id_factory=FakeThreadIdFactory(),
        request_security=security,
        clock=lambda: NOW,
    )
    return httpx.ASGITransport(app=app), unit_of_work, execution, security


def _request(
    transport: httpx.ASGITransport,
    method: str,
    path: str,
    *,
    body: object | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://flowpilot.test",
        ) as client:
            return await client.request(
                method,
                path,
                json=body,
                headers=headers,
            )

    return asyncio.run(send())


def test_product_app_composes_command_runtime_and_replays_idempotently(
    valid_create_mapping: dict[str, Any],
) -> None:
    command = copy.deepcopy(valid_create_mapping)
    command["payload"]["initial_message_ref"] = (
        "message://tenant-a/knowledge-question-zh-001"
    )
    command = _with_digest(command)
    transport, unit_of_work, execution, security = _product_client(command)

    health = _request(transport, "GET", "/health")
    accepted = _request(transport, "POST", "/v1/task-commands", body=command)
    task = _request(
        transport,
        "GET",
        f"/v1/tasks/{command['task_id']}",
    )
    replayed = _request(transport, "POST", "/v1/task-commands", body=command)

    assert health.json()["configured"] is True
    assert accepted.status_code == 202
    assert accepted.json()["replayed"] is False
    assert task.status_code == 200
    assert task.json()["status"] == "RECEIVED"
    assert task.json()["thread_id"] == "thread_00000001"
    assert task.json()["version"] == 0
    assert task.json()["release"] == FAKE_TASK_INITIALIZATION.release.to_mapping()
    assert replayed.status_code == 202
    assert replayed.json()["replayed"] is True
    assert replayed.json()["command_id"] == accepted.json()["command_id"]
    assert len(execution.calls) == 1
    assert execution.calls[0].payload["initial_message_ref"] == (
        "message://tenant-a/knowledge-question-zh-001"
    )
    assert len(security.command_calls) == 2
    assert (
        unit_of_work.store.commands_by_id[
            (command["tenant_id"], command["command_id"])
        ].accepted_at
        == NOW
    )


def test_product_app_does_not_trust_browser_tenant_header(
    valid_create_mapping: dict[str, Any],
) -> None:
    trusted_command = copy.deepcopy(valid_create_mapping)
    transport, unit_of_work, execution, security = _product_client(trusted_command)
    forged = copy.deepcopy(trusted_command)
    forged["tenant_id"] = "tenant-b"
    forged["security_context"]["tenant_id"] = "tenant-b"
    forged = _with_digest(forged)

    response = _request(
        transport,
        "POST",
        "/v1/task-commands",
        body=forged,
        headers={"X-Tenant-ID": "tenant-b"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "API_REQUEST_IDENTITY_MISMATCH"
    assert unit_of_work.store.commands_by_id == {}
    assert execution.calls == []
    assert security.command_calls == []


def test_product_app_maps_runtime_failure_without_leaking_provider_details(
    valid_create_mapping: dict[str, Any],
) -> None:
    transport, _unit_of_work, execution, _security = _product_client(
        valid_create_mapping
    )
    execution.failure = RuntimeError("provider api_key=never-expose")

    response = _request(
        transport,
        "POST",
        "/v1/task-commands",
        body=valid_create_mapping,
    )

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": ErrorCode.EXECUTION_UNAVAILABLE.value,
            "message": "runtime execution is unavailable",
            "retryable": True,
            "detail_ref": None,
        }
    }
    assert "api_key" not in response.text
    assert "never-expose" not in response.text


def test_product_app_rejects_mismatched_runtime_receipt(
    valid_create_mapping: dict[str, Any],
) -> None:
    transport, _unit_of_work, execution, _security = _product_client(
        valid_create_mapping
    )
    execution.invalid_receipt = True

    response = _request(
        transport,
        "POST",
        "/v1/task-commands",
        body=valid_create_mapping,
    )

    assert response.status_code == 502
    assert response.json()["error"] == {
        "code": ErrorCode.EXECUTION_PROTOCOL_ERROR.value,
        "message": "runtime returned an invalid execution receipt",
        "retryable": False,
        "detail_ref": None,
    }


def test_product_composition_remains_port_only() -> None:
    import flowpilot_api.composition as api_composition
    import flowpilot_application.composition as application_composition

    composition_source = "\n".join(
        (
            inspect.getsource(api_composition),
            inspect.getsource(application_composition),
        )
    )
    forbidden = {
        "flowpilot_agent_runtime",
        "flowpilot_model_gateway",
        "flowpilot_persistence",
        "flowpilot_worker",
        "litellm",
        "agents",
        "claude_agent_sdk",
    }

    assert all(module_name not in composition_source for module_name in forbidden)


def test_product_composition_requires_governance_port_and_access_policy_together(
    valid_create_mapping: dict[str, Any],
) -> None:
    unit_of_work = FakeUnitOfWorkFactory()
    with pytest.raises(ValueError, match="configured together"):
        create_product_app(
            command_unit_of_work=unit_of_work,
            task_query_unit_of_work=unit_of_work,
            task_event_unit_of_work=MemoryDataUnitOfWorkFactory(),
            execution=FakeExecutionPort(),
            task_initialization=FAKE_TASK_INITIALIZATION,
            thread_id_factory=FakeThreadIdFactory(),
            request_security=StaticRequestSecurity(_identity(valid_create_mapping)),
            governance_access=GovernanceAccessPolicy(
                allowed_roles=frozenset({"governance-reader"}),
                allowed_purposes=frozenset({"security_review"}),
            ),
            clock=lambda: NOW,
        )
