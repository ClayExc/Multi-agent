"""SSE consumption tests: frame parsing, dedupe, gap detection, recovery.

失败=断线重连（重放 + Last-Event-ID 续传、按 event_id 去重）；恢复=序列
缺口检测与重建收敛（TaskEventSubscriptionService gaps 语义在适配层模拟）；
正常=时间线按运行/等待/失败事件重建。
"""

from __future__ import annotations

import json

import pytest


def _frame(envelope: dict) -> bytes:
    return (
        f"id: {envelope['event_id']}\n"
        f"event: task.event\n"
        f"data: {json.dumps(envelope, ensure_ascii=False, separators=(',', ':'))}\n\n"
    ).encode()


def _sse_bytes(events: list[dict]) -> bytes:
    return b"".join(_frame(event) for event in events)


def test_parse_single_frame() -> None:
    from flowpilot_shell.sse_client import parse_sse

    envelope = {"event_id": "evt_0000000001", "a": 1}
    parsed = list(parse_sse([_frame(envelope)]))
    assert len(parsed) == 1
    assert parsed[0].id == "evt_0000000001"
    assert parsed[0].event == "task.event"
    assert json.loads(parsed[0].data) == envelope


def test_parse_frames_split_across_chunks() -> None:
    """正常: 帧被任意切分到多个 chunk 时仍能完整解析（流式边界）。"""
    from flowpilot_shell.sse_client import parse_sse

    events = [
        {"event_id": "evt_0000000001", "a": 1},
        {"event_id": "evt_0000000002", "b": [1, 2]},
    ]
    raw = _sse_bytes(events)
    # 每 3 字节一切，覆盖帧内/帧间切分
    chunks = [raw[i : i + 3] for i in range(0, len(raw), 3)]
    parsed = list(parse_sse(chunks))
    assert [item.id for item in parsed] == ["evt_0000000001", "evt_0000000002"]
    assert [
        json.loads(item.data)["a"] if "a" in item.data else None for item in parsed
    ][0] == 1


def test_parse_crlf_and_ping_comments() -> None:
    """正常: CRLF 行尾与 : ping 心跳被正确处理。"""
    from flowpilot_shell.sse_client import parse_sse

    raw = (
        b": ping\r\n\r\nevent: task.event\r\nid: evt_0000000001\r\n"
        b'data: {"x": 1}\r\n\r\n: ping\n\n'
    )
    parsed = list(parse_sse([raw]))
    assert len(parsed) == 1
    assert parsed[0].id == "evt_0000000001"


def test_parse_multiline_data() -> None:
    """正常: 多行 data 字段按 SSE 规范用换行拼接。"""
    from flowpilot_shell.sse_client import parse_sse

    raw = b"event: task.event\ndata: line1\ndata: line2\n\n"
    parsed = list(parse_sse([raw]))
    assert parsed[0].data == "line1\nline2"


def test_parse_incomplete_trailing_frame_raises() -> None:
    """失败: 流在帧中间结束必须报错而不是静默丢弃。"""
    from flowpilot_shell.sse_client import ShellContractError, parse_sse

    raw = b'id: evt_0000000001\nevent: task.event\ndata: {"x":'
    with pytest.raises(ShellContractError):
        list(parse_sse([raw]))


def test_timeline_dedupes_redelivery(fixture_files) -> None:
    """正常: at-least-once 重投按 event_id 去重。"""
    from flowpilot_shell.models import EventView
    from flowpilot_shell.sse_client import TimelineReconstructor

    events = fixture_files["events.v1.json"]["events"]
    task_events = [e for e in events if e["task_id"] == "task_repair_003"]
    timeline = TimelineReconstructor()
    for _round in range(2):  # 同一批事件投递两次（断线重连重放）
        for event in task_events:
            timeline.ingest(EventView.from_mapping(event))
    assert timeline.counts()["task_repair_003"] == len(task_events)
    assert timeline.gaps_for("task_repair_003") == ()


def test_timeline_detects_sequence_gap(fixture_files) -> None:
    """恢复: task_002 fixture 故意缺失 seq=3，缺口必须被检出。"""
    from flowpilot_shell.models import EventView
    from flowpilot_shell.sse_client import TimelineReconstructor

    events = fixture_files["events.v1.json"]["events"]
    timeline = TimelineReconstructor()
    for event in events:
        if event["task_id"] == "task_vpn_perm_002":
            timeline.ingest(EventView.from_mapping(event))
    assert timeline.gaps_for("task_vpn_perm_002") == (3,)
    sequences = [e.sequence for e in timeline.events_for("task_vpn_perm_002")]
    assert sequences == [1, 2, 4]


def test_timeline_gap_filled_after_replay(fixture_files) -> None:
    """恢复: 重放补齐 seq=3 后缺口消失（重连补齐语义）。"""
    from flowpilot_shell.models import EventView
    from flowpilot_shell.sse_client import TimelineReconstructor

    events = fixture_files["events.v1.json"]["events"]
    timeline = TimelineReconstructor()
    task_events = [e for e in events if e["task_id"] == "task_vpn_perm_002"]
    for event in task_events:
        timeline.ingest(EventView.from_mapping(event))
    assert timeline.gaps_for("task_vpn_perm_002") == (3,)
    gap_event = {
        "event_id": "evt_002gap_00003",
        "event_type": "task.status.changed.v1",
        "tenant_id": "tenant-it",
        "task_id": "task_vpn_perm_002",
        "thread_id": "thread_vpn_perm_002",
        "task_version": 1,
        "sequence": 3,
        "trace_id": "trc_002gap0000003",
        "run_id": "run_0002vpn01",
        "producer": "worker",
        "producer_principal_ref": "workload://worker/default",
        "correlation_id": "corr_002gap0000003",
        "causation_id": None,
        "data_classification": "internal",
        "payload": {"from": "RUNNABLE", "to": "RUNNING", "reason_code": "start"},
        "occurred_at": "2026-08-01T07:37:00Z",
    }
    timeline.ingest(EventView.from_mapping(gap_event))
    assert timeline.gaps_for("task_vpn_perm_002") == ()


def test_store_converges_with_projection(store_with_fixtures) -> None:
    """恢复: 重建后外壳状态与后端终态一致（投影为准 + 事件为史）。"""
    store = store_with_fixtures
    task = store.task("task_inventory_005")
    assert task is not None and task.status == "FAILED"
    assert task.error is not None and task.error.code == "INVENTORY_INSUFFICIENT"
    # 时间线包含失败事件
    event_types = [e.event_type for e in store.timeline_events("task_inventory_005")]
    assert "task.failed.v1" in event_types
    # 重建不改变投影（终态一致）
    store.rebuild_from_projection(task)
    assert store.task("task_inventory_005").status == "FAILED"


def test_waiting_and_approval_events_reconstruct(store_with_fixtures) -> None:
    """正常: 等待状态任务的事件时间线完整（信息补全 / 审批等待）。"""
    store = store_with_fixtures
    repair_types = [e.event_type for e in store.timeline_events("task_repair_003")]
    assert "task.input.required.v1" in repair_types
    approval_types = [e.event_type for e in store.timeline_events("task_onboard_004")]
    assert "task.approval.required.v1" in approval_types
    # 等待字段来自投影
    assert store.task("task_repair_003").waiting_on.request_id == "req_repair_0001"
    assert store.task("task_onboard_004").waiting_on.request_id == "apr_00000004"
