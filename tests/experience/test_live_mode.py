"""Authoritative live API/SSE mode: convergence, recovery and authority."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from copy import deepcopy

import pytest


class FakeApi:
    def __init__(self, tasks: list[object]) -> None:
        self.tasks = list(tasks)
        self.calls: list[str] = []

    def get_task(self, task_id: str):
        self.calls.append(task_id)
        if not self.tasks:
            raise AssertionError("unexpected authoritative Task refresh")
        return self.tasks.pop(0)


def _event(raw_task: dict, *, sequence: int, tenant_id: str = "tenant-it"):
    from flowpilot_shell.sse_client import SseEvent

    event_id = f"evt_live_mode_{sequence:04d}"
    envelope = {
        "event_id": event_id,
        "event_type": "task.status.changed.v1",
        "tenant_id": tenant_id,
        "task_id": raw_task["task_id"],
        "thread_id": raw_task["thread_id"],
        "task_version": sequence,
        "sequence": sequence,
        "trace_id": f"trace-live-mode-{sequence:04d}",
        "run_id": "run_live_mode_0001",
        "producer": "worker",
        "producer_principal_ref": "workload://worker/default",
        "correlation_id": "corr_live_mode_0001",
        "causation_id": None,
        "data_classification": "internal",
        "payload": {
            "from": "RUNNING",
            "to": raw_task["status"],
            "reason_code": "projection_changed",
        },
        "occurred_at": raw_task["updated_at"],
    }
    return SseEvent(
        event="task.event",
        id=event_id,
        data=json.dumps(envelope, ensure_ascii=False),
    )


def _task_states(fixture_files):
    from flowpilot_shell.models import TaskView

    base = deepcopy(
        next(
            item
            for item in fixture_files["tasks.v1.json"]["tasks"]
            if item["task_id"] == "task_repair_003"
        )
    )
    waiting_user = TaskView.from_mapping(base)
    approval = deepcopy(base)
    approval["status"] = "WAITING_APPROVAL"
    approval["version"] += 1
    approval["waiting_on"] = {
        "type": "approval",
        "request_id": "apr_live_mode_0001",
        "expires_at": None,
    }
    waiting_approval = TaskView.from_mapping(approval)
    completed = deepcopy(approval)
    completed["status"] = "COMPLETED"
    completed["version"] += 1
    completed["waiting_on"] = None
    completed["result_ref"] = "result://task/live-mode-result"
    completed["completed_at"] = completed["updated_at"]
    completed["active_run_id"] = None
    terminal = TaskView.from_mapping(completed)
    return base, waiting_user, waiting_approval, terminal


def test_live_session_refreshes_authoritative_projection_on_gap(fixture_files) -> None:
    from flowpilot_shell.live import LiveSession

    raw, _waiting, approval, _terminal = _task_states(fixture_files)
    api = FakeApi([approval])
    session = LiveSession(api)

    update = session.ingest(_event(raw, sequence=2))

    assert update.gaps == (1,)
    assert update.projection_refreshed is True
    assert session.store.task(raw["task_id"]).status == "WAITING_APPROVAL"
    assert session.reconnect_headers() == {"Last-Event-ID": update.event_id}
    assert api.calls == [raw["task_id"]]


def test_live_session_handles_multiple_interrupts_and_terminal_refresh(
    fixture_files,
) -> None:
    from flowpilot_shell.live import LiveSession

    raw, waiting_user, waiting_approval, terminal = _task_states(fixture_files)
    api = FakeApi([waiting_user, waiting_approval, terminal])
    session = LiveSession(api)

    statuses = []
    for sequence in (1, 2, 3):
        session.ingest(_event(raw, sequence=sequence))
        statuses.append(session.store.task(raw["task_id"]).status)

    assert statuses == ["WAITING_USER", "WAITING_APPROVAL", "COMPLETED"]
    assert session.store.task(raw["task_id"]).result_ref == (
        "result://task/live-mode-result"
    )


def test_live_session_rejects_forged_event_and_projection_tenant(
    fixture_files,
) -> None:
    from flowpilot_shell.live import LiveSession
    from flowpilot_shell.models import ShellContractError, TaskView

    raw, waiting_user, _approval, _terminal = _task_states(fixture_files)
    api = FakeApi([waiting_user])
    session = LiveSession(api)
    with pytest.raises(ShellContractError, match="authoritative Task"):
        session.ingest(_event(raw, sequence=1, tenant_id="tenant-forged"))
    assert api.calls == [raw["task_id"]]

    forged = deepcopy(raw)
    forged["tenant_id"] = "tenant-forged"
    projection_api = FakeApi([TaskView.from_mapping(forged)])
    projection_session = LiveSession(projection_api)
    with pytest.raises(ShellContractError, match="authoritative Task"):
        projection_session.ingest(_event(raw, sequence=1))


def test_live_session_deduplicates_replay_without_another_task_read(
    fixture_files,
) -> None:
    from flowpilot_shell.live import LiveSession

    raw, waiting_user, _approval, _terminal = _task_states(fixture_files)
    api = FakeApi([waiting_user])
    session = LiveSession(api)
    frame = _event(raw, sequence=1)

    first = session.ingest(frame)
    replay = session.ingest(frame)

    assert first.projection_refreshed is True
    assert replay.projection_refreshed is False
    assert api.calls == [raw["task_id"]]
    assert len(session.store.timeline_events(raw["task_id"])) == 1


def test_live_backend_requires_server_owned_configuration() -> None:
    from flowpilot_shell.models import ShellContractError

    from web.server import build_backend

    with pytest.raises(ShellContractError, match="requires"):
        build_backend({"WEB_SHELL_MODE": "live"})
    with pytest.raises(ShellContractError, match="demo or live"):
        build_backend({"WEB_SHELL_MODE": "browser-selected"})


def test_live_server_rejects_raw_browser_authority() -> None:
    from web.server import DemoServer, LiveBackend

    server = DemoServer(
        LiveBackend("http://127.0.0.1:1"),
        0,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    request = urllib.request.Request(
        f"http://{host}:{port}/api/v1/task-commands",
        data=json.dumps(
            {
                "tenant_id": "tenant-forged",
                "security_context": {"tenant_id": "tenant-forged"},
            }
        ).encode(),
        headers={
            "Content-Type": "application/json",
            "X-FlowPilot-Tenant-Id": "tenant-forged",
        },
        method="POST",
    )
    try:
        with pytest.raises(urllib.error.HTTPError) as captured:
            urllib.request.urlopen(request, timeout=5)
        assert captured.value.code == 403
        payload = json.loads(captured.value.read().decode())
        assert payload["error"]["code"] == "BROWSER_AUTHORITY_FORBIDDEN"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
