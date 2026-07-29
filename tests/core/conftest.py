from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from flowpilot_domain import TaskCommand

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _load_case(case_id: str) -> dict[str, Any]:
    case_file = REPOSITORY_ROOT / "contracts" / "conformance" / "rc2-cases.json"
    content = json.loads(case_file.read_text(encoding="utf-8"))
    for case in content["cases"]:
        if case["case_id"] == case_id:
            return copy.deepcopy(case["instance"])
    raise LookupError(case_id)


@pytest.fixture
def valid_create_mapping() -> dict[str, Any]:
    return _load_case("task_command.create.valid")


@pytest.fixture
def command_factory(
    valid_create_mapping: dict[str, Any],
) -> Callable[..., TaskCommand]:
    def factory(
        *,
        command_id: str = "cmd_12345678",
        command_type: str = "task.create.v1",
        tenant_id: str = "tenant-a",
        task_id: str = "task_12345678",
        expected_task_version: int | None = None,
        idempotency_key: str | None = None,
        payload: dict[str, Any] | None = None,
        subject_id: str = "user-123",
        security_tenant_id: str | None = None,
        security_purpose: str = "it_support",
    ) -> TaskCommand:
        value = copy.deepcopy(valid_create_mapping)
        value["command_id"] = command_id
        value["command_type"] = command_type
        value["tenant_id"] = tenant_id
        value["task_id"] = task_id
        value["expected_task_version"] = expected_task_version
        value["idempotency_key"] = idempotency_key or (
            "sha256:" + "a" * 64
        )
        value["actor"]["id"] = subject_id
        value["security_context"]["subject_id"] = subject_id
        value["security_context"]["tenant_id"] = (
            security_tenant_id or tenant_id
        )
        value["security_context"]["purpose"] = security_purpose
        if payload is not None:
            value["payload"] = payload
        value["command_digest"] = "sha256:" + "0" * 64
        unsigned = TaskCommand.from_mapping(value)
        value["command_digest"] = unsigned.recompute_digest()
        return TaskCommand.from_mapping(value)

    return factory
