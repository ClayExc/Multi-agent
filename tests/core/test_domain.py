from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from flowpilot_domain import (
    ActionAgent,
    ActionResource,
    ActionTool,
    Approval,
    ApprovalStatus,
    DataClassification,
    DomainErrorCode,
    DomainViolation,
    PlannedAction,
    Task,
    TaskStatus,
    ToolOperation,
    assert_task_transition,
)
from jsonschema import FormatChecker
from jsonschema.validators import validator_for
from referencing import Registry, Resource


def _waiting_task_mapping(security_context: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": "task_12345678",
        "thread_id": "thread_12345678",
        "tenant_id": "tenant-a",
        "status": "WAITING_USER",
        "version": 2,
        "run_generation": 1,
        "purpose": "it_support",
        "data_classification": "confidential",
        "security_context": security_context,
        "release": {
            "graph_version": "graph-v1",
            "domain_pack_version": "it-service-v1",
            "context_policy_version": "context-v1",
            "policy_version": "policy-v1",
            "tool_schema_set": "tools-v1",
        },
        "waiting_on": {
            "type": "user_input",
            "request_id": "clarification-123",
            "expires_at": None,
        },
        "result_ref": None,
        "error": None,
        "created_at": "2026-07-28T08:00:00Z",
        "updated_at": "2026-07-28T08:01:00Z",
        "completed_at": None,
    }


def _planned_action() -> PlannedAction:
    now = datetime(2026, 7, 28, 8, tzinfo=UTC)
    return PlannedAction(
        action_id="act_12345678",
        tenant_id="tenant-a",
        task_id="task_12345678",
        requester_id="user-123",
        agent=ActionAgent(id="agent-core", version="v1"),
        tool=ActionTool(
            name="it.ticket.update.v1",
            schema_hash="sha256:" + "c" * 64,
            operation=ToolOperation.WRITE,
        ),
        arguments={"ticket_id": "INC-123", "priority": "high"},
        resource=ActionResource(
            type="ticket", id="INC-123", owner_id="user-123"
        ),
        purpose="it_support",
        data_classification=DataClassification.CONFIDENTIAL,
        policy_version="policy-v1",
        expires_at=now + timedelta(minutes=15),
    )


def _assert_contract_valid(schema_name: str, instance: dict[str, Any]) -> None:
    schema_root = Path(__file__).resolve().parents[2] / "contracts" / "jsonschema"
    registry = Registry()
    schemas: dict[str, dict[str, Any]] = {}
    for schema_path in schema_root.glob("*.json"):
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        schemas[schema_path.name] = schema
        registry = registry.with_resource(
            schema["$id"], Resource.from_contents(schema)
        )
    selected = schemas[schema_name]
    validator_class = validator_for(selected)
    validator_class.check_schema(selected)
    validator_class(
        selected,
        registry=registry,
        format_checker=FormatChecker(),
    ).validate(instance)


def test_legal_waiting_task_and_transition_are_accepted(
    valid_create_mapping: dict[str, Any],
) -> None:
    task = Task.from_mapping(
        _waiting_task_mapping(valid_create_mapping["security_context"])
    )

    assert task.status is TaskStatus.WAITING_USER
    assert task.to_mapping()["waiting_on"]["type"] == "user_input"
    _assert_contract_valid("task.v1.schema.json", task.to_mapping())
    assert_task_transition(TaskStatus.WAITING_USER, TaskStatus.RUNNABLE)


def test_illegal_waiting_projection_and_terminal_transition_are_rejected(
    valid_create_mapping: dict[str, Any],
) -> None:
    value = _waiting_task_mapping(valid_create_mapping["security_context"])
    value["waiting_on"]["type"] = "approval"

    with pytest.raises(DomainViolation) as invalid_state:
        Task.from_mapping(value)
    with pytest.raises(DomainViolation) as invalid_transition:
        assert_task_transition(TaskStatus.COMPLETED, TaskStatus.RUNNABLE)

    assert invalid_state.value.code is DomainErrorCode.INVALID_STATE
    assert invalid_transition.value.code is DomainErrorCode.INVALID_TRANSITION


def test_approval_binds_full_planned_action_digest() -> None:
    action = _planned_action()
    now = datetime(2026, 7, 28, 8, tzinfo=UTC)
    approval = Approval(
        approval_id="apr_12345678",
        tenant_id=action.tenant_id,
        task_id=action.task_id,
        requester_id=action.requester_id,
        action_id=action.action_id,
        action_digest=action.digest(),
        tool_schema_hash=action.tool.schema_hash,
        policy_decision_id="pd_12345678",
        policy_version=action.policy_version,
        status=ApprovalStatus.APPROVED,
        approver_id="approver-456",
        decision_reason="approved for incident response",
        separation_of_duties_result=True,
        requested_at=now,
        decided_at=now + timedelta(minutes=1),
        expires_at=action.expires_at.astimezone(
            timezone(timedelta(hours=2))
        ),
    )

    approval.assert_action_binding(action)
    _assert_contract_valid("planned-action.v1.schema.json", action.to_mapping())
    _assert_contract_valid("approval.v1.schema.json", approval.to_mapping())

    tampered = PlannedAction.from_mapping(
        {
            **action.to_mapping(),
            "arguments": {"ticket_id": "INC-999", "priority": "high"},
        }
    )
    with pytest.raises(DomainViolation) as captured:
        approval.assert_action_binding(tampered)

    assert captured.value.code is DomainErrorCode.APPROVAL_BINDING_MISMATCH


def test_approval_expiry_mismatch_is_rejected() -> None:
    action = _planned_action()
    now = datetime(2026, 7, 28, 8, tzinfo=UTC)
    approval = Approval(
        approval_id="apr_12345678",
        tenant_id=action.tenant_id,
        task_id=action.task_id,
        requester_id=action.requester_id,
        action_id=action.action_id,
        action_digest=action.digest(),
        tool_schema_hash=action.tool.schema_hash,
        policy_decision_id="pd_12345678",
        policy_version=action.policy_version,
        status=ApprovalStatus.APPROVED,
        approver_id="approver-456",
        decision_reason="approved for incident response",
        separation_of_duties_result=True,
        requested_at=now,
        decided_at=now + timedelta(minutes=1),
        expires_at=action.expires_at + timedelta(minutes=15),
    )

    with pytest.raises(DomainViolation) as captured:
        approval.assert_action_binding(action)

    assert captured.value.code is DomainErrorCode.APPROVAL_BINDING_MISMATCH


def test_requester_cannot_approve_own_action() -> None:
    action = _planned_action()
    now = datetime(2026, 7, 28, 8, tzinfo=UTC)

    with pytest.raises(DomainViolation) as captured:
        Approval(
            approval_id="apr_12345678",
            tenant_id=action.tenant_id,
            task_id=action.task_id,
            requester_id=action.requester_id,
            action_id=action.action_id,
            action_digest=action.digest(),
            tool_schema_hash=action.tool.schema_hash,
            policy_decision_id="pd_12345678",
            policy_version=action.policy_version,
            status=ApprovalStatus.APPROVED,
            approver_id=action.requester_id,
            decision_reason=None,
            separation_of_duties_result=True,
            requested_at=now,
            decided_at=now + timedelta(minutes=1),
            expires_at=now + timedelta(minutes=15),
        )

    assert captured.value.code is DomainErrorCode.APPROVAL_BINDING_MISMATCH


def test_task_security_context_cannot_cross_tenant(
    valid_create_mapping: dict[str, Any],
) -> None:
    security_context = copy.deepcopy(valid_create_mapping["security_context"])
    security_context["tenant_id"] = "tenant-b"

    with pytest.raises(DomainViolation) as captured:
        Task.from_mapping(_waiting_task_mapping(security_context))

    assert captured.value.code is DomainErrorCode.SECURITY_BINDING_MISMATCH
