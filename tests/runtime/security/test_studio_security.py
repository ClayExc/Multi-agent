from __future__ import annotations

import asyncio
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
from flowpilot_worker.studio import create_studio_graph_definition


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
        assert captured.value.code is GraphErrorCode.STUDIO_PROFILE_FORBIDDEN

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "forbidden",
    [
        {"tenant_id": "tenant-production"},
        {"task_id": "task-production"},
        {"lease_token": "lease-secret"},
        {"api_key": "provider-secret"},
        {"tool_payload": {"write": True}},
    ],
)
def test_studio_input_drops_authoritative_or_sensitive_state(
    forbidden: dict[str, object],
) -> None:
    async def scenario() -> None:
        graph = create_studio_graph_definition().graph
        result = await graph.ainvoke({"scenario": "happy_path", **forbidden})
        serialized = json.dumps(result, sort_keys=True)

        assert result["status"] == "COMPLETED"
        for key, value in forbidden.items():
            assert key not in result
            if isinstance(value, str):
                assert value not in serialized

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


def test_unknown_studio_state_remains_hidden_from_every_debug_frame() -> None:
    async def scenario() -> None:
        graph = create_studio_graph_definition().graph
        result = await graph.ainvoke(
            {
                "scenario": "happy_path",
                "future_unclassified_state": "hidden-value",
            }
        )
        serialized = json.dumps(
            result["debug_projection"],
            sort_keys=True,
        )
        assert "future_unclassified_state" not in serialized
        assert "hidden-value" not in serialized

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
