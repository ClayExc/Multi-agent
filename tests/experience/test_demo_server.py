"""Demo server tests: serve pages, fixture API, SSE shape, command intake.

正常=演示页/视图/API/SSE 可用且数据与 fixture 一致；失败=404/503 错误面板；
恢复=Last-Event-ID 续传与重建入口；安全=补全提交/重试走非审批命令路径，
版本冲突被拒绝。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from urllib.parse import urlencode

import pytest
from flowpilot_shell.sse_client import parse_sse


def _get(
    base: str, path: str, headers: dict[str, str] | None = None
) -> tuple[int, bytes]:
    request = urllib.request.Request(base + path, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _post_form(base: str, path: str, data: dict[str, str]) -> tuple[int, dict]:
    body = urlencode(data).encode("utf-8")
    request = urllib.request.Request(
        base + path,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _first_sse_event(
    base: str, path: str = "/api/v1/tasks/events", headers: dict[str, str] | None = None
) -> dict:
    """Read the SSE stream frame-by-frame until the first task.event, then close."""
    request = urllib.request.Request(base + path, headers=headers or {})
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status == 200
        assert response.headers.get("Content-Type", "").startswith("text/event-stream")
        buffer = b""
        while True:
            chunk = response.read(4096)
            if not chunk:
                break
            buffer += chunk
            while True:
                boundary = buffer.find(b"\n\n")
                if boundary < 0:
                    break
                frame = buffer[:boundary]
                buffer = buffer[boundary + 2 :]
                if frame.startswith(b":"):
                    continue  # keep-alive ping
                events = list(parse_sse([frame + b"\n\n"]))
                for parsed in events:
                    if parsed.event == "task.event":
                        return json.loads(parsed.data)
    raise AssertionError("SSE stream ended without a task.event frame")


def test_serves_shell_index(demo_server) -> None:
    """正常: 演示页可访问。"""
    _server, base = demo_server
    status, body = _get(base, "/")
    assert status == 200
    text = body.decode("utf-8")
    assert "FlowPilot 工作台" in text
    assert "app.js" in text


def test_serves_static_assets(demo_server) -> None:
    """正常: 静态外壳资源可访问。"""
    _server, base = demo_server
    status, body = _get(base, "/static/app.js")
    assert status == 200
    assert b"EventSource" in body
    status, _ = _get(base, "/static/shell.css")
    assert status == 200


def test_serves_fixture_api(demo_server) -> None:
    """正常: 模拟 API 返回 Task v1 投影（与 fixture 一致）。"""
    _server, base = demo_server
    status, body = _get(base, "/api/v1/tasks/task_onboard_001")
    assert status == 200
    payload = json.loads(body)
    assert payload["task_id"] == "task_onboard_001"
    assert payload["status"] == "COMPLETED"
    assert payload["result_ref"] == "ref://artifacts/res_onboard_001"


def test_api_404_and_503_demo_modes(demo_server) -> None:
    """失败: 未知任务 404 / 模拟不可用 503，均返回 ErrorEnvelope。"""
    _server, base = demo_server
    status, body = _get(base, "/api/v1/tasks/task_missing_9999")
    assert status == 404
    assert json.loads(body)["error"]["code"] == "TASK_NOT_FOUND"
    status, body = _get(base, "/api/v1/tasks/task_onboard_001?simulate=unavailable")
    assert status == 503
    assert json.loads(body)["error"]["retryable"] is True


def test_views_task_list_and_detail(demo_server) -> None:
    """正常: 服务端渲染的任务列表与详情片段可浏览。"""
    _server, base = demo_server
    status, body = _get(base, "/views/tasks")
    assert status == 200
    text = body.decode("utf-8")
    assert "task_onboard_001" in text and "task_inventory_005" in text
    status, body = _get(base, "/views/tasks/task_onboard_004")
    text = body.decode("utf-8")
    assert "等待审批" in text
    assert "审批卡" in text
    assert "itsm.permission.grant.v1" in text


def test_views_error_panels(demo_server) -> None:
    """失败: 视图级 503/404 渲染错误面板与重试入口（不渲染假数据）。"""
    _server, base = demo_server
    status, body = _get(base, "/views/tasks/task_onboard_001?demo=unavailable")
    text = body.decode("utf-8")
    assert "加载失败" in text and "可重试" in text and 'data-action="retry"' in text
    status, body = _get(base, "/views/tasks/task_missing_9999")
    text = body.decode("utf-8")
    assert "任务不存在" in text
    assert "task-row" not in text


def test_sse_stream_shape_matches_stream_py(demo_server) -> None:
    """正常: SSE 帧形态与 apps/api stream.py 一致（id/event/data + 事件 JSON）。"""
    event = _first_sse_event(demo_server[1])
    assert event["event_type"] in {
        "task.created.v1",
        "task.status.changed.v1",
        "task.approval.required.v1",
    }
    assert event["event_id"].startswith("evt_")
    assert event["task_id"].startswith("task_")
    assert event["tenant_id"] == "tenant-it"


def test_sse_resume_with_last_event_id(demo_server) -> None:
    """恢复: Last-Event-ID 续传（重连从断点后补发）。"""
    event = _first_sse_event(demo_server[1])
    first_id = event["event_id"]
    resumed = _first_sse_event(demo_server[1], headers={"Last-Event-ID": first_id})
    assert resumed["event_id"] != first_id


def test_completion_form_submit_updates_stream(demo_server) -> None:
    """正常: 信息补全表单提交被受理，SSE 流出现后续状态事件。"""
    _server, base = demo_server
    status, payload = _post_form(
        base,
        "/shell/commands/submit",
        {"task_id": "task_repair_003", "request_id": "req_repair_0001"},
    )
    assert status == 200
    assert payload["accepted"] is True
    receipt = payload["receipt"]
    assert receipt["task_id"] == "task_repair_003"
    assert receipt["execution_receipt"]["disposition"] == "accepted"
    # 受理后投影前进（WAITING_USER → RUNNABLE → RUNNING，任务仍处于等待）
    status, body = _get(base, "/api/v1/tasks/task_repair_003")
    assert json.loads(body)["status"] == "RUNNING"


def test_retry_command_accepts_and_moves_projection(demo_server) -> None:
    """正常: 错误面板重试入口提交 retry 命令并被受理。"""
    _server, base = demo_server
    status, payload = _post_form(
        base, "/shell/commands/retry", {"task_id": "task_inventory_005"}
    )
    assert status == 200
    assert payload["accepted"] is True
    status, body = _get(base, "/api/v1/tasks/task_inventory_005")
    projection = json.loads(body)
    assert projection["status"] == "RUNNABLE"
    assert projection["error"] is None


def test_version_conflict_rejected(demo_server) -> None:
    """失败: 版本冲突的命令被拒绝（409），不产生任何副作用。"""
    from flowpilot_shell.commands import build_submit_message_command

    _server, base = demo_server
    status, body = _get(base, "/api/v1/tasks/task_repair_003")
    projection = json.loads(body)
    command = build_submit_message_command(
        tenant_id=projection["tenant_id"],
        task_id=projection["task_id"],
        actor={"type": "user", "id": projection["security_context"]["subject_id"]},
        security_context=projection["security_context"],
        expected_task_version=999,  # 故意不匹配
        message_id="msg_stale_0001",
        message_ref="ref://messages/stale",
    )
    raw = json.dumps(command).encode("utf-8")
    request = urllib.request.Request(
        base + "/api/v1/task-commands",
        data=raw,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(request, timeout=10)
    assert excinfo.value.code == 409
    envelope = json.loads(excinfo.value.read().decode("utf-8"))
    assert envelope["error"]["code"] == "TASK_VERSION_CONFLICT"
    # 投影未被推进
    _status, body = _get(base, "/api/v1/tasks/task_repair_003")
    assert json.loads(body)["status"] == "WAITING_USER"


def test_approval_decide_command_rejected_by_demo_backend(demo_server) -> None:
    """安全: 即使伪造审批命令，演示后端也拒绝（外壳侧本就不构建此类命令）。"""
    from flowpilot_shell.commands import build_submit_message_command

    _server, base = demo_server
    status, body = _get(base, "/api/v1/tasks/task_onboard_004")
    projection = json.loads(body)
    forged = build_submit_message_command(
        tenant_id=projection["tenant_id"],
        task_id=projection["task_id"],
        actor={"type": "user", "id": projection["security_context"]["subject_id"]},
        security_context=projection["security_context"],
        expected_task_version=projection["version"],
        message_id="msg_forged_0001",
        message_ref="ref://messages/forged",
    )
    forged["command_type"] = "task.approval.decide.v1"
    raw = json.dumps(forged).encode("utf-8")
    request = urllib.request.Request(
        base + "/api/v1/task-commands",
        data=raw,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(request, timeout=10)
    assert excinfo.value.code in (409, 422)
    # 审批状态未被推进（不推断审批成功）
    _status, body = _get(base, "/api/v1/tasks/task_onboard_004")
    assert json.loads(body)["status"] == "WAITING_APPROVAL"
