from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from flowpilot_domain import DataClassification

from .wire import (
    ProviderPort,
    ProviderToolProposal,
    ProviderWireError,
    ProviderWireErrorCode,
    ProviderWireRequest,
    assert_provider_input_safe,
    assert_provider_output_safe,
    assert_provider_tool_safe,
)


class ModelTask(StrEnum):
    CLASSIFY = "classify"
    SUMMARIZE = "summarize"
    RERANK = "rerank"
    JUDGE = "judge"


class ModelGatewayErrorCode(StrEnum):
    ROUTE_DENIED = "MODEL_ROUTE_DENIED"
    BUDGET_EXHAUSTED = "MODEL_BUDGET_EXHAUSTED"
    CONTENT_BLOCKED = "MODEL_CONTENT_BLOCKED"
    INVALID_OUTPUT = "MODEL_INVALID_OUTPUT"
    PROVIDER_UNAVAILABLE = "MODEL_PROVIDER_UNAVAILABLE"


class ModelGatewayError(RuntimeError):
    def __init__(
        self,
        code: ModelGatewayErrorCode,
        safe_message: str,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class ModelRequest:
    request_id: str
    task_id: str
    tenant_id: str
    task: ModelTask
    payload: Mapping[str, Any]
    data_classification: DataClassification
    provider_allowlist: tuple[str, ...]
    maximum_input_tokens: int
    maximum_output_tokens: int

    def __post_init__(self) -> None:
        if (
            not self.provider_allowlist
            or len(self.provider_allowlist) != len(set(self.provider_allowlist))
        ):
            raise ValueError("provider allowlist must be non-empty and unique")
        if self.maximum_input_tokens < 1 or self.maximum_output_tokens < 1:
            raise ValueError("model token budgets must be positive")


@dataclass(frozen=True, slots=True)
class ModelResult:
    result_id: str
    request_id: str
    provider: str
    model: str
    output: Mapping[str, Any]
    input_tokens: int
    output_tokens: int
    tool_proposals: tuple[ProviderToolProposal, ...] = ()


class ModelGatewayPort(Protocol):
    async def complete(self, request: ModelRequest) -> ModelResult: ...


@dataclass(frozen=True, slots=True)
class ProviderRoute:
    provider: str
    model: str
    maximum_classification: DataClassification


_CLASSIFICATION_RANK = {
    DataClassification.PUBLIC: 0,
    DataClassification.INTERNAL: 1,
    DataClassification.CONFIDENTIAL: 2,
    DataClassification.RESTRICTED: 3,
}


class DeterministicModelGateway:
    def __init__(
        self,
        *,
        routes: tuple[ProviderRoute, ...],
        outputs: Mapping[str, Mapping[str, Any]] | None = None,
        providers: Mapping[str, ProviderPort] | None = None,
    ) -> None:
        """Route by classification ceiling; delegate completion to ports.

        ``providers`` is the ProviderPort registry: provider name -> port.
        A route whose provider has a registered port is completed through
        that port (wire protocol); otherwise the gateway falls back to its
        deterministic built-in completion so existing callers keep working.
        """
        self._routes = routes
        self._outputs = dict(outputs or {})
        self._providers = dict(providers or {})
        self.calls: list[ModelRequest] = []

    async def complete(self, request: ModelRequest) -> ModelResult:
        self._assert_request_safe(request)
        self.calls.append(request)
        route = next(
            (
                candidate
                for candidate in self._routes
                if candidate.provider in request.provider_allowlist
                and _CLASSIFICATION_RANK[request.data_classification]
                <= _CLASSIFICATION_RANK[candidate.maximum_classification]
            ),
            None,
        )
        if route is None:
            raise ModelGatewayError(
                ModelGatewayErrorCode.ROUTE_DENIED,
                "no approved provider route is available",
            )
        port = self._providers.get(route.provider)
        if port is not None:
            return await self._complete_via_port(port, request)
        output = self._outputs.get(request.request_id, {"outcome": request.task.value})
        self._assert_output_safe(output, ())
        encoded_input = repr(sorted(request.payload.items())).encode()
        input_tokens = max(1, len(encoded_input) // 4)
        output_tokens = max(1, len(repr(output).encode()) // 4)
        if (
            input_tokens > request.maximum_input_tokens
            or output_tokens > request.maximum_output_tokens
        ):
            raise ModelGatewayError(
                ModelGatewayErrorCode.BUDGET_EXHAUSTED,
                "model request exceeded a hard token budget",
            )
        suffix = hashlib.sha256(request.request_id.encode()).hexdigest()[:16]
        return ModelResult(
            result_id=f"mgr_{suffix}",
            request_id=request.request_id,
            provider=route.provider,
            model=route.model,
            output=dict(output),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    async def _complete_via_port(
        self,
        port: ProviderPort,
        request: ModelRequest,
    ) -> ModelResult:
        wire_request = ProviderWireRequest(
            request_id=request.request_id,
            task=request.task.value,
            payload=request.payload,
            data_classification=request.data_classification,
            maximum_input_tokens=request.maximum_input_tokens,
            maximum_output_tokens=request.maximum_output_tokens,
        )
        try:
            response = await port.complete(wire_request)
        except ProviderWireError as exc:
            raise self._map_wire_error(exc) from exc
        if (
            response.input_tokens > request.maximum_input_tokens
            or response.output_tokens > request.maximum_output_tokens
        ):
            raise ModelGatewayError(
                ModelGatewayErrorCode.BUDGET_EXHAUSTED,
                "provider port violated a hard token budget",
            )
        self._assert_output_safe(response.output, response.tool_proposals)
        suffix = hashlib.sha256(request.request_id.encode()).hexdigest()[:16]
        return ModelResult(
            result_id=f"mgr_{suffix}",
            request_id=request.request_id,
            provider=response.provider,
            model=response.model,
            output=dict(response.output),
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            tool_proposals=response.tool_proposals,
        )

    @staticmethod
    def _map_wire_error(exc: ProviderWireError) -> ModelGatewayError:
        if exc.code is ProviderWireErrorCode.PROVIDER_UNAVAILABLE:
            # The wire contract has exactly one retryable code; normalize any
            # misbehaving port back to the stable retryable gateway error.
            return ModelGatewayError(
                ModelGatewayErrorCode.PROVIDER_UNAVAILABLE,
                exc.safe_message,
                retryable=True,
            )
        if exc.code is ProviderWireErrorCode.BUDGET_EXHAUSTED:
            return ModelGatewayError(
                ModelGatewayErrorCode.BUDGET_EXHAUSTED,
                exc.safe_message,
            )
        if exc.code is ProviderWireErrorCode.CONTENT_BLOCKED:
            return ModelGatewayError(
                ModelGatewayErrorCode.CONTENT_BLOCKED,
                "model content failed centralized safety validation",
            )
        return ModelGatewayError(
            ModelGatewayErrorCode.INVALID_OUTPUT,
            exc.safe_message,
        )

    @staticmethod
    def _assert_request_safe(request: ModelRequest) -> None:
        try:
            assert_provider_input_safe(request.payload)
        except ProviderWireError:
            raise ModelGatewayError(
                ModelGatewayErrorCode.CONTENT_BLOCKED,
                "model input failed centralized safety validation",
            ) from None

    @staticmethod
    def _assert_output_safe(
        output: Mapping[str, Any],
        proposals: tuple[ProviderToolProposal, ...],
    ) -> None:
        try:
            assert_provider_output_safe(output)
            for proposal in proposals:
                assert_provider_tool_safe(proposal.arguments)
                assert_provider_tool_safe(proposal.resource)
        except ProviderWireError:
            raise ModelGatewayError(
                ModelGatewayErrorCode.CONTENT_BLOCKED,
                "model output failed centralized safety validation",
            ) from None
