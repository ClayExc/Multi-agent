from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from flowpilot_domain import (
    DomainErrorCode,
    DomainViolation,
    TaskCommand,
)
from flowpilot_domain.primitives import MAX_SAFE_INTEGER


def test_official_create_fixture_round_trips_with_contract_digest(
    valid_create_mapping: dict[str, Any],
) -> None:
    command = TaskCommand.from_mapping(valid_create_mapping)

    assert command.recompute_digest() == valid_create_mapping["command_digest"]
    assert command.payload["attachment_refs"] == ()
    command.assert_digest()
    command.assert_security_binding()


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
