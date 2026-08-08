from __future__ import annotations

import asyncio
from importlib.metadata import version
from types import SimpleNamespace
from typing import Any

import pytest
from flowpilot_agent_runtime import (
    OPENAI_AGENTS_PROVIDER,
    OPENAI_API_KEY_ENV,
    OpenAIAgentsSDKTransport,
    SDKRunCall,
)
from flowpilot_domain import DataClassification
from flowpilot_model_gateway import (
    DEEPSEEK_API_KEY_ENV,
    DEEPSEEK_V4_FLASH_MODEL_ID,
    LITELLM_DEEPSEEK_ROUTE,
    PRIMARY_FAST_MODEL,
    LiteLLMProvider,
    OnlineLiteLLMTransport,
    ProviderWireRequest,
)


def _wire_request() -> ProviderWireRequest:
    return ProviderWireRequest(
        request_id="locked_litellm_req_12345678",
        task="summarize",
        payload={"purpose": "it_support"},
        data_classification=DataClassification.INTERNAL,
        maximum_input_tokens=4096,
        maximum_output_tokens=256,
    )


def _sdk_call() -> SDKRunCall:
    return SDKRunCall(
        request_id="locked_openai_req_12345678",
        agent_id="knowledge-agent",
        prompt_version="prompt-v1",
        logical_model=PRIMARY_FAST_MODEL,
        instructions="Return JSON.",
        input_json='{"context":"synthetic"}',
        maximum_turns=2,
        maximum_output_tokens=128,
        timeout_ms=30_000,
        session_ref=None,
    )


def test_locked_litellm_namespace_matches_bridge_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    litellm = pytest.importorskip("litellm")
    assert version("litellm") == "1.95.0"
    captured: dict[str, Any] = {}

    async def acompletion(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "id": "locked-deepseek-response-1",
            "model": DEEPSEEK_V4_FLASH_MODEL_ID,
            "choices": [{"message": {"content": '{"answer":"synthetic"}'}}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        }

    monkeypatch.setattr(litellm, "acompletion", acompletion)
    monkeypatch.setenv(DEEPSEEK_API_KEY_ENV, "synthetic-test-key")
    provider = LiteLLMProvider(
        OnlineLiteLLMTransport(
            enabled=True,
            module_loader=lambda: litellm,
        )
    )

    result = asyncio.run(provider.complete(_wire_request()))

    assert result.model == PRIMARY_FAST_MODEL
    assert result.output == {"answer": "synthetic"}
    assert captured["model"] == LITELLM_DEEPSEEK_ROUTE
    assert captured["response_format"] == {"type": "json_object"}
    assert "api_key" not in captured
    assert "synthetic-test-key" not in repr(captured)


def test_locked_openai_agents_namespace_matches_bridge_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents = pytest.importorskip("agents")
    assert version("openai-agents") == "0.19.4"
    captured: dict[str, Any] = {}

    async def run(
        starting_agent: Any,
        input_value: str,
        **kwargs: Any,
    ) -> Any:
        captured["agent"] = starting_agent
        captured["input"] = input_value
        captured["kwargs"] = kwargs
        return SimpleNamespace(
            final_output='{"answer":"synthetic"}',
            last_response_id="locked-openai-response-1",
            context_wrapper=SimpleNamespace(
                usage=SimpleNamespace(
                    input_tokens=5,
                    output_tokens=2,
                    total_tokens=7,
                    requests=1,
                )
            ),
        )

    monkeypatch.setattr(agents.Runner, "run", staticmethod(run))
    monkeypatch.setenv(OPENAI_API_KEY_ENV, "synthetic-test-key")
    transport = OpenAIAgentsSDKTransport(
        enabled=True,
        provider_model_id="synthetic-openai-model",
        module_loader=lambda: agents,
    )

    result = asyncio.run(transport.run(_sdk_call()))

    assert result.structured_output == {"answer": "synthetic"}
    assert result.usage.total_tokens == 7
    assert result.session_ref == (
        f"provider-session://{OPENAI_AGENTS_PROVIDER}/locked-openai-response-1"
    )
    assert captured["agent"].tools == []
    assert captured["agent"].handoffs == []
    assert captured["agent"].mcp_servers == []
    run_config = captured["kwargs"]["run_config"]
    assert run_config.tracing_disabled is True
    assert run_config.trace_include_sensitive_data is False
    assert "synthetic-test-key" not in repr(captured)
