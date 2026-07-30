from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from artifacts.acceptance.generators.studio_agent_server import (
    run_studio_agent_server_smoke,
)

ROOT = Path(__file__).resolve().parents[3]
EXPECTED_PATH = [
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
]


@pytest.fixture(scope="module")
def studio_evidence(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[dict[str, Any], Path]:
    output = tmp_path_factory.mktemp("studio-agent-server") / "evidence.json"
    evidence = run_studio_agent_server_smoke(
        repository_root=ROOT,
        output_path=output,
    )
    return evidence, output


def test_agent_server_registers_stable_graph_and_topology(
    studio_evidence: tuple[dict[str, Any], Path],
) -> None:
    evidence, _ = studio_evidence
    graph = evidence["graph"]

    assert graph["registered_graph_ids"] == ["flowpilot_it_service"]
    assert graph["stable_graph_id"] == "flowpilot_it_service"
    assert graph["topology_matches_oracle"] is True
    assert graph["topology_node_count"] == 16
    assert graph["topology_edge_count"] == 22
    assert graph["topology_digest"].startswith("sha256:")


def test_real_thread_interrupts_resumes_and_aligns_checkpoints(
    studio_evidence: tuple[dict[str, Any], Path],
) -> None:
    evidence, _ = studio_evidence
    execution = evidence["execution"]
    alignment = evidence["checkpoint_alignment"]

    assert execution == {
        "checkpoint_sequence": 4,
        "context_rebuilt": True,
        "debug_frame_count": 18,
        "handoff_count": 1,
        "interrupts": ["clarification", "approval"],
        "path": EXPECTED_PATH,
        "retry_count": 1,
        "run_generation": 1,
        "status": "COMPLETED",
        "terminal_reason": "SYNTHETIC_SUCCESS",
        "tool_scope_rebuilt": True,
    }
    assert alignment["history_count"] == 19
    assert alignment["metadata_steps"] == list(range(17, -2, -1))
    assert alignment["parent_chain_closed"] is True
    assert alignment["frame_sequences"][-1] == 4
    assert alignment["history_sequences"][0] == 4


def test_agent_server_projection_and_failure_paths_fail_closed(
    studio_evidence: tuple[dict[str, Any], Path],
) -> None:
    evidence, _ = studio_evidence
    security = evidence["security"]

    assert security == {
        "approval_denial_failed_closed": True,
        "authoritative_input_hidden": True,
        "business_fact_sources_unchanged": True,
        "external_network": "disabled",
        "final_tool_stage": "no_authoritative_write",
        "production_environment_loaded": False,
        "production_profile_edit_rejected": True,
        "projection_default_deny": True,
        "sensitive_input_hidden": True,
        "tool_mode": "fake_readonly",
        "unknown_scenario_rejected": True,
    }


def test_server_cleanup_and_evidence_encoding_are_reproducible(
    studio_evidence: tuple[dict[str, Any], Path],
) -> None:
    evidence, output = studio_evidence
    raw = output.read_bytes()

    assert evidence["cleanup"] == {
        "port_released": True,
        "runtime_directory_removed": True,
        "server_process_stopped": True,
    }
    assert not (ROOT / ".langgraph_api").exists()
    assert raw.endswith(b"\n")
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert json.loads(raw) == evidence
    serialized = raw.decode("utf-8")
    for forbidden in (
        "tenant-production-sentinel",
        "provider-secret-sentinel",
        "provider-session-sentinel",
        "person@example.invalid",
        "hidden-context-sentinel",
        "future-state-sentinel",
        "success_rate",
        "120/36",
    ):
        assert forbidden not in serialized
