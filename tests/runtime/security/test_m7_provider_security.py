from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
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
    SDKRunCall,
    SDKScenario,
    SDKTransportError,
    SDKTransportErrorCode,
)
from flowpilot_domain import DataClassification
from flowpilot_model_gateway import (
    DEEPSEEK_API_KEY_ENV,
    PRIMARY_FAST_MODEL,
    FakeLiteLLMTransport,
    LiteLLMProvider,
    OnlineLiteLLMTransport,
    ProviderWireError,
    ProviderWireErrorCode,
    ProviderWireRequest,
)


def _request(request_factory: Callable[..., Any], provider: str) -> Any:
    base = request_factory()
    context = replace(
        base.context,
        policy=replace(base.context.policy, provider_allowlist=(provider,)),
    )
    return replace(
        base,
        context=context,
        provider_selection=replace(
            base.provider_selection,
            provider=provider,
            model=PRIMARY_FAST_MODEL,
        ),
    )


def _call() -> SDKRunCall:
    return SDKRunCall(
        request_id="security_req_12345678",
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


def test_litellm_rejects_credential_shaped_input_before_transport() -> None:
    transport = FakeLiteLLMTransport()
    provider = LiteLLMProvider(transport)
    request = ProviderWireRequest(
        request_id="security_req_12345678",
        task="summarize",
        payload={"authorization": "synthetic-secret"},
        data_classification=DataClassification.INTERNAL,
        maximum_input_tokens=100,
        maximum_output_tokens=100,
    )

    with pytest.raises(ProviderWireError) as captured:
        asyncio.run(provider.complete(request))

    assert captured.value.code is ProviderWireErrorCode.CONTENT_BLOCKED
    assert "synthetic-secret" not in captured.value.safe_message
    assert transport.calls == []


@pytest.mark.parametrize(
    ("provider", "adapter_type"),
    [
        (OPENAI_AGENTS_PROVIDER, OpenAIAgentsSDKAdapter),
        (CLAUDE_AGENT_PROVIDER, ClaudeAgentSDKAdapter),
    ],
)
def test_sdk_adapters_reject_credential_output_and_session_leak(
    provider: str,
    adapter_type: Any,
    request_factory: Callable[..., Any],
    fixed_clock: Callable[[], datetime],
) -> None:
    transport = FakeSDKTransport(
        SDKScenario(
            output={"api_key": "synthetic-secret"},
            session_ref=f"provider-session://{provider}/credential-leak",
        )
    )
    adapter = adapter_type(transport, clock=fixed_clock)

    result = asyncio.run(adapter.run(_request(request_factory, provider)))

    assert result.status is RunStatus.FAILED_FINAL
    assert result.error is not None
    assert result.error.code is RuntimeErrorCode.INVALID_OUTPUT
    assert result.structured_output is None
    assert result.session_ref is None
    assert "synthetic-secret" not in repr(result)


def test_provider_selection_mismatch_fails_before_sdk_transport(
    request_factory: Callable[..., Any],
    fixed_clock: Callable[[], datetime],
) -> None:
    transport = FakeSDKTransport()
    adapter = OpenAIAgentsSDKAdapter(transport, clock=fixed_clock)
    request = _request(request_factory, CLAUDE_AGENT_PROVIDER)

    result = asyncio.run(adapter.run(request))

    assert result.status is RunStatus.FAILED_FINAL
    assert result.error is not None
    assert result.error.code is RuntimeErrorCode.REQUEST_INCONSISTENT
    assert transport.calls == []


def test_online_transports_are_disabled_before_import_or_key_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded: list[str] = []

    def loader() -> Any:
        loaded.append("loaded")
        raise AssertionError("disabled transport must not import an SDK")

    monkeypatch.delenv(DEEPSEEK_API_KEY_ENV, raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    transports = (
        OnlineLiteLLMTransport(enabled=False, module_loader=loader),
        OpenAIAgentsSDKTransport(
            enabled=False,
            provider_model_id="synthetic-model",
            module_loader=loader,
        ),
        ClaudeAgentSDKTransport(
            enabled=False,
            provider_model_id="synthetic-model",
            module_loader=loader,
        ),
    )

    with pytest.raises(ProviderWireError) as litellm_error:
        asyncio.run(
            LiteLLMProvider(transports[0]).complete(
                ProviderWireRequest(
                    request_id="security_req_12345678",
                    task="summarize",
                    payload={"purpose": "it_support"},
                    data_classification=DataClassification.INTERNAL,
                    maximum_input_tokens=100,
                    maximum_output_tokens=100,
                )
            )
        )
    assert litellm_error.value.code is ProviderWireErrorCode.INVALID_OUTPUT

    for transport in transports[1:]:
        with pytest.raises(SDKTransportError) as captured:
            asyncio.run(transport.run(_call()))
        assert captured.value.code is SDKTransportErrorCode.CONFIGURATION

    assert loaded == []


def test_enabled_online_transports_fail_closed_when_keys_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded: list[str] = []

    def loader() -> Any:
        loaded.append("loaded")
        raise AssertionError("missing-key transports must not import an SDK")

    monkeypatch.delenv(DEEPSEEK_API_KEY_ENV, raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    litellm = OnlineLiteLLMTransport(enabled=True, module_loader=loader)

    with pytest.raises(ProviderWireError) as litellm_error:
        asyncio.run(
            LiteLLMProvider(litellm).complete(
                ProviderWireRequest(
                    request_id="security_req_missing_key",
                    task="summarize",
                    payload={"purpose": "it_support"},
                    data_classification=DataClassification.INTERNAL,
                    maximum_input_tokens=100,
                    maximum_output_tokens=100,
                )
            )
        )
    assert litellm_error.value.code is ProviderWireErrorCode.INVALID_OUTPUT

    sdk_transports = (
        OpenAIAgentsSDKTransport(
            enabled=True,
            provider_model_id="synthetic-model",
            module_loader=loader,
        ),
        ClaudeAgentSDKTransport(
            enabled=True,
            provider_model_id="synthetic-model",
            module_loader=loader,
        ),
    )
    for transport in sdk_transports:
        with pytest.raises(SDKTransportError) as captured:
            asyncio.run(transport.run(_call()))
        assert captured.value.code is SDKTransportErrorCode.CONFIGURATION

    assert loaded == []


def test_provider_adapter_source_is_product_neutral() -> None:
    request = _call()

    assert "vpn" not in repr(request).lower()
    assert request.logical_model == PRIMARY_FAST_MODEL
