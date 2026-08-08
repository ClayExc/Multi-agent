from __future__ import annotations

import inspect
import json
import os
from collections.abc import AsyncIterator, Callable, Mapping
from importlib import import_module
from time import monotonic
from typing import Any

from flowpilot_model_gateway import ONLINE_SMOKE_ENV

from .models import RuntimeUsage
from .sdk import (
    CLAUDE_AGENT_PROVIDER,
    OPENAI_AGENTS_PROVIDER,
    SDKRunCall,
    SDKRunCompletion,
    SDKTransportError,
    SDKTransportErrorCode,
)

OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
ANTHROPIC_API_KEY_ENV = "ANTHROPIC_API_KEY"
OPENAI_MODEL_ENV = "FLOWPILOT_OPENAI_AGENTS_MODEL"
CLAUDE_MODEL_ENV = "FLOWPILOT_CLAUDE_AGENT_MODEL"


class OpenAIAgentsSDKTransport:
    """Online OpenAI Agents SDK bridge, disabled unless explicitly enabled."""

    def __init__(
        self,
        *,
        enabled: bool,
        provider_model_id: str | None,
        module_loader: Callable[[], Any] | None = None,
    ) -> None:
        self._enabled = enabled
        self._provider_model_id = provider_model_id
        self._module_loader = module_loader or (lambda: import_module("agents"))

    @classmethod
    def from_environment(cls) -> OpenAIAgentsSDKTransport:
        return cls(
            enabled=os.environ.get(ONLINE_SMOKE_ENV) == "1",
            provider_model_id=os.environ.get(OPENAI_MODEL_ENV),
        )

    async def run(self, call: SDKRunCall) -> SDKRunCompletion:
        if (
            not self._enabled
            or not self._provider_model_id
            or not os.environ.get(OPENAI_API_KEY_ENV)
        ):
            raise SDKTransportError(SDKTransportErrorCode.CONFIGURATION)
        started = monotonic()
        raw_session = _unpack_session(call.session_ref, OPENAI_AGENTS_PROVIDER)
        try:
            module = self._module_loader()
            agent = module.Agent(
                name=call.agent_id,
                instructions=call.instructions,
                model=self._provider_model_id,
                tools=[],
                handoffs=[],
            )
            run_config = module.RunConfig(
                tracing_disabled=True,
                trace_include_sensitive_data=False,
                workflow_name="flowpilot-runtime-node",
            )
            kwargs: dict[str, Any] = {
                "max_turns": call.maximum_turns,
                "run_config": run_config,
            }
            if raw_session is not None:
                kwargs["previous_response_id"] = raw_session
            result = await _await(module.Runner.run(agent, call.input_json, **kwargs))
            usage = _field(_field(result, "context_wrapper"), "usage")
            last_response_id = _optional_text(result, "last_response_id")
            return SDKRunCompletion(
                structured_output=_json_object(_field(result, "final_output")),
                usage=RuntimeUsage(
                    input_tokens=_integer(usage, "input_tokens"),
                    output_tokens=_integer(usage, "output_tokens"),
                    total_tokens=_integer(usage, "total_tokens"),
                    turns=max(1, _integer(usage, "requests")),
                    elapsed_ms=_elapsed_ms(started),
                ),
                session_ref=_pack_session(
                    OPENAI_AGENTS_PROVIDER,
                    last_response_id,
                ),
                provider_run_ref=(
                    f"provider-run://{OPENAI_AGENTS_PROVIDER}/{last_response_id}"
                    if last_response_id is not None
                    else None
                ),
            )
        except SDKTransportError:
            raise
        except Exception as exc:
            raise _classify_sdk_error(
                exc,
                had_session=raw_session is not None,
            ) from None


class ClaudeAgentSDKTransport:
    """Online Claude Agent SDK bridge with tools disabled and bounded turns."""

    def __init__(
        self,
        *,
        enabled: bool,
        provider_model_id: str | None,
        module_loader: Callable[[], Any] | None = None,
    ) -> None:
        self._enabled = enabled
        self._provider_model_id = provider_model_id
        self._module_loader = module_loader or (
            lambda: import_module("claude_agent_sdk")
        )

    @classmethod
    def from_environment(cls) -> ClaudeAgentSDKTransport:
        return cls(
            enabled=os.environ.get(ONLINE_SMOKE_ENV) == "1",
            provider_model_id=os.environ.get(CLAUDE_MODEL_ENV),
        )

    async def run(self, call: SDKRunCall) -> SDKRunCompletion:
        if (
            not self._enabled
            or not self._provider_model_id
            or not os.environ.get(ANTHROPIC_API_KEY_ENV)
        ):
            raise SDKTransportError(SDKTransportErrorCode.CONFIGURATION)
        started = monotonic()
        raw_session = _unpack_session(call.session_ref, CLAUDE_AGENT_PROVIDER)
        try:
            module = self._module_loader()
            options: dict[str, Any] = {
                "model": self._provider_model_id,
                "max_turns": call.maximum_turns,
                # ``allowed_tools`` is only an auto-approval list in the
                # Claude Agent SDK.  ``tools=[]`` is the authoritative base
                # tool removal and serializes to ``--tools \"\"``.
                "tools": [],
                "allowed_tools": [],
                "disallowed_tools": [],
                "mcp_servers": {},
                "strict_mcp_config": True,
                "plugins": [],
                "agents": None,
                "hooks": None,
                "skills": [],
                "setting_sources": [],
                "can_use_tool": None,
                "system_prompt": call.instructions,
            }
            if raw_session is not None:
                options["resume"] = raw_session
            query_result = module.query(
                prompt=call.input_json,
                options=module.ClaudeAgentOptions(**options),
            )
            result_message: Any | None = None
            turns = 0
            async for message in _async_iter(query_result):
                name = type(message).__name__
                if name == "AssistantMessage":
                    turns += 1
                if name == "ResultMessage":
                    result_message = message
            if result_message is None:
                raise SDKTransportError(SDKTransportErrorCode.INVALID_OUTPUT)
            session_id = _optional_text(result_message, "session_id")
            usage = _field(result_message, "usage")
            total_cost_usd = _optional_number(result_message, "total_cost_usd")
            input_tokens = _integer(usage, "input_tokens")
            output_tokens = _integer(usage, "output_tokens")
            return SDKRunCompletion(
                structured_output=_json_object(_field(result_message, "result")),
                usage=RuntimeUsage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens,
                    turns=max(1, turns),
                    cost_microunits=int((total_cost_usd or 0.0) * 1_000_000),
                    elapsed_ms=_elapsed_ms(started),
                ),
                session_ref=_pack_session(CLAUDE_AGENT_PROVIDER, session_id),
                provider_run_ref=(
                    f"provider-run://{CLAUDE_AGENT_PROVIDER}/{session_id}"
                    if session_id is not None
                    else None
                ),
            )
        except SDKTransportError:
            raise
        except Exception as exc:
            raise _classify_sdk_error(
                exc,
                had_session=raw_session is not None,
            ) from None


async def _await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    raise SDKTransportError(SDKTransportErrorCode.INVALID_OUTPUT)


async def _async_iter(value: Any) -> AsyncIterator[Any]:
    if not hasattr(value, "__aiter__"):
        raise SDKTransportError(SDKTransportErrorCode.INVALID_OUTPUT)
    async for item in value:
        yield item


def _field(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        if key not in value:
            raise SDKTransportError(SDKTransportErrorCode.INVALID_OUTPUT)
        return value[key]
    result = getattr(value, key, None)
    if result is None:
        raise SDKTransportError(SDKTransportErrorCode.INVALID_OUTPUT)
    return result


def _integer(value: Any, key: str) -> int:
    result = _field(value, key)
    if isinstance(result, bool) or not isinstance(result, int) or result < 0:
        raise SDKTransportError(SDKTransportErrorCode.INVALID_OUTPUT)
    return int(result)


def _optional_text(value: Any, key: str) -> str | None:
    result = value.get(key) if isinstance(value, Mapping) else getattr(value, key, None)
    if result is None:
        return None
    if not isinstance(result, str) or not result:
        raise SDKTransportError(SDKTransportErrorCode.INVALID_OUTPUT)
    return result


def _optional_number(value: Any, key: str) -> float | None:
    result = value.get(key) if isinstance(value, Mapping) else getattr(value, key, None)
    if result is None:
        return None
    if isinstance(result, bool) or not isinstance(result, (int, float)) or result < 0:
        raise SDKTransportError(SDKTransportErrorCode.INVALID_OUTPUT)
    return float(result)


def _json_object(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str):
        raise SDKTransportError(SDKTransportErrorCode.INVALID_OUTPUT)
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        raise SDKTransportError(SDKTransportErrorCode.INVALID_OUTPUT) from None
    if not isinstance(decoded, dict):
        raise SDKTransportError(SDKTransportErrorCode.INVALID_OUTPUT)
    return decoded


def _pack_session(provider: str, value: str | None) -> str | None:
    if value is None:
        return None
    if not value or any(character.isspace() for character in value):
        raise SDKTransportError(SDKTransportErrorCode.INVALID_OUTPUT)
    return f"provider-session://{provider}/{value}"


def _unpack_session(value: str | None, provider: str) -> str | None:
    if value is None:
        return None
    prefix = f"provider-session://{provider}/"
    if not value.startswith(prefix) or len(value) == len(prefix):
        raise SDKTransportError(SDKTransportErrorCode.SESSION_INVALID)
    return value[len(prefix) :]


def _classify_sdk_error(
    error: Exception,
    *,
    had_session: bool,
) -> SDKTransportError:
    name = type(error).__name__.lower()
    if had_session and any(
        part in name for part in ("badrequest", "notfound", "session")
    ):
        code = SDKTransportErrorCode.SESSION_INVALID
    elif "rate" in name and "limit" in name:
        code = SDKTransportErrorCode.RATE_LIMITED
    elif "timeout" in name:
        code = SDKTransportErrorCode.TIMED_OUT
    elif any(part in name for part in ("connection", "network", "apierror")):
        code = SDKTransportErrorCode.UNAVAILABLE
    elif "maxturn" in name:
        code = SDKTransportErrorCode.BUDGET_EXHAUSTED
    elif "guardrail" in name or "permission" in name:
        code = SDKTransportErrorCode.GUARDRAIL_BLOCKED
    elif "auth" in name or "config" in name:
        code = SDKTransportErrorCode.CONFIGURATION
    else:
        code = SDKTransportErrorCode.INVALID_OUTPUT
    return SDKTransportError(code)


def _elapsed_ms(started: float) -> int:
    return max(1, int((monotonic() - started) * 1_000))
