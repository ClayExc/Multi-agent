"""S4 Agent Server oracle for the fail-before-checkpoint Studio boundary.

The process lifecycle stays in the accepted legacy evidence runner.  Only the
public Agent Server probe is replaced here because the old probe expected a
rejected browser input to leave a synthetic ``prepare`` checkpoint behind.
The current security boundary rejects before Pregel and exposes no Thread
state, history, task, or pending write.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any
from unittest.mock import patch

from artifacts.acceptance.generators import studio_agent_server as legacy


async def _rejected_input(
    client: Any,
    *,
    input_value: Mapping[str, object],
    expected_message: str,
) -> None:
    thread = legacy._mapping(  # noqa: SLF001
        await client.threads.create(), field="rejected_thread"
    )
    thread_id = str(thread["thread_id"])
    result = legacy._mapping(  # noqa: SLF001
        await client.runs.wait(
            thread_id,
            legacy.GRAPH_ID,
            input=dict(input_value),
            raise_error=False,
        ),
        field="rejected_result",
    )
    state = legacy._mapping(  # noqa: SLF001
        await client.threads.get_state(thread_id), field="rejected_state"
    )
    history = legacy._mapping_list(  # noqa: SLF001
        await client.threads.get_history(thread_id, limit=100),
        field="rejected_history",
    )
    if result != {
        "__error__": {"error": "GraphError", "message": expected_message}
    }:
        raise legacy.StudioAgentServerError("Studio rejection is not stable")
    if state.get("values") != {} or state.get("next") != []:
        raise legacy.StudioAgentServerError(
            "rejected Studio input retained state or a next node"
        )
    if "tasks" not in state or state["tasks"] != []:
        raise legacy.StudioAgentServerError(
            "rejected Studio input retained a pending task or write"
        )
    if history:
        raise legacy.StudioAgentServerError(
            "rejected Studio input created checkpoint history"
        )


async def _state_fingerprint(client: Any, thread_id: str) -> tuple[object, ...]:
    state = legacy._mapping(  # noqa: SLF001
        await client.threads.get_state(thread_id), field="authority_state"
    )
    history = legacy._mapping_list(  # noqa: SLF001
        await client.threads.get_history(thread_id, limit=100),
        field="authority_history",
    )
    return (
        state.get("values"),
        state.get("next"),
        state.get("tasks"),
        state.get("checkpoint"),
        len(history),
    )


def _checkpoint_id(state: Mapping[str, Any]) -> str:
    checkpoint = legacy._mapping(  # noqa: SLF001
        state.get("checkpoint"), field="state.checkpoint"
    )
    value = checkpoint.get("checkpoint_id")
    if not isinstance(value, str) or not value:
        raise legacy.StudioAgentServerError("checkpoint_id is missing")
    return value


async def _probe_agent_server_v2(
    base_url: str,
    topology_oracle: Mapping[str, Any],
) -> dict[str, Any]:
    client = legacy.get_client(url=base_url)
    registered = legacy._mapping_list(  # noqa: SLF001
        await client.assistants.search(), field="assistants"
    )
    graph_ids = sorted(str(item.get("graph_id")) for item in registered)
    if graph_ids != [legacy.GRAPH_ID]:
        raise legacy.StudioAgentServerError(
            "Agent Server did not register exactly the stable graph ID"
        )
    graph = legacy._mapping(  # noqa: SLF001
        await client.assistants.get_graph(legacy.GRAPH_ID, xray=True),
        field="graph",
    )
    node_count, edge_count, topology_digest = legacy._validate_topology(  # noqa: SLF001
        graph, topology_oracle
    )

    thread = legacy._mapping(  # noqa: SLF001
        await client.threads.create(), field="thread"
    )
    thread_id = str(thread["thread_id"])
    first = legacy._mapping(  # noqa: SLF001
        await client.runs.wait(
            thread_id,
            legacy.GRAPH_ID,
            input={"scenario": "full_demo"},
        ),
        field="first_run",
    )
    first_state = legacy._mapping(  # noqa: SLF001
        await client.threads.get_state(thread_id), field="first_state"
    )
    first_values = legacy._state_values(first_state, field="first_state")  # noqa: SLF001
    first_interrupt = legacy._interrupt_kind(first, field="first_run")  # noqa: SLF001
    if first_interrupt != "clarification" or first_values.get(
        "checkpoint_sequence"
    ) != 0:
        raise legacy.StudioAgentServerError(
            "clarification interrupt or checkpoint differs"
        )
    legacy._require_state_next(  # noqa: SLF001
        first_state, ["clarification_interrupt"], field="first_state"
    )
    clarification_checkpoint = _checkpoint_id(first_state)

    before_wrong_kind = await _state_fingerprint(client, thread_id)
    wrong_kind = legacy._mapping(  # noqa: SLF001
        await client.runs.wait(
            thread_id,
            legacy.GRAPH_ID,
            command={"resume": {"approved": True}},
            raise_error=False,
        ),
        field="wrong_kind",
    )
    if wrong_kind != {
        "__error__": {
            "error": "GraphError",
            "message": "Studio resume decision does not match the current interrupt",
        }
    } or await _state_fingerprint(client, thread_id) != before_wrong_kind:
        raise legacy.StudioAgentServerError(
            "wrong-kind Resume changed the clarification checkpoint"
        )

    second = legacy._mapping(  # noqa: SLF001
        await client.runs.wait(
            thread_id,
            legacy.GRAPH_ID,
            command={"resume": {"confirmed": True}},
        ),
        field="second_run",
    )
    second_state = legacy._mapping(  # noqa: SLF001
        await client.threads.get_state(thread_id), field="second_state"
    )
    second_values = legacy._state_values(second_state, field="second_state")  # noqa: SLF001
    second_interrupt = legacy._interrupt_kind(second, field="second_run")  # noqa: SLF001
    if (
        second_interrupt != "approval"
        or second_values.get("checkpoint_sequence") != 1
        or second_values.get("handoff_count") != 1
        or second_values.get("context_rebuilt") is not True
        or second_values.get("tool_scope_rebuilt") is not True
    ):
        raise legacy.StudioAgentServerError(
            "approval interrupt, Handoff, or checkpoint differs"
        )
    legacy._require_state_next(  # noqa: SLF001
        second_state, ["approval_interrupt"], field="second_state"
    )
    approval_checkpoint = _checkpoint_id(second_state)

    before_historical_clarification = await _state_fingerprint(client, thread_id)
    historical_clarification = legacy._mapping(  # noqa: SLF001
        await client.runs.wait(
            thread_id,
            legacy.GRAPH_ID,
            command={"resume": {"confirmed": True}},
            checkpoint_id=clarification_checkpoint,
            raise_error=False,
        ),
        field="historical_clarification",
    )
    if historical_clarification != {
        "__error__": {
            "error": "GraphError",
            "message": "Studio resume must target the latest checkpoint",
        }
    } or await _state_fingerprint(
        client, thread_id
    ) != before_historical_clarification:
        raise legacy.StudioAgentServerError(
            "historical clarification checkpoint changed current state"
        )

    before_stale = await _state_fingerprint(client, thread_id)
    stale = legacy._mapping(  # noqa: SLF001
        await client.runs.wait(
            thread_id,
            legacy.GRAPH_ID,
            command={"resume": {"confirmed": True}},
            raise_error=False,
        ),
        field="stale_resume",
    )
    if stale != {
        "__error__": {
            "error": "GraphError",
            "message": "Studio resume decision does not match the current interrupt",
        }
    } or await _state_fingerprint(client, thread_id) != before_stale:
        raise legacy.StudioAgentServerError(
            "stale clarification Resume changed the approval checkpoint"
        )

    final = legacy._mapping(  # noqa: SLF001
        await client.runs.wait(
            thread_id,
            legacy.GRAPH_ID,
            command={"resume": {"approved": True}},
            checkpoint_id=approval_checkpoint,
        ),
        field="final_run",
    )
    final_state = legacy._mapping(  # noqa: SLF001
        await client.threads.get_state(thread_id), field="final_state"
    )
    final_values = legacy._state_values(final_state, field="final_state")  # noqa: SLF001
    if final != final_values:
        raise legacy.StudioAgentServerError(
            "run result and persisted final state do not align"
        )
    legacy._require_state_next(final_state, [], field="final_state")  # noqa: SLF001
    if (
        final_values.get("status") != "COMPLETED"
        or final_values.get("terminal_reason") != "SYNTHETIC_SUCCESS"
        or final_values.get("checkpoint_sequence") != 4
        or final_values.get("run_generation") != 1
        or final_values.get("retry_count") != 1
        or final_values.get("handoff_count") != 1
        or final_values.get("tool_mode") != "fake_readonly"
        or final_values.get("tool_stage") != "no_authoritative_write"
        or tuple(final_values.get("visited_nodes", ()))
        != legacy._EXPECTED_PATH  # noqa: SLF001
    ):
        raise legacy.StudioAgentServerError(
            "full_demo terminal state or path differs"
        )
    frames = legacy._mapping_list(  # noqa: SLF001
        final_values.get("debug_projection"),
        field="final_state.debug_projection",
    )
    frame_sequences, projection_safe = legacy._validate_projection(frames)  # noqa: SLF001
    history = legacy._mapping_list(  # noqa: SLF001
        await client.threads.get_history(thread_id, limit=100), field="history"
    )
    history_steps, history_sequences = legacy._validate_checkpoint_history(  # noqa: SLF001
        history
    )

    before_historical = await _state_fingerprint(client, thread_id)
    historical = legacy._mapping(  # noqa: SLF001
        await client.runs.wait(
            thread_id,
            legacy.GRAPH_ID,
            command={"resume": {"approved": True}},
            checkpoint_id=approval_checkpoint,
            raise_error=False,
        ),
        field="historical_resume",
    )
    if historical != {
        "__error__": {
            "error": "GraphError",
            "message": "Studio resume must target the latest checkpoint",
        }
    } or await _state_fingerprint(client, thread_id) != before_historical:
        raise legacy.StudioAgentServerError(
            "historical checkpoint Resume changed terminal history"
        )

    denied_thread = legacy._mapping(  # noqa: SLF001
        await client.threads.create(), field="denied_thread"
    )
    denied_thread_id = str(denied_thread["thread_id"])
    denied_interrupt = legacy._mapping(  # noqa: SLF001
        await client.runs.wait(
            denied_thread_id,
            legacy.GRAPH_ID,
            input={"scenario": "approval"},
        ),
        field="denied_interrupt",
    )
    if (
        legacy._interrupt_kind(denied_interrupt, field="denied_interrupt")  # noqa: SLF001
        != "approval"
    ):
        raise legacy.StudioAgentServerError(
            "denied path did not stop for approval"
        )
    denied = legacy._mapping(  # noqa: SLF001
        await client.runs.wait(
            denied_thread_id,
            legacy.GRAPH_ID,
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
        raise legacy.StudioAgentServerError(
            "approval denial did not fail without an authoritative write"
        )

    await _rejected_input(
        client,
        input_value={"scenario": "happy_path", "profile": "production"},
        expected_message="Studio input cannot select another execution profile",
    )
    await _rejected_input(
        client,
        input_value={"scenario": "not_registered"},
        expected_message="Studio scenario is not registered",
    )
    await _rejected_input(
        client,
        input_value={
            "scenario": "happy_path",
            "tenant_id": "tenant-production-sentinel",
            "credential": "provider-secret-sentinel",
            "reasoning": "hidden-context-sentinel",
        },
        expected_message="Studio input contains authoritative or sensitive state",
    )
    await _rejected_input(
        client,
        input_value={
            "scenario": "happy_path",
            "future_browser_field": "future-state-sentinel",
        },
        expected_message="Studio input contains a field that is not registered",
    )

    return {
        "schema_version": legacy.SCHEMA_VERSION,
        "graph": {
            "registered_graph_ids": graph_ids,
            "stable_graph_id": legacy.GRAPH_ID,
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
            "path": list(legacy._EXPECTED_PATH),  # noqa: SLF001
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
            "authoritative_input_rejected": True,
            "external_network": "disabled",
            "final_tool_stage": "no_authoritative_write",
            "historical_checkpoint_replay_rejected": True,
            "production_environment_loaded": False,
            "production_profile_edit_rejected": True,
            "projection_default_deny": projection_safe,
            "rejected_thread_history_empty": True,
            "rejected_thread_next_empty": True,
            "rejected_thread_pending_writes_empty": True,
            "rejected_thread_values_empty": True,
            "resume_authority_rejected": True,
            "sensitive_input_hidden": True,
            "sensitive_input_rejected": True,
            "tool_mode": "fake_readonly",
            "unknown_field_rejected": True,
            "unknown_scenario_rejected": True,
        },
    }


def run_studio_agent_server_smoke_v2(
    *,
    repository_root: Path,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Run the accepted lifecycle with the current S4 public-API probe."""

    with patch.object(legacy, "_probe_agent_server", _probe_agent_server_v2):
        return legacy.run_studio_agent_server_smoke(
            repository_root=repository_root,
            output_path=output_path,
        )
