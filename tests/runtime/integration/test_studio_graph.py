from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
from flowpilot_domain import TaskCommand
from flowpilot_graph import (
    FLOWPILOT_GRAPH_FACTORY_ID,
    FLOWPILOT_GRAPH_ID,
    GraphError,
    GraphErrorCode,
    assert_same_graph_factory,
    projection_digest,
    topology_snapshot,
)
from flowpilot_graph.langgraph_runtime import LangGraphRuntime
from flowpilot_worker.knowledge import KNOWLEDGE_GRAPH_VERSION, KNOWLEDGE_INTENT
from flowpilot_worker.studio import create_studio_graph_definition
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from langgraph_cli.config import validate_config_file

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
TOPOLOGY_SNAPSHOT = (
    REPOSITORY_ROOT
    / "tests"
    / "runtime"
    / "snapshots"
    / "flowpilot_it_service.topology.json"
)
DEBUG_PROJECTION_SNAPSHOT = (
    REPOSITORY_ROOT
    / "tests"
    / "runtime"
    / "snapshots"
    / "studio-safe.debug-projection.json"
)


def test_langgraph_config_is_studio_safe_and_loadable() -> None:
    path = REPOSITORY_ROOT / "langgraph.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    validated = validate_config_file(path)

    assert set(raw["graphs"]) == {FLOWPILOT_GRAPH_ID}
    assert raw["graphs"][FLOWPILOT_GRAPH_ID].endswith(
        "flowpilot_worker/studio.py:graph"
    )
    assert raw["source"] == {"kind": "uv", "root": "."}
    assert raw["env"] == {
        "FLOWPILOT_STUDIO_PROFILE": "studio-safe",
        "FLOWPILOT_EXTERNAL_NETWORK": "disabled",
        "LANGSMITH_TRACING": "false",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUTF8": "1",
    }
    assert isinstance(validated, dict)
    serialized = json.dumps(raw, sort_keys=True).lower()
    assert ".env" not in serialized
    assert "tunnel" not in serialized
    assert "0.0.0.0" not in serialized


def test_worker_and_studio_share_the_only_graph_factory(
    command_factory: Callable[..., TaskCommand],
    graph_factory: Callable[..., tuple],
) -> None:
    del command_factory
    worker, _, _, _ = graph_factory()
    studio = create_studio_graph_definition()

    assert isinstance(worker, LangGraphRuntime)
    assert worker.definition.factory_id == FLOWPILOT_GRAPH_FACTORY_ID
    assert studio.factory_id == FLOWPILOT_GRAPH_FACTORY_ID
    assert_same_graph_factory(worker.definition, studio)

    divergent = replace(studio, factory_id="flowpilot.graph.forked")
    with pytest.raises(GraphError) as captured:
        assert_same_graph_factory(worker.definition, divergent)
    assert captured.value.code is GraphErrorCode.GRAPH_FACTORY_DIVERGED


def test_topology_snapshot_matches_compiled_graph() -> None:
    expected = json.loads(TOPOLOGY_SNAPSHOT.read_text(encoding="utf-8"))
    actual = topology_snapshot()
    definition = create_studio_graph_definition()
    compiled = definition.graph.get_graph()
    expected_edges: set[tuple[str, str, bool]] = set()
    for edge in expected["edges"]:
        sources = (
            edge["source"] if isinstance(edge["source"], list) else [edge["source"]]
        )
        targets = (
            edge["target"] if isinstance(edge["target"], list) else [edge["target"]]
        )
        expected_edges.update(
            (source, target, "condition" in edge)
            for source in sources
            for target in targets
        )
    compiled_edges = {
        (edge.source, edge.target, edge.conditional) for edge in compiled.edges
    }

    assert actual == expected
    assert definition.graph_id == FLOWPILOT_GRAPH_ID
    assert definition.topology_digest == expected["topology_digest"]
    assert set(compiled.nodes) == {
        "__start__",
        "__end__",
        *expected["nodes"],
    }
    assert compiled_edges == expected_edges


def test_full_demo_interrupts_resumes_handoffs_and_retries() -> None:
    async def scenario() -> None:
        definition = create_studio_graph_definition(checkpointer=InMemorySaver())
        graph = definition.graph
        config = {
            "configurable": {
                "thread_id": "studio-debug-cursor-not-a-task",
            }
        }

        first = await graph.ainvoke({"scenario": "full_demo"}, config=config)
        first_interrupts = first.get("__interrupt__", ())
        assert len(first_interrupts) == 1
        assert first_interrupts[0].value["kind"] == "clarification"
        assert first["current_node"] == "route_request"

        second = await graph.ainvoke(
            Command(resume={"confirmed": True}),
            config=config,
        )
        second_interrupts = second.get("__interrupt__", ())
        assert len(second_interrupts) == 1
        assert second_interrupts[0].value["kind"] == "approval"
        assert second["reads_complete"] is True
        assert second["context_rebuilt"] is True
        assert second["tool_scope_rebuilt"] is True

        completed = await graph.ainvoke(
            Command(resume={"approved": True}),
            config=config,
        )

        assert completed["status"] == "COMPLETED"
        assert completed["terminal_reason"] == "SYNTHETIC_SUCCESS"
        assert completed["checkpoint_sequence"] == 4
        assert completed["run_generation"] == 1
        assert completed["retry_count"] == 1
        assert completed["visited_nodes"].count("run_agent") == 2
        assert completed["visited_nodes"].count("route_result") == 2
        assert "knowledge_read" in completed["visited_nodes"]
        assert "service_read" in completed["visited_nodes"]
        assert "handoff" in completed["visited_nodes"]
        assert "retry" in completed["visited_nodes"]
        assert completed["tool_stage"] == "no_authoritative_write"
        assert completed["knowledge_call_count"] == 1
        assert completed["citation_count"] == 1
        assert completed["service_read_skipped"] is True

        frames = completed["debug_projection"]
        assert len(frames) == 18
        expected_projection = json.loads(
            DEBUG_PROJECTION_SNAPSHOT.read_text(encoding="utf-8")
        )
        assert expected_projection == {
            "schema": "flowpilot.debug-projection-snapshot.v1",
            "frame_digests": [projection_digest(frame) for frame in frames],
        }
        assert [frame["step"] for frame in frames] == sorted(
            frame["step"] for frame in frames
        )
        assert all(frame["profile"] == "studio-safe" for frame in frames)
        assert all(frame["recovery"]["run_generation"] == 1 for frame in frames)

    asyncio.run(scenario())


def test_default_product_demo_exposes_five_stage_recovery_progress() -> None:
    async def scenario() -> None:
        definition = create_studio_graph_definition(checkpointer=InMemorySaver())
        graph = definition.graph
        config = {
            "configurable": {
                "thread_id": "studio-product-progress-not-a-task",
            }
        }

        waiting = await graph.ainvoke({}, config=config)
        waiting_interrupts = waiting.get("__interrupt__", ())
        assert len(waiting_interrupts) == 1
        assert waiting_interrupts[0].value == {
            "schema": "flowpilot.studio-interrupt.v1",
            "kind": "clarification",
            "request_ref": "clarification://sha256/2a87392f28f68d4a",
            "required_fields": ["question"],
        }
        assert waiting["knowledge_call_count"] == 0
        assert waiting["model_call_count"] == 0
        assert waiting["debug_projection"][-1]["progress"] == {
            "current_step": 2,
            "total_steps": 5,
            "phase": "interrupt",
        }

        completed = await graph.ainvoke(
            Command(resume={"confirmed": True}),
            config=config,
        )

        assert completed["status"] == "COMPLETED"
        assert completed["terminal_reason"] == (
            "ENTERPRISE_KNOWLEDGE_COMPLETED"
        )
        assert completed["knowledge_call_count"] == 1
        assert completed["model_call_count"] == 2
        assert completed["citation_count"] == 1
        assert completed["artifact_count"] == 1
        assert completed["recovery_resumed"] is True
        assert completed["service_read_skipped"] is True

        frames = completed["debug_projection"]
        product_steps = [frame["progress"]["current_step"] for frame in frames]
        assert product_steps == sorted(product_steps)
        assert set(product_steps) == {1, 2, 3, 4, 5}
        assert all(frame["progress"]["total_steps"] == 5 for frame in frames)
        assert all(
            frame["workflow"]["graph_id"] == FLOWPILOT_GRAPH_ID
            and frame["workflow"]["graph_version"]
            == KNOWLEDGE_GRAPH_VERSION
            and frame["workflow"]["intent"] == KNOWLEDGE_INTENT
            for frame in frames
        )
        assert frames[-1]["workflow"]["actor"] == "artifact_writer"
        assert frames[-1]["model"] == {
            "call_count": 2,
            "outcome": "completed",
        }
        assert frames[-1]["references"] == {
            "citation_count": 1,
            "artifact_count": 1,
        }
        assert frames[-1]["recovery"]["resumed"] is True

    asyncio.run(scenario())


@pytest.mark.parametrize(
    (
        "scenario_name",
        "terminal_reason",
        "failure_code",
        "model_call_count",
    ),
    [
        ("provider_timeout", "PROVIDER_TIMEOUT", "PROVIDER_TIMEOUT", 2),
        (
            "recovery_failed",
            "RECOVERY_FAILED",
            "GRAPH_CHECKPOINT_UNAVAILABLE",
            0,
        ),
    ],
)
def test_product_failures_have_stable_actionable_projection(
    scenario_name: str,
    terminal_reason: str,
    failure_code: str,
    model_call_count: int,
) -> None:
    async def scenario() -> None:
        result = await create_studio_graph_definition().graph.ainvoke(
            {"scenario": scenario_name}
        )

        assert result["status"] == "FAILED"
        assert result["terminal_reason"] == terminal_reason
        assert result["failure_code"] == failure_code
        assert result["model_call_count"] == model_call_count
        assert result["artifact_count"] == 0
        assert result["tool_stage"] == "no_authoritative_write"
        final_frame = result["debug_projection"][-1]
        assert final_frame["progress"] == {
            "current_step": 5,
            "total_steps": 5,
            "phase": "terminal",
        }
        assert final_frame["terminal_reason"] == terminal_reason
        assert final_frame["failure_code"] == failure_code
        assert final_frame["references"]["artifact_count"] == 0

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("scenario_name", "terminal_reason", "failure_code"),
    [
        (
            "budget_exhausted",
            "BUDGET_EXHAUSTED",
            "STUDIO_BUDGET_EXHAUSTED",
        ),
        (
            "compensate",
            "SYNTHETIC_FAILURE",
            "STUDIO_RUNTIME_FAILED",
        ),
    ],
)
def test_budget_and_compensation_paths_fail_closed(
    scenario_name: str,
    terminal_reason: str,
    failure_code: str,
) -> None:
    async def scenario() -> None:
        graph = create_studio_graph_definition().graph
        result = await graph.ainvoke({"scenario": scenario_name})

        assert result["status"] == "FAILED"
        assert result["terminal_reason"] == terminal_reason
        assert result["failure_code"] == failure_code
        assert result["tool_stage"] == "no_authoritative_write"
        if scenario_name == "compensate":
            assert result["compensation_status"] == ("not_required_no_side_effect")

    asyncio.run(scenario())
