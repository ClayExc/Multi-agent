from __future__ import annotations

from dataclasses import dataclass

from flowpilot_domain import SecurityContextRef, ToolOperation
from flowpilot_security import AuthenticatedWorkload
from flowpilot_tool_contracts import ToolContract, ToolRequest

from .errors import GatewayControlError, GatewayReason
from .ports import ToolAdapter


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    contract: ToolContract
    operation: ToolOperation
    audience: str
    upstream_provider: str
    allowed_agents: frozenset[str]
    allowed_tenants: frozenset[str]
    allowed_purposes: frozenset[str]
    credential_scopes: frozenset[str]
    adapter: ToolAdapter
    secret_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.audience or not self.upstream_provider:
            raise ValueError("tool audience and provider cannot be empty")
        if not all(
            (
                self.allowed_agents,
                self.allowed_tenants,
                self.allowed_purposes,
                self.credential_scopes,
            )
        ):
            raise ValueError("tool allowlists and credential scopes cannot be empty")
        if self.secret_ref is not None and not self.secret_ref.startswith(
            "secret://development/"
        ):
            raise ValueError("tool secret reference must use the development provider")


class ToolRegistry:
    def __init__(self, definitions: tuple[ToolDefinition, ...]) -> None:
        by_name: dict[str, ToolDefinition] = {}
        for definition in definitions:
            name = definition.contract.name
            if name in by_name:
                raise ValueError("duplicate tool registry entry")
            by_name[name] = definition
        self._by_name = by_name

    def authorize(
        self,
        *,
        request: ToolRequest,
        context: SecurityContextRef,
        workload: AuthenticatedWorkload,
    ) -> ToolDefinition:
        action = request.planned_action
        definition = self._by_name.get(action.tool.name)
        if definition is None:
            raise GatewayControlError(
                GatewayReason.TOOL_NOT_REGISTERED.value,
                "tool is not registered",
            )
        if (
            definition.contract.schema_hash != action.tool.schema_hash
            or definition.operation is not action.tool.operation
        ):
            raise GatewayControlError(
                GatewayReason.TOOL_SCHEMA_MISMATCH.value,
                "tool schema or operation does not match the registry",
            )
        if (
            workload.agent_id not in definition.allowed_agents
            or context.tenant_id not in definition.allowed_tenants
            or context.purpose not in definition.allowed_purposes
        ):
            raise GatewayControlError(
                GatewayReason.TOOL_NOT_ALLOWED.value,
                "tool allowlist denied this subject or purpose",
            )
        try:
            definition.contract.validate_input(action.arguments)
        except ValueError as exc:
            raise GatewayControlError(
                GatewayReason.TOOL_INPUT_INVALID.value,
                "tool arguments do not match the pinned input schema",
            ) from exc
        return definition
