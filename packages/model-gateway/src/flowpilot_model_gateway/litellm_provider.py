from __future__ import annotations

import asyncio
import inspect
import json
import os
from collections import defaultdict, deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from importlib import import_module
from typing import Any, Protocol

from .wire import (
    ProviderWireError,
    ProviderWireErrorCode,
    ProviderWireRequest,
    ProviderWireResponse,
    assert_wire_credential_free,
    meter_input_tokens,
    meter_output_tokens,
    stable_wire_id,
)

PRIMARY_FAST_MODEL = "flowpilot.primary.fast"
DEEPSEEK_V4_FLASH_MODEL_ID = "deepseek-v4-flash"
LITELLM_DEEPSEEK_ROUTE = f"deepseek/{DEEPSEEK_V4_FLASH_MODEL_ID}"
LITELLM_PROVIDER = "litellm"
ONLINE_SMOKE_ENV = "FLOWPILOT_ENABLE_ONLINE_PROVIDER_SMOKE"
DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_KEY"


class LiteLLMTransportErrorCode(StrEnum):
    UNAVAILABLE = "unavailable"
    RATE_LIMITED = "rate_limited"
    TIMED_OUT = "timed_out"
    INVALID_RESPONSE = "invalid_response"
    CONFIGURATION = "configuration"


class LiteLLMTransportError(RuntimeError):
    def __init__(self, code: LiteLLMTransportErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


@dataclass(frozen=True, slots=True)
class LiteLLMMessage:
    role: str
    content: str

    def __post_init__(self) -> None:
        if self.role not in {"system", "user"} or not self.content:
            raise ValueError("LiteLLM messages require a supported role and content")


@dataclass(frozen=True, slots=True)
class LiteLLMCall:
    request_id: str
    task: str
    payload: Mapping[str, Any]
    transport_model: str
    messages: tuple[LiteLLMMessage, ...]
    maximum_output_tokens: int
    timeout_ms: int


@dataclass(frozen=True, slots=True)
class LiteLLMCompletion:
    response_id: str
    provider_model_id: str
    output: Mapping[str, Any]
    input_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        if not self.response_id or not self.provider_model_id:
            raise ValueError("LiteLLM completion identity is required")
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise ValueError("LiteLLM completion usage cannot be negative")


class LiteLLMTransport(Protocol):
    async def complete(self, call: LiteLLMCall) -> LiteLLMCompletion: ...


@dataclass(frozen=True, slots=True)
class LiteLLMScenario:
    output: Mapping[str, Any] | None = None
    failure: LiteLLMTransportError | None = None


class FakeLiteLLMTransport:
    """Deterministic transport used by every default/offline gate."""

    def __init__(self, default: LiteLLMScenario | None = None) -> None:
        self._default = default or LiteLLMScenario()
        self._scripts: dict[str, deque[LiteLLMScenario]] = defaultdict(deque)
        self.calls: list[LiteLLMCall] = []

    def script(
        self,
        request_id: str,
        scenarios: Sequence[LiteLLMScenario],
    ) -> None:
        self._scripts[request_id] = deque(scenarios)

    async def complete(self, call: LiteLLMCall) -> LiteLLMCompletion:
        self.calls.append(call)
        queued = self._scripts.get(call.request_id)
        scenario = queued.popleft() if queued else self._default
        if scenario.failure is not None:
            raise scenario.failure
        output = (
            dict(scenario.output)
            if scenario.output is not None
            else {"outcome": call.task}
        )
        return LiteLLMCompletion(
            response_id=stable_wire_id("llm", f"{call.request_id}:{repr(output)}"),
            provider_model_id=DEEPSEEK_V4_FLASH_MODEL_ID,
            output=output,
            input_tokens=meter_input_tokens(call.payload),
            output_tokens=meter_output_tokens(output),
        )


@dataclass(frozen=True, slots=True)
class LiteLLMProviderConfig:
    logical_model: str = PRIMARY_FAST_MODEL
    provider_model_id: str = DEEPSEEK_V4_FLASH_MODEL_ID
    transport_model: str = LITELLM_DEEPSEEK_ROUTE
    timeout_ms: int = 30_000

    def __post_init__(self) -> None:
        if self.logical_model != PRIMARY_FAST_MODEL:
            raise ValueError("product logic must use flowpilot.primary.fast")
        if self.provider_model_id != DEEPSEEK_V4_FLASH_MODEL_ID:
            raise ValueError("the accepted DeepSeek model id is required")
        if not self.transport_model or not 1 <= self.timeout_ms <= 3_600_000:
            raise ValueError("LiteLLM provider configuration is invalid")


class LiteLLMProvider:
    """ProviderPort adapter with a private logical-to-provider model mapping."""

    name = LITELLM_PROVIDER

    def __init__(
        self,
        transport: LiteLLMTransport,
        *,
        config: LiteLLMProviderConfig | None = None,
    ) -> None:
        self._transport = transport
        self._config = config or LiteLLMProviderConfig()

    async def complete(self, request: ProviderWireRequest) -> ProviderWireResponse:
        try:
            assert_wire_credential_free(request.payload)
            encoded = json.dumps(
                {"task": request.task, "payload": request.payload},
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError):
            raise ProviderWireError(
                ProviderWireErrorCode.INVALID_OUTPUT,
                "provider input violates the credential-free wire boundary",
            ) from None
        call = LiteLLMCall(
            request_id=request.request_id,
            task=request.task,
            payload=request.payload,
            transport_model=self._config.transport_model,
            messages=(
                LiteLLMMessage(
                    role="system",
                    content=(
                        "Return one JSON object matching the requested FlowPilot task. "
                        "Do not include hidden reasoning, credentials, or tool "
                        "execution."
                    ),
                ),
                LiteLLMMessage(role="user", content=encoded),
            ),
            maximum_output_tokens=request.maximum_output_tokens,
            timeout_ms=min(self._config.timeout_ms, 3_600_000),
        )
        try:
            completion = await asyncio.wait_for(
                self._transport.complete(call),
                timeout=call.timeout_ms / 1_000,
            )
        except TimeoutError:
            raise _wire_unavailable("provider request timed out") from None
        except LiteLLMTransportError as exc:
            raise _map_transport_error(exc) from None
        try:
            assert_wire_credential_free(completion.output)
        except ValueError:
            raise ProviderWireError(
                ProviderWireErrorCode.INVALID_OUTPUT,
                "provider response violated the credential-free wire boundary",
            ) from None
        if not completion.output:
            raise ProviderWireError(
                ProviderWireErrorCode.INVALID_OUTPUT,
                "provider response did not contain structured output",
            )
        if completion.provider_model_id != self._config.provider_model_id:
            raise ProviderWireError(
                ProviderWireErrorCode.INVALID_OUTPUT,
                "provider response used an unexpected model identity",
            )
        if (
            completion.input_tokens > request.maximum_input_tokens
            or completion.output_tokens > request.maximum_output_tokens
        ):
            raise ProviderWireError(
                ProviderWireErrorCode.BUDGET_EXHAUSTED,
                "provider response exceeded a hard token budget",
            )
        return ProviderWireResponse(
            response_id=completion.response_id,
            request_id=request.request_id,
            provider=self.name,
            model=self._config.logical_model,
            output=dict(completion.output),
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
        )


class OnlineLiteLLMTransport:
    """Explicitly enabled online bridge; credentials remain SDK-owned env data."""

    def __init__(
        self,
        *,
        enabled: bool,
        module_loader: Callable[[], Any] | None = None,
    ) -> None:
        self._enabled = enabled
        self._module_loader = module_loader or (lambda: import_module("litellm"))

    @classmethod
    def from_environment(cls) -> OnlineLiteLLMTransport:
        return cls(enabled=os.environ.get(ONLINE_SMOKE_ENV) == "1")

    async def complete(self, call: LiteLLMCall) -> LiteLLMCompletion:
        if not self._enabled or not os.environ.get(DEEPSEEK_API_KEY_ENV):
            raise LiteLLMTransportError(LiteLLMTransportErrorCode.CONFIGURATION)
        try:
            module = self._module_loader()
            operation = module.acompletion(
                model=call.transport_model,
                messages=[
                    {"role": item.role, "content": item.content}
                    for item in call.messages
                ],
                max_tokens=call.maximum_output_tokens,
                timeout=call.timeout_ms / 1_000,
                response_format={"type": "json_object"},
            )
            response = await _await(operation)
            content = _nested(response, "choices", 0, "message", "content")
            output = _json_object(content)
            usage = _field(response, "usage")
            response_model = str(_field(response, "model"))
            if response_model.rsplit("/", 1)[-1] != DEEPSEEK_V4_FLASH_MODEL_ID:
                raise LiteLLMTransportError(LiteLLMTransportErrorCode.INVALID_RESPONSE)
            return LiteLLMCompletion(
                response_id=str(_field(response, "id")),
                provider_model_id=DEEPSEEK_V4_FLASH_MODEL_ID,
                output=output,
                input_tokens=int(_field(usage, "prompt_tokens")),
                output_tokens=int(_field(usage, "completion_tokens")),
            )
        except LiteLLMTransportError:
            raise
        except Exception as exc:
            raise _classify_online_error(exc) from None


async def _await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    raise LiteLLMTransportError(LiteLLMTransportErrorCode.INVALID_RESPONSE)


def _field(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        if key not in value:
            raise LiteLLMTransportError(LiteLLMTransportErrorCode.INVALID_RESPONSE)
        return value[key]
    result = getattr(value, key, None)
    if result is None:
        raise LiteLLMTransportError(LiteLLMTransportErrorCode.INVALID_RESPONSE)
    return result


def _nested(value: Any, *path: str | int) -> Any:
    current = value
    for item in path:
        if isinstance(item, int):
            if not isinstance(current, Sequence) or len(current) <= item:
                raise LiteLLMTransportError(LiteLLMTransportErrorCode.INVALID_RESPONSE)
            current = current[item]
        else:
            current = _field(current, item)
    return current


def _json_object(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str):
        raise LiteLLMTransportError(LiteLLMTransportErrorCode.INVALID_RESPONSE)
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        raise LiteLLMTransportError(
            LiteLLMTransportErrorCode.INVALID_RESPONSE
        ) from None
    if not isinstance(decoded, dict):
        raise LiteLLMTransportError(LiteLLMTransportErrorCode.INVALID_RESPONSE)
    return decoded


def _classify_online_error(error: Exception) -> LiteLLMTransportError:
    name = type(error).__name__.lower()
    if "rate" in name and "limit" in name:
        code = LiteLLMTransportErrorCode.RATE_LIMITED
    elif "timeout" in name:
        code = LiteLLMTransportErrorCode.TIMED_OUT
    elif any(part in name for part in ("connection", "network", "apierror")):
        code = LiteLLMTransportErrorCode.UNAVAILABLE
    elif any(part in name for part in ("auth", "permission", "config")):
        code = LiteLLMTransportErrorCode.CONFIGURATION
    else:
        code = LiteLLMTransportErrorCode.INVALID_RESPONSE
    return LiteLLMTransportError(code)


def _map_transport_error(error: LiteLLMTransportError) -> ProviderWireError:
    if error.code in {
        LiteLLMTransportErrorCode.UNAVAILABLE,
        LiteLLMTransportErrorCode.RATE_LIMITED,
        LiteLLMTransportErrorCode.TIMED_OUT,
    }:
        return _wire_unavailable("provider transport is temporarily unavailable")
    return ProviderWireError(
        ProviderWireErrorCode.INVALID_OUTPUT,
        "provider configuration or response is invalid",
    )


def _wire_unavailable(message: str) -> ProviderWireError:
    return ProviderWireError(
        ProviderWireErrorCode.PROVIDER_UNAVAILABLE,
        message,
        retryable=True,
    )
