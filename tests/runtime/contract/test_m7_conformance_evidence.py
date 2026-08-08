from __future__ import annotations

import json
from importlib.metadata import version
from pathlib import Path
from typing import Any

from flowpilot_model_gateway import (
    DEEPSEEK_V4_FLASH_MODEL_ID,
    PRIMARY_FAST_MODEL,
)

EVIDENCE_PATH = Path(__file__).parents[1] / "evidence" / "WP-070-a2-CONFORMANCE.json"


def test_wp070_a2_conformance_evidence_is_bound_to_locked_runtime() -> None:
    report: dict[str, Any] = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))

    assert report["schema"] == "flowpilot.provider-runtime-conformance.v1"
    assert report["attempt_id"] == "WP-070-a2"
    assert report["gate"] == "PASS"
    assert report["logical_model"] == PRIMARY_FAST_MODEL
    assert report["online_provider_calls"] == 0
    assert report["online_smoke_default_enabled"] is False
    assert report["locked_dependencies"] == {
        "claude-agent-sdk": version("claude-agent-sdk"),
        "litellm": version("litellm"),
        "openai-agents": version("openai-agents"),
    }

    adapters = {item["id"]: item for item in report["adapters"]}
    assert set(adapters) == {
        "litellm",
        "openai-agents-sdk",
        "claude-agent-sdk",
    }
    assert adapters["litellm"]["provider_model_id"] == (DEEPSEEK_V4_FLASH_MODEL_ID)
    assert adapters["litellm"]["port"] == "ProviderPort"
    assert adapters["openai-agents-sdk"]["port"] == "AgentRuntimePort"
    assert adapters["claude-agent-sdk"]["port"] == "AgentRuntimePort"
    assert all(
        outcome == "PASS"
        for adapter in adapters.values()
        for outcome in adapter["checks"].values()
    )
    assert (
        adapters["openai-agents-sdk"]["checks"]["provider_session_is_not_checkpoint"]
        == "PASS"
    )
    assert adapters["claude-agent-sdk"]["checks"]["tool_surface_empty"] == "PASS"
