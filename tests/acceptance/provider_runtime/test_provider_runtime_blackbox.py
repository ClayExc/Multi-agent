from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from flowpilot_agent_runtime import (
    ANTHROPIC_API_KEY_ENV,
    CLAUDE_MODEL_ENV,
    OPENAI_API_KEY_ENV,
    OPENAI_MODEL_ENV,
    ClaudeAgentSDKTransport,
    FakeSDKTransport,
    OpenAIAgentsSDKTransport,
    RunStatus,
    RuntimeErrorCode,
    RuntimeUsage,
    SDKRunCall,
    SDKRunCompletion,
    SDKScenario,
    SDKTransportError,
    SDKTransportErrorCode,
    ToolOperation,
    ToolProposal,
)
from flowpilot_context import LayerName
from flowpilot_model_gateway import (
    DEEPSEEK_API_KEY_ENV,
    ONLINE_SMOKE_ENV,
    FakeLiteLLMTransport,
    LiteLLMCompletion,
    LiteLLMProvider,
    LiteLLMProviderConfig,
    LiteLLMScenario,
    LiteLLMTransportError,
    LiteLLMTransportErrorCode,
    OnlineLiteLLMTransport,
    ProviderWireError,
    ProviderWireErrorCode,
)

from .blackbox import (
    PRIVATE_SESSION,
    PROVIDERS,
    SYNTHETIC_SECRET,
    adapter_for,
    call_business_fingerprint,
    runtime_request,
    sdk_call,
    wire_request,
)


class _TripwireLoader:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> Any:
        self.calls += 1
        raise AssertionError("an offline gate attempted to load an online SDK")


class _HangingLiteLLMTransport:
    async def complete(self, call: Any) -> Any:
        await asyncio.sleep(1)
        raise AssertionError("timeout cancellation did not occur")


class _HangingSDKTransport:
    async def run(self, call: SDKRunCall) -> SDKRunCompletion:
        await asyncio.sleep(1)
        raise AssertionError("timeout cancellation did not occur")


@pytest.mark.parametrize("configured_value", [None, "0", "true"])
async def test_online_bridges_remain_off_unless_explicitly_enabled(
    monkeypatch: pytest.MonkeyPatch,
    configured_value: str | None,
) -> None:
    if configured_value is None:
        monkeypatch.delenv(ONLINE_SMOKE_ENV, raising=False)
    else:
        monkeypatch.setenv(ONLINE_SMOKE_ENV, configured_value)
    monkeypatch.setenv(DEEPSEEK_API_KEY_ENV, SYNTHETIC_SECRET)
    monkeypatch.setenv(OPENAI_API_KEY_ENV, SYNTHETIC_SECRET)
    monkeypatch.setenv(ANTHROPIC_API_KEY_ENV, SYNTHETIC_SECRET)
    monkeypatch.setenv(OPENAI_MODEL_ENV, "synthetic-openai-model")
    monkeypatch.setenv(CLAUDE_MODEL_ENV, "synthetic-claude-model")
    transports = (
        OnlineLiteLLMTransport.from_environment(),
        OpenAIAgentsSDKTransport.from_environment(),
        ClaudeAgentSDKTransport.from_environment(),
    )
    loaders = tuple(_TripwireLoader() for _ in transports)
    for transport, loader in zip(transports, loaders, strict=True):
        monkeypatch.setattr(transport, "_module_loader", loader)

    with pytest.raises(LiteLLMTransportError) as lite_error:
        await transports[0].complete(SimpleNamespace())
    with pytest.raises(SDKTransportError) as openai_error:
        await transports[1].run(sdk_call())
    with pytest.raises(SDKTransportError) as claude_error:
        await transports[2].run(sdk_call())

    assert lite_error.value.code is LiteLLMTransportErrorCode.CONFIGURATION
    assert openai_error.value.code is SDKTransportErrorCode.CONFIGURATION
    assert claude_error.value.code is SDKTransportErrorCode.CONFIGURATION
    assert [loader.calls for loader in loaders] == [0, 0, 0]
    assert SYNTHETIC_SECRET not in repr((lite_error, openai_error, claude_error))


async def test_missing_keys_fail_before_any_sdk_module_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ONLINE_SMOKE_ENV, "1")
    monkeypatch.delenv(DEEPSEEK_API_KEY_ENV, raising=False)
    monkeypatch.delenv(OPENAI_API_KEY_ENV, raising=False)
    monkeypatch.delenv(ANTHROPIC_API_KEY_ENV, raising=False)
    loaders = tuple(_TripwireLoader() for _ in range(3))
    lite = OnlineLiteLLMTransport(enabled=True, module_loader=loaders[0])
    openai = OpenAIAgentsSDKTransport(
        enabled=True,
        provider_model_id="synthetic-openai-model",
        module_loader=loaders[1],
    )
    claude = ClaudeAgentSDKTransport(
        enabled=True,
        provider_model_id="synthetic-claude-model",
        module_loader=loaders[2],
    )

    with pytest.raises(LiteLLMTransportError) as lite_error:
        await lite.complete(SimpleNamespace())
    with pytest.raises(SDKTransportError) as openai_error:
        await openai.run(sdk_call())
    with pytest.raises(SDKTransportError) as claude_error:
        await claude.run(sdk_call())

    assert lite_error.value.code is LiteLLMTransportErrorCode.CONFIGURATION
    assert openai_error.value.code is SDKTransportErrorCode.CONFIGURATION
    assert claude_error.value.code is SDKTransportErrorCode.CONFIGURATION
    assert [loader.calls for loader in loaders] == [0, 0, 0]


async def test_litellm_timeout_is_retryable_and_sanitized() -> None:
    provider = LiteLLMProvider(
        _HangingLiteLLMTransport(),
        config=LiteLLMProviderConfig(timeout_ms=1),
    )

    with pytest.raises(ProviderWireError) as captured:
        await provider.complete(wire_request())

    assert captured.value.code is ProviderWireErrorCode.PROVIDER_UNAVAILABLE
    assert captured.value.retryable is True
    assert SYNTHETIC_SECRET not in repr(captured.value)


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_sdk_timeout_is_retryable_and_sanitized(provider: str) -> None:
    request = runtime_request(provider)
    request = replace(
        request,
        budget=replace(request.budget, timeout_ms=1),
    )

    result = await adapter_for(provider, _HangingSDKTransport()).run(request)

    assert result.status is RunStatus.FAILED_RETRYABLE
    assert result.error is not None
    assert result.error.code is RuntimeErrorCode.PROVIDER_UNAVAILABLE
    assert result.error.retryable is True
    assert SYNTHETIC_SECRET not in repr(result)


async def test_litellm_rate_limit_maps_to_retryable_unavailable() -> None:
    transport = FakeLiteLLMTransport(
        LiteLLMScenario(
            failure=LiteLLMTransportError(
                LiteLLMTransportErrorCode.RATE_LIMITED
            )
        )
    )

    with pytest.raises(ProviderWireError) as captured:
        await LiteLLMProvider(transport).complete(wire_request())

    assert captured.value.code is ProviderWireErrorCode.PROVIDER_UNAVAILABLE
    assert captured.value.retryable is True


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_sdk_rate_limit_maps_to_retryable_unavailable(provider: str) -> None:
    transport = FakeSDKTransport(
        SDKScenario(
            failure=SDKTransportError(SDKTransportErrorCode.RATE_LIMITED)
        )
    )

    result = await adapter_for(provider, transport).run(runtime_request(provider))

    assert result.status is RunStatus.FAILED_RETRYABLE
    assert result.error is not None
    assert result.error.code is RuntimeErrorCode.PROVIDER_UNAVAILABLE
    assert result.error.retryable is True


async def test_litellm_empty_output_and_budget_overrun_cannot_succeed() -> None:
    empty = LiteLLMProvider(FakeLiteLLMTransport(LiteLLMScenario(output={})))
    with pytest.raises(ProviderWireError) as empty_error:
        await empty.complete(wire_request())
    assert empty_error.value.code is ProviderWireErrorCode.INVALID_OUTPUT

    class OverBudgetTransport:
        async def complete(self, call: Any) -> LiteLLMCompletion:
            return LiteLLMCompletion(
                response_id="llm_acceptance_over_budget",
                provider_model_id="deepseek-v4-flash",
                output={"answer": "synthetic"},
                input_tokens=513,
                output_tokens=1,
            )

    with pytest.raises(ProviderWireError) as budget_error:
        await LiteLLMProvider(OverBudgetTransport()).complete(wire_request())
    assert budget_error.value.code is ProviderWireErrorCode.BUDGET_EXHAUSTED
    assert budget_error.value.retryable is False


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_sdk_empty_output_and_measured_budget_overrun_cannot_succeed(
    provider: str,
) -> None:
    empty_result = await adapter_for(
        provider,
        FakeSDKTransport(SDKScenario(output={})),
    ).run(runtime_request(provider))
    assert empty_result.status is RunStatus.FAILED_FINAL
    assert empty_result.error is not None
    assert empty_result.error.code is RuntimeErrorCode.INVALID_OUTPUT

    usage = RuntimeUsage(
        input_tokens=513,
        output_tokens=1,
        total_tokens=514,
        turns=1,
        elapsed_ms=1,
    )
    budget_result = await adapter_for(
        provider,
        FakeSDKTransport(SDKScenario(output={"answer": "synthetic"}, usage=usage)),
    ).run(runtime_request(provider))
    assert budget_result.status is RunStatus.BUDGET_EXHAUSTED
    assert budget_result.structured_output is None
    assert budget_result.usage == usage


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_invalid_session_rebuilds_once_without_mutating_business_call(
    provider: str,
) -> None:
    old_session = f"provider-session://{provider}/expired-session"
    new_session = f"provider-session://{provider}/replacement-session"
    request = runtime_request(provider, session_ref=old_session)
    transport = FakeSDKTransport()
    transport.script(
        request.request_id,
        (
            SDKScenario(
                failure=SDKTransportError(SDKTransportErrorCode.SESSION_INVALID)
            ),
            SDKScenario(output={"answer": "recovered"}, session_ref=new_session),
        ),
    )

    result = await adapter_for(provider, transport).run(request)

    assert result.status is RunStatus.COMPLETED
    assert result.session_ref == new_session
    assert request.session_ref == old_session
    assert [call.session_ref for call in transport.calls] == [old_session, None]
    assert call_business_fingerprint(transport.calls[0]) == call_business_fingerprint(
        transport.calls[1]
    )
    assert old_session not in transport.calls[0].input_json


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_nested_context_session_is_rejected_before_transport(
    provider: str,
) -> None:
    request = runtime_request(provider)
    layers = list(request.context.layers)
    task_index = next(
        index
        for index, layer in enumerate(layers)
        if layer.name is LayerName.TASK_STATE
    )
    layers[task_index] = replace(
        layers[task_index],
        content={"status": "RUNNING", "private": [{"session_ref": PRIVATE_SESSION}]},
    )
    request = replace(
        request,
        context=replace(request.context, layers=tuple(layers)),
    )
    transport = FakeSDKTransport()

    result = await adapter_for(provider, transport).run(request)

    assert result.status is RunStatus.FAILED_FINAL
    assert result.error is not None
    assert result.error.code is RuntimeErrorCode.REQUEST_INCONSISTENT
    assert result.structured_output is None
    assert transport.calls == []
    assert PRIVATE_SESSION not in repr(result)


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_nested_output_session_is_rejected_without_leak(provider: str) -> None:
    transport = FakeSDKTransport(
        SDKScenario(
            output={"answer": {"evidence": [{"session_ref": PRIVATE_SESSION}]}}
        )
    )

    result = await adapter_for(provider, transport).run(runtime_request(provider))

    assert result.status is RunStatus.FAILED_FINAL
    assert result.error is not None
    assert result.error.code is RuntimeErrorCode.INVALID_OUTPUT
    assert result.structured_output is None
    assert result.session_ref is None
    assert PRIVATE_SESSION not in repr(result)


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("location", ["arguments", "resource"])
async def test_nested_tool_session_is_rejected_without_leak(
    provider: str,
    location: str,
) -> None:
    nested = {"metadata": [{"session_ref": PRIVATE_SESSION}]}
    proposal = ToolProposal(
        proposal_id="tprop_acceptance123",
        tool="knowledge.search.v1",
        operation=ToolOperation.READ,
        arguments=nested if location == "arguments" else {"query": "synthetic"},
        resource=nested if location == "resource" else {"type": "knowledge"},
        purpose="it_support",
    )
    transport = FakeSDKTransport(SDKScenario(tool_proposals=(proposal,)))

    result = await adapter_for(provider, transport).run(runtime_request(provider))

    assert result.status is RunStatus.FAILED_FINAL
    assert result.error is not None
    assert result.error.code is RuntimeErrorCode.INVALID_OUTPUT
    assert result.structured_output is None
    assert result.tool_proposals == ()
    assert result.session_ref is None
    assert PRIVATE_SESSION not in repr(result)


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_typed_session_channel_stays_opaque_and_outside_business_json(
    provider: str,
) -> None:
    request_session = f"provider-session://{provider}/request-session"
    result_session = f"provider-session://{provider}/result-session"
    transport = FakeSDKTransport(
        SDKScenario(
            output={"answer": "synthetic"},
            session_ref=result_session,
        )
    )

    result = await adapter_for(provider, transport).run(
        runtime_request(provider, session_ref=request_session)
    )

    assert result.status is RunStatus.COMPLETED
    assert result.session_ref == result_session
    assert transport.calls[0].session_ref == request_session
    assert "session_ref" not in transport.calls[0].input_json
    assert request_session not in transport.calls[0].input_json
    assert result.structured_output == {"answer": "synthetic"}


async def test_litellm_rejects_nested_session_on_both_wire_directions() -> None:
    transport = FakeLiteLLMTransport()
    with pytest.raises(ProviderWireError) as input_error:
        await LiteLLMProvider(transport).complete(
            wire_request(
                payload={"private": [{"session_ref": PRIVATE_SESSION}]}
            )
        )
    assert input_error.value.code is ProviderWireErrorCode.INVALID_OUTPUT
    assert transport.calls == []

    output_transport = FakeLiteLLMTransport(
        LiteLLMScenario(
            output={"answer": {"session_ref": PRIVATE_SESSION}}
        )
    )
    with pytest.raises(ProviderWireError) as output_error:
        await LiteLLMProvider(output_transport).complete(wire_request())
    assert output_error.value.code is ProviderWireErrorCode.INVALID_OUTPUT
    assert PRIVATE_SESSION not in repr(output_error.value)


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_runtime_rejects_credential_shaped_input_and_output_without_leak(
    provider: str,
) -> None:
    request = runtime_request(provider)
    layers = list(request.context.layers)
    security_index = next(
        index
        for index, layer in enumerate(layers)
        if layer.name is LayerName.SECURITY_VIEW
    )
    layers[security_index] = replace(
        layers[security_index],
        content={"private": [{"authorization": SYNTHETIC_SECRET}]},
    )
    input_transport = FakeSDKTransport()
    input_result = await adapter_for(provider, input_transport).run(
        replace(request, context=replace(request.context, layers=tuple(layers)))
    )
    assert input_result.status is RunStatus.FAILED_FINAL
    assert input_result.error is not None
    assert input_result.error.code is RuntimeErrorCode.REQUEST_INCONSISTENT
    assert input_transport.calls == []
    assert SYNTHETIC_SECRET not in repr(input_result)

    output_transport = FakeSDKTransport(
        SDKScenario(
            output={"answer": {"credential": SYNTHETIC_SECRET}}
        )
    )
    output_result = await adapter_for(provider, output_transport).run(
        runtime_request(provider)
    )
    assert output_result.status is RunStatus.FAILED_FINAL
    assert output_result.error is not None
    assert output_result.error.code is RuntimeErrorCode.INVALID_OUTPUT
    assert output_result.structured_output is None
    assert SYNTHETIC_SECRET not in repr(output_result)


async def test_litellm_rejects_credential_shaped_wire_values_without_leak() -> None:
    input_transport = FakeLiteLLMTransport()
    with pytest.raises(ProviderWireError) as input_error:
        await LiteLLMProvider(input_transport).complete(
            wire_request(
                payload={"private": [{"api_key": SYNTHETIC_SECRET}]}
            )
        )
    assert input_error.value.code is ProviderWireErrorCode.CONTENT_BLOCKED
    assert input_transport.calls == []
    assert SYNTHETIC_SECRET not in repr(input_error.value)

    output_transport = FakeLiteLLMTransport(
        LiteLLMScenario(
            output={"answer": {"credential": SYNTHETIC_SECRET}}
        )
    )
    with pytest.raises(ProviderWireError) as output_error:
        await LiteLLMProvider(output_transport).complete(wire_request())
    assert output_error.value.code is ProviderWireErrorCode.CONTENT_BLOCKED
    assert SYNTHETIC_SECRET not in repr(output_error.value)


async def test_fake_online_bridges_reject_non_object_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DEEPSEEK_API_KEY_ENV, SYNTHETIC_SECRET)
    monkeypatch.setenv(OPENAI_API_KEY_ENV, SYNTHETIC_SECRET)
    monkeypatch.setenv(ANTHROPIC_API_KEY_ENV, SYNTHETIC_SECRET)

    class LiteModule:
        @staticmethod
        async def acompletion(**kwargs: Any) -> dict[str, Any]:
            return {
                "id": "lite-malformed",
                "model": "deepseek-v4-flash",
                "choices": [{"message": {"content": "[1]"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }

    with pytest.raises(LiteLLMTransportError) as lite_error:
        await OnlineLiteLLMTransport(
            enabled=True,
            module_loader=lambda: LiteModule,
        ).complete(
            SimpleNamespace(
                transport_model="deepseek/deepseek-v4-flash",
                messages=(),
                maximum_output_tokens=8,
                timeout_ms=1_000,
            )
        )
    assert lite_error.value.code is LiteLLMTransportErrorCode.INVALID_RESPONSE

    captured: dict[str, Any] = {}

    class Agent:
        def __init__(self, **kwargs: Any) -> None:
            captured["openai_agent"] = kwargs

    class RunConfig:
        def __init__(self, **kwargs: Any) -> None:
            captured["openai_config"] = kwargs

    class Runner:
        @staticmethod
        async def run(agent: Any, input_value: str, **kwargs: Any) -> Any:
            usage = SimpleNamespace(
                input_tokens=1,
                output_tokens=1,
                total_tokens=2,
                requests=1,
            )
            return SimpleNamespace(
                final_output="[1]",
                last_response_id="response-1",
                context_wrapper=SimpleNamespace(usage=usage),
            )

    openai_module = SimpleNamespace(Agent=Agent, RunConfig=RunConfig, Runner=Runner)
    with pytest.raises(SDKTransportError) as openai_error:
        await OpenAIAgentsSDKTransport(
            enabled=True,
            provider_model_id="synthetic-openai-model",
            module_loader=lambda: openai_module,
        ).run(sdk_call())
    assert openai_error.value.code is SDKTransportErrorCode.INVALID_OUTPUT

    class ClaudeAgentOptions:
        def __init__(self, **kwargs: Any) -> None:
            captured["claude_options"] = kwargs

    class ResultMessage:
        result = "[1]"
        session_id = "session-1"
        usage = {"input_tokens": 1, "output_tokens": 1}
        total_cost_usd = 0.0

    async def query(**kwargs: Any):  # type: ignore[no-untyped-def]
        yield ResultMessage()

    claude_module = SimpleNamespace(
        ClaudeAgentOptions=ClaudeAgentOptions,
        query=query,
    )
    with pytest.raises(SDKTransportError) as claude_error:
        await ClaudeAgentSDKTransport(
            enabled=True,
            provider_model_id="synthetic-claude-model",
            module_loader=lambda: claude_module,
        ).run(sdk_call())
    assert claude_error.value.code is SDKTransportErrorCode.INVALID_OUTPUT
    observed = (captured, lite_error, openai_error, claude_error)
    assert SYNTHETIC_SECRET not in repr(observed)


async def test_fake_online_sdk_tool_surfaces_are_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(OPENAI_API_KEY_ENV, SYNTHETIC_SECRET)
    monkeypatch.setenv(ANTHROPIC_API_KEY_ENV, SYNTHETIC_SECRET)
    captured: dict[str, Any] = {}

    class Agent:
        def __init__(self, **kwargs: Any) -> None:
            captured["openai_agent"] = kwargs

    class RunConfig:
        def __init__(self, **kwargs: Any) -> None:
            captured["openai_config"] = kwargs

    class Runner:
        @staticmethod
        async def run(agent: Any, input_value: str, **kwargs: Any) -> Any:
            usage = SimpleNamespace(
                input_tokens=2,
                output_tokens=1,
                total_tokens=3,
                requests=1,
            )
            return SimpleNamespace(
                final_output='{"answer":"synthetic"}',
                last_response_id="response-1",
                context_wrapper=SimpleNamespace(usage=usage),
            )

    openai_module = SimpleNamespace(Agent=Agent, RunConfig=RunConfig, Runner=Runner)
    await OpenAIAgentsSDKTransport(
        enabled=True,
        provider_model_id="synthetic-openai-model",
        module_loader=lambda: openai_module,
    ).run(sdk_call())

    class ClaudeAgentOptions:
        def __init__(self, **kwargs: Any) -> None:
            captured["claude_options"] = kwargs

    class ResultMessage:
        result = '{"answer":"synthetic"}'
        session_id = "session-1"
        usage = {"input_tokens": 2, "output_tokens": 1}
        total_cost_usd = 0.0

    async def query(**kwargs: Any):  # type: ignore[no-untyped-def]
        yield ResultMessage()

    claude_module = SimpleNamespace(
        ClaudeAgentOptions=ClaudeAgentOptions,
        query=query,
    )
    await ClaudeAgentSDKTransport(
        enabled=True,
        provider_model_id="synthetic-claude-model",
        module_loader=lambda: claude_module,
    ).run(sdk_call())

    assert captured["openai_agent"]["tools"] == []
    assert captured["openai_agent"]["handoffs"] == []
    assert captured["openai_config"]["tracing_disabled"] is True
    assert captured["openai_config"]["trace_include_sensitive_data"] is False
    claude_options = captured["claude_options"]
    assert claude_options["tools"] == []
    assert claude_options["allowed_tools"] == []
    assert claude_options["mcp_servers"] == {}
    assert claude_options["strict_mcp_config"] is True
    assert claude_options["plugins"] == []
    assert claude_options["agents"] is None
    assert claude_options["hooks"] is None
    assert claude_options["skills"] == []
    assert claude_options["setting_sources"] == []
    assert claude_options["can_use_tool"] is None
    assert SYNTHETIC_SECRET not in repr(captured)
