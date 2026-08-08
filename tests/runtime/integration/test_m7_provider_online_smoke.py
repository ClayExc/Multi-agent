from __future__ import annotations

import asyncio
import os

import pytest
from flowpilot_domain import DataClassification
from flowpilot_model_gateway import (
    ONLINE_SMOKE_ENV,
    PRIMARY_FAST_MODEL,
    LiteLLMProvider,
    OnlineLiteLLMTransport,
    ProviderWireRequest,
)

pytestmark = pytest.mark.skipif(
    os.environ.get(ONLINE_SMOKE_ENV) != "1",
    reason=f"online provider smoke requires explicit {ONLINE_SMOKE_ENV}=1",
)


def test_deepseek_v4_flash_online_smoke_is_explicit_only() -> None:
    provider = LiteLLMProvider(OnlineLiteLLMTransport.from_environment())
    request = ProviderWireRequest(
        request_id="online_smoke_12345678",
        task="summarize",
        payload={
            "purpose": "provider_connectivity_smoke",
            "text": "Return a JSON object with ok=true.",
        },
        data_classification=DataClassification.PUBLIC,
        maximum_input_tokens=512,
        maximum_output_tokens=64,
    )

    result = asyncio.run(provider.complete(request))

    assert result.model == PRIMARY_FAST_MODEL
    assert isinstance(result.output, dict)
    assert result.input_tokens > 0
    assert result.output_tokens > 0
