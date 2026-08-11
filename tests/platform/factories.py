from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

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
from flowpilot_mcp_knowledge import (
    KNOWLEDGE_CONTRACT,
    KnowledgeMcpAdapter,
    KnowledgeRecord,
)
from flowpilot_persistence import MemoryDatabase, MemoryDataUnitOfWorkFactory
from flowpilot_policy import (
    ApprovalVerifier,
    PolicyDecision,
    PolicyDecisionKind,
    PolicyEnforcer,
    PolicyError,
    PolicyErrorCode,
    ResolvedPolicyDecision,
)
from flowpilot_security import (
    AuthenticatedWorkload,
    CapabilityHandle,
    SecurityVerifier,
    TrustedSecurityContext,
    trusted_context_snapshot_hash,
)
from flowpilot_tool_contracts import AgentPrincipal, ToolContract, ToolRequest

NOW = datetime(2026, 7, 30, 8, 0, tzinfo=UTC)
TENANT = "tenant-alpha"
OTHER_TENANT = "tenant-bravo"
SUBJECT = "user-alice"
APPROVER = "user-reviewer"
AGENT_ID = "flowpilot-agent"
AGENT_VERSION = "m0.1"
AGENT_PRINCIPAL = "workload://flowpilot/agent/m0"
PURPOSE = "it-service-fulfillment"
POLICY_VERSION = "policy-m0.1"
AUDIENCE = "mcp://flowpilot-gateway"
IDENTITY_ISSUER = "https://identity.fixture.local/realms/flowpilot"
USER_AUTHORIZED_PARTY = "flowpilot-web-fixture"
WORKLOAD_AUTHORIZED_PARTY = "flowpilot-worker-fixture"
WORKLOAD_SUBJECT = "service-account-flowpilot-worker-fixture"
USER_TOKEN_HASH = canonical_sha256({"credential": "user-fixture"})
WORKLOAD_TOKEN_HASH = canonical_sha256({"credential": "workload-fixture"})
CONTEXT_ROLES = frozenset({"requester", "group:vpn-users"})
CONTEXT_SCOPES = frozenset({"tasks:read", "tools:invoke"})


def bind_context_snapshot(context: SecurityContextRef) -> SecurityContextRef:
    return replace(
        context,
        context_hash=trusted_context_snapshot_hash(
            context_id=context.context_id,
            context_ref=context.context_ref,
            tenant_id=context.tenant_id,
            subject_id=context.subject_id,
            subject_type=context.subject_type,
            issuer=IDENTITY_ISSUER,
            authorized_party=USER_AUTHORIZED_PARTY,
            roles=CONTEXT_ROLES,
            scopes=CONTEXT_SCOPES,
            authentication=context.authentication,
            purpose=context.purpose,
            data_classification_ceiling=context.data_classification_ceiling,
            issued_at=context.issued_at,
            expires_at=context.expires_at,
            source_token_hash=USER_TOKEN_HASH,
        ),
    )

WRITE_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["ticket_id", "status"],
    "properties": {
        "ticket_id": {"type": "string", "minLength": 1, "maxLength": 64},
        "status": {
            "type": "string",
            "enum": ["in_progress", "resolved"],
        },
    },
}
WRITE_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["ticket_id", "status"],
    "properties": {
        "ticket_id": {"type": "string", "minLength": 1, "maxLength": 64},
        "status": {
            "type": "string",
            "enum": ["in_progress", "resolved"],
        },
    },
}
WRITE_CONTRACT = ToolContract.create(
    name="ticket.update.v1",
    input_schema=WRITE_INPUT_SCHEMA,
    output_schema=WRITE_OUTPUT_SCHEMA,
)


class TickingClock:
    def __init__(self, start: datetime = NOW) -> None:
        self._next = start

    def __call__(self) -> datetime:
        value = self._next
        self._next += timedelta(microseconds=1)
        return value


class ContextSource:
    def __init__(self, context: SecurityContextRef) -> None:
        self.context = context
        self.available = True
        self.active = True
        self.resolution_count = 0
        self.roles = CONTEXT_ROLES
        self.scopes = CONTEXT_SCOPES

    async def resolve(self, context_ref: str) -> TrustedSecurityContext:
        self.resolution_count += 1
        if not self.available:
            raise RuntimeError("context backend unavailable")
        if context_ref != self.context.context_ref:
            raise RuntimeError("context not found")
        return TrustedSecurityContext(
            context=self.context,
            active=self.active,
            roles=self.roles,
            scopes=self.scopes,
            issuer=IDENTITY_ISSUER,
            authorized_party=USER_AUTHORIZED_PARTY,
            identity_token_hash=USER_TOKEN_HASH,
        )


class PolicySource:
    def __init__(self, record: ResolvedPolicyDecision) -> None:
        self.record = record
        self.available = True
        self.resolve_count = 0

    async def resolve(self, decision_id: str) -> ResolvedPolicyDecision:
        self.resolve_count += 1
        if not self.available:
            raise RuntimeError("PDP unavailable")
        if decision_id != self.record.decision.decision_id:
            raise PolicyError(
                code=PolicyErrorCode.UNAVAILABLE,
                safe_message="policy not found",
            )
        return self.record


class ApprovalSource:
    def __init__(self, approval: Approval | None) -> None:
        self.approval = approval
        self.available = True

    async def resolve(self, approval_id: str) -> Approval:
        if not self.available or self.approval is None:
            raise RuntimeError("approval unavailable")
        if approval_id != self.approval.approval_id:
            raise RuntimeError("approval not found")
        return self.approval


class ApproverDirectory:
    def __init__(self) -> None:
        self.authorized = True

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
            self.authorized
            and tenant_id == TENANT
            and subject_id == APPROVER
            and "change_approver" in roles
        )


class CredentialBroker:
    def __init__(self) -> None:
        self.issue_count = 0
        self.last_ttl_seconds: int | None = None
        self.available = True

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
        if not self.available:
            raise RuntimeError("credential broker unavailable")
        self.issue_count += 1
        self.last_ttl_seconds = ttl_seconds
        return CapabilityHandle(
            handle_ref=f"capability://fixture/{self.issue_count}",
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


class SignalSink:
    def __init__(self) -> None:
        self.available = True
        self.trace_sampled = False
        self.traces: list[Any] = []
        self.audits: list[AuditDraft] = []
        self.security: list[SecurityDraft] = []

    async def ensure_unsampled_available(self) -> None:
        if not self.available:
            raise RuntimeError("unsampled signal sink unavailable")

    async def emit_trace(self, event: Any) -> None:
        if not self.trace_sampled:
            self.traces.append(event)

    async def append_audit(self, audit: AuditDraft) -> None:
        if not self.available:
            raise RuntimeError("audit sink unavailable")
        self.audits.append(audit)

    async def append_blocked_pair(
        self, audit: AuditDraft, security: SecurityDraft
    ) -> None:
        if not self.available:
            raise RuntimeError("security sink unavailable")
        self.audits.append(audit)
        self.security.append(security)


class WriteAdapter:
    def __init__(self) -> None:
        self.mode = "verified"
        self.invocation_count = 0
        self.reconciliation_count = 0
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
        self.invocation_count += 1
        if self.mode == "not_sent":
            raise GatewayAdapterError(
                GatewayAdapterDisposition.NOT_SENT,
                "PROVIDER_NOT_SENT",
                "upstream invocation was not sent",
            )
        if self.mode == "rejected":
            raise GatewayAdapterError(
                GatewayAdapterDisposition.REJECTED,
                "PROVIDER_REJECTED",
                "upstream rejected the request",
            )
        if self.mode == "unknown_not_executed":
            raise GatewayAdapterError(
                GatewayAdapterDisposition.OUTCOME_UNKNOWN,
                "PROVIDER_TIMEOUT",
                "upstream outcome is unknown",
            )
        if idempotency_key not in self.values:
            self.logical_write_count += 1
            self.values[idempotency_key] = dict(arguments)
        if self.mode == "unknown_executed":
            raise GatewayAdapterError(
                GatewayAdapterDisposition.OUTCOME_UNKNOWN,
                "PROVIDER_TIMEOUT",
                "upstream outcome is unknown",
            )
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
        if self.mode == "readback_unavailable":
            raise RuntimeError("readback unavailable")
        if self.mode == "readback_secret":
            data: Mapping[str, Any] = {
                "ticket_id": str(arguments["ticket_id"]),
                "status": str(arguments["status"]),
                "password": "super-secret",
            }
        else:
            data = dict(stored or {})
        matched = stored == dict(arguments) and self.mode != "readback_mismatch"
        return ReadbackResult(
            data=data,
            evidence_ref="evidence://ticket/readback",
            observed_ref="ticket://observed/TCK-100",
            matched=matched,
        )

    async def reconcile(
        self,
        *,
        arguments: Mapping[str, Any],
        capability: CapabilityHandle,
        idempotency_key: str,
    ) -> ReconciliationResult:
        del arguments, capability
        self.reconciliation_count += 1
        if self.mode == "reconcile_unavailable":
            raise RuntimeError("reconciliation unavailable")
        stored = self.values.get(idempotency_key)
        if stored is None:
            return ReconciliationResult(
                disposition=ReconciliationDisposition.CONFIRMED_NOT_EXECUTED,
                data=None,
                evidence_ref="evidence://idempotency/absent",
                observed_ref="idempotency://absent",
                method="upstream_idempotency_lookup",
            )
        return ReconciliationResult(
            disposition=ReconciliationDisposition.VERIFIED,
            data=dict(stored),
            evidence_ref="evidence://idempotency/present",
            observed_ref="idempotency://present",
            method="upstream_idempotency_lookup",
        )


@dataclass(slots=True)
class GatewayFixture:
    gateway: McpGateway
    invocation: GatewayInvocation
    context_source: ContextSource
    policy_source: PolicySource
    approval_source: ApprovalSource
    approvers: ApproverDirectory
    credentials: CredentialBroker
    signals: SignalSink
    database: MemoryDatabase
    data_uow: MemoryDataUnitOfWorkFactory
    adapter: KnowledgeMcpAdapter | WriteAdapter
    action: PlannedAction
    policy: PolicyDecision
    approval: Approval | None

    def replace_invocation(
        self,
        *,
        action: PlannedAction | None = None,
        workload: AuthenticatedWorkload | None = None,
        policy_decision_id: str | None = None,
        approval_id: str | None | object = ...,
    ) -> GatewayInvocation:
        selected_action = action or self.action
        selected_approval = (
            self.invocation.request.approval_id
            if approval_id is ...
            else approval_id
        )
        request_mapping = self.invocation.request.to_mapping()
        request_mapping["planned_action"] = selected_action.to_mapping()
        request_mapping["action_digest"] = selected_action.digest()
        request_mapping["policy_decision_id"] = (
            policy_decision_id or self.policy.decision_id
        )
        request_mapping["approval_id"] = selected_approval
        request = ToolRequest.from_mapping(request_mapping)
        return replace(
            self.invocation,
            request=request,
            workload=workload or self.invocation.workload,
        )

    def replace_policy_for_action(
        self,
        action: PlannedAction,
        *,
        expires_at: datetime | None = None,
    ) -> PolicyDecision:
        mapping = self.policy.to_mapping()
        mapping["tenant_id"] = action.tenant_id
        mapping["task_id"] = action.task_id
        mapping["action"] = {
            "tool": action.tool.name,
            "operation": action.tool.operation.value,
            "action_digest": action.digest(),
        }
        mapping["policy_version"] = action.policy_version
        mapping["expires_at"] = (
            expires_at or action.expires_at
        ).isoformat().replace("+00:00", "Z")
        preimage = policy_input(self.invocation.request.security_context, action)
        mapping["input_hash"] = canonical_sha256(preimage)
        decision = PolicyDecision.from_mapping(mapping)
        self.policy = decision
        self.policy_source.record = ResolvedPolicyDecision.create(
            decision=decision,
            input_preimage=preimage,
        )
        return decision


def policy_input(
    context: SecurityContextRef, action: PlannedAction
) -> dict[str, Any]:
    return {
        "tenant_id": action.tenant_id,
        "purpose": action.purpose,
        "subject_ref": context.context_ref,
        "subject_context_hash": context.context_hash,
        "agent": {
            "id": AGENT_ID,
            "version": AGENT_VERSION,
            "principal_ref": AGENT_PRINCIPAL,
        },
        "action": {
            "tool": action.tool.name,
            "operation": action.tool.operation.value,
            "action_digest": action.digest(),
        },
    }


def make_fixture(
    *,
    operation: ToolOperation = ToolOperation.WRITE,
    decision_kind: PolicyDecisionKind = PolicyDecisionKind.ALLOW,
    obligations: list[dict[str, Any]] | None = None,
) -> GatewayFixture:
    clock = TickingClock()
    expires_at = NOW + timedelta(minutes=15)
    authentication = AuthenticationRef(
        method=AuthenticationMethod.OIDC,
        assurance_level=AssuranceLevel.HIGH,
        session_id_hash=canonical_sha256({"session": "fixture"}),
    )
    context_issued_at = NOW - timedelta(minutes=5)
    context_expires_at = NOW + timedelta(hours=1)
    context = SecurityContextRef(
        context_id="secctx_alpha0001",
        context_ref="security-context://tenant-alpha/user-alice",
        context_hash=trusted_context_snapshot_hash(
            context_id="secctx_alpha0001",
            context_ref="security-context://tenant-alpha/user-alice",
            tenant_id=TENANT,
            subject_id=SUBJECT,
            subject_type=ActorType.USER,
            issuer=IDENTITY_ISSUER,
            authorized_party=USER_AUTHORIZED_PARTY,
            roles=CONTEXT_ROLES,
            scopes=CONTEXT_SCOPES,
            authentication=authentication,
            purpose=PURPOSE,
            data_classification_ceiling=DataClassification.CONFIDENTIAL,
            issued_at=context_issued_at,
            expires_at=context_expires_at,
            source_token_hash=USER_TOKEN_HASH,
        ),
        tenant_id=TENANT,
        subject_id=SUBJECT,
        subject_type=ActorType.USER,
        purpose=PURPOSE,
        authentication=authentication,
        data_classification_ceiling=DataClassification.CONFIDENTIAL,
        issued_at=context_issued_at,
        expires_at=context_expires_at,
    )
    if operation is ToolOperation.READ:
        contract = KNOWLEDGE_CONTRACT
        arguments: Mapping[str, Any] = {"query": "restart", "limit": 5}
        resource_type = "knowledge_record"
        adapter: KnowledgeMcpAdapter | WriteAdapter = KnowledgeMcpAdapter(
            (
                KnowledgeRecord(
                    tenant_id=TENANT,
                    source_ref=(
                        "knowledge://tenant-alpha/runbooks/database/"
                        "1.0#controlled-restart"
                    ),
                    document_version="1.0",
                    section="Restart database service",
                    redacted_summary="Use the controlled restart runbook.",
                    content_hash=canonical_sha256(
                        {"content": "Use the controlled restart runbook."}
                    ),
                    data_classification="internal",
                    acl_subjects=frozenset({"group:vpn-users"}),
                    allowed_workload_principals=frozenset(
                        {AGENT_PRINCIPAL}
                    ),
                    allowed_purposes=frozenset({PURPOSE}),
                    effective_at=NOW - timedelta(days=1),
                    expires_at=NOW + timedelta(days=1),
                ),
                KnowledgeRecord(
                    tenant_id=OTHER_TENANT,
                    source_ref=(
                        "knowledge://tenant-bravo/runbooks/payroll/"
                        "1.0#restart"
                    ),
                    document_version="1.0",
                    section="Restart payroll service",
                    redacted_summary="Tenant Bravo private runbook.",
                    content_hash=canonical_sha256(
                        {"content": "Tenant Bravo private runbook."}
                    ),
                    data_classification="internal",
                    acl_subjects=frozenset({"group:vpn-users"}),
                    allowed_workload_principals=frozenset(
                        {AGENT_PRINCIPAL}
                    ),
                    allowed_purposes=frozenset({PURPOSE}),
                    effective_at=NOW - timedelta(days=1),
                    expires_at=NOW + timedelta(days=1),
                ),
            ),
            clock=clock,
        )
    else:
        contract = WRITE_CONTRACT
        arguments = {"ticket_id": "TCK-100", "status": "resolved"}
        resource_type = "ticket"
        adapter = WriteAdapter()
    action = PlannedAction(
        action_id="act_alpha0001",
        tenant_id=TENANT,
        task_id="task_alpha0001",
        requester_id=SUBJECT,
        agent=ActionAgent(id=AGENT_ID, version=AGENT_VERSION),
        tool=ActionTool(
            name=contract.name,
            schema_hash=contract.schema_hash,
            operation=operation,
        ),
        arguments=arguments,
        resource=ActionResource(type=resource_type, id="TCK-100"),
        purpose=PURPOSE,
        data_classification=DataClassification.INTERNAL,
        policy_version=POLICY_VERSION,
        expires_at=expires_at,
    )
    preimage = policy_input(context, action)
    requirements = (
        {
            "roles": ["change_approver"],
            "minimum_approvers": 1,
            "separation_of_duties": True,
        }
        if decision_kind is PolicyDecisionKind.REQUIRE_APPROVAL
        else None
    )
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
                "operation": operation.value,
                "action_digest": action.digest(),
            },
            "decision": decision_kind.value,
            "reason_codes": ["POLICY_FIXTURE_ALLOW"],
            "obligations": obligations or [],
            "approval_requirements": requirements,
            "policy_version": POLICY_VERSION,
            "input_canonicalization": "rfc8785",
            "input_hash": canonical_sha256(preimage),
            "evaluated_at": (NOW - timedelta(minutes=1))
            .isoformat()
            .replace("+00:00", "Z"),
            "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        }
    )
    policy_record = ResolvedPolicyDecision.create(
        decision=decision,
        input_preimage=preimage,
    )
    approval = (
        Approval(
            approval_id="apr_alpha0001",
            tenant_id=TENANT,
            task_id=action.task_id,
            requester_id=SUBJECT,
            action_id=action.action_id,
            action_digest=action.digest(),
            tool_schema_hash=action.tool.schema_hash,
            policy_decision_id=decision.decision_id,
            policy_version=POLICY_VERSION,
            status=ApprovalStatus.APPROVED,
            approver_id=APPROVER,
            decision_reason="approved for deterministic fixture",
            separation_of_duties_result=True,
            requested_at=NOW - timedelta(minutes=3),
            decided_at=NOW - timedelta(minutes=2),
            expires_at=expires_at,
        )
        if decision_kind is PolicyDecisionKind.REQUIRE_APPROVAL
        else None
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
            "action_digest": action.digest(),
            "policy_decision_id": decision.decision_id,
            "idempotency_key": canonical_sha256(
                {"tenant": TENANT, "tool": action.tool.name, "logical": 1}
            ),
            "approval_id": approval.approval_id if approval is not None else None,
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
        attested=True,
        issuer=IDENTITY_ISSUER,
        authorized_party=WORKLOAD_AUTHORIZED_PARTY,
        subject_id=WORKLOAD_SUBJECT,
        credential_hash=WORKLOAD_TOKEN_HASH,
    )
    invocation = GatewayInvocation(
        request=request,
        workload=workload,
        thread_id="thread_alpha0001",
        run_id="run_alpha0001",
        correlation_id="corr-alpha-0001",
    )
    context_source = ContextSource(context)
    policy_source = PolicySource(policy_record)
    approval_source = ApprovalSource(approval)
    approvers = ApproverDirectory()
    credentials = CredentialBroker()
    signals = SignalSink()
    database = MemoryDatabase()
    data_uow = MemoryDataUnitOfWorkFactory(database)
    registry = ToolRegistry(
        (
            ToolDefinition(
                contract=contract,
                operation=operation,
                audience=AUDIENCE,
                upstream_provider="fixture-mcp",
                allowed_agents=frozenset({AGENT_ID}),
                allowed_tenants=frozenset({TENANT}),
                allowed_purposes=frozenset({PURPOSE}),
                credential_scopes=(
                    frozenset({"knowledge.search"})
                    if operation is ToolOperation.READ
                    else frozenset({"tool.invoke"})
                ),
                adapter=adapter,
            ),
        )
    )
    gateway = McpGateway(
        GatewayDependencies(
            registry=registry,
            security_contexts=context_source,
            security=SecurityVerifier(),
            policies=policy_source,
            policy=PolicyEnforcer(),
            approvals=approval_source,
            approval=ApprovalVerifier(),
            approvers=approvers,
            credentials=credentials,
            data_uow=data_uow,
            signals=signals,
            clock=clock,
        )
    )
    return GatewayFixture(
        gateway=gateway,
        invocation=invocation,
        context_source=context_source,
        policy_source=policy_source,
        approval_source=approval_source,
        approvers=approvers,
        credentials=credentials,
        signals=signals,
        database=database,
        data_uow=data_uow,
        adapter=adapter,
        action=action,
        policy=decision,
        approval=approval,
    )
