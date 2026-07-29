from __future__ import annotations

import copy
import json
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
for package in ("domain", "application", "persistence"):
    source = REPOSITORY_ROOT / "packages" / package / "src"
    sys.path.insert(0, str(source))

from flowpilot_domain import PlannedAction, Task, TaskCommand  # noqa: E402
from flowpilot_persistence import ExecutionIntent  # noqa: E402


def load_case(case_id: str) -> dict[str, Any]:
    case_file = REPOSITORY_ROOT / "contracts" / "conformance" / "rc2-cases.json"
    content = json.loads(case_file.read_text(encoding="utf-8"))
    for case in content["cases"]:
        if case["case_id"] == case_id:
            return copy.deepcopy(case["instance"])
    raise LookupError(case_id)


@pytest.fixture
def command_factory() -> Callable[..., TaskCommand]:
    valid = load_case("task_command.create.valid")

    def factory(
        *,
        command_id: str = "cmd_12345678",
        tenant_id: str = "tenant-a",
        task_id: str = "task_12345678",
        idempotency_key: str = "sha256:" + "a" * 64,
    ) -> TaskCommand:
        value = copy.deepcopy(valid)
        value["command_id"] = command_id
        value["tenant_id"] = tenant_id
        value["task_id"] = task_id
        value["idempotency_key"] = idempotency_key
        value["security_context"]["tenant_id"] = tenant_id
        value["command_digest"] = "sha256:" + "0" * 64
        unsigned = TaskCommand.from_mapping(value)
        value["command_digest"] = unsigned.recompute_digest()
        return TaskCommand.from_mapping(value)

    return factory


@pytest.fixture
def execution_intent() -> ExecutionIntent:
    planned_mapping = load_case("planned_action.server_constructed.valid")
    policy_mapping = load_case("policy.single_approval.valid")
    approval_mapping = load_case("approval.sod.valid")
    expires_at = datetime.fromisoformat(
        planned_mapping["expires_at"].replace("Z", "+00:00")
    )
    action_digest = PlannedAction.from_mapping(planned_mapping).digest()
    policy_mapping["action"]["action_digest"] = action_digest
    approval_mapping["action_digest"] = action_digest
    return ExecutionIntent(
        tool_execution_id="tex_12345678",
        request_id="treq_12345678",
        tenant_id=planned_mapping["tenant_id"],
        task_id=planned_mapping["task_id"],
        tool_name=planned_mapping["tool"]["name"],
        idempotency_key="sha256:" + "c" * 64,
        action_id=planned_mapping["action_id"],
        action_digest=action_digest,
        planned_action=planned_mapping,
        planned_action_expires_at=expires_at,
        policy_decision_id=policy_mapping["decision_id"],
        policy_version=policy_mapping["policy_version"],
        policy_decision=policy_mapping,
        policy_expires_at=datetime.fromisoformat(
            policy_mapping["expires_at"].replace("Z", "+00:00")
        ),
        tool_schema_hash=planned_mapping["tool"]["schema_hash"],
        approval_id=approval_mapping["approval_id"],
        approval=approval_mapping,
        approval_expires_at=datetime.fromisoformat(
            approval_mapping["expires_at"].replace("Z", "+00:00")
        ),
        created_at=datetime.fromisoformat("2026-07-28T08:30:00+00:00"),
    )


@pytest.fixture
def task_projection() -> Task:
    return Task.from_mapping(load_case("task.completed.valid"))
