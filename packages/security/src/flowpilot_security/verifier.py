from __future__ import annotations

from datetime import datetime

from flowpilot_domain import PlannedAction, SecurityContextRef
from flowpilot_tool_contracts import AgentPrincipal

from .errors import SecurityError, SecurityErrorCode
from .models import AuthenticatedWorkload, TrustedSecurityContext

_CLASSIFICATION_RANK = {
    "public": 0,
    "internal": 1,
    "confidential": 2,
    "restricted": 3,
}


class SecurityVerifier:
    def verify_context(
        self,
        *,
        presented: SecurityContextRef,
        trusted: TrustedSecurityContext,
        now: datetime,
    ) -> SecurityContextRef:
        if not trusted.active:
            raise SecurityError(
                SecurityErrorCode.CONTEXT_NOT_ACTIVE,
                "security context is no longer active",
            )
        if trusted.context.to_mapping() != presented.to_mapping():
            raise SecurityError(
                SecurityErrorCode.CONTEXT_UNTRUSTED,
                "security context does not match its trusted reference",
            )
        if now < presented.issued_at or now >= presented.expires_at:
            raise SecurityError(
                SecurityErrorCode.CONTEXT_EXPIRED,
                "security context is not valid at execution time",
            )
        return trusted.context

    def verify_action_context(
        self,
        *,
        context: SecurityContextRef,
        action: PlannedAction,
    ) -> None:
        if context.tenant_id != action.tenant_id:
            raise SecurityError(
                SecurityErrorCode.TENANT_MISMATCH,
                "trusted tenant does not match the planned action",
            )
        if context.subject_id != action.requester_id:
            raise SecurityError(
                SecurityErrorCode.CONTEXT_UNTRUSTED,
                "trusted subject does not match the action requester",
            )
        if context.purpose != action.purpose:
            raise SecurityError(
                SecurityErrorCode.PURPOSE_DENIED,
                "trusted purpose does not match the planned action",
            )
        if _CLASSIFICATION_RANK[
            action.data_classification.value
        ] > _CLASSIFICATION_RANK[
            context.data_classification_ceiling.value
        ]:
            raise SecurityError(
                SecurityErrorCode.CONTEXT_UNTRUSTED,
                "action classification exceeds the trusted context ceiling",
            )

    def verify_workload(
        self,
        *,
        declared: AgentPrincipal,
        action: PlannedAction,
        workload: AuthenticatedWorkload,
        expected_audience: str,
        now: datetime,
    ) -> None:
        if not workload.attested:
            raise SecurityError(
                SecurityErrorCode.WORKLOAD_UNTRUSTED,
                "workload identity is not server-attested",
            )
        if now < workload.issued_at or now >= workload.expires_at:
            raise SecurityError(
                SecurityErrorCode.WORKLOAD_EXPIRED,
                "workload identity is not valid at execution time",
            )
        if (
            (declared.id, declared.version, declared.principal_ref)
            != (
                workload.agent_id,
                workload.agent_version,
                workload.principal_ref,
            )
            or (action.agent.id, action.agent.version)
            != (workload.agent_id, workload.agent_version)
        ):
            raise SecurityError(
                SecurityErrorCode.AGENT_MISMATCH,
                "authenticated workload does not match the declared Agent",
            )
        if workload.audience != expected_audience:
            raise SecurityError(
                SecurityErrorCode.AUDIENCE_MISMATCH,
                "workload audience does not match the Gateway tool audience",
            )
        if action.tenant_id not in workload.tenant_ids:
            raise SecurityError(
                SecurityErrorCode.TENANT_MISMATCH,
                "workload is not authorized for the action tenant",
            )
        if action.purpose not in workload.purposes:
            raise SecurityError(
                SecurityErrorCode.PURPOSE_DENIED,
                "workload is not authorized for the action purpose",
            )
        if action.tool.name not in workload.allowed_tools:
            raise SecurityError(
                SecurityErrorCode.TOOL_SCOPE_DENIED,
                "workload is not authorized for the tool",
            )
