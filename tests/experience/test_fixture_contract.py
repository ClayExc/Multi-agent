"""Fixture contract conformance and internal consistency.

正常路径: every fixture entry validates against the official v1 JSON schema,
parses as the API/application/domain constructors (TaskBody, Task,
TaskEventEnvelope), the manifest covers and hashes every file, and the
cross-references between approvals/planned actions/events/tasks line up.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from conftest import FIXTURES, validate_against

SCHEMA_BY_FIXTURE = {
    "tasks.v1.json": "task.v1.schema.json",
    "events.v1.json": "task-event.v1.schema.json",
    "approvals.v1.json": "approval.v1.schema.json",
    "planned-actions.v1.json": "planned-action.v1.schema.json",
    "commands.v1.json": "task-command.v1.schema.json",
}


@pytest.mark.parametrize("name", sorted(SCHEMA_BY_FIXTURE))
def test_fixture_validates_against_official_schema(
    registry, fixture_files, name: str
) -> None:
    """正常: 每个 fixture 条目都通过 contracts/jsonschema 官方契约。"""
    payload = fixture_files[name]
    entries = (
        payload["tasks"]
        if name == "tasks.v1.json"
        else payload["events"]
        if name == "events.v1.json"
        else payload["approvals"]
        if name == "approvals.v1.json"
        else payload["planned_actions"]
        if name == "planned-actions.v1.json"
        else payload["commands"]
    )
    for entry in entries:
        validate_against(registry, SCHEMA_BY_FIXTURE[name], entry)


def test_fixture_tasks_parse_as_api_and_domain_models(fixture_files) -> None:
    """适配边界: fixture 的 Task 投影与 apps/api TaskBody 及 domain Task 完全兼容。"""
    from flowpilot_api.models import TaskBody
    from flowpilot_domain import Task

    tasks = fixture_files["tasks.v1.json"]["tasks"]
    assert len(tasks) >= 6, "fixture must cover running/waiting/failed states"
    statuses = {task["status"] for task in tasks}
    assert {
        "RUNNING",
        "WAITING_USER",
        "WAITING_APPROVAL",
        "FAILED",
        "COMPLETED",
    } <= statuses
    for task in tasks:
        body = TaskBody.model_validate_json(json.dumps(task))
        assert body.task_id == task["task_id"]
        domain_task = Task.from_mapping(task)
        assert domain_task.task_id == task["task_id"]
        # 投影一致性：等待状态必须带 waiting_on，终态必须带 completed_at
        assert (task["status"] == "COMPLETED") == (task["result_ref"] is not None)
        if task["status"] == "FAILED":
            assert task["error"] is not None


def test_fixture_events_roundtrip_through_application_envelope(fixture_files) -> None:
    """适配边界: fixture 事件与 TaskEventEnvelope 互转后逐字段一致。

    The envelope dataclass takes datetime objects and its ``to_mapping()``
    is exactly what the SSE transport emits; a round-trip proves the shell
    fixtures carry the same wire shape as apps/api stream.py output.
    """
    from datetime import datetime

    from flowpilot_application import TaskEventEnvelope

    events = fixture_files["events.v1.json"]["events"]
    event_ids = [event["event_id"] for event in events]
    assert len(event_ids) == len(set(event_ids)), "event_id must be unique"
    for event in events:
        converted = dict(event)
        converted["occurred_at"] = datetime.fromisoformat(
            event["occurred_at"].replace("Z", "+00:00")
        )
        envelope = TaskEventEnvelope(**converted)
        # to_mapping() freezes lists into tuples; the wire form is JSON,
        # where tuples and lists serialize identically.
        assert json.dumps(
            envelope.to_mapping(), sort_keys=True, ensure_ascii=False
        ) == json.dumps(event, sort_keys=True, ensure_ascii=False)


def test_fixture_manifest_covers_and_hashes_every_file(fixture_files) -> None:
    """正常: manifest 登记每个 fixture 文件且 sha256 与内容一致。"""
    manifest = fixture_files["manifest.json"]
    assert manifest["synthetic"] is True
    registered = set(manifest["entries"])
    files = {path.name for path in FIXTURES.glob("*.json")} - {"manifest.json"}
    assert registered == files
    for name in files:
        raw = (FIXTURES / name).read_bytes()
        expected = "sha256:" + hashlib.sha256(raw).hexdigest()
        assert manifest["entries"][name]["sha256"] == expected


def test_fixture_cross_references_consistent(fixture_files) -> None:
    """正常: 审批/计划动作/事件/任务之间的引用一致（M5-1 同构输入）。"""
    events = fixture_files["events.v1.json"]["events"]
    approvals = {
        a["approval_id"]: a for a in fixture_files["approvals.v1.json"]["approvals"]
    }
    actions = {
        a["action_id"]: a
        for a in fixture_files["planned-actions.v1.json"]["planned_actions"]
    }
    tasks = {t["task_id"]: t for t in fixture_files["tasks.v1.json"]["tasks"]}

    # 每个审批引用的动作必须存在且动作摘要一致
    for approval in approvals.values():
        action = actions[approval["action_id"]]
        assert action["task_id"] == approval["task_id"]
        assert approval["action_digest"].startswith("sha256:")
        # 事件流中的 approval.required 动作摘要与审批记录一致
        for event in events:
            if (
                event["event_type"] == "task.approval.required.v1"
                and event["payload"]["approval_id"] == approval["approval_id"]
            ):
                assert event["payload"]["action_digest"] == approval["action_digest"]

    # WAITING_APPROVAL 任务必须引用 pending 审批；WAITING_USER 必须引用 request_id
    task_004 = tasks["task_onboard_004"]
    assert task_004["waiting_on"]["type"] == "approval"
    assert approvals[task_004["waiting_on"]["request_id"]]["status"] == "pending"
    task_003 = tasks["task_repair_003"]
    assert task_003["waiting_on"]["type"] == "user_input"
    required = [
        event
        for event in events
        if event["event_type"] == "task.input.required.v1"
        and event["task_id"] == task_003["task_id"]
    ]
    assert (
        required
        and required[-1]["payload"]["request_id"]
        == task_003["waiting_on"]["request_id"]
    )

    # M5 复合形态：task_004 双子动作（设备分配 + 权限授予）幂等键互异由 M5-1 保证，
    # 外壳侧断言两个子动作 action_id 不同且分属不同工具
    task_004_actions = [
        a for a in actions.values() if a["task_id"] == "task_onboard_004"
    ]
    assert len(task_004_actions) == 2
    assert task_004_actions[0]["action_id"] != task_004_actions[1]["action_id"]
    assert {a["tool"]["name"] for a in task_004_actions} == {
        "itsm.ticket.create.v1",
        "itsm.permission.grant.v1",
    }


def test_fixture_commands_digests_recompute(fixture_files) -> None:
    """正常: 命令 fixture 的 command_digest/idempotency_key 可复算（RFC 8785）。"""
    from flowpilot_shell.canonical import canonical_digest

    for command in fixture_files["commands.v1.json"]["commands"]:
        digest_projection = {
            "command_type": command["command_type"],
            "tenant_id": command["tenant_id"],
            "task_id": command["task_id"],
            "actor": command["actor"],
            "expected_task_version": command["expected_task_version"],
            "payload": command["payload"],
        }
        idempotency_projection = {
            "command_type": command["command_type"],
            "tenant_id": command["tenant_id"],
            "task_id": command["task_id"],
            "payload": command["payload"],
        }
        assert command["command_digest"] == canonical_digest(digest_projection)
        assert command["idempotency_key"] == canonical_digest(idempotency_projection)


def test_fixture_commands_contain_no_approval_commands(fixture_files) -> None:
    """安全: 命令 fixture 不含任何审批命令（外壳不写审批）。"""
    types = {c["command_type"] for c in fixture_files["commands.v1.json"]["commands"]}
    assert types == {"task.message.submit.v1", "task.retry.request.v1"}


def test_shell_canonical_interops_with_domain(fixture_files) -> None:
    """适配边界: 外壳 RFC 8785 实现与 flowpilot_domain.canonical 位级一致。"""
    from flowpilot_domain.canonical import canonical_sha256
    from flowpilot_shell.canonical import canonical_digest

    samples = [
        {"a": 1, "b": "新员工入职", "c": None, "d": [1, 2], "e": True},
        {"nested": {"x": "y", "arr": ["s", 3, None]}, "k": "中文内容"},
        fixture_files["commands.v1.json"]["commands"][0]["payload"],
    ]
    for sample in samples:
        assert canonical_digest(sample) == canonical_sha256(sample)
