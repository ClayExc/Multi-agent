from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from flowpilot_agent_runtime import (
    CLAUDE_AGENT_PROVIDER,
    OPENAI_AGENTS_PROVIDER,
    AgentMode,
    AgentProfile,
    AgentRunRequest,
    AllowedTool,
    ClaudeAgentSDKAdapter,
    OpenAIAgentsSDKAdapter,
    OutputSchemaRef,
    ProviderSelection,
    RuntimeBudget,
    SDKRunCall,
    SDKTransport,
    ToolOperation,
)
from flowpilot_context import (
    ContextEnvelope,
    ContextLayer,
    ContextManifest,
    ContextPolicy,
    LayerName,
    TrustLevel,
)
from flowpilot_domain import (
    ActorType,
    AssuranceLevel,
    AuthenticationMethod,
    AuthenticationRef,
    DataClassification,
    SecurityContextRef,
)
from flowpilot_model_gateway import PRIMARY_FAST_MODEL, ProviderWireRequest

FIXED_NOW = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)
PROVIDERS = (OPENAI_AGENTS_PROVIDER, CLAUDE_AGENT_PROVIDER)
PRIVATE_SESSION = "provider-session://private/nested-session"
SYNTHETIC_SECRET = "fp-test-secret-do-not-use"


def wire_request(
    *,
    payload: dict[str, Any] | None = None,
    maximum_input_tokens: int = 512,
    maximum_output_tokens: int = 128,
) -> ProviderWireRequest:
    return ProviderWireRequest(
        request_id="provider_req_acceptance_12345678",
        task="summarize",
        payload=payload or {"topic": "synthetic incident"},
        data_classification=DataClassification.INTERNAL,
        maximum_input_tokens=maximum_input_tokens,
        maximum_output_tokens=maximum_output_tokens,
    )


def sdk_call(*, session_ref: str | None = None) -> SDKRunCall:
    return SDKRunCall(
        request_id="sdk_req_acceptance_12345678",
        agent_id="knowledge-agent",
        prompt_version="prompt-v1",
        logical_model=PRIMARY_FAST_MODEL,
        instructions="Return one JSON object.",
        input_json='{"context":"synthetic"}',
        maximum_turns=2,
        maximum_output_tokens=128,
        timeout_ms=30_000,
        session_ref=session_ref,
    )


def runtime_request(
    provider: str,
    *,
    session_ref: str | None = None,
) -> AgentRunRequest:
    security = SecurityContextRef(
        context_id="secctx_acceptance123",
        context_ref="security://acceptance/synthetic",
        context_hash="sha256:" + "1" * 64,
        tenant_id="tenant-acceptance",
        subject_id="user-acceptance",
        subject_type=ActorType.USER,
        purpose="it_support",
        authentication=AuthenticationRef(
            method=AuthenticationMethod.OIDC,
            assurance_level=AssuranceLevel.SUBSTANTIAL,
        ),
        data_classification_ceiling=DataClassification.INTERNAL,
        issued_at=FIXED_NOW,
        expires_at=FIXED_NOW + timedelta(hours=1),
    )
    layers = (
        ContextLayer(
            name=LayerName.SYSTEM_POLICY,
            trust=TrustLevel.CONTROLLED_INSTRUCTION,
            classification=DataClassification.INTERNAL,
            content={"policy": "offline-provider-review"},
            source_refs=("policy://acceptance/v1",),
        ),
        ContextLayer(
            name=LayerName.SECURITY_VIEW,
            trust=TrustLevel.AUTHENTICATED_DERIVED,
            classification=DataClassification.INTERNAL,
            content={"subject": "user-acceptance"},
            source_refs=("security://acceptance/synthetic",),
        ),
        ContextLayer(
            name=LayerName.TASK_STATE,
            trust=TrustLevel.BUSINESS_STATE,
            classification=DataClassification.INTERNAL,
            content={"status": "RUNNING"},
            source_refs=("task://acceptance-task/v1",),
        ),
    )
    context = ContextEnvelope(
        context_id="ctx_acceptance123",
        task_id="task-acceptance",
        tenant_id="tenant-acceptance",
        agent_id="knowledge-agent",
        purpose="it_support",
        policy=ContextPolicy(
            context_policy_version="context-policy-v1",
            data_classification_ceiling=DataClassification.INTERNAL,
            provider_allowlist=(provider,),
            token_budget=512,
        ),
        layers=layers,
        manifest=ContextManifest(
            included_refs=tuple(
                reference
                for layer in layers
                for reference in layer.source_refs
            ),
            excluded_fields=(),
            redactions=(),
            input_tokens_estimated=64,
        ),
    )
    return AgentRunRequest(
        request_id="arq_acceptance123",
        task_id="task-acceptance",
        tenant_id="tenant-acceptance",
        trace_id="0123456789abcdef0123456789abcdef",
        run_id="run_acceptance123",
        agent=AgentProfile(
            id="knowledge-agent",
            version="1.0.0",
            prompt_version="prompt-v1",
            mode=AgentMode.STRUCTURED,
            output_schema=OutputSchemaRef(
                id="schema://acceptance-answer/v1",
                hash="sha256:" + "2" * 64,
            ),
            allowed_tools=(
                AllowedTool(
                    name="knowledge.search.v1",
                    schema_hash="sha256:" + "3" * 64,
                    operation=ToolOperation.READ,
                ),
            ),
            maximum_handoffs=0,
        ),
        context=context,
        security_context=security,
        provider_selection=ProviderSelection(
            provider=provider,
            model=PRIMARY_FAST_MODEL,
            data_policy_id="data-policy-v1",
            routing_reason_code="M7_ACCEPTANCE",
        ),
        budget=RuntimeBudget(
            maximum_turns=2,
            maximum_tool_calls=1,
            maximum_input_tokens=512,
            maximum_output_tokens=128,
            maximum_total_tokens=640,
            maximum_cost_microunits=1_000,
            timeout_ms=30_000,
        ),
        session_ref=session_ref,
        issued_at=FIXED_NOW,
    )


def adapter_for(
    provider: str,
    transport: SDKTransport,
) -> OpenAIAgentsSDKAdapter | ClaudeAgentSDKAdapter:
    if provider == OPENAI_AGENTS_PROVIDER:
        return OpenAIAgentsSDKAdapter(transport, clock=lambda: FIXED_NOW)
    return ClaudeAgentSDKAdapter(transport, clock=lambda: FIXED_NOW)


def call_business_fingerprint(call: SDKRunCall) -> str:
    value = asdict(call)
    value.pop("session_ref")
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
