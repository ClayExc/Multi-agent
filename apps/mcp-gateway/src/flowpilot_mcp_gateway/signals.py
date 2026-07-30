from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from flowpilot_domain import Approval, SecurityContextRef
from flowpilot_policy import PolicyDecision
from flowpilot_security import assert_safe_projection
from flowpilot_tool_contracts import AgentPrincipal, ToolRequest

from .models import GatewayInvocation, LifecycleEvent


def stable_signal_id(prefix: str, *parts: str) -> str:
    preimage = "\x1f".join(parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(preimage).hexdigest()[:32]}"


@dataclass(frozen=True, slots=True)
class AuditDraft:
    event_id: str
    event_type: str
    occurred_at: datetime
    tenant_id: str
    trace_id: str
    thread_id: str
    run_id: str | None
    task_id: str
    producer_principal_ref: str
    correlation_id: str
    causation_id: str
    actor_type: str
    actor_id: str
    agent: AgentPrincipal
    action: str
    resource: Mapping[str, Any]
    decision: str
    policy_decision_id: str | None
    policy_version: str | None
    reason_codes: tuple[str, ...]
    approval_id: str | None
    action_digest: str
    tool_execution_id: str
    result: str
    data_classification: str
    security_event_id: str | None = None

    def to_mapping(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at.astimezone(UTC)
            .isoformat()
            .replace("+00:00", "Z"),
            "tenant_id": self.tenant_id,
            "trace_id": self.trace_id,
            "thread_id": self.thread_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "producer": "mcp_gateway",
            "producer_principal_ref": self.producer_principal_ref,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "actor": {"type": self.actor_type, "id": self.actor_id},
            "agent": self.agent.to_mapping(),
            "action": self.action,
            "resource": dict(self.resource),
            "decision": self.decision,
            "policy_decision_id": self.policy_decision_id,
            "policy_version": self.policy_version,
            "reason_codes": list(self.reason_codes),
            "approval_id": self.approval_id,
            "action_digest": self.action_digest,
            "tool_execution_id": self.tool_execution_id,
            "security_event_id": self.security_event_id,
            "arguments_redacted": {"field_names": []},
            "result": self.result,
            "data_classification": self.data_classification,
        }
        assert_safe_projection(value)
        return value


@dataclass(frozen=True, slots=True)
class SecurityDraft:
    event_id: str
    event_type: str
    occurred_at: datetime
    tenant_id: str
    trace_id: str
    thread_id: str
    task_id: str
    run_id: str | None
    producer_principal_ref: str
    correlation_id: str
    causation_id: str
    context: SecurityContextRef | None
    agent: AgentPrincipal
    reason_codes: tuple[str, ...]
    category: str
    policy_decision_id: str | None
    audit_event_id: str

    def to_mapping(self) -> dict[str, Any]:
        value = {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at.astimezone(UTC)
            .isoformat()
            .replace("+00:00", "Z"),
            "tenant_id": self.tenant_id,
            "trace_id": self.trace_id,
            "thread_id": self.thread_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "producer": "mcp_gateway",
            "producer_principal_ref": self.producer_principal_ref,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "subject_context_ref": (
                self.context.context_ref if self.context is not None else None
            ),
            "subject_context_hash": (
                self.context.context_hash if self.context is not None else None
            ),
            "agent_principal": self.agent.to_mapping(),
            "control": {
                "component": "mcp_gateway",
                "rule_id": self.reason_codes[0],
                "rule_version": "m0.v1",
            },
            "reason_codes": list(self.reason_codes),
            "severity": "high",
            "category": self.category,
            "control_outcome": "blocked",
            "impact": "attempted",
            "disposition": "contained",
            "resource_refs": [],
            "evidence_refs": [],
            "policy_decision_id": self.policy_decision_id,
            "audit_event_id": self.audit_event_id,
            "data_classification": "internal",
        }
        assert_safe_projection(value)
        return value


class SignalSinkPort(Protocol):
    async def ensure_unsampled_available(self) -> None: ...

    async def emit_trace(self, event: LifecycleEvent) -> None: ...

    async def append_audit(self, audit: AuditDraft) -> None: ...

    async def append_blocked_pair(
        self, audit: AuditDraft, security: SecurityDraft
    ) -> None: ...


def build_audit_draft(
    *,
    invocation: GatewayInvocation,
    execution_id: str,
    now: datetime,
    reason_codes: tuple[str, ...],
    result: str,
    event_type: str,
    policy: PolicyDecision | None,
    approval: Approval | None,
    trusted_context: SecurityContextRef | None,
    security_event_id: str | None = None,
) -> AuditDraft:
    request = invocation.request
    tenant_id = (
        trusted_context.tenant_id
        if trusted_context is not None
        else "unresolved"
    )
    actor_type = (
        trusted_context.subject_type.value
        if trusted_context is not None
        else "service"
    )
    actor_id = (
        trusted_context.subject_id
        if trusted_context is not None
        else "unresolved"
    )
    authenticated_agent = AgentPrincipal(
        id=invocation.workload.agent_id,
        version=invocation.workload.agent_version,
        principal_ref=invocation.workload.principal_ref,
    )
    event_id = stable_signal_id(
        "evt",
        execution_id,
        result,
        reason_codes[0],
        now.astimezone(UTC).isoformat(),
    )
    return AuditDraft(
        event_id=event_id,
        event_type=event_type,
        occurred_at=now,
        tenant_id=tenant_id,
        trace_id=request.trace_id,
        thread_id=invocation.thread_id,
        run_id=invocation.run_id,
        task_id=request.planned_action.task_id,
        producer_principal_ref=invocation.workload.principal_ref,
        correlation_id=invocation.correlation_id,
        causation_id=request.request_id,
        actor_type=actor_type,
        actor_id=actor_id,
        agent=authenticated_agent,
        action=request.planned_action.tool.name,
        resource={
            "type": request.planned_action.resource.type,
            "id": request.planned_action.resource.id,
        },
        decision=(
            policy.decision.value if policy is not None else "not_applicable"
        ),
        policy_decision_id=(
            policy.decision_id if policy is not None else None
        ),
        policy_version=(
            policy.policy_version if policy is not None else None
        ),
        reason_codes=reason_codes,
        approval_id=approval.approval_id if approval is not None else None,
        action_digest=request.action_digest,
        tool_execution_id=execution_id,
        result=result,
        data_classification=request.planned_action.data_classification.value,
        security_event_id=security_event_id,
    )


def build_blocked_pair(
    *,
    invocation: GatewayInvocation,
    execution_id: str,
    now: datetime,
    reason_code: str,
    event_type: str,
    category: str,
    policy: PolicyDecision | None,
    trusted_context: SecurityContextRef | None,
) -> tuple[AuditDraft, SecurityDraft]:
    timestamp = now.astimezone(UTC).isoformat()
    audit_event_id = stable_signal_id(
        "evt", execution_id, "blocked", reason_code, timestamp
    )
    security_event_id = stable_signal_id(
        "sevt", execution_id, "blocked", reason_code, timestamp
    )
    request: ToolRequest = invocation.request
    audit = build_audit_draft(
        invocation=invocation,
        execution_id=execution_id,
        now=now,
        reason_codes=(reason_code,),
        result="blocked",
        event_type="audit.authorization.denied.v1",
        policy=policy,
        approval=None,
        trusted_context=trusted_context,
        security_event_id=security_event_id,
    )
    if audit.event_id != audit_event_id:
        raise AssertionError("stable blocked audit identity drifted")
    security = SecurityDraft(
        event_id=security_event_id,
        event_type=event_type,
        occurred_at=now,
        tenant_id=(
            trusted_context.tenant_id
            if trusted_context is not None
            else "unresolved"
        ),
        trace_id=request.trace_id,
        thread_id=invocation.thread_id,
        task_id=request.planned_action.task_id,
        run_id=invocation.run_id,
        producer_principal_ref=invocation.workload.principal_ref,
        correlation_id=invocation.correlation_id,
        causation_id=request.request_id,
        context=trusted_context,
        agent=AgentPrincipal(
            id=invocation.workload.agent_id,
            version=invocation.workload.agent_version,
            principal_ref=invocation.workload.principal_ref,
        ),
        reason_codes=(reason_code,),
        category=category,
        policy_decision_id=(
            policy.decision_id if policy is not None else None
        ),
        audit_event_id=audit_event_id,
    )
    return audit, security
