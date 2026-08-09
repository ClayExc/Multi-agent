from __future__ import annotations

import asyncio
import copy
import os
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from langgraph_sdk import get_client
from langgraph_sdk.errors import InternalServerError

from artifacts.acceptance.generators import (
    studio_agent_server as server_support,
)

ROOT = Path(__file__).resolve().parents[3]
GRAPH_ID = "flowpilot_it_service"


def test_real_agent_server_rejects_command_and_state_authority() -> None:
    runtime_directory = ROOT / ".langgraph_api"
    assert not runtime_directory.exists()
    port = server_support._allocate_local_port()  # noqa: SLF001
    base_url = f"http://127.0.0.1:{port}"
    command = [
        sys.executable,
        "-B",
        "-m",
        "langgraph_cli",
        "dev",
        "--config",
        "langgraph.json",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--no-browser",
    ]
    creationflags = 0
    if os.name == "nt":
        creationflags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )

    with tempfile.TemporaryFile() as log_file:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=server_support._server_environment(),  # noqa: SLF001
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
        try:
            server_support._wait_until_ready(  # noqa: SLF001
                process,
                base_url,
                timeout_seconds=30.0,
                log_file=log_file,
            )
            asyncio.run(_probe_authority_boundaries(base_url))
        finally:
            server_support._stop_process_tree(process)  # noqa: SLF001
            assert process.poll() is not None
            assert server_support._port_released(port)  # noqa: SLF001
            assert server_support._remove_runtime_directory(ROOT)  # noqa: SLF001


async def _probe_authority_boundaries(base_url: str) -> None:
    client = get_client(url=base_url)
    for command, expected_message in (
        (
            {
                "resume": {"confirmed": True},
                "update": {
                    "approval_granted": True,
                    "checkpoint_sequence": 99,
                },
            },
            "Studio command may only contain a resume decision",
        ),
        (
            {"resume": {"confirmed": True}, "goto": "finalize"},
            "Studio command may only contain a resume decision",
        ),
        (
            {
                "resume": {
                    "confirmed": True,
                    "approval_granted": True,
                }
            },
            "Studio command resume decision is not registered",
        ),
        (
            {"resume": {"confirmed": {"nested": True}}},
            "Studio command resume decision is not registered",
        ),
        (
            {"resume": {"approved": True}},
            "Studio resume decision does not match the current interrupt",
        ),
    ):
        await _assert_server_command_rejected(
            client,
            command,
            expected_message=expected_message,
        )

    approval_thread = await _suspended_thread(client)
    approval = await client.runs.wait(
        approval_thread,
        GRAPH_ID,
        command={"resume": {"confirmed": True}},
    )
    assert _interrupt_kind(approval) == "approval"
    before_replay = await _server_state_fingerprint(
        client,
        approval_thread,
    )
    replay = await client.runs.wait(
        approval_thread,
        GRAPH_ID,
        command={"resume": {"confirmed": True}},
        raise_error=False,
    )
    assert replay == {
        "__error__": {
            "error": "GraphError",
            "message": (
                "Studio resume decision does not match the current interrupt"
            ),
        }
    }
    after_replay = await _server_state_fingerprint(client, approval_thread)
    assert after_replay == before_replay
    replay_values, replay_next, _, _, replay_sequence, replay_status, kind = (
        after_replay
    )
    assert replay_next == ("approval_interrupt",)
    assert replay_values["artifact_count"] == 0
    assert "failure_code" not in replay_values
    assert replay_sequence == 1
    assert replay_status == "RUNNING"
    assert kind == "approval"

    checkpoint_thread = await _suspended_thread(client)
    clarification_state = await client.threads.get_state(checkpoint_thread)
    clarification_checkpoint = _state_checkpoint_id(clarification_state)
    checkpoint_approval = await client.runs.wait(
        checkpoint_thread,
        GRAPH_ID,
        command={"resume": {"confirmed": True}},
    )
    assert _interrupt_kind(checkpoint_approval) == "approval"
    approval_state = await client.threads.get_state(checkpoint_thread)
    approval_checkpoint = _state_checkpoint_id(approval_state)
    before_historical_clarification = await _server_state_fingerprint(
        client,
        checkpoint_thread,
    )
    historical_clarification = await client.runs.wait(
        checkpoint_thread,
        GRAPH_ID,
        command={"resume": {"confirmed": True}},
        checkpoint_id=clarification_checkpoint,
        raise_error=False,
    )
    assert historical_clarification == {
        "__error__": {
            "error": "GraphError",
            "message": "Studio resume must target the latest checkpoint",
        }
    }
    assert await _server_state_fingerprint(
        client,
        checkpoint_thread,
    ) == before_historical_clarification

    checkpoint_completed = await client.runs.wait(
        checkpoint_thread,
        GRAPH_ID,
        command={"resume": {"approved": True}},
        checkpoint_id=approval_checkpoint,
    )
    assert checkpoint_completed["status"] == "COMPLETED"
    terminal_before_replay = await _server_state_fingerprint(
        client,
        checkpoint_thread,
    )
    historical_approval = await client.runs.wait(
        checkpoint_thread,
        GRAPH_ID,
        command={"resume": {"approved": True}},
        checkpoint_id=approval_checkpoint,
        raise_error=False,
    )
    assert historical_approval == {
        "__error__": {
            "error": "GraphError",
            "message": "Studio resume must target the latest checkpoint",
        }
    }
    assert await _server_state_fingerprint(
        client,
        checkpoint_thread,
    ) == terminal_before_replay

    thread_id = await _suspended_thread(client)
    before = await _server_state_fingerprint(client, thread_id)
    with pytest.raises(InternalServerError) as update_failure:
        await client.threads.update_state(
            thread_id,
            {
                "approval_granted": True,
                "checkpoint_sequence": 99,
            },
        )
    assert update_failure.value.status_code == 500
    refreshed_client = get_client(url=base_url)
    after = await _server_state_fingerprint(refreshed_client, thread_id)
    assert after == before

    normal_thread = await _suspended_thread(client)
    approval = await client.runs.wait(
        normal_thread,
        GRAPH_ID,
        command={"resume": {"confirmed": True}},
    )
    assert _interrupt_kind(approval) == "approval"
    completed = await client.runs.wait(
        normal_thread,
        GRAPH_ID,
        command={"resume": {"approved": True}},
    )
    assert completed["status"] == "COMPLETED"
    assert completed["checkpoint_sequence"] == 4
    assert completed["retry_count"] == 1

    denied_thread = await _suspended_thread(client)
    denied_approval = await client.runs.wait(
        denied_thread,
        GRAPH_ID,
        command={"resume": {"confirmed": True}},
    )
    assert _interrupt_kind(denied_approval) == "approval"
    denied = await client.runs.wait(
        denied_thread,
        GRAPH_ID,
        command={"resume": {"approved": False}},
    )
    assert denied["status"] == "FAILED"
    assert denied["failure_code"] == "STUDIO_APPROVAL_DENIED"
    assert denied["artifact_count"] == 0


async def _assert_server_command_rejected(
    client: Any,
    command: Mapping[str, Any],
    *,
    expected_message: str,
) -> None:
    thread_id = await _suspended_thread(client)
    before = await _server_state_fingerprint(client, thread_id)
    result = await client.runs.wait(
        thread_id,
        GRAPH_ID,
        command=dict(command),
        raise_error=False,
    )
    assert result == {
        "__error__": {
            "error": "GraphError",
            "message": expected_message,
        }
    }
    after = await _server_state_fingerprint(client, thread_id)
    assert after == before


async def _suspended_thread(client: Any) -> str:
    thread = await client.threads.create()
    thread_id = str(thread["thread_id"])
    waiting = await client.runs.wait(
        thread_id,
        GRAPH_ID,
        input={"scenario": "full_demo"},
    )
    assert _interrupt_kind(waiting) == "clarification"
    return thread_id


async def _server_state_fingerprint(
    client: Any,
    thread_id: str,
) -> tuple[dict[str, Any], tuple[str, ...], int, bool, int, str, str | None]:
    state = await client.threads.get_state(thread_id)
    history = await client.threads.get_history(thread_id, limit=100)
    values = copy.deepcopy(dict(state["values"]))
    return (
        values,
        tuple(state["next"]),
        len(history),
        bool(values["approval_granted"]),
        int(values["checkpoint_sequence"]),
        str(values["status"]),
        _state_interrupt_kind(state),
    )


def _state_interrupt_kind(state: Mapping[str, Any]) -> str | None:
    tasks = state.get("tasks")
    assert isinstance(tasks, list)
    if not tasks:
        return None
    assert len(tasks) == 1
    interrupts = tasks[0].get("interrupts")
    assert isinstance(interrupts, list)
    assert len(interrupts) == 1
    value = interrupts[0].get("value")
    assert isinstance(value, Mapping)
    return str(value.get("kind"))


def _state_checkpoint_id(state: Mapping[str, Any]) -> str:
    checkpoint = state.get("checkpoint")
    assert isinstance(checkpoint, Mapping)
    checkpoint_id = checkpoint.get("checkpoint_id")
    assert isinstance(checkpoint_id, str)
    assert checkpoint_id
    return checkpoint_id


def _interrupt_kind(result: Mapping[str, Any]) -> str:
    interrupts = result.get("__interrupt__")
    assert isinstance(interrupts, list)
    assert len(interrupts) == 1
    value = interrupts[0].get("value")
    assert isinstance(value, Mapping)
    return str(value.get("kind"))
