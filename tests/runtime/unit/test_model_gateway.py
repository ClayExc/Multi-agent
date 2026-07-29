from __future__ import annotations

import asyncio

import pytest
from flowpilot_domain import DataClassification
from flowpilot_model_gateway import (
    DeterministicModelGateway,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelRequest,
    ModelTask,
    ProviderRoute,
)


def _request(
    *,
    classification: DataClassification = DataClassification.INTERNAL,
    maximum_input_tokens: int = 100,
) -> ModelRequest:
    return ModelRequest(
        request_id="mgrq_12345678",
        task_id="task_12345678",
        tenant_id="tenant-a",
        task=ModelTask.CLASSIFY,
        payload={"text": "vpn"},
        data_classification=classification,
        provider_allowlist=("approved-provider",),
        maximum_input_tokens=maximum_input_tokens,
        maximum_output_tokens=100,
    )


def test_model_gateway_selects_one_approved_route() -> None:
    gateway = DeterministicModelGateway(
        routes=(
            ProviderRoute(
                provider="other-provider",
                model="other-model",
                maximum_classification=DataClassification.RESTRICTED,
            ),
            ProviderRoute(
                provider="approved-provider",
                model="fake-model",
                maximum_classification=DataClassification.CONFIDENTIAL,
            ),
        )
    )

    result = asyncio.run(gateway.complete(_request()))

    assert result.provider == "approved-provider"
    assert result.model == "fake-model"
    assert len(gateway.calls) == 1


def test_model_gateway_denies_data_above_route_ceiling() -> None:
    gateway = DeterministicModelGateway(
        routes=(
            ProviderRoute(
                provider="approved-provider",
                model="fake-model",
                maximum_classification=DataClassification.CONFIDENTIAL,
            ),
        )
    )

    with pytest.raises(ModelGatewayError) as captured:
        asyncio.run(
            gateway.complete(
                _request(classification=DataClassification.RESTRICTED)
            )
        )

    assert captured.value.code is ModelGatewayErrorCode.ROUTE_DENIED


def test_model_gateway_enforces_hard_budget() -> None:
    gateway = DeterministicModelGateway(
        routes=(
            ProviderRoute(
                provider="approved-provider",
                model="fake-model",
                maximum_classification=DataClassification.CONFIDENTIAL,
            ),
        )
    )

    with pytest.raises(ModelGatewayError) as captured:
        asyncio.run(gateway.complete(_request(maximum_input_tokens=1)))

    assert captured.value.code is ModelGatewayErrorCode.BUDGET_EXHAUSTED
