from __future__ import annotations

import asyncio
import copy
import json

import pytest
from flowpilot_graph import (
    DebugProjectionPolicy,
    GraphError,
    GraphErrorCode,
    StudioProfile,
    debug_projection,
    product_debug_projection,
)
from flowpilot_worker.studio import (
    _append_visits,
    _merge_frames,
    create_studio_graph_definition,
)
from langgraph.checkpoint.memory import InMemorySaver


@pytest.mark.parametrize(
    "environment",
    [
        {"FLOWPILOT_STUDIO_PROFILE": "production"},
        {"FLOWPILOT_STUDIO_PROFILE": "studio-integration"},
        {
            "FLOWPILOT_STUDIO_PROFILE": "studio-safe",
            "OPENAI_API_KEY": "synthetic-must-never-load",
        },
        {
            "FLOWPILOT_STUDIO_PROFILE": "studio-safe",
            "DATABASE_URL": "postgresql://synthetic.invalid",
        },
        {
            "FLOWPILOT_STUDIO_PROFILE": "studio-safe",
            "FLOWPILOT_EXTERNAL_NETWORK": "enabled",
        },
    ],
)
def test_studio_refuses_production_profiles_credentials_and_endpoints(
    environment: dict[str, str],
) -> None:
    with pytest.raises(GraphError) as captured:
        create_studio_graph_definition(environment=environment)
    assert captured.value.code is GraphErrorCode.STUDIO_PROFILE_FORBIDDEN


def test_production_profile_state_edit_is_rejected_with_stable_code() -> None:
    async def scenario() -> None:
        graph = create_studio_graph_definition().graph
        with pytest.raises(GraphError) as captured:
            await graph.ainvoke(
                {
                    "profile": "production",
                    "scenario": "happy_path",
                }
            )
        assert captured.value.code is GraphErrorCode.STUDIO_STATE_EDIT_FORBIDDEN

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "forbidden",
    [
        {"tenant_id": "tenant-production"},
        {"task_id": "task-production"},
        {"lease_token": "lease-secret"},
        {"api_key": "provider-secret"},
        {"tool_payload": {"write": True}},
        {"profile": "studio-safe"},
        {"visited_nodes": ["run_agent"]},
        {"frame_id": "prepare:1:0:0"},
        {"studio_input_validated": True},
        {"reasoning": "hidden-chain"},
    ],
)
def test_studio_input_rejects_authoritative_or_sensitive_state(
    forbidden: dict[str, object],
) -> None:
    async def scenario() -> None:
        graph = create_studio_graph_definition().graph
        with pytest.raises(GraphError) as captured:
            await graph.ainvoke({"scenario": "happy_path", **forbidden})
        assert captured.value.code is (
            GraphErrorCode.STUDIO_STATE_EDIT_FORBIDDEN
        )

    asyncio.run(scenario())


def test_debug_projection_is_default_deny_and_opaque() -> None:
    raw_state = {
        "current_node": "run_agent",
        "route": "finalize",
        "status": "RUNNING",
        "task_ref": "task_person@example.com",
        "checkpoint_sequence": 7,
        "run_generation": 3,
        "lease_status": "synthetic",
        "budget_remaining": 4,
        "retry_count": 1,
        "maximum_retries": 2,
        "context_layers": {"L0": True, "L1": True, "L2": True},
        "context_token_budget": 512,
        "knowledge_call_count": 1,
        "citation_count": 1,
        "service_read_skipped": True,
        "unknown_future_field": "must-not-appear",
        "api_key": "must-not-appear",
        "provider_session": "must-not-appear",
        "raw_context": "must-not-appear",
        "email": "person@example.com",
    }

    projection = debug_projection(
        raw_state,
        policy=DebugProjectionPolicy(profile=StudioProfile.SAFE),
    )
    serialized = json.dumps(projection, sort_keys=True)

    assert projection["recovery"]["task_ref"].startswith("task://sha256/")
    assert projection["knowledge"] == {
        "call_count": 1,
        "citation_count": 1,
        "service_read_skipped": True,
    }
    for forbidden in (
        "must-not-appear",
        "person@example.com",
        "api_key",
        "provider_session",
        "raw_context",
        "unknown_future_field",
    ):
        assert forbidden not in serialized


def test_unknown_studio_state_is_rejected_at_the_input_boundary() -> None:
    async def scenario() -> None:
        graph = create_studio_graph_definition().graph
        with pytest.raises(GraphError) as captured:
            await graph.ainvoke(
                {
                    "scenario": "happy_path",
                    "future_unclassified_state": "hidden-value",
                }
            )
        assert captured.value.code is (
            GraphErrorCode.STUDIO_STATE_EDIT_FORBIDDEN
        )

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "nested_input",
    [
        {"scenario": {"payload": {"tenant-id": "tenant-forged"}}},
        {"scenario": {"payload": [{"access-token": "credential"}]}},
        {"scenario": {"payload": {"chain-of-thought": "hidden"}}},
        {"scenario": {"payload": {"visited-nodes": ["run_agent"]}}},
    ],
)
def test_studio_input_recursively_rejects_authority_and_sensitive_keys(
    nested_input: dict[str, object],
) -> None:
    async def scenario() -> None:
        graph = create_studio_graph_definition().graph
        with pytest.raises(GraphError) as captured:
            await graph.ainvoke(nested_input)
        assert captured.value.code is (
            GraphErrorCode.STUDIO_STATE_EDIT_FORBIDDEN
        )

    asyncio.run(scenario())


def test_visited_node_reducer_accepts_only_registered_server_nodes() -> None:
    assert _append_visits(["prepare"], ["run_agent"]) == [
        "prepare",
        "run_agent",
    ]
    for forged in (["browser_node"], ["run-agent"], ["reasoning"]):
        with pytest.raises(GraphError) as captured:
            _append_visits(["prepare"], forged)
        assert captured.value.code is GraphErrorCode.DEBUG_PROJECTION_UNSAFE


def test_frame_reducer_revalidates_both_sides_and_binds_id_to_fingerprint() -> None:
    async def valid_frame() -> dict[str, object]:
        result = await create_studio_graph_definition().graph.ainvoke(
            {"scenario": "happy_path"}
        )
        return copy.deepcopy(result["debug_projection"][0])

    frame = asyncio.run(valid_frame())
    replayed = _merge_frames([frame], [copy.deepcopy(frame)])
    assert replayed == [frame]

    same_id_different_content = copy.deepcopy(frame)
    same_id_different_content["status"] = "FAILED"
    with pytest.raises(GraphError) as collision:
        _merge_frames([frame], [same_id_different_content])
    assert collision.value.code is GraphErrorCode.DEBUG_PROJECTION_UNSAFE

    damaged_left = copy.deepcopy(frame)
    damaged_left["reasoning"] = "persisted-hidden-chain"
    with pytest.raises(GraphError) as left_failure:
        _merge_frames([damaged_left], [frame])
    assert left_failure.value.code is GraphErrorCode.DEBUG_PROJECTION_UNSAFE

    damaged_right = copy.deepcopy(frame)
    damaged_right["node"] = "browser_node"
    with pytest.raises(GraphError) as right_failure:
        _merge_frames([frame], [damaged_right])
    assert right_failure.value.code is GraphErrorCode.DEBUG_PROJECTION_UNSAFE

    assert frame["status"] == "RUNNING"
    assert "reasoning" not in frame


def test_browser_cannot_seed_a_valid_server_frame() -> None:
    async def scenario() -> None:
        source = await create_studio_graph_definition().graph.ainvoke(
            {"scenario": "happy_path"}
        )
        forged_frame = copy.deepcopy(source["debug_projection"][0])
        graph = create_studio_graph_definition().graph
        with pytest.raises(GraphError) as captured:
            await graph.ainvoke(
                {
                    "scenario": "happy_path",
                    "debug_projection": [forged_frame],
                }
            )
        assert captured.value.code is (
            GraphErrorCode.STUDIO_STATE_EDIT_FORBIDDEN
        )
        assert len(source["debug_projection"]) > 0
        assert forged_frame == source["debug_projection"][0]

    asyncio.run(scenario())


@pytest.mark.parametrize("server_copy", [False, True])
def test_rejected_browser_authority_has_zero_applied_retention(
    server_copy: bool,
) -> None:
    async def scenario() -> None:
        saver = InMemorySaver()
        if server_copy:
            graph = create_studio_graph_definition().graph.copy(
                update={"checkpointer": saver}
            )
        else:
            graph = create_studio_graph_definition(checkpointer=saver).graph
        config = {
            "configurable": {
                "thread_id": "studio-rejected-browser-authority",
            }
        }
        with pytest.raises(GraphError) as captured:
            await graph.ainvoke(
                {
                    "scenario": "happy_path",
                    "profile": "production",
                    "tenant_id": "tenant-forged",
                    "credential": "credential-forged",
                    "reasoning": "hidden-chain-forged",
                    "visited_nodes": ["run_agent"],
                    "debug_projection": [
                        {
                            "frame_id": "prepare:1:0:0",
                            "reasoning": "frame-hidden-chain",
                        }
                    ],
                },
                config=config,
            )
        assert captured.value.code is (
            GraphErrorCode.STUDIO_STATE_EDIT_FORBIDDEN
        )

        snapshot = await graph.aget_state(config)
        values = dict(snapshot.values)
        assert values == {}
        assert snapshot.next == ()
        assert sum(
            len(checkpoints)
            for namespaces in saver.storage.values()
            for checkpoints in namespaces.values()
        ) == 0
        assert len(saver.writes) == 0

    asyncio.run(scenario())


def test_product_projection_exposes_progress_without_business_content() -> None:
    raw_state = {
        "graph_id": "flowpilot_it_service",
        "graph_version": "flowpilot.enterprise-knowledge.m7.v1",
        "intent": "knowledge_question",
        "active_actor": "answer_agent",
        "progress_step": 4,
        "progress_total": 5,
        "progress_phase": "model",
        "current_node": "run_agent",
        "status": "RUNNING",
        "runtime_outcome": "failed_retryable",
        "model_call_count": 1,
        "knowledge_call_count": 1,
        "citation_count": 2,
        "artifact_count": 0,
        "checkpoint_sequence": 8,
        "run_generation": 2,
        "recovery_resumed": True,
        "question": "person@example.invalid needs a private answer",
        "answer_markdown": "confidential answer must remain hidden",
        "knowledge_sources": [{"redacted_summary": "hidden summary"}],
        "session_ref": "provider-session-must-remain-hidden",
        "security_context": {"tenant_id": "tenant-must-remain-hidden"},
    }

    projection = product_debug_projection(raw_state)
    serialized = json.dumps(projection, sort_keys=True)

    assert projection["progress"] == {
        "current_step": 4,
        "total_steps": 5,
        "phase": "model",
    }
    assert projection["workflow"] == {
        "graph_id": "flowpilot_it_service",
        "graph_version": "flowpilot.enterprise-knowledge.m7.v1",
        "intent": "knowledge_question",
        "actor": "answer_agent",
    }
    assert projection["model"] == {
        "call_count": 1,
        "outcome": "failed_retryable",
    }
    assert projection["references"] == {
        "citation_count": 2,
        "artifact_count": 0,
    }
    assert projection["recovery"]["resumed"] is True
    for forbidden_value in (
        "person@example.invalid",
        "confidential answer",
        "hidden summary",
        "provider-session-must-remain-hidden",
        "tenant-must-remain-hidden",
    ):
        assert forbidden_value not in serialized

    def collect_keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return {
                *(str(key) for key in value),
                *(
                    nested
                    for child in value.values()
                    for nested in collect_keys(child)
                ),
            }
        if isinstance(value, list):
            return {
                nested
                for child in value
                for nested in collect_keys(child)
            }
        return set()

    assert collect_keys(projection).isdisjoint(
        {
            "question",
            "answer_markdown",
            "knowledge_sources",
            "session_ref",
            "security_context",
        }
    )
