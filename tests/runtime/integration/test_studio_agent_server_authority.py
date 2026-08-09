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
    ):
        await _assert_server_command_rejected(
            client,
            command,
            expected_message=expected_message,
        )

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
) -> tuple[dict[str, Any], tuple[str, ...], int, bool, int, str]:
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
    )


def _interrupt_kind(result: Mapping[str, Any]) -> str:
    interrupts = result.get("__interrupt__")
    assert isinstance(interrupts, list)
    assert len(interrupts) == 1
    value = interrupts[0].get("value")
    assert isinstance(value, Mapping)
    return str(value.get("kind"))
