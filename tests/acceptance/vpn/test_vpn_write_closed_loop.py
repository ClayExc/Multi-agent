"""AC-E2E-001 write closed loop — approval → Gateway write → VERIFIED → audit.

Black-box acceptance of the VPN ticket write vertical slice (steps 6-8 of
AC-E2E-001): the escalation observation carries the user's tried steps, the
worker proposes a ticket update and interrupts for approval, the approver
decides through the public API (separation of duties enforced), the write
executes once through the ticket MCP mock with readback verification, and
the final answer contains the real ticket id. Replays never duplicate the
upstream ticket; ``UNKNOWN`` outcomes are never blindly re-invoked; a
permission revocation invalidates the old approval and blocks resume.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from flowpilot_api import TrustedRequestIdentity, create_app
from flowpilot_api.testing import StaticRequestSecurity
from flowpilot_application import (
    ApplicationError,
    ApprovalDecisionService,
    ErrorCode,
    RequestObservationService,
    RequestReferenceQuery,
    ResolvedRequestReference,
    ResultArtifactService,
)
from flowpilot_application.testing import (
    FakeApprovalEventPort,
    FakeApprovalRepository,
    FakeRequestReferenceResolver,
    FakeResultArtifactPort,
)
from flowpilot_context import ContextBuilder
from flowpilot_domain import (
    Approval,
    ApprovalStatus,
    DataClassification,
    TaskCommand,
    ToolOperation,
    canonical_sha256,
)
from flowpilot_graph import (
    GraphStatus,
    InMemoryCheckpointStore,
    InMemoryLeaseStore,
)
from flowpilot_mcp_gateway import GatewayAdapterDisposition, GatewayAdapterError
from flowpilot_mcp_ticket import TICKET_UPDATE_SCOPE, TicketMcpAdapter
from flowpilot_security import CapabilityHandle
from flowpilot_tool_contracts import (
    GatewayCall,
    ToolResult,
    ToolResultStatus,
    Verification,
    VerificationMethod,
)
from flowpilot_worker import (
    VpnTicketWriteConfig,
    VpnTicketWriteGraph,
    build_ticket_proposal,
)
from langgraph.checkpoint.memory import InMemorySaver

FIXED_NOW = datetime(2026, 7, 28, 8, 30, tzinfo=UTC)
TENANT_A = "tenant-a"
REQUESTER = "user-123"
APPROVER = "user-reviewer"
AGENT_PRINCIPAL = "workload://flowpilot/vpn-write/p1"
PURPOSE = "it_support"
TRIED_STEPS = "restarted the VPN client and rebooted the laptop"

CONFIG = VpnTicketWriteConfig()


class RepoApprovalSource:
    """Adapts the application approval repository to the graph's source port."""

    def __init__(self, approvals: FakeApprovalRepository) -> None:
        self._approvals = approvals

    async def resolve(self, approval_id: str) -> Approval:
        approval = await self._approvals.get(TENANT_A, approval_id)
        if approval is None:
            raise RuntimeError("approval not found")
        return approval


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}_{hashlib.sha256(value.encode()).hexdigest()[:20]}"


def _capability() -> CapabilityHandle:
    return CapabilityHandle(
        handle_ref="capability://ticket/vpn-write",
        audience="mcp://flowpilot-gateway",
        scopes=frozenset({TICKET_UPDATE_SCOPE}),
        tenant_id=TENANT_A,
        subject_id=REQUESTER,
        subject_acl=frozenset({"subject:user-123", "group:vpn-users"}),
        workload_principal_ref=AGENT_PRINCIPAL,
        purpose=PURPOSE,
        data_classification_ceiling="confidential",
        action_digest=canonical_sha256({"ticket": "vpn-write"}),
        issued_at=FIXED_NOW - timedelta(seconds=1),
        expires_at=FIXED_NOW + timedelta(minutes=5),
    )


class TicketGatewayProbe:
    """Transport-shaped Gateway client; preserves public idempotency counts."""

    def __init__(
        self,
        adapter: TicketMcpAdapter,
        capability: CapabilityHandle,
        *,
        result_mode: str = "verified",
    ) -> None:
        self.adapter = adapter
        self.capability = capability
        self.result_mode = result_mode
        self.calls: list[GatewayCall] = []
        self.logical_execution_count = 0
        self._cache: dict[tuple[str, str, str], ToolResult] = {}

    async def execute(self, call: GatewayCall) -> ToolResult:
        self.calls.append(call)
        request = call.request
        action = request.planned_action
        key = (action.tenant_id, action.tool.name, request.idempotency_key)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        self.logical_execution_count += 1
        try:
            invocation = await self.adapter.invoke(
                arguments=action.arguments,
                capability=self.capability,
                idempotency_key=request.idempotency_key,
            )
            readback = await self.adapter.readback(
                arguments=action.arguments,
                invocation=invocation,
                capability=self.capability,
                idempotency_key=request.idempotency_key,
            )
        except GatewayAdapterError as exc:
            if exc.disposition is GatewayAdapterDisposition.OUTCOME_UNKNOWN:
                result = ToolResult(
                    execution_id="tex_ticketunknown01",
                    request_id=request.request_id,
                    operation=ToolOperation.WRITE,
                    status=ToolResultStatus.UNKNOWN,
                    data=None,
                    display_summary=(
                        "Ticket write outcome is unknown; reconciliation "
                        "is required."
                    ),
                    output_classification="internal",
                    policy_decision_id=request.policy_decision_id,
                    retryable=False,
                    retry_basis=None,
                    error_code="PLATFORM_UPSTREAM_OUTCOME_UNKNOWN",
                    verification=None,
                    reconciliation={
                        "state": "pending",
                        "strategy": "upstream_idempotency_lookup",
                        "next_action": "reconcile_only",
                        "ref": None,
                    },
                    started_at=FIXED_NOW,
                    finished_at=FIXED_NOW,
                )
            else:
                result = ToolResult(
                    execution_id="tex_ticketdenied01",
                    request_id=request.request_id,
                    operation=ToolOperation.WRITE,
                    status=ToolResultStatus.FAILED_FINAL,
                    data=None,
                    display_summary="Ticket write was deterministically denied.",
                    output_classification="internal",
                    policy_decision_id=request.policy_decision_id,
                    retryable=False,
                    retry_basis=None,
                    error_code=exc.safe_code,
                    verification=None,
                    reconciliation=None,
                    started_at=FIXED_NOW,
                    finished_at=FIXED_NOW,
                )
        else:
            request_id = (
                "treq_bindingmismatch01"
                if self.result_mode == "binding_mismatch"
                else request.request_id
            )
            result = ToolResult(
                execution_id="tex_ticketprobe01",
                request_id=request_id,
                operation=ToolOperation.WRITE,
                status=(
                    ToolResultStatus.UNKNOWN
                    if not readback.matched
                    else ToolResultStatus.VERIFIED
                ),
                data=dict(readback.data) if readback.matched else None,
                display_summary="Ticket write verified by authoritative readback.",
                output_classification="internal",
                policy_decision_id=request.policy_decision_id,
                retryable=False,
                retry_basis=None,
                error_code=None,
                verification=Verification(
                    method=VerificationMethod.READ_BACK,
                    matched=readback.matched,
                    observed_ref=readback.observed_ref,
                ),
                evidence_ref=(
                    "evidence://ticket/readback" if readback.matched else None
                ),
                reconciliation=None,
                started_at=FIXED_NOW,
                finished_at=FIXED_NOW,
            )
        self._cache[key] = result
        return result


@dataclass(frozen=True, slots=True)
class WriteLoopHarness:
    graph: VpnTicketWriteGraph
    checkpoints: InMemoryCheckpointStore
    leases: InMemoryLeaseStore
    probe: TicketGatewayProbe
    artifacts: FakeResultArtifactPort
    approvals: FakeApprovalRepository
    events: FakeApprovalEventPort
    decisions: ApprovalDecisionService
    create: TaskCommand
    observation: ResolvedRequestReference
    proposal: Mapping[str, Any]
    saver: InMemorySaver


def _resolved_observation() -> ResolvedRequestReference:
    query = RequestReferenceQuery(
        tenant_id=TENANT_A,
        task_id="task_vpnwrite001",
        message_id="msg_vpnescal01",
        message_ref="message://tenant-a/vpn/escalation",
        purpose=PURPOSE,
        security_context_ref="security-context://tenant-a/user-123",
    )
    value = {
        "query": query.to_mapping(),
        "observation_ref": "observation://tenant-a/vpn-escalated",
        "source_digest": canonical_sha256(
            {"message": "VPN 691 unresolved after guided steps"}
        ),
        "intent": "vpn_escalation",
        "fields": {
            "symptom_code": "691",
            "platform": "windows_11",
            "environment": "home_network",
            "tried_steps": TRIED_STEPS,
        },
        "data_classification": "internal",
    }
    unsigned = ResolvedRequestReference(
        query=query,
        observation_ref=value["observation_ref"],
        source_digest=value["source_digest"],
        intent=value["intent"],
        fields=value["fields"],
        data_classification=DataClassification(value["data_classification"]),
        observation_digest="sha256:" + "0" * 64,
    )
    value["observation_digest"] = unsigned.recompute_digest()
    return ResolvedRequestReference(
        query=query,
        observation_ref=value["observation_ref"],
        source_digest=value["source_digest"],
        intent=value["intent"],
        fields=value["fields"],
        data_classification=DataClassification(value["data_classification"]),
        observation_digest=value["observation_digest"],
    )


def _create_command() -> TaskCommand:
    context = {
        "context_id": "secctx_vpnwrite01",
        "context_ref": "security-context://tenant-a/user-123",
        "context_hash": canonical_sha256(
            {"tenant_id": TENANT_A, "subject_id": REQUESTER, "purpose": PURPOSE}
        ),
        "tenant_id": TENANT_A,
        "subject_id": REQUESTER,
        "subject_type": "user",
        "purpose": PURPOSE,
        "authentication": {
            "method": "oidc",
            "assurance_level": "high",
            "session_id_hash": canonical_sha256({"session": "vpn-write"}),
        },
        "data_classification_ceiling": "confidential",
        "issued_at": "2026-07-28T08:20:00Z",
        "expires_at": "2026-07-28T09:30:00Z",
    }
    value = {
        "command_id": "cmd_vpnwrite01",
        "command_type": "task.create.v1",
        "tenant_id": TENANT_A,
        "task_id": "task_vpnwrite001",
        "actor": {"type": "user", "id": REQUESTER},
        "security_context": context,
        "expected_task_version": None,
        "idempotency_key": canonical_sha256({"create": "task_vpnwrite001"}),
        "command_digest": "sha256:" + "0" * 64,
        "correlation_id": "corr-vpn-write-01",
        "payload": {
            "initial_message_id": "msg_vpnescal01",
            "initial_message_ref": "message://tenant-a/vpn/escalation",
            "channel": "web",
            "purpose": PURPOSE,
        },
        "issued_at": "2026-07-28T08:20:00Z",
    }
    unsigned = TaskCommand.from_mapping(value)
    value["command_digest"] = unsigned.recompute_digest()
    return TaskCommand.from_mapping(value)


def _requester_context() -> dict[str, Any]:
    return {
        "context_id": "secctx_vpnwrite01",
        "context_ref": "security-context://tenant-a/user-123",
        "context_hash": canonical_sha256(
            {"tenant_id": TENANT_A, "subject_id": REQUESTER, "purpose": PURPOSE}
        ),
        "tenant_id": TENANT_A,
        "subject_id": REQUESTER,
        "subject_type": "user",
        "purpose": PURPOSE,
        "authentication": {
            "method": "oidc",
            "assurance_level": "high",
            "session_id_hash": canonical_sha256({"session": "vpn-write"}),
        },
        "data_classification_ceiling": "confidential",
        "issued_at": "2026-07-28T08:20:00Z",
        "expires_at": "2026-07-28T09:30:00Z",
    }


def _approver_context() -> dict[str, Any]:
    return {
        "context_id": "secctx_vpnreview01",
        "context_ref": "security-context://tenant-a/user-reviewer",
        "context_hash": canonical_sha256(
            {"tenant_id": TENANT_A, "subject_id": APPROVER, "purpose": PURPOSE}
        ),
        "tenant_id": TENANT_A,
        "subject_id": APPROVER,
        "subject_type": "user",
        "purpose": PURPOSE,
        "authentication": {
            "method": "oidc",
            "assurance_level": "high",
            "session_id_hash": canonical_sha256({"session": "vpn-review"}),
        },
        "data_classification_ceiling": "confidential",
        "issued_at": "2026-07-28T08:25:00Z",
        "expires_at": "2026-07-28T09:30:00Z",
    }


def _decide_command(
    *,
    approval_id: str,
    action_digest: str,
    decision: str,
    actor_id: str = APPROVER,
    command_id: str = "cmd_vpnreview01",
    context: dict[str, Any] | None = None,
) -> TaskCommand:
    selected_context = context if context is not None else _approver_context()
    value = {
        "command_id": command_id,
        "command_type": "task.approval.decide.v1",
        "tenant_id": TENANT_A,
        "task_id": "task_vpnwrite001",
        "actor": {"type": "user", "id": actor_id},
        "security_context": selected_context,
        "expected_task_version": 1,
        "idempotency_key": canonical_sha256(
            {"decide": approval_id, "digest": action_digest}
        ),
        "command_digest": "sha256:" + "0" * 64,
        "correlation_id": "corr-vpn-review-01",
        "payload": {
            "approval_id": approval_id,
            "action_digest": action_digest,
            "decision": decision,
        },
        "issued_at": "2026-07-28T08:26:00Z",
    }
    unsigned = TaskCommand.from_mapping(value)
    value["command_digest"] = unsigned.recompute_digest()
    return TaskCommand.from_mapping(value)


def _command_mapping(command: TaskCommand) -> dict[str, Any]:
    value: dict[str, Any] = {
        "command_id": command.command_id,
        "command_type": command.command_type.value,
        "tenant_id": command.tenant_id,
        "task_id": command.task_id,
        "actor": command.actor.to_mapping(),
        "security_context": command.security_context.to_mapping(),
        "expected_task_version": command.expected_task_version,
        "idempotency_key": command.idempotency_key,
        "command_digest": command.command_digest,
        "payload": dict(command.payload),
        "issued_at": command.issued_at.isoformat().replace("+00:00", "Z"),
    }
    if command.correlation_id is not None:
        value["correlation_id"] = command.correlation_id
    return value


def _pending_approval(proposal: Mapping[str, Any], create: TaskCommand) -> Approval:
    return Approval(
        approval_id=str(proposal["approval_id"]),
        tenant_id=TENANT_A,
        task_id=create.task_id,
        requester_id=REQUESTER,
        action_id=str(proposal["action_id"]),
        action_digest=str(proposal["action_digest"]),
        tool_schema_hash=str(proposal["tool_schema_hash"]),
        policy_decision_id=str(proposal["policy_decision_id"]),
        policy_version=CONFIG.policy_version,
        status=ApprovalStatus.PENDING,
        approver_id=None,
        decision_reason=None,
        separation_of_duties_result=None,
        requested_at=FIXED_NOW - timedelta(minutes=4),
        decided_at=None,
        expires_at=FIXED_NOW + timedelta(minutes=15),
    )


async def _build_harness(*, result_mode: str = "verified") -> WriteLoopHarness:
    create = _create_command()
    observation = _resolved_observation()
    adapter = TicketMcpAdapter(TENANT_A, clock=lambda: FIXED_NOW)
    adapter.mode = "verified"
    probe = TicketGatewayProbe(
        adapter,
        _capability(),
        result_mode=result_mode,
    )
    artifacts = FakeResultArtifactPort()
    checkpoints = InMemoryCheckpointStore()
    leases = InMemoryLeaseStore(clock=lambda: FIXED_NOW)
    saver = InMemorySaver()
    records = {observation.query.message_ref: observation}
    requests = RequestObservationService(
        resolver=FakeRequestReferenceResolver(records),
        required_fields={"vpn_escalation": ()},
    )
    resolved = await requests.resolve(create)
    approvals = FakeApprovalRepository()
    events = FakeApprovalEventPort()
    proposal = build_ticket_proposal(
        config=CONFIG,
        command=create,
        observation=resolved,
    )
    approvals.approvals[(TENANT_A, str(proposal["approval_id"]))] = (
        _pending_approval(proposal, create)
    )
    graph = VpnTicketWriteGraph(
        requests=requests,
        artifacts=ResultArtifactService(artifacts),
        gateway=probe,
        checkpoints=checkpoints,
        context_builder=ContextBuilder(clock=lambda: FIXED_NOW),
        clock=lambda: FIXED_NOW,
        checkpointer=saver,
        approvals=RepoApprovalSource(approvals),
    )
    decisions = ApprovalDecisionService(
        approvals=approvals,
        events=events,
        clock=lambda: FIXED_NOW,
    )
    return WriteLoopHarness(
        graph=graph,
        checkpoints=checkpoints,
        leases=leases,
        probe=probe,
        artifacts=artifacts,
        approvals=approvals,
        events=events,
        decisions=decisions,
        create=create,
        observation=observation,
        proposal=proposal,
        saver=saver,
    )


def _interrupt_card(harness: WriteLoopHarness) -> Mapping[str, Any]:
    """Extract the approval card from the interrupted graph result."""
    state = harness.graph.last_safe_state
    assert state is not None
    interrupts = state.get("__interrupt__")
    assert interrupts, "graph must interrupt with an approval card"
    first = interrupts[0] if isinstance(interrupts, (tuple, list)) else interrupts
    value = getattr(first, "value", first)
    assert isinstance(value, Mapping)
    return value


def _resumed_result_ref(harness: WriteLoopHarness) -> str:
    (result_ref,) = tuple(harness.artifacts.artifacts_by_ref)
    return result_ref


async def _run_until_approval(
    harness: WriteLoopHarness,
) -> tuple[Any, str, str]:
    lease = await harness.leases.acquire(
        TENANT_A, harness.create.task_id, "run_vpnwrite01"
    )
    try:
        outcome = await harness.graph.execute(
            harness.create,
            execution_ref="execution://vpn/write/create",
            lease=lease,
        )
    finally:
        await harness.leases.release(lease)
    assert outcome.state.status is GraphStatus.WAITING_APPROVAL
    assert outcome.state.pending_reason == "vpn_approval:ticket_update"
    approval_id = str(harness.proposal["approval_id"])
    action_digest = str(harness.proposal["action_digest"])
    return outcome, approval_id, action_digest


async def _resume_with_decision(
    harness: WriteLoopHarness,
    decision_command: TaskCommand,
) -> Any:
    lease = await harness.leases.acquire(
        TENANT_A, harness.create.task_id, "run_vpnwrite02"
    )
    try:
        return await harness.graph.execute(
            decision_command,
            execution_ref="execution://vpn/write/decide",
            lease=lease,
        )
    finally:
        await harness.leases.release(lease)


async def test_ac_e2e_001_write_closed_loop_approve_write_verify_audit() -> None:
    harness = await _build_harness()
    _outcome, approval_id, action_digest = await _run_until_approval(harness)

    # The approval card was interrupted with the v1 approval-required fields.
    card = _interrupt_card(harness)
    assert card["kind"] == "approval"
    assert card["approval_id"] == approval_id
    assert card["action_digest"] == action_digest
    assert card["display_ref"].startswith("proposal://")
    assert card["expires_at"]

    # Approver (a different subject) decides through the public API.
    decide = _decide_command(
        approval_id=approval_id,
        action_digest=action_digest,
        decision="approve",
    )
    app = create_app(
        approval_decisions=harness.decisions,
        request_security=StaticRequestSecurity(
            TrustedRequestIdentity(
                tenant_id=TENANT_A,
                subject_id=APPROVER,
                subject_type=decide.actor.type,
                purpose=PURPOSE,
                security_context_id=decide.security_context.context_id,
                security_context_ref=decide.security_context.context_ref,
                security_context_hash=decide.security_context.context_hash,
            )
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://flowpilot.acceptance"
    ) as client:
        response = await client.post(
            "/v1/task-commands", json=_command_mapping(decide)
        )
    assert response.status_code == 202
    body = response.json()
    assert body["approval_id"] == approval_id
    assert body["status"] == "approved"
    assert body["action_digest"] == action_digest

    # The approval record is decided with separation of duties and the
    # task.approval.decided.v1 event is published.
    stored = harness.approvals.approvals[(TENANT_A, approval_id)]
    assert stored.status is ApprovalStatus.APPROVED
    assert stored.approver_id == APPROVER
    assert stored.approver_id != stored.requester_id
    assert stored.separation_of_duties_result is True
    assert len(harness.events.decisions) == 1
    published, decision = harness.events.decisions[0]
    assert decision == "approved"
    assert published.approval_id == approval_id

    # Resume: the write executes exactly once, verified by readback.
    resumed = await _resume_with_decision(harness, decide)
    assert resumed.state.status is GraphStatus.COMPLETED
    assert resumed.state.result_ref is not None
    assert harness.probe.adapter.logical_ticket_count == 1
    assert harness.probe.logical_execution_count == 1

    # The final answer contains the real ticket id and the write arguments
    # carried the user's tried steps.
    artifact = harness.artifacts.artifacts_by_ref[resumed.state.result_ref]
    ticket_id = harness.probe.adapter.records()[0].ticket_id
    assert ticket_id in artifact.content
    assert artifact.citations[0].source_ref == f"ticket://{TENANT_A}/{ticket_id}"
    write_call = harness.probe.calls[-1]
    assert write_call.request.approval_id == approval_id
    assert write_call.request.action_digest == action_digest
    assert write_call.request.planned_action.arguments["summary"] == TRIED_STEPS


async def test_ac_e2e_001_replayed_command_creates_one_ticket_only() -> None:
    harness = await _build_harness()
    _outcome, approval_id, action_digest = await _run_until_approval(harness)
    decide = _decide_command(
        approval_id=approval_id,
        action_digest=action_digest,
        decision="approve",
    )
    await harness.decisions.decide(decide)
    await _resume_with_decision(harness, decide)

    # The same execution command replayed ten times: one ticket upstream.
    result_ref = _resumed_result_ref(harness)
    for _ in range(10):
        lease = await harness.leases.acquire(
            TENANT_A, harness.create.task_id, "run_vpnwrite_replay"
        )
        try:
            replay = await harness.graph.execute(
                harness.create,
                execution_ref="execution://vpn/write/replay",
                lease=lease,
            )
        finally:
            await harness.leases.release(lease)
        assert replay.state.status is GraphStatus.COMPLETED
        assert replay.state.result_ref == result_ref

    assert harness.probe.adapter.logical_ticket_count == 1
    assert harness.probe.adapter.invocation_count == 1
    assert len(harness.artifacts.artifacts_by_ref) == 1


async def test_unknown_outcome_never_duplicates_the_ticket() -> None:
    harness = await _build_harness()
    harness.probe.adapter.mode = "unknown_executed"
    _outcome, approval_id, action_digest = await _run_until_approval(harness)
    decide = _decide_command(
        approval_id=approval_id,
        action_digest=action_digest,
        decision="approve",
    )
    await harness.decisions.decide(decide)

    resumed = await _resume_with_decision(harness, decide)

    # The upstream created the ticket but the outcome is unknown: the worker
    # fails without blind re-invocation (reconciliation is the Gateway's job).
    assert resumed.state.status is GraphStatus.FAILED
    assert resumed.state.failure_code == "RUNTIME_TICKET_OUTCOME_UNKNOWN"
    assert harness.probe.adapter.logical_ticket_count == 1
    assert harness.probe.adapter.invocation_count == 1
    assert harness.probe.logical_execution_count == 1
    assert len(harness.artifacts.artifacts_by_ref) == 0


async def test_requester_cannot_approve_own_ticket_write() -> None:
    harness = await _build_harness()
    _outcome, approval_id, action_digest = await _run_until_approval(harness)
    own_decision = _decide_command(
        approval_id=approval_id,
        action_digest=action_digest,
        decision="approve",
        actor_id=REQUESTER,
        command_id="cmd_vpnself01",
        context=_requester_context(),
    )
    app = create_app(
        approval_decisions=harness.decisions,
        request_security=StaticRequestSecurity(
            TrustedRequestIdentity(
                tenant_id=TENANT_A,
                subject_id=REQUESTER,
                subject_type=own_decision.actor.type,
                purpose=PURPOSE,
                security_context_id=own_decision.security_context.context_id,
                security_context_ref=own_decision.security_context.context_ref,
                security_context_hash=own_decision.security_context.context_hash,
            )
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://flowpilot.acceptance"
    ) as client:
        response = await client.post(
            "/v1/task-commands", json=_command_mapping(own_decision)
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CORE_APPROVAL_DUTIES_VIOLATION"
    assert harness.approvals.approvals[(TENANT_A, approval_id)].status is (
        ApprovalStatus.PENDING
    )
    assert harness.events.decisions == []
    assert harness.probe.adapter.invocation_count == 0


async def test_tampered_action_digest_is_rejected_at_decision_and_resume() -> None:
    harness = await _build_harness()
    _outcome, approval_id, action_digest = await _run_until_approval(harness)
    forged_digest = canonical_sha256({"tampered": True})
    tampered = _decide_command(
        approval_id=approval_id,
        action_digest=forged_digest,
        decision="approve",
        command_id="cmd_vpntamper01",
    )
    app = create_app(
        approval_decisions=harness.decisions,
        request_security=StaticRequestSecurity(
            TrustedRequestIdentity(
                tenant_id=TENANT_A,
                subject_id=APPROVER,
                subject_type=tampered.actor.type,
                purpose=PURPOSE,
                security_context_id=tampered.security_context.context_id,
                security_context_ref=tampered.security_context.context_ref,
                security_context_hash=tampered.security_context.context_hash,
            )
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://flowpilot.acceptance"
    ) as client:
        response = await client.post(
            "/v1/task-commands", json=_command_mapping(tampered)
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CORE_APPROVAL_BINDING_MISMATCH"
    assert harness.approvals.approvals[(TENANT_A, approval_id)].status is (
        ApprovalStatus.PENDING
    )

    # Worker-side resume with the tampered digest is also refused.
    declined = await _resume_with_decision(harness, tampered)
    assert declined.state.status is GraphStatus.FAILED
    assert declined.state.failure_code == "RUNTIME_APPROVAL_BINDING_MISMATCH"
    assert harness.probe.adapter.logical_ticket_count == 0


async def test_permission_revocation_invalidates_approval_and_blocks_resume() -> None:
    harness = await _build_harness()
    _outcome, approval_id, action_digest = await _run_until_approval(harness)
    decide = _decide_command(
        approval_id=approval_id,
        action_digest=action_digest,
        decision="approve",
    )
    await harness.decisions.decide(decide)
    assert harness.approvals.approvals[(TENANT_A, approval_id)].status is (
        ApprovalStatus.APPROVED
    )

    # The approver's permission is revoked: the old approval is invalidated.
    revoked = await harness.decisions.revoke(
        tenant_id=TENANT_A,
        approval_id=approval_id,
        reason="approver role revoked",
    )
    assert revoked.status is ApprovalStatus.REVOKED
    assert len(harness.events.decisions) == 2
    _published, decision = harness.events.decisions[1]
    assert decision == "revoked"

    # Resume with the revoked approval is refused and nothing is written.
    resumed = await _resume_with_decision(harness, decide)
    assert resumed.state.status is GraphStatus.FAILED
    assert resumed.state.failure_code == "RUNTIME_APPROVAL_INVALID"
    assert harness.probe.adapter.logical_ticket_count == 0
    assert harness.probe.adapter.invocation_count == 0

    # A second decision against the revoked record is refused as a conflict.
    again = _decide_command(
        approval_id=approval_id,
        action_digest=action_digest,
        decision="approve",
        command_id="cmd_vpnreview02",
    )
    try:
        await harness.decisions.decide(again)
    except ApplicationError as exc:
        assert exc.code is ErrorCode.APPROVAL_CONFLICT
    else:
        raise AssertionError("expected APPROVAL_CONFLICT")


async def test_wrong_approver_identity_is_rejected_at_the_api() -> None:
    harness = await _build_harness()
    _outcome, approval_id, action_digest = await _run_until_approval(harness)
    decide = _decide_command(
        approval_id=approval_id,
        action_digest=action_digest,
        decision="approve",
    )
    # An identity that does not match the command security context is refused
    # before the decision service runs.
    forged = StaticRequestSecurity(
        TrustedRequestIdentity(
            tenant_id=TENANT_A,
            subject_id="user-eve",
            subject_type=decide.actor.type,
            purpose=PURPOSE,
            security_context_id=decide.security_context.context_id,
            security_context_ref=decide.security_context.context_ref,
            security_context_hash=decide.security_context.context_hash,
        )
    )
    app = create_app(approval_decisions=harness.decisions, request_security=forged)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://flowpilot.acceptance"
    ) as client:
        response = await client.post(
            "/v1/task-commands", json=_command_mapping(decide)
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "API_REQUEST_IDENTITY_MISMATCH"
    assert harness.probe.adapter.invocation_count == 0
