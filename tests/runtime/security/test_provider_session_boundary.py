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
    FakeSDKTransport,
    OpenAIAgentsSDKAdapter,
    RunStatus,
    RuntimeErrorCode,
    SDKScenario,
    ToolOperation,
    ToolProposal,
    ToolScopeError,
    validate_tool_proposals,
)
from flowpilot_model_gateway import PRIMARY_FAST_MODEL

PROVIDERS = (OPENAI_AGENTS_PROVIDER, CLAUDE_AGENT_PROVIDER)
PRIVATE_SESSION = "provider-session://private/nested-session"


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


def _adapter(
    provider: str,
    transport: FakeSDKTransport,
    clock: Callable[[], datetime],
) -> OpenAIAgentsSDKAdapter | ClaudeAgentSDKAdapter:
    if provider == OPENAI_AGENTS_PROVIDER:
        return OpenAIAgentsSDKAdapter(transport, clock=clock)
    return ClaudeAgentSDKAdapter(transport, clock=clock)


def _proposal(
    *,
    arguments: dict[str, Any] | None = None,
    resource: dict[str, Any] | None = None,
) -> ToolProposal:
    return ToolProposal(
        proposal_id="tprop_session_boundary_1",
        tool="knowledge.search.v1",
        operation=ToolOperation.READ,
        arguments=arguments or {"query": "synthetic"},
        resource=resource or {"type": "knowledge"},
        purpose="it_support",
    )


@pytest.mark.parametrize("provider", PROVIDERS)
def test_nested_context_session_ref_is_rejected_before_transport(
    provider: str,
    request_factory: Callable[..., Any],
    fixed_clock: Callable[[], datetime],
) -> None:
    request = _request(request_factory, provider)
    layers = list(request.context.layers)
    task_layer = layers[-1]
    layers[-1] = replace(
        task_layer,
        content={
            "status": "RUNNING",
            "private": [{"session_ref": PRIVATE_SESSION}],
        },
    )
    request = replace(
        request,
        context=replace(request.context, layers=tuple(layers)),
    )
    transport = FakeSDKTransport()

    result = asyncio.run(_adapter(provider, transport, fixed_clock).run(request))

    assert result.status is RunStatus.FAILED_FINAL
    assert result.error is not None
    assert result.error.code is RuntimeErrorCode.REQUEST_INCONSISTENT
    assert result.structured_output is None
    assert result.session_ref is None
    assert transport.calls == []
    assert PRIVATE_SESSION not in repr(result)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_nested_structured_output_session_ref_is_rejected(
    provider: str,
    request_factory: Callable[..., Any],
    fixed_clock: Callable[[], datetime],
) -> None:
    transport = FakeSDKTransport(
        SDKScenario(output={"answer": {"evidence": [{"session_ref": PRIVATE_SESSION}]}})
    )

    result = asyncio.run(
        _adapter(provider, transport, fixed_clock).run(
            _request(request_factory, provider)
        )
    )

    assert result.status is RunStatus.FAILED_FINAL
    assert result.error is not None
    assert result.error.code is RuntimeErrorCode.INVALID_OUTPUT
    assert result.structured_output is None
    assert result.session_ref is None
    assert PRIVATE_SESSION not in repr(result)


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("location", ["arguments", "resource"])
def test_nested_tool_proposal_session_ref_is_rejected(
    provider: str,
    location: str,
    request_factory: Callable[..., Any],
    fixed_clock: Callable[[], datetime],
) -> None:
    nested = {"metadata": [{"session_ref": PRIVATE_SESSION}]}
    proposal = _proposal(**{location: nested})
    transport = FakeSDKTransport(SDKScenario(tool_proposals=(proposal,)))

    result = asyncio.run(
        _adapter(provider, transport, fixed_clock).run(
            _request(request_factory, provider)
        )
    )

    assert result.status is RunStatus.FAILED_FINAL
    assert result.error is not None
    assert result.error.code is RuntimeErrorCode.INVALID_OUTPUT
    assert result.structured_output is None
    assert result.tool_proposals == ()
    assert result.session_ref is None
    assert PRIVATE_SESSION not in repr(result)


@pytest.mark.parametrize("location", ["arguments", "resource"])
def test_shared_tool_validation_rejects_nested_session_ref(
    location: str,
    request_factory: Callable[..., Any],
) -> None:
    request = request_factory()
    nested = {"metadata": [{"session_ref": PRIVATE_SESSION}]}

    with pytest.raises(ToolScopeError):
        validate_tool_proposals(
            request,
            (_proposal(**{location: nested}),),
        )


@pytest.mark.parametrize("provider", PROVIDERS)
def test_top_level_typed_session_refs_remain_opaque_and_allowed(
    provider: str,
    request_factory: Callable[..., Any],
    fixed_clock: Callable[[], datetime],
) -> None:
    request_session = f"provider-session://{provider}/request-session"
    result_session = f"provider-session://{provider}/result-session"
    request = replace(
        _request(request_factory, provider),
        session_ref=request_session,
    )
    transport = FakeSDKTransport(
        SDKScenario(
            output={"answer": "synthetic"},
            session_ref=result_session,
        )
    )

    result = asyncio.run(_adapter(provider, transport, fixed_clock).run(request))

    assert result.status is RunStatus.COMPLETED
    assert result.session_ref == result_session
    assert transport.calls[0].session_ref == request_session
    assert "session_ref" not in transport.calls[0].input_json
    assert request_session not in transport.calls[0].input_json
    assert result.structured_output == {"answer": "synthetic"}
