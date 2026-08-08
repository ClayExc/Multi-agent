from __future__ import annotations

import asyncio
import hashlib
import json
from collections import defaultdict, deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from flowpilot_model_gateway import PRIMARY_FAST_MODEL

from .models import (
    AgentRunRequest,
    AgentRunResult,
    RunStatus,
    RuntimeErrorCode,
    RuntimeFailure,
    RuntimeUsage,
    ToolProposal,
)
from .validation import (
    RequestConsistencyError,
    ToolScopeError,
    usage_exceeds_budget,
    validate_request,
    validate_tool_proposals,
)

OPENAI_AGENTS_PROVIDER = "openai-agents-sdk"
CLAUDE_AGENT_PROVIDER = "claude-agent-sdk"

_FORBIDDEN_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "bearer_token",
        "cookie",
        "credential",
        "credentials",
        "private_key",
        "provider_session",
    }
)


class SDKTransportErrorCode(StrEnum):
    UNAVAILABLE = "unavailable"
    RATE_LIMITED = "rate_limited"
    TIMED_OUT = "timed_out"
    INVALID_OUTPUT = "invalid_output"
    BUDGET_EXHAUSTED = "budget_exhausted"
    GUARDRAIL_BLOCKED = "guardrail_blocked"
    SESSION_INVALID = "session_invalid"
    CONFIGURATION = "configuration"


class SDKTransportError(RuntimeError):
    def __init__(self, code: SDKTransportErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


@dataclass(frozen=True, slots=True)
class SDKRunCall:
    request_id: str
    agent_id: str
    prompt_version: str
    logical_model: str
    instructions: str
    input_json: str
    maximum_turns: int
    maximum_output_tokens: int
    timeout_ms: int
    session_ref: str | None

    def __post_init__(self) -> None:
        if self.logical_model != PRIMARY_FAST_MODEL:
            raise ValueError("SDK calls must use flowpilot.primary.fast")
        if not self.request_id or not self.agent_id or not self.input_json:
            raise ValueError("SDK calls require request and agent identity")


@dataclass(frozen=True, slots=True)
class SDKRunCompletion:
    structured_output: Mapping[str, Any]
    usage: RuntimeUsage
    session_ref: str | None = None
    provider_run_ref: str | None = None
    tool_proposals: tuple[ToolProposal, ...] = ()


class SDKTransport(Protocol):
    async def run(self, call: SDKRunCall) -> SDKRunCompletion: ...


@dataclass(frozen=True, slots=True)
class SDKScenario:
    output: Mapping[str, Any] | None = None
    failure: SDKTransportError | None = None
    usage: RuntimeUsage | None = None
    session_ref: str | None = None
    provider_run_ref: str | None = None
    tool_proposals: tuple[ToolProposal, ...] = ()


class FakeSDKTransport:
    """Shared deterministic transport for OpenAI and Claude adapters."""

    def __init__(self, default: SDKScenario | None = None) -> None:
        self._default = default or SDKScenario()
        self._scripts: dict[str, deque[SDKScenario]] = defaultdict(deque)
        self.calls: list[SDKRunCall] = []

    def script(self, request_id: str, scenarios: Sequence[SDKScenario]) -> None:
        self._scripts[request_id] = deque(scenarios)

    async def run(self, call: SDKRunCall) -> SDKRunCompletion:
        self.calls.append(call)
        queued = self._scripts.get(call.request_id)
        scenario = queued.popleft() if queued else self._default
        if scenario.failure is not None:
            raise scenario.failure
        output = (
            dict(scenario.output)
            if scenario.output is not None
            else {"outcome": "completed"}
        )
        input_tokens = max(1, len(call.input_json.encode()) // 4)
        output_tokens = max(1, len(repr(output).encode()) // 4)
        usage = scenario.usage or RuntimeUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            turns=1,
            elapsed_ms=1,
        )
        return SDKRunCompletion(
            structured_output=output,
            usage=usage,
            session_ref=scenario.session_ref,
            provider_run_ref=scenario.provider_run_ref
            or _stable_ref("provider-run", call.request_id),
            tool_proposals=scenario.tool_proposals,
        )


class _SDKAdapter:
    def __init__(
        self,
        *,
        provider_name: str,
        transport: SDKTransport,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._provider_name = provider_name
        self._transport = transport
        self._clock = clock or (lambda: datetime.now(UTC))

    async def run(self, request: AgentRunRequest) -> AgentRunResult:
        now = self._clock().astimezone(UTC)
        try:
            validate_request(request, now=now)
            self._validate_selection(request)
            call = self._build_call(request)
        except (RequestConsistencyError, TypeError, ValueError):
            return self._failure(
                request,
                status=RunStatus.FAILED_FINAL,
                code=RuntimeErrorCode.REQUEST_INCONSISTENT,
                now=now,
            )
        try:
            completion = await self._invoke(call)
        except SDKTransportError as exc:
            if (
                exc.code is SDKTransportErrorCode.SESSION_INVALID
                and call.session_ref is not None
            ):
                try:
                    completion = await self._invoke(replace(call, session_ref=None))
                except SDKTransportError as retry_exc:
                    return self._transport_failure(request, retry_exc, now)
            else:
                return self._transport_failure(request, exc, now)
        if not _credential_free(completion):
            return self._failure(
                request,
                status=RunStatus.FAILED_FINAL,
                code=RuntimeErrorCode.INVALID_OUTPUT,
                now=now,
            )
        if not completion.structured_output:
            return self._failure(
                request,
                status=RunStatus.FAILED_FINAL,
                code=RuntimeErrorCode.INVALID_OUTPUT,
                now=now,
            )
        if usage_exceeds_budget(request, completion.usage):
            return self._failure(
                request,
                status=RunStatus.BUDGET_EXHAUSTED,
                code=RuntimeErrorCode.BUDGET_EXHAUSTED,
                now=now,
                usage=completion.usage,
            )
        try:
            validate_tool_proposals(request, completion.tool_proposals)
        except ToolScopeError:
            return self._failure(
                request,
                status=RunStatus.FAILED_FINAL,
                code=RuntimeErrorCode.TOOL_SCOPE_VIOLATION,
                now=now,
                usage=completion.usage,
            )
        return AgentRunResult(
            result_id=_stable_id(request.request_id, self._provider_name),
            request_id=request.request_id,
            status=RunStatus.COMPLETED,
            trace_id=request.trace_id,
            provider_name=self._provider_name,
            provider_model=PRIMARY_FAST_MODEL,
            structured_output=dict(completion.structured_output),
            public_reasoning_summary=(
                f"{self._provider_name} completed one bounded runtime node."
            ),
            tool_proposals=completion.tool_proposals,
            session_ref=completion.session_ref,
            provider_run_ref=completion.provider_run_ref,
            usage=completion.usage,
            completed_at=now,
        )

    async def _invoke(self, call: SDKRunCall) -> SDKRunCompletion:
        try:
            return await asyncio.wait_for(
                self._transport.run(call),
                timeout=call.timeout_ms / 1_000,
            )
        except TimeoutError:
            raise SDKTransportError(SDKTransportErrorCode.TIMED_OUT) from None

    def _validate_selection(self, request: AgentRunRequest) -> None:
        selection = request.provider_selection
        if (
            selection.provider != self._provider_name
            or selection.model != PRIMARY_FAST_MODEL
        ):
            raise RequestConsistencyError("runtime adapter/provider selection mismatch")

    @staticmethod
    def _build_call(request: AgentRunRequest) -> SDKRunCall:
        context = request.context.to_mapping()
        if not _credential_free(context):
            raise RequestConsistencyError(
                "runtime context contains forbidden credential data"
            )
        input_json = json.dumps(
            {
                "context": context,
                "output_schema": {
                    "id": request.agent.output_schema.id,
                    "hash": request.agent.output_schema.hash,
                },
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return SDKRunCall(
            request_id=request.request_id,
            agent_id=request.agent.id,
            prompt_version=request.agent.prompt_version,
            logical_model=request.provider_selection.model,
            instructions=(
                "Follow the supplied FlowPilot context and return one JSON object. "
                "Do not reveal hidden reasoning or execute business tools."
            ),
            input_json=input_json,
            maximum_turns=request.budget.maximum_turns,
            maximum_output_tokens=request.budget.maximum_output_tokens,
            timeout_ms=request.budget.timeout_ms,
            session_ref=request.session_ref,
        )

    def _transport_failure(
        self,
        request: AgentRunRequest,
        error: SDKTransportError,
        now: datetime,
    ) -> AgentRunResult:
        if error.code in {
            SDKTransportErrorCode.UNAVAILABLE,
            SDKTransportErrorCode.RATE_LIMITED,
            SDKTransportErrorCode.TIMED_OUT,
        }:
            return self._failure(
                request,
                status=RunStatus.FAILED_RETRYABLE,
                code=RuntimeErrorCode.PROVIDER_UNAVAILABLE,
                retryable=True,
                now=now,
            )
        if error.code is SDKTransportErrorCode.BUDGET_EXHAUSTED:
            return self._failure(
                request,
                status=RunStatus.BUDGET_EXHAUSTED,
                code=RuntimeErrorCode.BUDGET_EXHAUSTED,
                now=now,
            )
        if error.code is SDKTransportErrorCode.GUARDRAIL_BLOCKED:
            return self._failure(
                request,
                status=RunStatus.GUARDRAIL_BLOCKED,
                code=RuntimeErrorCode.GUARDRAIL_BLOCKED,
                now=now,
            )
        return self._failure(
            request,
            status=RunStatus.FAILED_FINAL,
            code=RuntimeErrorCode.INVALID_OUTPUT,
            now=now,
        )

    def _failure(
        self,
        request: AgentRunRequest,
        *,
        status: RunStatus,
        code: RuntimeErrorCode,
        now: datetime,
        retryable: bool = False,
        usage: RuntimeUsage | None = None,
    ) -> AgentRunResult:
        return AgentRunResult(
            result_id=_stable_id(request.request_id, self._provider_name),
            request_id=request.request_id,
            status=status,
            trace_id=request.trace_id,
            provider_name=self._provider_name,
            provider_model=PRIMARY_FAST_MODEL,
            structured_output=None,
            public_reasoning_summary=None,
            usage=usage or RuntimeUsage(),
            error=RuntimeFailure(code=code, retryable=retryable),
            completed_at=now,
        )


class OpenAIAgentsSDKAdapter(_SDKAdapter):
    def __init__(
        self,
        transport: SDKTransport,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(
            provider_name=OPENAI_AGENTS_PROVIDER,
            transport=transport,
            clock=clock,
        )


class ClaudeAgentSDKAdapter(_SDKAdapter):
    def __init__(
        self,
        transport: SDKTransport,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(
            provider_name=CLAUDE_AGENT_PROVIDER,
            transport=transport,
            clock=clock,
        )


def _credential_free(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() in _FORBIDDEN_KEYS:
                return False
            if not _credential_free(child):
                return False
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return all(_credential_free(child) for child in value)
    elif isinstance(value, SDKRunCompletion):
        return (
            _credential_free(value.structured_output)
            and _credential_free(value.tool_proposals)
            and _safe_ref(value.session_ref)
            and _safe_ref(value.provider_run_ref)
        )
    elif isinstance(value, ToolProposal):
        return _credential_free(value.arguments) and _credential_free(value.resource)
    return True


def _safe_ref(value: str | None) -> bool:
    if value is None:
        return True
    normalized = value.lower()
    return (
        1 <= len(value) <= 512
        and not any(key in normalized for key in _FORBIDDEN_KEYS)
        and not any(character.isspace() for character in value)
    )


def _stable_id(request_id: str, provider: str) -> str:
    suffix = hashlib.sha256(f"{request_id}:{provider}".encode()).hexdigest()[:16]
    return f"arr_{suffix}"


def _stable_ref(prefix: str, request_id: str) -> str:
    suffix = hashlib.sha256(request_id.encode()).hexdigest()[:20]
    return f"{prefix}://opaque/{suffix}"
