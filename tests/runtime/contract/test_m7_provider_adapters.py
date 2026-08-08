from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest
from flowpilot_agent_runtime import (
    CLAUDE_AGENT_PROVIDER,
    OPENAI_AGENTS_PROVIDER,
    ClaudeAgentSDKAdapter,
    ClaudeAgentSDKTransport,
    FakeSDKTransport,
    OpenAIAgentsSDKAdapter,
    OpenAIAgentsSDKTransport,
    RunStatus,
    RuntimeErrorCode,
    RuntimeUsage,
    SDKRunCall,
    SDKScenario,
    SDKTransportError,
    SDKTransportErrorCode,
)
from flowpilot_domain import DataClassification
from flowpilot_model_gateway import (
    DEEPSEEK_API_KEY_ENV,
    DEEPSEEK_V4_FLASH_MODEL_ID,
    LITELLM_DEEPSEEK_ROUTE,
    LITELLM_PROVIDER,
    PRIMARY_FAST_MODEL,
    FakeLiteLLMTransport,
    LiteLLMProvider,
    LiteLLMProviderConfig,
    LiteLLMScenario,
    LiteLLMTransportError,
    LiteLLMTransportErrorCode,
    OnlineLiteLLMTransport,
    ProviderWireError,
    ProviderWireErrorCode,
    ProviderWireRequest,
    run_provider_conformance,
)


def _wire_request(
    *,
    maximum_input_tokens: int = 4096,
    maximum_output_tokens: int = 1024,
) -> ProviderWireRequest:
    return ProviderWireRequest(
        request_id="provider_req_12345678",
        task="summarize",
        payload={"agent_id": "knowledge-agent", "purpose": "it_support"},
        data_classification=DataClassification.INTERNAL,
        maximum_input_tokens=maximum_input_tokens,
        maximum_output_tokens=maximum_output_tokens,
    )


def _sdk_request(
    request_factory: Callable[..., Any],
    provider: str,
    *,
    session_ref: str | None = None,
) -> Any:
    base = request_factory()
    policy = replace(base.context.policy, provider_allowlist=(provider,))
    context = replace(base.context, policy=policy)
    selection = replace(
        base.provider_selection,
        provider=provider,
        model=PRIMARY_FAST_MODEL,
    )
    return replace(
        base,
        context=context,
        provider_selection=selection,
        session_ref=session_ref,
    )


def _sdk_call(*, session_ref: str | None = None) -> SDKRunCall:
    return SDKRunCall(
        request_id="sdk_req_12345678",
        agent_id="knowledge-agent",
        prompt_version="prompt-v1",
        logical_model=PRIMARY_FAST_MODEL,
        instructions="Return JSON.",
        input_json='{"context":"synthetic"}',
        maximum_turns=2,
        maximum_output_tokens=256,
        timeout_ms=30_000,
        session_ref=session_ref,
    )


def _adapter(provider: str, transport: FakeSDKTransport, clock: Callable):
    if provider == OPENAI_AGENTS_PROVIDER:
        return OpenAIAgentsSDKAdapter(transport, clock=clock)
    return ClaudeAgentSDKAdapter(transport, clock=clock)


def test_litellm_provider_uses_private_deepseek_mapping_and_conforms(
    fixed_clock: Callable[[], datetime],
) -> None:
    transport = FakeLiteLLMTransport(LiteLLMScenario(output={"answer": "synthetic"}))
    provider = LiteLLMProvider(transport)

    result = asyncio.run(provider.complete(_wire_request()))
    report = asyncio.run(run_provider_conformance(provider, clock=fixed_clock))

    assert result.provider == LITELLM_PROVIDER
    assert result.model == PRIMARY_FAST_MODEL
    assert result.output == {"answer": "synthetic"}
    assert transport.calls[0].transport_model == LITELLM_DEEPSEEK_ROUTE
    assert DEEPSEEK_V4_FLASH_MODEL_ID not in repr(_wire_request())
    assert report.passed is True
    assert all(check.passed for check in report.checks)


def test_litellm_provider_rejects_empty_structured_output() -> None:
    provider = LiteLLMProvider(FakeLiteLLMTransport(LiteLLMScenario(output={})))

    with pytest.raises(ProviderWireError) as captured:
        asyncio.run(provider.complete(_wire_request()))

    assert captured.value.code is ProviderWireErrorCode.INVALID_OUTPUT
    assert captured.value.retryable is False


def test_litellm_provider_enforces_its_own_timeout() -> None:
    class HangingTransport:
        async def complete(self, call: Any) -> Any:
            await asyncio.sleep(1)
            raise AssertionError("the transport should have been cancelled")

    provider = LiteLLMProvider(
        HangingTransport(),
        config=LiteLLMProviderConfig(timeout_ms=1),
    )

    with pytest.raises(ProviderWireError) as captured:
        asyncio.run(provider.complete(_wire_request()))

    assert captured.value.code is ProviderWireErrorCode.PROVIDER_UNAVAILABLE
    assert captured.value.retryable is True


@pytest.mark.parametrize(
    ("failure", "expected_code", "retryable"),
    [
        (
            SDKTransportError(SDKTransportErrorCode.RATE_LIMITED),
            RuntimeErrorCode.PROVIDER_UNAVAILABLE,
            True,
        ),
        (
            SDKTransportError(SDKTransportErrorCode.TIMED_OUT),
            RuntimeErrorCode.PROVIDER_UNAVAILABLE,
            True,
        ),
        (
            SDKTransportError(SDKTransportErrorCode.INVALID_OUTPUT),
            RuntimeErrorCode.INVALID_OUTPUT,
            False,
        ),
        (
            SDKTransportError(SDKTransportErrorCode.BUDGET_EXHAUSTED),
            RuntimeErrorCode.BUDGET_EXHAUSTED,
            False,
        ),
        (
            SDKTransportError(SDKTransportErrorCode.GUARDRAIL_BLOCKED),
            RuntimeErrorCode.GUARDRAIL_BLOCKED,
            False,
        ),
    ],
)
@pytest.mark.parametrize(
    "provider",
    [OPENAI_AGENTS_PROVIDER, CLAUDE_AGENT_PROVIDER],
)
def test_sdk_adapters_map_transport_failures_to_stable_runtime_codes(
    provider: str,
    failure: SDKTransportError,
    expected_code: RuntimeErrorCode,
    retryable: bool,
    request_factory: Callable[..., Any],
    fixed_clock: Callable[[], datetime],
) -> None:
    transport = FakeSDKTransport(SDKScenario(failure=failure))
    adapter = _adapter(provider, transport, fixed_clock)

    result = asyncio.run(adapter.run(_sdk_request(request_factory, provider)))

    assert result.structured_output is None
    assert result.error is not None
    assert result.error.code is expected_code
    assert result.error.retryable is retryable
    assert result.status is (
        RunStatus.FAILED_RETRYABLE
        if retryable
        else {
            RuntimeErrorCode.BUDGET_EXHAUSTED: RunStatus.BUDGET_EXHAUSTED,
            RuntimeErrorCode.GUARDRAIL_BLOCKED: RunStatus.GUARDRAIL_BLOCKED,
        }.get(expected_code, RunStatus.FAILED_FINAL)
    )


@pytest.mark.parametrize(
    "provider",
    [OPENAI_AGENTS_PROVIDER, CLAUDE_AGENT_PROVIDER],
)
def test_sdk_adapters_complete_one_bounded_node_with_exact_usage(
    provider: str,
    request_factory: Callable[..., Any],
    fixed_clock: Callable[[], datetime],
) -> None:
    usage = RuntimeUsage(
        input_tokens=20,
        output_tokens=8,
        total_tokens=28,
        turns=1,
        elapsed_ms=4,
    )
    transport = FakeSDKTransport(
        SDKScenario(
            output={"answer": "synthetic"},
            usage=usage,
            session_ref=f"provider-session://{provider}/session-1",
            provider_run_ref=f"provider-run://{provider}/run-1",
        )
    )
    adapter = _adapter(provider, transport, fixed_clock)

    result = asyncio.run(adapter.run(_sdk_request(request_factory, provider)))

    assert result.status is RunStatus.COMPLETED
    assert result.provider_name == provider
    assert result.provider_model == PRIMARY_FAST_MODEL
    assert result.structured_output == {"answer": "synthetic"}
    assert result.usage == usage
    assert result.public_reasoning_summary is not None
    assert "hidden" not in result.public_reasoning_summary.lower()
    assert len(transport.calls) == 1
    assert transport.calls[0].maximum_turns == 4
    assert transport.calls[0].logical_model == PRIMARY_FAST_MODEL


@pytest.mark.parametrize(
    "provider",
    [OPENAI_AGENTS_PROVIDER, CLAUDE_AGENT_PROVIDER],
)
def test_invalid_sdk_session_is_rebuilt_without_mutating_business_request(
    provider: str,
    request_factory: Callable[..., Any],
    fixed_clock: Callable[[], datetime],
) -> None:
    old_session = f"provider-session://{provider}/expired-session"
    new_session = f"provider-session://{provider}/new-session"
    request = _sdk_request(
        request_factory,
        provider,
        session_ref=old_session,
    )
    transport = FakeSDKTransport()
    transport.script(
        request.request_id,
        (
            SDKScenario(
                failure=SDKTransportError(SDKTransportErrorCode.SESSION_INVALID)
            ),
            SDKScenario(
                output={"answer": "re-established"},
                session_ref=new_session,
            ),
        ),
    )
    adapter = _adapter(provider, transport, fixed_clock)

    result = asyncio.run(adapter.run(request))

    assert result.status is RunStatus.COMPLETED
    assert result.session_ref == new_session
    assert request.session_ref == old_session
    assert [call.session_ref for call in transport.calls] == [old_session, None]
    assert {call.logical_model for call in transport.calls} == {PRIMARY_FAST_MODEL}


@pytest.mark.parametrize(
    "provider",
    [OPENAI_AGENTS_PROVIDER, CLAUDE_AGENT_PROVIDER],
)
def test_sdk_adapter_enforces_usage_budget_after_transport(
    provider: str,
    request_factory: Callable[..., Any],
    fixed_clock: Callable[[], datetime],
) -> None:
    transport = FakeSDKTransport(
        SDKScenario(
            usage=RuntimeUsage(
                input_tokens=4097,
                output_tokens=1,
                total_tokens=4098,
                turns=1,
                elapsed_ms=1,
            )
        )
    )
    adapter = _adapter(provider, transport, fixed_clock)

    result = asyncio.run(adapter.run(_sdk_request(request_factory, provider)))

    assert result.status is RunStatus.BUDGET_EXHAUSTED
    assert result.error is not None
    assert result.error.code is RuntimeErrorCode.BUDGET_EXHAUSTED


@pytest.mark.parametrize(
    "provider",
    [OPENAI_AGENTS_PROVIDER, CLAUDE_AGENT_PROVIDER],
)
def test_sdk_adapters_reject_empty_structured_output(
    provider: str,
    request_factory: Callable[..., Any],
    fixed_clock: Callable[[], datetime],
) -> None:
    adapter = _adapter(
        provider,
        FakeSDKTransport(SDKScenario(output={})),
        fixed_clock,
    )

    result = asyncio.run(adapter.run(_sdk_request(request_factory, provider)))

    assert result.status is RunStatus.FAILED_FINAL
    assert result.error is not None
    assert result.error.code is RuntimeErrorCode.INVALID_OUTPUT


@pytest.mark.parametrize(
    "provider",
    [OPENAI_AGENTS_PROVIDER, CLAUDE_AGENT_PROVIDER],
)
def test_sdk_adapters_enforce_their_own_timeout(
    provider: str,
    request_factory: Callable[..., Any],
    fixed_clock: Callable[[], datetime],
) -> None:
    class HangingTransport:
        async def run(self, call: SDKRunCall) -> Any:
            await asyncio.sleep(1)
            raise AssertionError("the transport should have been cancelled")

    request = _sdk_request(request_factory, provider)
    request = replace(
        request,
        budget=replace(request.budget, timeout_ms=1),
    )
    adapter = (
        OpenAIAgentsSDKAdapter(HangingTransport(), clock=fixed_clock)
        if provider == OPENAI_AGENTS_PROVIDER
        else ClaudeAgentSDKAdapter(HangingTransport(), clock=fixed_clock)
    )

    result = asyncio.run(adapter.run(request))

    assert result.status is RunStatus.FAILED_RETRYABLE
    assert result.error is not None
    assert result.error.code is RuntimeErrorCode.PROVIDER_UNAVAILABLE
    assert result.error.retryable is True


def test_online_litellm_bridge_parses_official_model_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeLiteLLMModule:
        @staticmethod
        async def acompletion(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {
                "id": "deepseek-response-1",
                "model": DEEPSEEK_V4_FLASH_MODEL_ID,
                "choices": [{"message": {"content": '{"answer":"synthetic"}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            }

    monkeypatch.setenv(DEEPSEEK_API_KEY_ENV, "synthetic-test-key")
    provider = LiteLLMProvider(
        OnlineLiteLLMTransport(
            enabled=True,
            module_loader=lambda: FakeLiteLLMModule,
        )
    )

    result = asyncio.run(provider.complete(_wire_request()))

    assert result.output == {"answer": "synthetic"}
    assert result.input_tokens == 12
    assert result.output_tokens == 4
    assert captured["model"] == LITELLM_DEEPSEEK_ROUTE
    assert "synthetic-test-key" not in repr(captured)


def test_online_litellm_bridge_rejects_provider_model_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeLiteLLMModule:
        @staticmethod
        async def acompletion(**kwargs: Any) -> dict[str, Any]:
            return {
                "id": "wrong-model-response-1",
                "model": "unexpected-provider-model",
                "choices": [{"message": {"content": '{"answer":"synthetic"}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            }

    monkeypatch.setenv(DEEPSEEK_API_KEY_ENV, "synthetic-test-key")
    provider = LiteLLMProvider(
        OnlineLiteLLMTransport(
            enabled=True,
            module_loader=lambda: FakeLiteLLMModule,
        )
    )

    with pytest.raises(ProviderWireError) as captured:
        asyncio.run(provider.complete(_wire_request()))

    assert captured.value.code is ProviderWireErrorCode.INVALID_OUTPUT
    assert captured.value.retryable is False


def test_openai_agents_online_bridge_disables_sensitive_trace_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class Agent:
        def __init__(self, **kwargs: Any) -> None:
            captured["agent"] = kwargs

    class RunConfig:
        def __init__(self, **kwargs: Any) -> None:
            captured["run_config"] = kwargs

    class Runner:
        @staticmethod
        async def run(agent: Any, input_value: str, **kwargs: Any) -> Any:
            captured["runner"] = (agent, input_value, kwargs)
            usage = SimpleNamespace(
                input_tokens=10,
                output_tokens=3,
                total_tokens=13,
                requests=1,
            )
            return SimpleNamespace(
                final_output='{"answer":"synthetic"}',
                last_response_id="resp-1",
                context_wrapper=SimpleNamespace(usage=usage),
            )

    module = SimpleNamespace(Agent=Agent, RunConfig=RunConfig, Runner=Runner)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-key")
    transport = OpenAIAgentsSDKTransport(
        enabled=True,
        provider_model_id="synthetic-openai-model",
        module_loader=lambda: module,
    )

    result = asyncio.run(transport.run(_sdk_call()))

    assert result.structured_output == {"answer": "synthetic"}
    assert captured["agent"]["tools"] == []
    assert captured["agent"]["handoffs"] == []
    assert captured["run_config"]["tracing_disabled"] is True
    assert captured["run_config"]["trace_include_sensitive_data"] is False
    assert "synthetic-test-key" not in repr(captured)


def test_claude_agent_online_bridge_disables_tools_and_bounds_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class ClaudeAgentOptions:
        def __init__(self, **kwargs: Any) -> None:
            captured["options"] = kwargs

    class AssistantMessage:
        pass

    class ResultMessage:
        result = '{"answer":"synthetic"}'
        session_id = "session-1"
        usage = {"input_tokens": 11, "output_tokens": 5}
        total_cost_usd = 0.000001

    async def query(**kwargs: Any):  # type: ignore[no-untyped-def]
        captured["query"] = kwargs
        yield AssistantMessage()
        yield ResultMessage()

    module = SimpleNamespace(
        ClaudeAgentOptions=ClaudeAgentOptions,
        query=query,
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-test-key")
    transport = ClaudeAgentSDKTransport(
        enabled=True,
        provider_model_id="synthetic-claude-model",
        module_loader=lambda: module,
    )

    result = asyncio.run(transport.run(_sdk_call()))

    assert result.structured_output == {"answer": "synthetic"}
    assert result.usage.cost_microunits == 1
    assert captured["options"]["tools"] == []
    assert captured["options"]["allowed_tools"] == []
    assert captured["options"]["disallowed_tools"] == []
    assert captured["options"]["mcp_servers"] == {}
    assert captured["options"]["strict_mcp_config"] is True
    assert captured["options"]["plugins"] == []
    assert captured["options"]["agents"] is None
    assert captured["options"]["hooks"] is None
    assert captured["options"]["skills"] == []
    assert captured["options"]["setting_sources"] == []
    assert captured["options"]["can_use_tool"] is None
    assert captured["options"]["max_turns"] == 2
    assert "synthetic-test-key" not in repr(captured)


def test_litellm_transport_failures_are_stable_and_sanitized() -> None:
    transport = FakeLiteLLMTransport(
        LiteLLMScenario(
            failure=LiteLLMTransportError(LiteLLMTransportErrorCode.RATE_LIMITED)
        )
    )
    provider = LiteLLMProvider(transport)

    with pytest.raises(ProviderWireError) as captured:
        asyncio.run(provider.complete(_wire_request()))

    assert captured.value.code is ProviderWireErrorCode.PROVIDER_UNAVAILABLE
    assert captured.value.retryable is True
    assert "key" not in captured.value.safe_message.lower()
