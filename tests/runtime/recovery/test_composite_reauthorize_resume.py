"""M5-2 recovery re-authentication / re-authorization — AC-E2E-002.

Two layers:

1. Composite-scenario recovery (graph layer): a crash restart re-runs the
   full approval validation (binding / duties / manager / approval-active)
   before any write; a tampered security binding is rejected on recovery
   (SECURITY_BINDING_MISMATCH) so the old approval is never executed.
2. Capability token rebuild (gateway layer, FP-MCP-006 / FP-SEC-007): the
   short-lived credential is re-issued after a Worker restart with the
   correct audience / scope / TTL / action binding (the token is rebuilt,
   never reused or silently skipped).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from flowpilot_domain import (
    ActionAgent,
    ActionResource,
    ActionTool,
    ActorType,
    Approval,
    ApprovalStatus,
    AssuranceLevel,
    AuthenticationMethod,
    AuthenticationRef,
    DataClassification,
    PlannedAction,
    SecurityContextRef,
    ToolOperation,
    canonical_sha256,
)
from flowpilot_graph import GraphError, GraphErrorCode, GraphStatus
from flowpilot_mcp_gateway import (
    AuditDraft,
    GatewayAdapterDisposition,
    GatewayAdapterError,
    GatewayDependencies,
    GatewayInvocation,
    McpGateway,
    ReadbackResult,
    ReconciliationDisposition,
    ReconciliationResult,
    SecurityDraft,
    ToolDefinition,
    ToolInvocationResult,
    ToolRegistry,
)
from flowpilot_persistence import MemoryDatabase, MemoryDataUnitOfWorkFactory
from flowpilot_policy import (
    ApprovalVerifier,
    PolicyDecision,
    PolicyDecisionKind,
    PolicyEnforcer,
    ResolvedPolicyDecision,
)
from flowpilot_security import (
    AuthenticatedWorkload,
    CapabilityHandle,
    SecurityVerifier,
    TrustedSecurityContext,
)
from flowpilot_tool_contracts import AgentPrincipal, ToolContract, ToolRequest

from onboarding_harness import (
    MANAGER,
    TENANT_A,
    build_approval_from_card,
    build_decide_command,
    build_harness,
    execute,
    rebuild_harness,
    run_until_approval,
    tamper_decide_command,
)

NOW = datetime(2026, 7, 30, 8, 0, tzinfo=UTC)
TENANT = "tenant-alpha"
SUBJECT = "user-alice"
APPROVER = "user-reviewer"
AGENT_ID = "flowpilot-agent"
AGENT_VERSION = "m0.1"
AGENT_PRINCIPAL = "workload://flowpilot/agent/m0"
PURPOSE = "it-service-fulfillment"
POLICY_VERSION = "policy-m0.1"
AUDIENCE = "mcp://flowpilot-gateway"

WRITE_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["ticket_id", "status"],
    "properties": {
        "ticket_id": {"type": "string", "minLength": 1, "maxLength": 64},
        "status": {"type": "string", "enum": ["in_progress", "resolved"]},
    },
}
WRITE_CONTRACT = ToolContract.create(
    name="ticket.update.v1",
    input_schema=WRITE_INPUT_SCHEMA,
    output_schema=WRITE_INPUT_SCHEMA,
)


class _Clock:
    def __init__(self, start: datetime = NOW) -> None:
        self._now = start

    def __call__(self) -> datetime:
        return self._now


class _ContextSource:
    def __init__(self, context: SecurityContextRef) -> None:
        self._context = context

    async def resolve(self, context_ref: str) -> TrustedSecurityContext:
        if context_ref != self._context.context_ref:
            raise RuntimeError("unknown security context")
        return TrustedSecurityContext(
            context=self._context,
            active=True,
            roles=frozenset({"employee"}),
        )


class _PolicySource:
    def __init__(self, record: ResolvedPolicyDecision) -> None:
        self._record = record

    async def resolve(self, decision_id: str) -> ResolvedPolicyDecision:
        return self._record


class _ApprovalSource:
    def __init__(self, approval: Approval | None) -> None:
        self._approval = approval

    async def resolve(self, approval_id: str) -> Approval:
        if self._approval is None:
            raise RuntimeError("no approval supplied")
        return self._approval


class _ApproverDirectory:
    async def has_any_role(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        roles: frozenset[str],
        now: datetime,
    ) -> bool:
        del now
        return (
            tenant_id == TENANT
            and subject_id == APPROVER
            and "change_approver" in roles
        )


class _CredentialBroker:
    def __init__(self) -> None:
        self.issue_count = 0
        self.last_ttl_seconds: int | None = None
        self.handles: list[CapabilityHandle] = []

    async def issue(
        self,
        *,
        tenant_id: str,
        audience: str,
        scopes: frozenset[str],
        subject_id: str,
        subject_acl: frozenset[str],
        workload_principal_ref: str,
        purpose: str,
        data_classification_ceiling: str,
        action_digest: str,
        ttl_seconds: int,
        now: datetime,
    ) -> CapabilityHandle:
        self.issue_count += 1
        self.last_ttl_seconds = ttl_seconds
        handle = CapabilityHandle(
            handle_ref=f"capability://recovery/{self.issue_count}/{uuid.uuid4().hex[:8]}",
            audience=audience,
            scopes=scopes,
            tenant_id=tenant_id,
            subject_id=subject_id,
            subject_acl=subject_acl,
            workload_principal_ref=workload_principal_ref,
            purpose=purpose,
            data_classification_ceiling=data_classification_ceiling,
            action_digest=action_digest,
            issued_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        self.handles.append(handle)
        return handle


class _SignalSink:
    async def ensure_unsampled_available(self) -> None:
        return None

    async def emit_trace(self, event: Any) -> None:
        return None

    async def append_audit(self, audit: AuditDraft) -> None:
        return None

    async def append_blocked_pair(
        self, audit: AuditDraft, security: SecurityDraft
    ) -> None:
        return None


class _WriteAdapter:
    def __init__(self) -> None:
        self.logical_write_count = 0
        self.values: dict[str, dict[str, Any]] = {}

    async def invoke(
        self,
        *,
        arguments: Mapping[str, Any],
        capability: CapabilityHandle,
        idempotency_key: str,
    ) -> ToolInvocationResult:
        del capability
        if idempotency_key not in self.values:
            self.logical_write_count += 1
            self.values[idempotency_key] = dict(arguments)
        return ToolInvocationResult(data=dict(self.values[idempotency_key]))

    async def readback(
        self,
        *,
        arguments: Mapping[str, Any],
        invocation: ToolInvocationResult,
        capability: CapabilityHandle,
        idempotency_key: str,
    ) -> ReadbackResult:
        del invocation, capability
        stored = self.values.get(idempotency_key)
        return ReadbackResult(
            data=dict(stored or {}),
            evidence_ref="evidence://ticket/readback",
            observed_ref="ticket://observed/TCK-100",
            matched=stored == dict(arguments),
        )

    async def reconcile(
        self,
        *,
        arguments: Mapping[str, Any],
        capability: CapabilityHandle,
        idempotency_key: str,
    ) -> ReconciliationResult:
        del capability
        stored = self.values.get(idempotency_key)
        if stored is None:
            return ReconciliationResult(
                disposition=ReconciliationDisposition.CONFIRMED_NOT_EXECUTED,
                data=None,
                evidence_ref=None,
                observed_ref=None,
                method="reconcile",
            )
        return ReconciliationResult(
            disposition=ReconciliationDisposition.VERIFIED,
            data=dict(stored),
            evidence_ref="evidence://ticket/reconcile",
            observed_ref="ticket://observed/TCK-100",
            method="reconcile",
        )


@dataclass(frozen=True, slots=True)
class _GatewayHarness:
    gateway: McpGateway
    credentials: _CredentialBroker
    action: PlannedAction
    policy: PolicyDecision
    clock: _Clock
    adapter: _WriteAdapter


def _build_gateway_harness(*, run_id: str) -> _GatewayHarness:
    clock = _Clock()
    expires_at = NOW + timedelta(minutes=15)
    context = SecurityContextRef(
        context_id="secctx_alpha0001",
        context_ref="security-context://tenant-alpha/user-alice",
        context_hash=canonical_sha256(
            {"tenant_id": TENANT, "subject_id": SUBJECT, "purpose": PURPOSE}
        ),
        tenant_id=TENANT,
        subject_id=SUBJECT,
        subject_type=ActorType.USER,
        purpose=PURPOSE,
        authentication=AuthenticationRef(
            method=AuthenticationMethod.OIDC,
            assurance_level=AssuranceLevel.HIGH,
            session_id_hash=canonical_sha256({"session": "fixture"}),
        ),
        data_classification_ceiling=DataClassification.CONFIDENTIAL,
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(hours=1),
    )
    adapter = _WriteAdapter()
    action = PlannedAction(
        action_id="act_alpha0001",
        tenant_id=TENANT,
        task_id="task_alpha0001",
        requester_id=SUBJECT,
        agent=ActionAgent(id=AGENT_ID, version=AGENT_VERSION),
        tool=ActionTool(
            name=WRITE_CONTRACT.name,
            schema_hash=WRITE_CONTRACT.schema_hash,
            operation=ToolOperation.WRITE,
        ),
        arguments={"ticket_id": "TCK-100", "status": "resolved"},
        resource=ActionResource(type="ticket", id="TCK-100"),
        purpose=PURPOSE,
        data_classification=DataClassification.INTERNAL,
        policy_version=POLICY_VERSION,
        expires_at=expires_at,
    )
    action_digest = action.digest()
    decision = PolicyDecision.from_mapping(
        {
            "decision_id": "pd_alpha0001",
            "tenant_id": TENANT,
            "task_id": action.task_id,
            "subject_ref": context.context_ref,
            "subject_context_hash": context.context_hash,
            "agent": {
                "id": AGENT_ID,
                "version": AGENT_VERSION,
                "principal_ref": AGENT_PRINCIPAL,
            },
            "action": {
                "tool": action.tool.name,
                "operation": "write",
                "action_digest": action_digest,
            },
            "decision": "allow",
            "reason_codes": ["POLICY_FIXTURE_ALLOW"],
            "obligations": [],
            "approval_requirements": None,
            "policy_version": POLICY_VERSION,
            "input_canonicalization": "rfc8785",
            "input_hash": canonical_sha256({"fixture": "input"}),
            "evaluated_at": (NOW - timedelta(minutes=1))
            .isoformat()
            .replace("+00:00", "Z"),
            "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        }
    )
    policy_record = ResolvedPolicyDecision.create(
        decision=decision,
        input_preimage={"fixture": "input"},
    )
    request = ToolRequest.from_mapping(
        {
            "request_id": "treq_alpha0001",
            "trace_id": "trace_alpha0000001",
            "security_context": context.to_mapping(),
            "agent_principal": AgentPrincipal(
                id=AGENT_ID,
                version=AGENT_VERSION,
                principal_ref=AGENT_PRINCIPAL,
            ).to_mapping(),
            "planned_action": action.to_mapping(),
            "action_digest": action_digest,
            "policy_decision_id": decision.decision_id,
            "idempotency_key": canonical_sha256(
                {"tenant": TENANT, "tool": action.tool.name, "logical": 1}
            ),
            "approval_id": None,
            "requested_at": NOW.isoformat().replace("+00:00", "Z"),
        }
    )
    workload = AuthenticatedWorkload(
        agent_id=AGENT_ID,
        agent_version=AGENT_VERSION,
        principal_ref=AGENT_PRINCIPAL,
        audience=AUDIENCE,
        tenant_ids=frozenset({TENANT}),
        purposes=frozenset({PURPOSE}),
        allowed_tools=frozenset({action.tool.name}),
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(hours=1),
    )
    invocation = GatewayInvocation(
        request=request,
        workload=workload,
        thread_id="thread_alpha0001",
        run_id=run_id,
        correlation_id="corr-alpha-0001",
    )
    credentials = _CredentialBroker()
    registry = ToolRegistry(
        (
            ToolDefinition(
                contract=WRITE_CONTRACT,
                operation=ToolOperation.WRITE,
                audience=AUDIENCE,
                upstream_provider="fixture-mcp",
                allowed_agents=frozenset({AGENT_ID}),
                allowed_tenants=frozenset({TENANT}),
                allowed_purposes=frozenset({PURPOSE}),
                credential_scopes=frozenset({"tool.invoke"}),
                adapter=adapter,
            ),
        )
    )
    gateway = McpGateway(
        GatewayDependencies(
            registry=registry,
            security_contexts=_ContextSource(context),
            security=SecurityVerifier(),
            policies=_PolicySource(policy_record),
            policy=PolicyEnforcer(),
            approvals=_ApprovalSource(None),
            approval=ApprovalVerifier(),
            approvers=_ApproverDirectory(),
            credentials=credentials,
            data_uow=MemoryDataUnitOfWorkFactory(MemoryDatabase()),
            signals=_SignalSink(),
            clock=clock,
        )
    )
    return _GatewayHarness(
        gateway=gateway,
        credentials=credentials,
        action=action,
        policy=decision,
        clock=clock,
        adapter=adapter,
    )


# --------------------------------------------------------------------------
# 1. Composite recovery re-authorization (graph layer).
# --------------------------------------------------------------------------


def test_recovery_revalidates_approval_before_any_write() -> None:
    """A crash between sub-actions re-runs the approval validation."""

    async def scenario() -> None:
        from onboarding_harness import OnboardingCrash, OnboardingProbeOptions

        harness_a = await build_harness(
            task_id="task_onbreauth001",
            probe_options=OnboardingProbeOptions(
                crash_after_tool="device.allocate.v1"
            ),
        )
        _outcome, card = await run_until_approval(harness_a)
        approval_id = str(card["approval_id"])
        approval = build_approval_from_card(
            card, create=harness_a.create, config=harness_a.config
        )
        harness_a.approvals.approvals[(TENANT_A, approval_id)] = approval
        await harness_a.approvals.approve(approval_id, MANAGER)
        resolves_before = harness_a.approvals.resolve_count.get(approval_id, 0)

        decide = build_decide_command(
            harness_a.create.task_id,
            approval_id=approval_id,
            action_digest=str(card["action_digest"]),
            decision="approve",
            actor_id=MANAGER,
        )
        with pytest.raises(OnboardingCrash):
            await execute(harness_a, decide, run_id="run_onb_reauth_crash")

        # Restart: the approval record is re-resolved and re-validated
        # (resolve count grows) before the permission write executes.
        harness_b = rebuild_harness(harness_a)
        resumed = await execute(harness_b, decide, run_id="run_onb_reauth_recover")
        assert resumed.state.status is GraphStatus.COMPLETED
        assert (
            harness_a.approvals.resolve_count[approval_id] > resolves_before
        )
        assert harness_a.probe.logical_counts == {
            "device.allocate.v1": 1,
            "permission.grant.v1": 1,
            "ticket.create.v1": 1,
        }

    asyncio.run(scenario())


def test_recovery_rejects_tampered_security_binding() -> None:
    """A replayed approval command with a tampered purpose is rejected."""

    async def scenario() -> None:
        from onboarding_harness import OnboardingCrash, OnboardingProbeOptions

        harness_a = await build_harness(
            task_id="task_onbreauth002",
            probe_options=OnboardingProbeOptions(
                crash_after_tool="device.allocate.v1"
            ),
        )
        _outcome, card = await run_until_approval(harness_a)
        approval_id = str(card["approval_id"])
        approval = build_approval_from_card(
            card, create=harness_a.create, config=harness_a.config
        )
        harness_a.approvals.approvals[(TENANT_A, approval_id)] = approval
        await harness_a.approvals.approve(approval_id, MANAGER)

        decide = build_decide_command(
            harness_a.create.task_id,
            approval_id=approval_id,
            action_digest=str(card["action_digest"]),
            decision="approve",
            actor_id=MANAGER,
        )
        with pytest.raises(OnboardingCrash):
            await execute(harness_a, decide, run_id="run_onb_reauth_tamper_crash")

        harness_b = rebuild_harness(harness_a)
        # Re-signed with a DIFFERENT purpose: the durable Checkpoint binding
        # must reject it before any approval validation or write.
        tampered = tamper_decide_command(
            decide,
            security_context={
                **decide.security_context.to_mapping(),
                "purpose": "evil_operation",
            },
        )
        with pytest.raises(GraphError) as captured:
            await execute(harness_b, tampered, run_id="run_onb_reauth_tamper")

        assert captured.value.code is GraphErrorCode.SECURITY_BINDING_MISMATCH
        # No write ever executed after the tamper.
        assert harness_a.probe.logical_counts.get("device.allocate.v1") == 1
        assert harness_a.probe.logical_counts.get("permission.grant.v1", 0) == 0

    asyncio.run(scenario())


# --------------------------------------------------------------------------
# 2. Capability token rebuild (gateway layer, FP-MCP-006 / FP-SEC-007).
# --------------------------------------------------------------------------


def test_restart_reissues_capability_token_with_correct_audience_scope_ttl() -> None:
    """The short-lived credential is rebuilt, never reused, on restart."""

    async def scenario() -> None:
        first = _build_gateway_harness(run_id="run_gateway_before_restart")
        first_result = await first.gateway.execute(
            _invocation(first, run_id="run_gateway_before_restart")
        )
        assert first_result.result.status.value == "verified"
        assert first.credentials.issue_count == 1
        token_before = first.credentials.handles[0]

        # Worker restart: the same action/thread is re-executed by a NEW
        # gateway instance (fresh process); authorization runs again and the
        # capability token is REBUILT.
        second = _build_gateway_harness(run_id="run_gateway_after_restart")
        second_result = await second.gateway.execute(
            _invocation(second, run_id="run_gateway_after_restart")
        )
        assert second_result.result.status.value == "verified"
        assert second.credentials.issue_count == 1
        token_after = second.credentials.handles[0]

        # audience / scope / action binding / subject are identical.
        assert token_after.audience == token_before.audience == AUDIENCE
        assert token_after.scopes == token_before.scopes == frozenset({"tool.invoke"})
        assert token_after.action_digest == token_before.action_digest
        assert token_after.action_digest == second.action.digest()
        assert token_after.tenant_id == token_before.tenant_id == TENANT
        assert token_after.subject_id == token_before.subject_id == SUBJECT
        assert token_after.purpose == token_before.purpose == PURPOSE
        assert (
            token_after.workload_principal_ref
            == token_before.workload_principal_ref
            == AGENT_PRINCIPAL
        )
        # TTL is correct on the rebuilt token: positive, bounded by the
        # enforced credential TTL and never beyond the authorization limit.
        assert second.credentials.last_ttl_seconds is not None
        ttl_seconds = second.credentials.last_ttl_seconds
        assert ttl_seconds >= 1
        lifetime = (
            token_after.expires_at - token_after.issued_at
        ).total_seconds()
        assert 0 < lifetime <= ttl_seconds
        authorization_limit = min(
            second.action.expires_at,
            second.policy.expires_at,
            second.clock().astimezone(UTC) + timedelta(hours=1),
        )
        assert token_after.expires_at <= authorization_limit
        assert token_after.issued_at <= second.clock().astimezone(UTC)
        # The rebuilt token is a NEW issuance, not the old handle.
        assert token_after.handle_ref != token_before.handle_ref
        # The upstream write executed exactly once per gateway generation
        # (idempotency key deduplicates within each instance).
        assert first.adapter.logical_write_count == 1
        assert second.adapter.logical_write_count == 1

    asyncio.run(scenario())


def _invocation(harness: _GatewayHarness, *, run_id: str) -> GatewayInvocation:
    context = harness.action
    request = ToolRequest.from_mapping(
        {
            "request_id": "treq_alpha0001",
            "trace_id": "trace_alpha0000001",
            "security_context": SecurityContextRef(
                context_id="secctx_alpha0001",
                context_ref="security-context://tenant-alpha/user-alice",
                context_hash=canonical_sha256(
                    {"tenant_id": TENANT, "subject_id": SUBJECT, "purpose": PURPOSE}
                ),
                tenant_id=TENANT,
                subject_id=SUBJECT,
                subject_type=ActorType.USER,
                purpose=PURPOSE,
                authentication=AuthenticationRef(
                    method=AuthenticationMethod.OIDC,
                    assurance_level=AssuranceLevel.HIGH,
                    session_id_hash=canonical_sha256({"session": "fixture"}),
                ),
                data_classification_ceiling=DataClassification.CONFIDENTIAL,
                issued_at=NOW - timedelta(minutes=5),
                expires_at=NOW + timedelta(hours=1),
            ).to_mapping(),
            "agent_principal": AgentPrincipal(
                id=AGENT_ID,
                version=AGENT_VERSION,
                principal_ref=AGENT_PRINCIPAL,
            ).to_mapping(),
            "planned_action": context.to_mapping(),
            "action_digest": context.digest(),
            "policy_decision_id": harness.policy.decision_id,
            "idempotency_key": canonical_sha256(
                {"tenant": TENANT, "tool": context.tool.name, "logical": 1}
            ),
            "approval_id": None,
            "requested_at": NOW.isoformat().replace("+00:00", "Z"),
        }
    )
    return GatewayInvocation(
        request=request,
        workload=AuthenticatedWorkload(
            agent_id=AGENT_ID,
            agent_version=AGENT_VERSION,
            principal_ref=AGENT_PRINCIPAL,
            audience=AUDIENCE,
            tenant_ids=frozenset({TENANT}),
            purposes=frozenset({PURPOSE}),
            allowed_tools=frozenset({context.tool.name}),
            issued_at=NOW - timedelta(minutes=5),
            expires_at=NOW + timedelta(hours=1),
        ),
        thread_id="thread_alpha0001",
        run_id=run_id,
        correlation_id="corr-alpha-0001",
    )
