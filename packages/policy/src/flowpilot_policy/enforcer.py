from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from flowpilot_domain import PlannedAction, SecurityContextRef
from flowpilot_tool_contracts import AgentPrincipal

from .errors import PolicyError, PolicyErrorCode
from .models import (
    AuditLevel,
    CredentialTtl,
    LimitRecords,
    MaskFields,
    PolicyDecision,
    PolicyDecisionKind,
    RequireMfa,
    RestrictProvider,
)

_ASSURANCE_RANK = {"low": 0, "substantial": 1, "high": 2}


@dataclass(frozen=True, slots=True)
class EnforcedPolicy:
    decision: PolicyDecision
    audit_level: str
    credential_ttl_seconds: int

    def apply_output(
        self, data: Mapping[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        result = dict(data)
        redaction_summary: dict[str, Any] = {}
        for obligation in self.decision.obligations:
            if isinstance(obligation, MaskFields):
                masked: list[str] = []
                for field in obligation.fields:
                    if field in result:
                        result[field] = "[REDACTED]"
                        masked.append(field)
                if masked:
                    redaction_summary["masked_fields"] = masked
            elif isinstance(obligation, LimitRecords):
                records = result.get("records")
                if isinstance(records, Sequence) and not isinstance(
                    records, (str, bytes, bytearray)
                ):
                    result["records"] = list(records[: obligation.maximum])
                    redaction_summary["record_limit"] = obligation.maximum
        return result, redaction_summary


class PolicyEnforcer:
    def enforce(
        self,
        *,
        decision: PolicyDecision,
        context: SecurityContextRef,
        agent: AgentPrincipal,
        action: PlannedAction,
        now: datetime,
        upstream_provider: str,
    ) -> EnforcedPolicy:
        if decision.decision is PolicyDecisionKind.DENY:
            raise PolicyError(
                PolicyErrorCode.DENIED,
                "policy denied the tool action",
                reason_codes=decision.reason_codes,
            )
        if now < decision.evaluated_at or now >= decision.expires_at:
            raise PolicyError(
                PolicyErrorCode.EXPIRED,
                "policy decision is not active at execution time",
            )
        if (
            decision.tenant_id != context.tenant_id
            or decision.tenant_id != action.tenant_id
            or decision.task_id != action.task_id
            or decision.subject_ref != context.context_ref
            or decision.subject_context_hash != context.context_hash
            or decision.agent.id != agent.id
            or decision.agent.version != agent.version
            or decision.agent.principal_ref != agent.principal_ref
            or decision.agent.id != action.agent.id
            or decision.agent.version != action.agent.version
            or decision.action.tool != action.tool.name
            or decision.action.operation != action.tool.operation.value
            or decision.action.action_digest != action.digest()
            or decision.policy_version != action.policy_version
            or decision.expires_at != action.expires_at
        ):
            raise PolicyError(
                PolicyErrorCode.BINDING_MISMATCH,
                "policy decision bindings do not match the tool request",
            )
        audit_level = "standard"
        credential_ttl = 300
        for obligation in decision.obligations:
            if isinstance(obligation, AuditLevel):
                audit_level = obligation.level
            elif isinstance(obligation, CredentialTtl):
                credential_ttl = obligation.seconds
            elif isinstance(obligation, RequireMfa):
                actual = context.authentication.assurance_level.value
                if _ASSURANCE_RANK[actual] < _ASSURANCE_RANK[
                    obligation.minimum_assurance
                ]:
                    raise PolicyError(
                        PolicyErrorCode.MFA_REQUIRED,
                        "security context assurance is below the policy minimum",
                    )
            elif isinstance(obligation, RestrictProvider):
                if upstream_provider not in obligation.providers:
                    raise PolicyError(
                        PolicyErrorCode.PROVIDER_RESTRICTED,
                        "tool provider is outside the policy allowlist",
                    )
            elif not isinstance(obligation, (MaskFields, LimitRecords)):
                raise PolicyError(
                    PolicyErrorCode.OBLIGATION_UNSUPPORTED,
                    "PEP cannot execute a policy obligation",
                )
        return EnforcedPolicy(
            decision=decision,
            audit_level=audit_level,
            credential_ttl_seconds=credential_ttl,
        )
