from __future__ import annotations

import asyncio
from importlib.metadata import version
from types import SimpleNamespace
from typing import Any

import pytest
from flowpilot_agent_runtime import (
    ANTHROPIC_API_KEY_ENV,
    ClaudeAgentSDKTransport,
    SDKRunCall,
)

CLAUDE_AGENT_SDK_VERSION = "0.2.134"


def _call() -> SDKRunCall:
    return SDKRunCall(
        request_id="sdk_shape_req_12345678",
        agent_id="knowledge-agent",
        prompt_version="prompt-v1",
        logical_model="flowpilot.primary.fast",
        instructions="Return JSON.",
        input_json='{"context":"synthetic"}',
        maximum_turns=2,
        maximum_output_tokens=128,
        timeout_ms=30_000,
        session_ref=None,
    )


def test_claude_agent_sdk_real_options_serialize_an_empty_tool_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdk = pytest.importorskip("claude_agent_sdk")
    transport_module = pytest.importorskip(
        "claude_agent_sdk._internal.transport.subprocess_cli"
    )
    assert version("claude-agent-sdk") == CLAUDE_AGENT_SDK_VERSION

    captured: dict[str, Any] = {}

    class ResultMessage:
        result = '{"answer":"synthetic"}'
        session_id = "shape-session-1"
        usage = {"input_tokens": 3, "output_tokens": 1}
        total_cost_usd = 0.0

    async def query(**kwargs: Any):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        yield ResultMessage()

    module = SimpleNamespace(
        ClaudeAgentOptions=sdk.ClaudeAgentOptions,
        query=query,
    )
    monkeypatch.setenv(ANTHROPIC_API_KEY_ENV, "synthetic-test-key")
    bridge = ClaudeAgentSDKTransport(
        enabled=True,
        provider_model_id="synthetic-claude-model",
        module_loader=lambda: module,
    )

    completion = asyncio.run(bridge.run(_call()))

    assert completion.structured_output == {"answer": "synthetic"}
    options = captured["options"]
    assert options.tools == []
    assert options.allowed_tools == []
    assert options.disallowed_tools == []
    assert options.mcp_servers == {}
    assert options.strict_mcp_config is True
    assert options.plugins == []
    assert options.agents is None
    assert options.hooks is None
    assert options.skills == []
    assert options.setting_sources == []
    assert options.can_use_tool is None

    options.cli_path = "claude"
    serializer = transport_module.SubprocessCLITransport(
        prompt="synthetic",
        options=options,
    )
    command = serializer._build_command()  # noqa: SLF001
    tools_index = command.index("--tools")

    assert command[tools_index + 1] == ""
    assert "--strict-mcp-config" in command
    assert "--allowedTools" not in command
    assert "--disallowedTools" not in command
    assert "--mcp-config" not in command
    assert "--plugin-dir" not in command
    assert not any(argument.startswith("--agent") for argument in command)
    assert "--setting-sources=" in command
    assert "synthetic-test-key" not in repr(command)
