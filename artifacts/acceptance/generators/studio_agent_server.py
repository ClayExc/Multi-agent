"""Generate sanitized evidence from a real local LangGraph Agent Server.

The probe starts the locked local development server without a browser, drives
the public Agent Server API, and stops the complete process tree. It consumes
only API responses and an S4-owned topology oracle; it does not import the
Worker graph or any producer test fixture.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from langgraph_sdk import get_client

SCHEMA_VERSION = "flowpilot.studio-agent-server-evidence.m2.v1"
GRAPH_ID = "flowpilot_it_service"
_EXPECTED_PATH = (
    "prepare",
    "build_context",
    "route_request",
    "clarification_interrupt",
    "build_context",
    "route_request",
    "knowledge_read",
    "service_read",
    "join_reads",
    "handoff",
    "route_request",
    "approval_interrupt",
    "run_agent",
    "route_result",
    "retry",
    "run_agent",
    "route_result",
    "finalize",
)
_EXPECTED_HISTORY_SEQUENCES = (
    4,
    3,
    3,
    3,
    2,
    2,
    2,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    0,
    0,
    0,
    0,
    0,
)
_EXPECTED_FRAME_SEQUENCES = (
    0,
    0,
    0,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    2,
    2,
    2,
    3,
    3,
    3,
    4,
)
_PRODUCTION_ENVIRONMENT_KEYS = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "DATABASE_URL",
        "FLOWPILOT_PRODUCTION_ENV",
        "LANGCHAIN_API_KEY",
        "LANGGRAPH_CLOUD_LICENSE_KEY",
        "LANGSMITH_API_KEY",
        "MCP_GATEWAY_TOKEN",
        "OPENAI_API_KEY",
        "REDIS_URL",
    }
)
_BUSINESS_SOURCE_ROOTS = (
    "apps",
    "domain-packs",
    "infra",
    "migrations",
    "packages",
)
_FRAME_KEYS = frozenset(
    {
        "budget",
        "context",
        "failure_code",
        "frame_id",
        "handoff",
        "interrupt",
        "knowledge",
        "node",
        "profile",
        "recovery",
        "route",
        "schema",
        "status",
        "step",
        "terminal_reason",
        "tools",
    }
)
_NESTED_FRAME_KEYS = {
    "budget": frozenset(
        {"remaining_steps", "retry_count", "maximum_retries"}
    ),
    "recovery": frozenset(
        {
            "task_ref",
            "checkpoint_sequence",
            "run_generation",
            "lease_status",
        }
    ),
    "interrupt": frozenset({"kind", "resolved"}),
    "handoff": frozenset(
        {
            "count",
            "reason_code",
            "context_rebuilt",
            "tool_scope_rebuilt",
        }
    ),
    "context": frozenset(
        {"layers", "token_budget", "trim_reason_code"}
    ),
    "tools": frozenset({"mode", "stage"}),
    "knowledge": frozenset(
        {"call_count", "citation_count", "service_read_skipped"}
    ),
}
_SENSITIVE_SENTINELS = (
    "tenant-production-sentinel",
    "provider-secret-sentinel",
    "provider-session-sentinel",
    "person@example.invalid",
    "hidden-context-sentinel",
    "future-state-sentinel",
)


class StudioAgentServerError(RuntimeError):
    """Raised when local Agent Server evidence is incomplete or unsafe."""


def _mapping(value: object, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise StudioAgentServerError(f"{field} must be an object")
    return {str(key): item for key, item in value.items()}


def _mapping_list(value: object, *, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
        raise StudioAgentServerError(f"{field} must be an array")
    return [
        _mapping(item, field=f"{field}[{index}]")
        for index, item in enumerate(value)
    ]


def _strict_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(
        pairs: list[tuple[str, Any]],
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise StudioAgentServerError(
                    f"duplicate JSON key in {path.name}: {key}"
                )
            result[key] = value
        return result

    try:
        decoded = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StudioAgentServerError(
            f"cannot load topology oracle: {path}"
        ) from exc
    return _mapping(decoded, field="topology_oracle")


def _normalized_topology(
    graph: Mapping[str, Any],
) -> tuple[list[str], list[dict[str, Any]]]:
    nodes = _mapping_list(graph.get("nodes"), field="graph.nodes")
    edges = _mapping_list(graph.get("edges"), field="graph.edges")
    node_ids = sorted(str(node.get("id")) for node in nodes)
    normalized_edges = sorted(
        (
            {
                "conditional": edge.get("conditional") is True,
                "source": str(edge.get("source")),
                "target": str(edge.get("target")),
            }
            for edge in edges
        ),
        key=lambda edge: (
            edge["source"],
            edge["target"],
            edge["conditional"],
        ),
    )
    return node_ids, normalized_edges


def _validate_topology(
    graph: Mapping[str, Any],
    oracle: Mapping[str, Any],
) -> tuple[int, int, str]:
    if oracle.get("graph_id") != GRAPH_ID:
        raise StudioAgentServerError("topology oracle graph_id differs")
    actual_nodes, actual_edges = _normalized_topology(graph)
    expected_nodes = sorted(
        str(value)
        for value in oracle.get("node_ids", [])
        if isinstance(value, str)
    )
    expected_edges = sorted(
        _mapping_list(oracle.get("edges"), field="topology_oracle.edges"),
        key=lambda edge: (
            str(edge.get("source")),
            str(edge.get("target")),
            edge.get("conditional") is True,
        ),
    )
    if actual_nodes != expected_nodes:
        raise StudioAgentServerError(
            "Agent Server node topology differs from the S4 oracle"
        )
    if actual_edges != expected_edges:
        raise StudioAgentServerError(
            "Agent Server edge topology differs from the S4 oracle"
        )
    normalized = {
        "graph_id": GRAPH_ID,
        "node_ids": actual_nodes,
        "edges": actual_edges,
    }
    canonical = json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    digest = "sha256:" + hashlib.sha256(canonical).hexdigest()
    return len(actual_nodes), len(actual_edges), digest


def _interrupt_kind(result: Mapping[str, Any], *, field: str) -> str:
    interrupts = _mapping_list(
        result.get("__interrupt__"),
        field=f"{field}.__interrupt__",
    )
    if len(interrupts) != 1:
        raise StudioAgentServerError(
            f"{field} must expose exactly one interrupt"
        )
    value = _mapping(
        interrupts[0].get("value"),
        field=f"{field}.__interrupt__[0].value",
    )
    kind = value.get("kind")
    if not isinstance(kind, str):
        raise StudioAgentServerError(f"{field} interrupt kind is missing")
    return kind


def _state_values(state: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    return _mapping(state.get("values"), field=f"{field}.values")


def _require_state_next(
    state: Mapping[str, Any],
    expected: Sequence[str],
    *,
    field: str,
) -> None:
    actual = state.get("next")
    if not isinstance(actual, Sequence) or isinstance(
        actual, (str, bytes, bytearray)
    ):
        raise StudioAgentServerError(f"{field}.next must be an array")
    if list(actual) != list(expected):
        raise StudioAgentServerError(f"{field}.next is not aligned")


def _validate_projection(
    frames: Sequence[Mapping[str, Any]],
) -> tuple[list[int], bool]:
    if len(frames) != 18:
        raise StudioAgentServerError("full_demo must expose 18 debug frames")
    sequences: list[int] = []
    for index, frame in enumerate(frames):
        if frozenset(frame) != _FRAME_KEYS:
            raise StudioAgentServerError(
                f"debug_projection[{index}] changed its closed field set"
            )
        if frame.get("schema") != "flowpilot.debug-projection.v1":
            raise StudioAgentServerError(
                f"debug_projection[{index}] schema differs"
            )
        if frame.get("profile") != "studio-safe":
            raise StudioAgentServerError(
                f"debug_projection[{index}] profile is not studio-safe"
            )
        for name, expected_keys in _NESTED_FRAME_KEYS.items():
            nested = _mapping(
                frame.get(name),
                field=f"debug_projection[{index}].{name}",
            )
            if frozenset(nested) != expected_keys:
                raise StudioAgentServerError(
                    f"debug_projection[{index}].{name} fields differ"
                )
        recovery = _mapping(
            frame["recovery"],
            field=f"debug_projection[{index}].recovery",
        )
        sequence = recovery.get("checkpoint_sequence")
        if isinstance(sequence, bool) or not isinstance(sequence, int):
            raise StudioAgentServerError(
                f"debug_projection[{index}] checkpoint sequence is invalid"
            )
        sequences.append(sequence)
        if recovery.get("run_generation") != 1:
            raise StudioAgentServerError(
                f"debug_projection[{index}] run_generation differs"
            )
        tools = _mapping(
            frame["tools"],
            field=f"debug_projection[{index}].tools",
        )
        if tools.get("mode") != "fake_readonly":
            raise StudioAgentServerError(
                f"debug_projection[{index}] tool mode is not readonly"
            )
        if tools.get("stage") not in {
            "proposal_only",
            "result_verified",
            "no_authoritative_write",
        }:
            raise StudioAgentServerError(
                f"debug_projection[{index}] tool stage is not closed"
            )
    if tuple(sequences) != _EXPECTED_FRAME_SEQUENCES:
        raise StudioAgentServerError(
            "debug frame checkpoint sequences do not align"
        )
    serialized = json.dumps(frames, ensure_ascii=False, sort_keys=True)
    forbidden = (
        *_SENSITIVE_SENTINELS,
        "api_key",
        "provider_session",
        "raw_context",
        "tenant_id",
        "future_unclassified_state",
    )
    if any(value in serialized for value in forbidden):
        raise StudioAgentServerError(
            "debug projection contains sensitive or unclassified state"
        )
    return sequences, True


def _validate_error(
    result: Mapping[str, Any],
    state: Mapping[str, Any],
    *,
    expected_message: str,
) -> None:
    error = _mapping(result.get("__error__"), field="run.__error__")
    if (
        error.get("error") != "GraphError"
        or error.get("message") != expected_message
    ):
        raise StudioAgentServerError("Agent Server error is not stable")
    values = _state_values(state, field="error_state")
    if (
        values.get("step_count") != 0
        or values.get("visited_nodes") != []
        or values.get("debug_projection") != []
    ):
        raise StudioAgentServerError(
            "rejected input advanced graph execution"
        )
    _require_state_next(state, ["prepare"], field="error_state")


def _validate_checkpoint_history(
    history: Sequence[Mapping[str, Any]],
) -> tuple[list[int], list[int]]:
    if len(history) != 19:
        raise StudioAgentServerError(
            "full_demo checkpoint history must contain 19 states"
        )
    steps: list[int] = []
    sequences: list[int] = []
    for index, state in enumerate(history):
        metadata = _mapping(
            state.get("metadata"),
            field=f"history[{index}].metadata",
        )
        step = metadata.get("step")
        if isinstance(step, bool) or not isinstance(step, int):
            raise StudioAgentServerError(
                f"history[{index}] metadata step is invalid"
            )
        steps.append(step)
        values = _state_values(state, field=f"history[{index}]")
        sequence = values.get("checkpoint_sequence", 0)
        if isinstance(sequence, bool) or not isinstance(sequence, int):
            raise StudioAgentServerError(
                f"history[{index}] checkpoint sequence is invalid"
            )
        sequences.append(sequence)
    if steps != list(range(17, -2, -1)):
        raise StudioAgentServerError(
            "checkpoint metadata steps contain a gap or duplicate"
        )
    if tuple(sequences) != _EXPECTED_HISTORY_SEQUENCES:
        raise StudioAgentServerError(
            "checkpoint history sequences do not align with resumes"
        )
    for newer, older in zip(history, history[1:], strict=False):
        if newer.get("parent_checkpoint_id") != older.get("checkpoint_id"):
            raise StudioAgentServerError(
                "checkpoint parent chain is not closed"
            )
    return steps, sequences


async def _probe_agent_server(
    base_url: str,
    topology_oracle: Mapping[str, Any],
) -> dict[str, Any]:
    client = get_client(url=base_url)
    assistants = await client.assistants.search()
    registered = _mapping_list(assistants, field="assistants")
    graph_ids = sorted(
        str(assistant.get("graph_id")) for assistant in registered
    )
    if graph_ids != [GRAPH_ID]:
        raise StudioAgentServerError(
            "Agent Server did not register exactly the stable graph ID"
        )
    graph = _mapping(
        await client.assistants.get_graph(GRAPH_ID, xray=True),
        field="graph",
    )
    node_count, edge_count, topology_digest = _validate_topology(
        graph,
        topology_oracle,
    )

    thread = _mapping(await client.threads.create(), field="thread")
    thread_id = thread.get("thread_id")
    if not isinstance(thread_id, str):
        raise StudioAgentServerError("Agent Server thread_id is missing")
    first = _mapping(
        await client.runs.wait(
            thread_id,
            GRAPH_ID,
            input={"scenario": "full_demo"},
        ),
        field="first_run",
    )
    first_state = _mapping(
        await client.threads.get_state(thread_id),
        field="first_state",
    )
    first_values = _state_values(first_state, field="first_state")
    first_interrupt = _interrupt_kind(first, field="first_run")
    if (
        first_interrupt != "clarification"
        or first_values.get("checkpoint_sequence") != 0
    ):
        raise StudioAgentServerError(
            "clarification interrupt or checkpoint differs"
        )
    _require_state_next(
        first_state,
        ["clarification_interrupt"],
        field="first_state",
    )

    second = _mapping(
        await client.runs.wait(
            thread_id,
            GRAPH_ID,
            command={"resume": {"confirmed": True}},
        ),
        field="second_run",
    )
    second_state = _mapping(
        await client.threads.get_state(thread_id),
        field="second_state",
    )
    second_values = _state_values(second_state, field="second_state")
    second_interrupt = _interrupt_kind(second, field="second_run")
    if (
        second_interrupt != "approval"
        or second_values.get("checkpoint_sequence") != 1
        or second_values.get("handoff_count") != 1
        or second_values.get("context_rebuilt") is not True
        or second_values.get("tool_scope_rebuilt") is not True
    ):
        raise StudioAgentServerError(
            "approval interrupt, Handoff, or checkpoint differs"
        )
    _require_state_next(
        second_state,
        ["approval_interrupt"],
        field="second_state",
    )

    final = _mapping(
        await client.runs.wait(
            thread_id,
            GRAPH_ID,
            command={"resume": {"approved": True}},
        ),
        field="final_run",
    )
    final_state = _mapping(
        await client.threads.get_state(thread_id),
        field="final_state",
    )
    final_values = _state_values(final_state, field="final_state")
    if final != final_values:
        raise StudioAgentServerError(
            "run result and persisted final state do not align"
        )
    _require_state_next(final_state, [], field="final_state")
    if (
        final_values.get("status") != "COMPLETED"
        or final_values.get("terminal_reason") != "SYNTHETIC_SUCCESS"
        or final_values.get("checkpoint_sequence") != 4
        or final_values.get("run_generation") != 1
        or final_values.get("retry_count") != 1
        or final_values.get("handoff_count") != 1
        or final_values.get("tool_mode") != "fake_readonly"
        or final_values.get("tool_stage") != "no_authoritative_write"
        or tuple(final_values.get("visited_nodes", ())) != _EXPECTED_PATH
    ):
        raise StudioAgentServerError(
            "full_demo terminal state or path differs"
        )
    frames = _mapping_list(
        final_values.get("debug_projection"),
        field="final_state.debug_projection",
    )
    frame_sequences, projection_safe = _validate_projection(frames)
    history = _mapping_list(
        await client.threads.get_history(thread_id, limit=100),
        field="history",
    )
    history_steps, history_sequences = _validate_checkpoint_history(
        history
    )

    denied_thread = _mapping(
        await client.threads.create(),
        field="denied_thread",
    )
    denied_thread_id = str(denied_thread["thread_id"])
    denied_interrupt = _mapping(
        await client.runs.wait(
            denied_thread_id,
            GRAPH_ID,
            input={"scenario": "approval"},
        ),
        field="denied_interrupt",
    )
    if _interrupt_kind(denied_interrupt, field="denied_interrupt") != "approval":
        raise StudioAgentServerError("denied path did not stop for approval")
    denied = _mapping(
        await client.runs.wait(
            denied_thread_id,
            GRAPH_ID,
            command={"resume": {"approved": False}},
        ),
        field="denied_run",
    )
    if (
        denied.get("status") != "FAILED"
        or denied.get("failure_code") != "STUDIO_APPROVAL_DENIED"
        or denied.get("compensation_status")
        != "not_required_no_side_effect"
        or denied.get("tool_stage") != "no_authoritative_write"
    ):
        raise StudioAgentServerError(
            "approval denial did not fail without an authoritative write"
        )

    profile_thread = _mapping(
        await client.threads.create(),
        field="profile_thread",
    )
    profile_thread_id = str(profile_thread["thread_id"])
    profile_result = _mapping(
        await client.runs.wait(
            profile_thread_id,
            GRAPH_ID,
            input={"scenario": "happy_path", "profile": "production"},
            raise_error=False,
        ),
        field="profile_result",
    )
    profile_state = _mapping(
        await client.threads.get_state(profile_thread_id),
        field="profile_state",
    )
    _validate_error(
        profile_result,
        profile_state,
        expected_message="Studio input cannot select another execution profile",
    )

    unknown_thread = _mapping(
        await client.threads.create(),
        field="unknown_thread",
    )
    unknown_thread_id = str(unknown_thread["thread_id"])
    unknown_result = _mapping(
        await client.runs.wait(
            unknown_thread_id,
            GRAPH_ID,
            input={"scenario": "not_registered"},
            raise_error=False,
        ),
        field="unknown_result",
    )
    unknown_state = _mapping(
        await client.threads.get_state(unknown_thread_id),
        field="unknown_state",
    )
    _validate_error(
        unknown_result,
        unknown_state,
        expected_message="Studio scenario is not registered",
    )

    injected_thread = _mapping(
        await client.threads.create(),
        field="injected_thread",
    )
    injected = _mapping(
        await client.runs.wait(
            str(injected_thread["thread_id"]),
            GRAPH_ID,
            input={
                "scenario": "happy_path",
                "tenant_id": _SENSITIVE_SENTINELS[0],
                "api_key": _SENSITIVE_SENTINELS[1],
                "provider_session": _SENSITIVE_SENTINELS[2],
                "email": _SENSITIVE_SENTINELS[3],
                "raw_context": _SENSITIVE_SENTINELS[4],
                "future_unclassified_state": _SENSITIVE_SENTINELS[5],
            },
        ),
        field="injected_run",
    )
    injected_serialized = json.dumps(
        injected,
        ensure_ascii=False,
        sort_keys=True,
    )
    if (
        injected.get("status") != "COMPLETED"
        or any(
            sentinel in injected_serialized
            for sentinel in _SENSITIVE_SENTINELS
        )
        or any(
            key in injected
            for key in (
                "tenant_id",
                "api_key",
                "provider_session",
                "email",
                "raw_context",
                "future_unclassified_state",
            )
        )
    ):
        raise StudioAgentServerError(
            "authoritative, sensitive, or unclassified input remained visible"
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "graph": {
            "registered_graph_ids": graph_ids,
            "stable_graph_id": GRAPH_ID,
            "topology_digest": topology_digest,
            "topology_edge_count": edge_count,
            "topology_matches_oracle": True,
            "topology_node_count": node_count,
        },
        "execution": {
            "checkpoint_sequence": 4,
            "context_rebuilt": True,
            "debug_frame_count": len(frames),
            "handoff_count": 1,
            "interrupts": [first_interrupt, second_interrupt],
            "path": list(_EXPECTED_PATH),
            "retry_count": 1,
            "run_generation": 1,
            "status": "COMPLETED",
            "terminal_reason": "SYNTHETIC_SUCCESS",
            "tool_scope_rebuilt": True,
        },
        "checkpoint_alignment": {
            "frame_sequences": frame_sequences,
            "history_count": len(history),
            "history_sequences": history_sequences,
            "metadata_steps": history_steps,
            "parent_chain_closed": True,
        },
        "security": {
            "approval_denial_failed_closed": True,
            "authoritative_input_hidden": True,
            "external_network": "disabled",
            "final_tool_stage": "no_authoritative_write",
            "production_environment_loaded": False,
            "production_profile_edit_rejected": True,
            "projection_default_deny": projection_safe,
            "sensitive_input_hidden": True,
            "tool_mode": "fake_readonly",
            "unknown_scenario_rejected": True,
        },
    }


def _source_fingerprint(repository_root: Path) -> str:
    digest = hashlib.sha256()
    for relative_root in _BUSINESS_SOURCE_ROOTS:
        source_root = repository_root / relative_root
        if not source_root.exists():
            continue
        for path in sorted(
            (
                item
                for item in source_root.rglob("*")
                if item.is_file()
                and "__pycache__" not in item.parts
                and item.suffix not in {".pyc", ".pyo"}
            ),
            key=lambda item: item.as_posix(),
        ):
            relative = path.relative_to(repository_root).as_posix()
            digest.update(relative.encode())
            digest.update(b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return "sha256:" + digest.hexdigest()


def _allocate_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _server_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for key in _PRODUCTION_ENVIRONMENT_KEYS:
        environment.pop(key, None)
    environment.update(
        {
            "FLOWPILOT_EXTERNAL_NETWORK": "disabled",
            "FLOWPILOT_STUDIO_PROFILE": "studio-safe",
            "LANGSMITH_TRACING": "false",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONUTF8": "1",
        }
    )
    return environment


def _wait_until_ready(
    process: subprocess.Popen[bytes],
    base_url: str,
    *,
    timeout_seconds: float,
    log_file: Any,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            log_file.seek(0)
            log_tail = log_file.read().decode(
                "utf-8",
                errors="replace",
            )[-4000:]
            raise StudioAgentServerError(
                "Agent Server exited before readiness:\n" + log_tail
            )
        try:
            with urllib.request.urlopen(  # noqa: S310
                base_url + "/info",
                timeout=1.0,
            ) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.1)
    raise StudioAgentServerError(
        f"Agent Server was not ready within {timeout_seconds:.1f}s"
    )


def _stop_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        completed = subprocess.run(
            [
                "taskkill",
                "/PID",
                str(process.pid),
                "/T",
                "/F",
            ],
            check=False,
            capture_output=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired as exc:
            raise StudioAgentServerError(
                "Agent Server process tree did not stop"
            ) from exc
        if completed.returncode != 0 and process.returncode is None:
            raise StudioAgentServerError(
                "taskkill did not stop the Agent Server process tree"
            )
        return
    kill_process_group = getattr(os, "killpg", None)
    if kill_process_group is None:
        raise StudioAgentServerError(
            "process-group shutdown is unavailable on this host"
        )
    kill_process_group(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        kill_process_group(
            process.pid,
            getattr(signal, "SIGKILL", signal.SIGTERM),
        )
        process.wait(timeout=10)


def _port_released(port: int, *, timeout_seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.2)
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return True
        time.sleep(0.1)
    return False


def _remove_runtime_directory(repository_root: Path) -> bool:
    runtime_directory = (repository_root / ".langgraph_api").resolve()
    if (
        runtime_directory.parent != repository_root
        or runtime_directory.name != ".langgraph_api"
    ):
        raise StudioAgentServerError(
            "Agent Server runtime directory escaped the repository"
        )
    if runtime_directory.is_symlink():
        raise StudioAgentServerError(
            "Agent Server runtime directory cannot be a symlink"
        )
    if runtime_directory.exists():
        if not runtime_directory.is_dir():
            raise StudioAgentServerError(
                "Agent Server runtime path is not a directory"
            )
        shutil.rmtree(runtime_directory)
    return not runtime_directory.exists()


def _write_evidence(path: Path, evidence: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(
            evidence,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    path.write_text(encoded, encoding="utf-8", newline="\n")


def run_studio_agent_server_smoke(
    *,
    repository_root: Path,
    output_path: Path | None = None,
    topology_oracle_path: Path | None = None,
    startup_timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Run the real local Agent Server smoke and return sanitized evidence."""

    root = repository_root.resolve()
    runtime_directory = root / ".langgraph_api"
    if runtime_directory.exists():
        raise StudioAgentServerError(
            "pre-existing .langgraph_api prevents isolated evidence"
        )
    oracle_path = topology_oracle_path or (
        root
        / "tests"
        / "acceptance"
        / "studio"
        / "expected_agent_server_topology.json"
    )
    topology_oracle = _strict_json(oracle_path)
    before_fingerprint = _source_fingerprint(root)
    port = _allocate_local_port()
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
    start_new_session = os.name != "nt"
    if os.name == "nt":
        creationflags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )

    evidence: dict[str, Any] | None = None
    server_stopped = False
    port_released = False
    runtime_directory_removed = False
    with tempfile.TemporaryFile() as log_file:
        process = subprocess.Popen(
            command,
            cwd=root,
            env=_server_environment(),
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            start_new_session=start_new_session,
        )
        try:
            _wait_until_ready(
                process,
                base_url,
                timeout_seconds=startup_timeout_seconds,
                log_file=log_file,
            )
            evidence = asyncio.run(
                _probe_agent_server(base_url, topology_oracle)
            )
        finally:
            _stop_process_tree(process)
            server_stopped = process.poll() is not None
            port_released = _port_released(port)
            runtime_directory_removed = _remove_runtime_directory(root)

    if evidence is None:
        raise StudioAgentServerError(
            "Agent Server did not produce evidence"
        )
    after_fingerprint = _source_fingerprint(root)
    if before_fingerprint != after_fingerprint:
        raise StudioAgentServerError(
            "Agent Server changed a business source or fact-source file"
        )
    if not (server_stopped and port_released and runtime_directory_removed):
        raise StudioAgentServerError(
            "Agent Server left a process, port, or runtime directory"
        )
    security = _mapping(evidence["security"], field="security")
    security["business_fact_sources_unchanged"] = True
    evidence["security"] = security
    evidence["cleanup"] = {
        "port_released": port_released,
        "runtime_directory_removed": runtime_directory_removed,
        "server_process_stopped": server_stopped,
    }
    if output_path is not None:
        _write_evidence(output_path, evidence)
    return evidence


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the FlowPilot local Studio Agent Server black box.",
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[3],
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--startup-timeout-seconds",
        type=float,
        default=30.0,
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    evidence = run_studio_agent_server_smoke(
        repository_root=args.repository_root,
        output_path=args.output,
        startup_timeout_seconds=args.startup_timeout_seconds,
    )
    print(
        json.dumps(
            {
                "cleanup": evidence["cleanup"],
                "graph_id": evidence["graph"]["stable_graph_id"],
                "output": str(args.output.resolve()),
                "schema_version": evidence["schema_version"],
                "status": evidence["execution"]["status"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
