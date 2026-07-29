from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from flowpilot_domain import DataClassification


class ModelTask(StrEnum):
    CLASSIFY = "classify"
    SUMMARIZE = "summarize"
    RERANK = "rerank"
    JUDGE = "judge"


class ModelGatewayErrorCode(StrEnum):
    ROUTE_DENIED = "MODEL_ROUTE_DENIED"
    BUDGET_EXHAUSTED = "MODEL_BUDGET_EXHAUSTED"
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
    ) -> None:
        self._routes = routes
        self._outputs = dict(outputs or {})
        self.calls: list[ModelRequest] = []

    async def complete(self, request: ModelRequest) -> ModelResult:
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
        output = self._outputs.get(request.request_id, {"outcome": request.task.value})
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
