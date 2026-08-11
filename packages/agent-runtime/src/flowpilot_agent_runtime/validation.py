from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from flowpilot_context import CLASSIFICATION_RANK, LayerName

from .models import AgentRunRequest, RuntimeUsage, ToolProposal

FORBIDDEN_SENSITIVE_FIELD_NAMES = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "bearer_token",
        "cookie",
        "client_secret",
        "credential",
        "credentials",
        "private_key",
        "password",
        "provider_session",
        "session_ref",
        "refresh_token",
        "secret",
        "session_token",
        "token",
    }
)


class RequestConsistencyError(ValueError):
    pass


class ToolScopeError(ValueError):
    pass


def _find_forbidden_key(value: object) -> str | None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower()
            if normalized in FORBIDDEN_SENSITIVE_FIELD_NAMES:
                return normalized
            found = _find_forbidden_key(child)
            if found is not None:
                return found
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            found = _find_forbidden_key(child)
            if found is not None:
                return found
    return None


def contains_forbidden_sensitive_field(value: object) -> bool:
    """Return whether a nested mapping/sequence carries a private field."""
    return _find_forbidden_key(value) is not None


def validate_request(
    request: AgentRunRequest,
    *,
    now: datetime,
) -> None:
    context = request.context
    security = request.security_context
    if request.task_id != context.task_id:
        raise RequestConsistencyError("request/context task mismatch")
    if len({request.tenant_id, context.tenant_id, security.tenant_id}) != 1:
        raise RequestConsistencyError("request/context/security tenant mismatch")
    if request.agent.id != context.agent_id:
        raise RequestConsistencyError("request/context agent mismatch")
    if context.purpose != security.purpose:
        raise RequestConsistencyError("context/security purpose mismatch")
    if request.provider_selection.provider not in context.policy.provider_allowlist:
        raise RequestConsistencyError("provider is outside the context allowlist")
    if security.expires_at <= now.astimezone(UTC):
        raise RequestConsistencyError("security context is expired")
    if (
        request.budget.maximum_input_tokens > context.policy.token_budget
        or context.manifest.input_tokens_estimated > request.budget.maximum_input_tokens
        or (
            context.manifest.input_tokens_actual is not None
            and context.manifest.input_tokens_actual
            > request.budget.maximum_input_tokens
        )
    ):
        raise RequestConsistencyError("request/context input budget mismatch")
    if (
        request.budget.maximum_input_tokens + request.budget.maximum_output_tokens
        > request.budget.maximum_total_tokens
    ):
        raise RequestConsistencyError("runtime total token budget is inconsistent")
    security_rank = CLASSIFICATION_RANK[security.data_classification_ceiling]
    context_rank = CLASSIFICATION_RANK[context.policy.data_classification_ceiling]
    if context_rank > security_rank:
        raise RequestConsistencyError(
            "context ceiling exceeds security classification ceiling"
        )
    if any(
        CLASSIFICATION_RANK[layer.classification] > min(context_rank, security_rank)
        for layer in context.layers
    ):
        raise RequestConsistencyError("context layer exceeds an effective ceiling")
    if contains_forbidden_sensitive_field(context.to_mapping()):
        raise RequestConsistencyError("context contains a forbidden sensitive field")
    # Accessing each base layer makes the exactly-one invariant explicit at the port.
    for layer_name in (
        LayerName.SYSTEM_POLICY,
        LayerName.SECURITY_VIEW,
        LayerName.TASK_STATE,
    ):
        context.layer(layer_name)


def validate_tool_proposals(
    request: AgentRunRequest,
    proposals: Sequence[ToolProposal],
) -> None:
    allowed = {(tool.name, tool.operation) for tool in request.agent.allowed_tools}
    for proposal in proposals:
        if (proposal.tool, proposal.operation) not in allowed:
            raise ToolScopeError("runtime proposed a tool outside the allowed scope")
        if contains_forbidden_sensitive_field(proposal.arguments):
            raise ToolScopeError("runtime proposal contains forbidden credential data")
        if contains_forbidden_sensitive_field(proposal.resource):
            raise ToolScopeError("runtime proposal contains forbidden credential data")


def usage_exceeds_budget(request: AgentRunRequest, usage: RuntimeUsage) -> bool:
    budget = request.budget
    return (
        usage.input_tokens > budget.maximum_input_tokens
        or usage.output_tokens > budget.maximum_output_tokens
        or usage.total_tokens > budget.maximum_total_tokens
        or usage.tool_calls > budget.maximum_tool_calls
        or usage.turns > budget.maximum_turns
        or usage.cost_microunits > budget.maximum_cost_microunits
        or usage.elapsed_ms > budget.timeout_ms
    )
