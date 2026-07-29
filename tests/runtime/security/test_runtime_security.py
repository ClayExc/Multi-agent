from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

import pytest
from flowpilot_agent_runtime import (
    AgentRunRequest,
    FakeAgentRuntime,
    RunStatus,
    RuntimeErrorCode,
)
from flowpilot_context import ContextLayer, LayerName, TrustLevel
from flowpilot_domain import DataClassification, TaskCommand
from flowpilot_worker import (
    ExecutionSubmissionError,
    InMemoryExecutionQueue,
    RuntimeExecutionAdapter,
)


def test_forged_command_security_tenant_is_rejected_before_queueing(
    command_factory: Callable[..., TaskCommand],
) -> None:
    async def scenario() -> None:
        queue = InMemoryExecutionQueue()
        adapter = RuntimeExecutionAdapter(queue)
        forged = command_factory(security_tenant_id="tenant-b")

        with pytest.raises(ExecutionSubmissionError):
            await adapter.submit(forged)

        assert queue.pending_count == 0

    asyncio.run(scenario())


def test_tampered_command_digest_is_rejected_before_queueing(
    command_factory: Callable[..., TaskCommand],
) -> None:
    async def scenario() -> None:
        queue = InMemoryExecutionQueue()
        adapter = RuntimeExecutionAdapter(queue)
        tampered = replace(
            command_factory(),
            command_digest="sha256:" + "f" * 64,
        )

        with pytest.raises(ExecutionSubmissionError):
            await adapter.submit(tampered)

        assert queue.pending_count == 0

    asyncio.run(scenario())


def test_expired_security_context_returns_stable_runtime_error(
    request_factory: Callable[..., AgentRunRequest],
    fixed_clock: Callable[[], datetime],
) -> None:
    request = request_factory()
    expired = replace(
        request,
        security_context=replace(
            request.security_context,
            expires_at=fixed_clock(),
        ),
    )
    runtime = FakeAgentRuntime(clock=fixed_clock)

    result = asyncio.run(runtime.run(expired))

    assert result.status is RunStatus.FAILED_FINAL
    assert result.error is not None
    assert result.error.code is RuntimeErrorCode.REQUEST_INCONSISTENT


def test_sensitive_context_field_fails_before_provider_result(
    request_factory: Callable[..., AgentRunRequest],
    fixed_clock: Callable[[], datetime],
) -> None:
    sensitive_layer = ContextLayer(
        name=LayerName.RECENT_MESSAGES,
        trust=TrustLevel.UNTRUSTED_DATA,
        classification=DataClassification.INTERNAL,
        content={"api_key": "must-not-pass"},
        source_refs=("message://12345678",),
    )
    runtime = FakeAgentRuntime(clock=fixed_clock)

    result = asyncio.run(
        runtime.run(request_factory(optional_layers=(sensitive_layer,)))
    )

    assert result.status is RunStatus.FAILED_FINAL
    assert result.error is not None
    assert result.error.code is RuntimeErrorCode.REQUEST_INCONSISTENT
