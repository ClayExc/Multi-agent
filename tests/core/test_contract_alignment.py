from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from flowpilot_domain import (
    DomainErrorCode,
    DomainViolation,
    PlannedAction,
    TaskCommand,
)
from flowpilot_domain.primitives import MAX_SAFE_INTEGER

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_official_create_fixture_round_trips_with_contract_digest(
    valid_create_mapping: dict[str, Any],
) -> None:
    command = TaskCommand.from_mapping(valid_create_mapping)

    assert command.recompute_digest() == valid_create_mapping["command_digest"]
    assert command.payload["attachment_refs"] == ()
    command.assert_digest()
    command.assert_security_binding()


def test_official_planned_action_preserves_nulls_for_contract_digest() -> None:
    cases = json.loads(
        (
            REPOSITORY_ROOT / "contracts" / "conformance" / "rc2-cases.json"
        ).read_text(encoding="utf-8")
    )["cases"]
    planned_mapping = next(
        case["instance"]
        for case in cases
        if case["case_id"] == "planned_action.server_constructed.valid"
    )
    policy_mapping = next(
        case["instance"]
        for case in cases
        if case["case_id"] == "policy.single_approval.valid"
    )

    action = PlannedAction.from_mapping(planned_mapping)

    assert action.to_mapping() == planned_mapping
    assert (
        action.digest()
        == policy_mapping["action"]["action_digest"]
        == "sha256:25d521416733830fb9190d1e57b51ff406967dd3e1a2499822e15994d1c7f711"
    )


def test_unknown_command_field_is_rejected(
    valid_create_mapping: dict[str, Any],
) -> None:
    valid_create_mapping["authorization"] = {"allow": True}

    with pytest.raises(DomainViolation) as captured:
        TaskCommand.from_mapping(valid_create_mapping)

    assert captured.value.code is DomainErrorCode.CONTRACT_VIOLATION


def test_maximum_safe_task_version_is_supported(
    command_factory: Callable[..., TaskCommand],
) -> None:
    command = command_factory(
        command_type="task.message.submit.v1",
        expected_task_version=MAX_SAFE_INTEGER,
        payload={
            "message_id": "msg_abcdefgh",
            "message_ref": "message://maximum-version",
            "attachment_refs": [],
        },
    )

    assert command.expected_task_version == MAX_SAFE_INTEGER
    command.assert_digest()


def test_integer_beyond_ijson_range_is_rejected(
    command_factory: Callable[..., TaskCommand],
) -> None:
    with pytest.raises(DomainViolation) as captured:
        command_factory(
            command_type="task.message.submit.v1",
            expected_task_version=MAX_SAFE_INTEGER + 1,
            payload={
                "message_id": "msg_abcdefgh",
                "message_ref": "message://too-large",
            },
        )

    assert captured.value.code is DomainErrorCode.CONTRACT_VIOLATION
