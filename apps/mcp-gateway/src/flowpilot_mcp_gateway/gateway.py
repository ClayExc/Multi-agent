from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta

from flowpilot_domain import Approval, SecurityContextRef, ToolOperation
from flowpilot_persistence import (
    DataUnitOfWorkFactory,
    ExecutionIntent,
    ExecutionOutcome,
    ExecutionRecord,
    LedgerStatus,
    OutboxEvent,
    PersistenceError,
    PersistenceErrorCode,
)
from flowpilot_persistence import (
    RetryBasis as LedgerRetryBasis,
)
from flowpilot_policy import (
    ApprovalSource,
    ApprovalVerifier,
    ApproverDirectoryPort,
    EnforcedPolicy,
    PolicyDecision,
    PolicyDecisionKind,
    PolicyDecisionSource,
    PolicyEnforcer,
    PolicyError,
    PolicyErrorCode,
)
from flowpilot_security import (
    CapabilityHandle,
    CredentialBrokerPort,
    SecurityContextSource,
    SecurityError,
    SecurityErrorCode,
    SecurityVerifier,
    assert_safe_projection,
)
from flowpilot_tool_contracts import (
    Reconciliation,
    RetryBasis,
    ToolContractError,
    ToolResult,
    ToolResultStatus,
    Verification,
    VerificationMethod,
)

from .errors import (
    GatewayAdapterDisposition,
    GatewayAdapterError,
    GatewayControlError,
    GatewayReason,
)
from .lifecycle import LifecycleRecorder
from .models import (
    GatewayExecution,
    GatewayInvocation,
    LifecycleOutcome,
    LifecycleStage,
)
from .ports import (
    Clock,
    ReconciliationDisposition,
    ReconciliationResult,
)
from .registry import ToolDefinition, ToolRegistry
from .signals import (
    AuditDraft,
    SignalSinkPort,
    build_audit_draft,
    build_blocked_pair,
)

GATEWAY_INBOUND_PORT_VERSION = "flowpilot.mcp-gateway.m0.v1"


@dataclass(frozen=True, slots=True)
class GatewayDependencies:
    registry: ToolRegistry
    security_contexts: SecurityContextSource
    security: SecurityVerifier
    policies: PolicyDecisionSource
    policy: PolicyEnforcer
    approvals: ApprovalSource
    approval: ApprovalVerifier
    approvers: ApproverDirectoryPort
    credentials: CredentialBrokerPort
    data_uow: DataUnitOfWorkFactory
    signals: SignalSinkPort
    clock: Clock


@dataclass(frozen=True, slots=True)
class _Authorization:
    context: SecurityContextRef
    subject_acl: frozenset[str]
    definition: ToolDefinition
    policy: PolicyDecision
    enforced_policy: EnforcedPolicy
    approval: Approval | None


class _AuthorizationRejected(RuntimeError):
    def __init__(
        self,
        context: SecurityContextRef,
        policy: PolicyDecision | None,
        cause: Exception,
    ) -> None:
        super().__init__("authorization was rejected")
        self.context = context
        self.policy = policy
        self.cause = cause


def _execution_id(invocation: GatewayInvocation) -> str:
    request = invocation.request
    preimage = "\x1f".join(
        (
            request.security_context.tenant_id,
            request.planned_action.tool.name,
            request.idempotency_key,
        )
    ).encode("utf-8")
    return "tex_" + hashlib.sha256(preimage).hexdigest()[:32]


class McpGateway:
    """Process-internal core; network transports must mount GatewayIngress."""

    def __init__(self, dependencies: GatewayDependencies) -> None:
        self._deps = dependencies

    async def execute(self, invocation: GatewayInvocation) -> GatewayExecution:
        started_at = self._deps.clock()
        execution_id = _execution_id(invocation)
        recorder = LifecycleRecorder(
            invocation=invocation,
            sink=self._deps.signals,
            clock=self._deps.clock,
        )
        await recorder.record(
            LifecycleStage.INGRESS,
            LifecycleOutcome.PASSED,
            GatewayReason.REQUEST_ACCEPTED.value,
        )
        try:
            await self._deps.signals.ensure_unsampled_available()
            authorization = await self._authorize(invocation, recorder)
        except _AuthorizationRejected as rejected:
            return await self._reject(
                invocation=invocation,
                execution_id=execution_id,
                recorder=recorder,
                started_at=started_at,
                exc=rejected.cause,
                policy=rejected.policy,
                trusted_context=rejected.context,
            )
        except Exception as exc:
            return await self._reject(
                invocation=invocation,
                execution_id=execution_id,
                recorder=recorder,
                started_at=started_at,
                exc=exc,
                policy=None,
                trusted_context=None,
            )
        if invocation.request.planned_action.tool.operation is ToolOperation.READ:
            return await self._execute_read(
                invocation=invocation,
                execution_id=execution_id,
                recorder=recorder,
                started_at=started_at,
                authorization=authorization,
            )
        return await self._execute_write(
            invocation=invocation,
            execution_id=execution_id,
            recorder=recorder,
            started_at=started_at,
            authorization=authorization,
        )

    async def reconcile(
        self, invocation: GatewayInvocation
    ) -> GatewayExecution:
        started_at = self._deps.clock()
        execution_id = _execution_id(invocation)
        recorder = LifecycleRecorder(
            invocation=invocation,
            sink=self._deps.signals,
            clock=self._deps.clock,
        )
        await recorder.record(
            LifecycleStage.INGRESS,
            LifecycleOutcome.PASSED,
            GatewayReason.REQUEST_ACCEPTED.value,
        )
        try:
            await self._deps.signals.ensure_unsampled_available()
            authorization = await self._authorize(invocation, recorder)
        except _AuthorizationRejected as rejected:
            return await self._reject(
                invocation=invocation,
                execution_id=execution_id,
                recorder=recorder,
                started_at=started_at,
                exc=rejected.cause,
                policy=rejected.policy,
                trusted_context=rejected.context,
            )
        except Exception as exc:
            return await self._reject(
                invocation=invocation,
                execution_id=execution_id,
                recorder=recorder,
                started_at=started_at,
                exc=exc,
                policy=None,
                trusted_context=None,
            )
        if (
            invocation.request.planned_action.tool.operation
            is not ToolOperation.WRITE
        ):
            return await self._reject(
                invocation=invocation,
                execution_id=execution_id,
                recorder=recorder,
                started_at=started_at,
                exc=GatewayControlError(
                    GatewayReason.RECONCILIATION_REQUIRED.value,
                    "only write executions can be reconciled",
                ),
                policy=authorization.policy,
                trusted_context=authorization.context,
            )
        try:
            record = await self._get_record(
                authorization.context.tenant_id, execution_id
            )
        except Exception as exc:
            return await self._reject(
                invocation=invocation,
                execution_id=execution_id,
                recorder=recorder,
                started_at=started_at,
                exc=exc,
                policy=authorization.policy,
                trusted_context=authorization.context,
            )
        if record is None:
            return await self._reject(
                invocation=invocation,
                execution_id=execution_id,
                recorder=recorder,
                started_at=started_at,
                exc=GatewayControlError(
                    GatewayReason.RECONCILIATION_REQUIRED.value,
                    "execution ledger record does not exist",
                ),
                policy=authorization.policy,
                trusted_context=authorization.context,
            )
        candidate_intent = self._execution_intent(
            invocation=invocation,
            execution_id=execution_id,
            authorization=authorization,
            created_at=record.intent.created_at,
        )
        if candidate_intent.fingerprint() != record.intent.fingerprint():
            return await self._reject(
                invocation=invocation,
                execution_id=execution_id,
                recorder=recorder,
                started_at=started_at,
                exc=GatewayControlError(
                    GatewayReason.IDEMPOTENCY_CONFLICT.value,
                    "reconciliation request does not match the ledger intent",
                ),
                policy=authorization.policy,
                trusted_context=authorization.context,
            )
        if record.status is not LedgerStatus.UNKNOWN:
            try:
                result = self._result_from_record(record)
            except Exception as exc:
                return await self._reject(
                    invocation=invocation,
                    execution_id=execution_id,
                    recorder=recorder,
                    started_at=started_at,
                    exc=exc,
                    policy=authorization.policy,
                    trusted_context=authorization.context,
                )
            return await self._finish(
                recorder=recorder,
                execution_id=execution_id,
                result=result,
                reason_code=GatewayReason.LEDGER_REPLAY.value,
            )
        await recorder.record(
            LifecycleStage.RECONCILIATION,
            LifecycleOutcome.STARTED,
            GatewayReason.RECONCILIATION_PENDING.value,
        )
        try:
            capability = await self._issue_capability(
                invocation=invocation,
                authorization=authorization,
            )
            reconciled = await authorization.definition.adapter.reconcile(
                arguments=invocation.request.planned_action.arguments,
                capability=capability,
                idempotency_key=invocation.request.idempotency_key,
            )
            return await self._apply_reconciliation(
                invocation=invocation,
                execution_id=execution_id,
                recorder=recorder,
                started_at=started_at,
                authorization=authorization,
                record=record,
                reconciled=reconciled,
            )
        except Exception:
            await recorder.record(
                LifecycleStage.RECONCILIATION,
                LifecycleOutcome.UNKNOWN,
                GatewayReason.RECONCILIATION_UNAVAILABLE.value,
            )
            return await self._finish(
                recorder=recorder,
                execution_id=execution_id,
                result=self._result_from_record(record),
                reason_code=GatewayReason.RECONCILIATION_UNAVAILABLE.value,
            )

    async def _authorize(
        self,
        invocation: GatewayInvocation,
        recorder: LifecycleRecorder,
    ) -> _Authorization:
        request = invocation.request
        now = self._deps.clock()
        try:
            trusted = await self._deps.security_contexts.resolve(
                request.security_context.context_ref
            )
        except SecurityError:
            raise
        except Exception as exc:
            raise SecurityError(
                SecurityErrorCode.CONTEXT_UNAVAILABLE,
                "trusted security context source is unavailable",
            ) from exc
        try:
            context = self._deps.security.verify_context(
                presented=request.security_context,
                trusted=trusted,
                now=now,
            )
            action = request.planned_action
            self._deps.security.verify_action_context(
                context=context, action=action
            )
            await recorder.record(
                LifecycleStage.IDENTITY,
                LifecycleOutcome.PASSED,
                GatewayReason.IDENTITY_VERIFIED.value,
            )
            definition = self._deps.registry.authorize(
                request=request,
                context=context,
                workload=invocation.workload,
            )
            self._deps.security.verify_workload(
                declared=request.agent_principal,
                action=action,
                workload=invocation.workload,
                expected_audience=definition.audience,
                now=now,
            )
            await recorder.record(
                LifecycleStage.REGISTRY,
                LifecycleOutcome.PASSED,
                GatewayReason.TOOL_ALLOWED.value,
                evidence_refs=(f"schema:{definition.contract.schema_hash}",),
            )
        except Exception as exc:
            raise _AuthorizationRejected(
                trusted.context, None, exc
            ) from exc
        try:
            record = await self._deps.policies.resolve(
                request.policy_decision_id
            )
        except PolicyError as exc:
            raise _AuthorizationRejected(context, None, exc) from exc
        except Exception as exc:
            failure = PolicyError(
                code=PolicyErrorCode.UNAVAILABLE,
                safe_message="trusted policy source is unavailable",
            )
            raise _AuthorizationRejected(
                context, None, failure
            ) from exc
        try:
            record.assert_integrity()
        except Exception as exc:
            raise _AuthorizationRejected(context, None, exc) from exc
        decision = record.decision
        try:
            if decision.decision_id != request.policy_decision_id:
                raise PolicyError(
                    code=PolicyErrorCode.BINDING_MISMATCH,
                    safe_message=(
                        "resolved policy identity does not match the request"
                    ),
                )
            enforced = self._deps.policy.enforce(
                decision=decision,
                context=context,
                agent=request.agent_principal,
                action=action,
                now=now,
                upstream_provider=definition.upstream_provider,
            )
            await recorder.record(
                LifecycleStage.POLICY,
                LifecycleOutcome.PASSED,
                GatewayReason.POLICY_ALLOWED.value,
                evidence_refs=(f"policy:{decision.decision_id}",),
            )
            approval: Approval | None = None
            if decision.decision is PolicyDecisionKind.REQUIRE_APPROVAL:
                if request.approval_id is None:
                    raise PolicyError(
                        code=PolicyErrorCode.APPROVAL_REQUIRED,
                        safe_message="policy requires an approval",
                    )
                try:
                    approval = await self._deps.approvals.resolve(
                        request.approval_id
                    )
                except PolicyError:
                    raise
                except Exception as exc:
                    raise GatewayControlError(
                        GatewayReason.APPROVAL_UNAVAILABLE.value,
                        "trusted approval source is unavailable",
                    ) from exc
                await self._deps.approval.verify(
                    approval=approval,
                    policy=decision,
                    action=action,
                    context=context,
                    approvers=self._deps.approvers,
                    now=now,
                )
                await recorder.record(
                    LifecycleStage.APPROVAL,
                    LifecycleOutcome.PASSED,
                    GatewayReason.APPROVAL_BOUND.value,
                    evidence_refs=(f"approval:{approval.approval_id}",),
                )
            else:
                if request.approval_id is not None:
                    raise PolicyError(
                        code=PolicyErrorCode.APPROVAL_INVALID,
                        safe_message=(
                            "approval cannot be attached to this policy decision"
                        ),
                    )
                await recorder.record(
                    LifecycleStage.APPROVAL,
                    LifecycleOutcome.SKIPPED,
                    GatewayReason.APPROVAL_NOT_REQUIRED.value,
                )
        except Exception as exc:
            raise _AuthorizationRejected(context, decision, exc) from exc
        return _Authorization(
            context=context,
            subject_acl=trusted.roles
            | frozenset({f"subject:{context.subject_id}"}),
            definition=definition,
            policy=decision,
            enforced_policy=enforced,
            approval=approval,
        )

    async def _execute_read(
        self,
        *,
        invocation: GatewayInvocation,
        execution_id: str,
        recorder: LifecycleRecorder,
        started_at: datetime,
        authorization: _Authorization,
    ) -> GatewayExecution:
        try:
            capability = await self._issue_capability(
                invocation=invocation,
                authorization=authorization,
            )
            await recorder.record(
                LifecycleStage.UPSTREAM,
                LifecycleOutcome.STARTED,
                GatewayReason.UPSTREAM_STARTED.value,
            )
            try:
                response = await authorization.definition.adapter.invoke(
                    arguments=invocation.request.planned_action.arguments,
                    capability=capability,
                    idempotency_key=invocation.request.idempotency_key,
                )
            except GatewayAdapterError as exc:
                if exc.safe_code == "KNOWLEDGE_ACCESS_DENIED":
                    code = GatewayReason.KNOWLEDGE_ACCESS_DENIED
                elif exc.safe_code == "KNOWLEDGE_QUERY_REJECTED":
                    code = GatewayReason.KNOWLEDGE_QUERY_REJECTED
                elif exc.disposition is GatewayAdapterDisposition.REJECTED:
                    code = GatewayReason.UPSTREAM_REJECTED
                elif exc.disposition is GatewayAdapterDisposition.NOT_SENT:
                    code = GatewayReason.UPSTREAM_NOT_SENT
                else:
                    code = GatewayReason.UPSTREAM_UNAVAILABLE
                raise GatewayControlError(
                    code.value,
                    "read tool invocation was rejected",
                ) from exc
            except Exception as exc:
                raise GatewayControlError(
                    GatewayReason.UPSTREAM_UNAVAILABLE.value,
                    "read tool upstream is unavailable",
                ) from exc
            authorization.definition.contract.validate_output(response.data)
            assert_safe_projection(response.data, field="tool_output")
            data, redactions = authorization.enforced_policy.apply_output(
                response.data
            )
            await recorder.record(
                LifecycleStage.UPSTREAM,
                LifecycleOutcome.PASSED,
                GatewayReason.UPSTREAM_SUCCEEDED.value,
            )
            result = ToolResult(
                execution_id=execution_id,
                request_id=invocation.request.request_id,
                operation=ToolOperation.READ,
                status=ToolResultStatus.VERIFIED,
                data=data,
                display_summary="Read tool result validated by the Gateway.",
                evidence_ref=None,
                output_classification=(
                    invocation.request.planned_action.data_classification.value
                ),
                policy_decision_id=authorization.policy.decision_id,
                redaction_summary=redactions,
                retryable=False,
                retry_basis=None,
                error_code=None,
                verification=Verification(
                    method=VerificationMethod.NOT_APPLICABLE,
                    matched=True,
                    observed_ref=None,
                ),
                reconciliation=None,
                started_at=started_at,
                finished_at=self._deps.clock(),
            )
            audit = build_audit_draft(
                invocation=invocation,
                execution_id=execution_id,
                now=self._deps.clock(),
                reason_codes=(GatewayReason.RESULT_VERIFIED.value,),
                result="success",
                event_type="audit.tool.verified.v1",
                policy=authorization.policy,
                approval=authorization.approval,
                trusted_context=authorization.context,
            )
            await self._deps.signals.append_audit(audit)
            await recorder.record(
                LifecycleStage.AUDIT,
                LifecycleOutcome.PASSED,
                GatewayReason.SIGNAL_RETAINED.value,
                evidence_refs=(f"audit:{audit.event_id}",),
            )
            return await self._finish(
                recorder=recorder,
                execution_id=execution_id,
                result=result,
                reason_code=GatewayReason.RESULT_VERIFIED.value,
            )
        except Exception as exc:
            return await self._reject(
                invocation=invocation,
                execution_id=execution_id,
                recorder=recorder,
                started_at=started_at,
                exc=exc,
                policy=authorization.policy,
                trusted_context=authorization.context,
            )

    async def _execute_write(
        self,
        *,
        invocation: GatewayInvocation,
        execution_id: str,
        recorder: LifecycleRecorder,
        started_at: datetime,
        authorization: _Authorization,
    ) -> GatewayExecution:
        intent = self._execution_intent(
            invocation=invocation,
            execution_id=execution_id,
            authorization=authorization,
            created_at=started_at,
        )
        try:
            record = await self._prepare(intent)
        except Exception as exc:
            return await self._reject(
                invocation=invocation,
                execution_id=execution_id,
                recorder=recorder,
                started_at=started_at,
                exc=exc,
                policy=authorization.policy,
                trusted_context=authorization.context,
            )
        if record.status is not LedgerStatus.PREPARED:
            await recorder.record(
                LifecycleStage.LEDGER,
                LifecycleOutcome.REPLAYED,
                GatewayReason.LEDGER_REPLAY.value,
            )
            if record.status in {
                LedgerStatus.VERIFIED,
                LedgerStatus.FAILED_FINAL,
                LedgerStatus.UNKNOWN,
            }:
                result = self._result_from_record(record)
                return await self._finish(
                    recorder=recorder,
                    execution_id=execution_id,
                    result=result,
                    reason_code=GatewayReason.LEDGER_REPLAY.value,
                )
            if record.status in {LedgerStatus.RUNNING, LedgerStatus.SUCCEEDED}:
                unknown = self._unknown_outcome(
                    recorded_at=self._deps.clock(),
                    error_code=GatewayReason.UPSTREAM_OUTCOME_UNKNOWN.value,
                )
                audit = self._terminal_audit(
                    invocation=invocation,
                    execution_id=execution_id,
                    outcome=unknown,
                    authorization=authorization,
                )
                try:
                    record = await self._record_outcome_with_audit(
                        intent=intent,
                        outcome=unknown,
                        audit=audit,
                    )
                    await self._best_effort_audit(audit)
                except Exception:
                    result = self._tool_result_from_outcome(intent, unknown)
                    return await self._finish(
                        recorder=recorder,
                        execution_id=execution_id,
                        result=result,
                        reason_code=GatewayReason.RESULT_UNKNOWN.value,
                    )
                result = self._result_from_record(record)
                return await self._finish(
                    recorder=recorder,
                    execution_id=execution_id,
                    result=result,
                    reason_code=GatewayReason.RESULT_UNKNOWN.value,
                )
            if record.status is not LedgerStatus.FAILED_RETRYABLE:
                raise GatewayControlError(
                    GatewayReason.RECONCILIATION_REQUIRED.value,
                    "ledger state cannot be executed or replayed",
                )
        await recorder.record(
            LifecycleStage.LEDGER,
            LifecycleOutcome.PASSED,
            GatewayReason.LEDGER_PREPARED.value,
            evidence_refs=(f"ledger:{execution_id}",),
        )
        try:
            await self._mark_running(
                intent.tenant_id, execution_id, now=self._deps.clock()
            )
        except Exception as exc:
            outcome = ExecutionOutcome(
                status=LedgerStatus.FAILED_RETRYABLE,
                recorded_at=self._deps.clock(),
                retryable=True,
                error_code=self._exception_code(exc),
                retry_basis=LedgerRetryBasis.NOT_SENT,
            )
            audit = self._terminal_audit(
                invocation=invocation,
                execution_id=execution_id,
                outcome=outcome,
                authorization=authorization,
            )
            retained = await self._best_effort_audit(audit)
            await recorder.record(
                LifecycleStage.AUDIT,
                (
                    LifecycleOutcome.PASSED
                    if retained
                    else LifecycleOutcome.FAILED
                ),
                (
                    GatewayReason.SIGNAL_RETAINED.value
                    if retained
                    else GatewayReason.SIGNAL_UNAVAILABLE.value
                ),
                evidence_refs=(
                    (f"audit:{audit.event_id}",) if retained else ()
                ),
            )
            result = self._tool_result_from_outcome(intent, outcome)
            return await self._finish(
                recorder=recorder,
                execution_id=execution_id,
                result=result,
                reason_code=GatewayReason.LEDGER_UNAVAILABLE.value,
            )
        try:
            capability = await self._issue_capability(
                invocation=invocation,
                authorization=authorization,
            )
        except Exception as exc:
            outcome = ExecutionOutcome(
                status=LedgerStatus.FAILED_RETRYABLE,
                recorded_at=self._deps.clock(),
                retryable=True,
                error_code=self._exception_code(exc),
                retry_basis=LedgerRetryBasis.NOT_SENT,
            )
            return await self._complete_write(
                invocation=invocation,
                intent=intent,
                authorization=authorization,
                recorder=recorder,
                outcome=outcome,
                reason_code=GatewayReason.UPSTREAM_NOT_SENT.value,
            )
        await recorder.record(
            LifecycleStage.UPSTREAM,
            LifecycleOutcome.STARTED,
            GatewayReason.UPSTREAM_STARTED.value,
        )
        try:
            response = await authorization.definition.adapter.invoke(
                arguments=invocation.request.planned_action.arguments,
                capability=capability,
                idempotency_key=invocation.request.idempotency_key,
            )
        except GatewayAdapterError as exc:
            if exc.disposition is GatewayAdapterDisposition.NOT_SENT:
                adapter_code = GatewayReason.UPSTREAM_NOT_SENT.value
                outcome = ExecutionOutcome(
                    status=LedgerStatus.FAILED_RETRYABLE,
                    recorded_at=self._deps.clock(),
                    retryable=True,
                    error_code=adapter_code,
                    retry_basis=LedgerRetryBasis.NOT_SENT,
                )
                reason = adapter_code
            elif exc.disposition is GatewayAdapterDisposition.REJECTED:
                adapter_code = GatewayReason.UPSTREAM_REJECTED.value
                outcome = ExecutionOutcome(
                    status=LedgerStatus.FAILED_FINAL,
                    recorded_at=self._deps.clock(),
                    retryable=False,
                    error_code=adapter_code,
                )
                reason = adapter_code
            else:
                adapter_code = GatewayReason.UPSTREAM_OUTCOME_UNKNOWN.value
                outcome = self._unknown_outcome(
                    recorded_at=self._deps.clock(),
                    error_code=adapter_code,
                )
                reason = adapter_code
            return await self._complete_write(
                invocation=invocation,
                intent=intent,
                authorization=authorization,
                recorder=recorder,
                outcome=outcome,
                reason_code=reason,
            )
        except Exception:
            return await self._complete_write(
                invocation=invocation,
                intent=intent,
                authorization=authorization,
                recorder=recorder,
                outcome=self._unknown_outcome(
                    recorded_at=self._deps.clock(),
                    error_code=GatewayReason.UPSTREAM_OUTCOME_UNKNOWN.value,
                ),
                reason_code=GatewayReason.UPSTREAM_OUTCOME_UNKNOWN.value,
            )
        await recorder.record(
            LifecycleStage.UPSTREAM,
            LifecycleOutcome.PASSED,
            GatewayReason.UPSTREAM_SUCCEEDED.value,
        )
        try:
            await recorder.record(
                LifecycleStage.READBACK,
                LifecycleOutcome.STARTED,
                GatewayReason.UPSTREAM_SUCCEEDED.value,
            )
            readback = await authorization.definition.adapter.readback(
                arguments=invocation.request.planned_action.arguments,
                invocation=response,
                capability=capability,
                idempotency_key=invocation.request.idempotency_key,
            )
            if not readback.matched:
                raise GatewayControlError(
                    GatewayReason.READBACK_MISMATCH.value,
                    "authoritative readback did not match the write",
                )
            authorization.definition.contract.validate_output(readback.data)
            assert_safe_projection(readback.data, field="tool_output")
            data, _ = authorization.enforced_policy.apply_output(readback.data)
            await recorder.record(
                LifecycleStage.READBACK,
                LifecycleOutcome.VERIFIED,
                GatewayReason.READBACK_VERIFIED.value,
                evidence_refs=(readback.evidence_ref, readback.observed_ref),
            )
            outcome = ExecutionOutcome(
                status=LedgerStatus.VERIFIED,
                recorded_at=self._deps.clock(),
                retryable=False,
                data=data,
                evidence_ref=readback.evidence_ref,
                verification={
                    "method": readback.method,
                    "matched": True,
                    "observed_ref": readback.observed_ref,
                },
            )
            return await self._complete_write(
                invocation=invocation,
                intent=intent,
                authorization=authorization,
                recorder=recorder,
                outcome=outcome,
                reason_code=GatewayReason.RESULT_VERIFIED.value,
            )
        except Exception:
            return await self._complete_write(
                invocation=invocation,
                intent=intent,
                authorization=authorization,
                recorder=recorder,
                outcome=self._unknown_outcome(
                    recorded_at=self._deps.clock(),
                    error_code=GatewayReason.READBACK_MISMATCH.value,
                ),
                reason_code=GatewayReason.RESULT_UNKNOWN.value,
            )

    async def _apply_reconciliation(
        self,
        *,
        invocation: GatewayInvocation,
        execution_id: str,
        recorder: LifecycleRecorder,
        started_at: datetime,
        authorization: _Authorization,
        record: ExecutionRecord,
        reconciled: ReconciliationResult,
    ) -> GatewayExecution:
        del started_at
        if reconciled.disposition is ReconciliationDisposition.UNKNOWN:
            await recorder.record(
                LifecycleStage.RECONCILIATION,
                LifecycleOutcome.UNKNOWN,
                GatewayReason.RECONCILIATION_PENDING.value,
            )
            return await self._finish(
                recorder=recorder,
                execution_id=execution_id,
                result=self._result_from_record(record),
                reason_code=GatewayReason.RECONCILIATION_PENDING.value,
            )
        if (
            reconciled.evidence_ref is None
            or reconciled.observed_ref is None
        ):
            raise GatewayControlError(
                GatewayReason.RECONCILIATION_UNAVAILABLE.value,
                "authoritative reconciliation evidence is incomplete",
            )
        if (
            reconciled.disposition
            is ReconciliationDisposition.CONFIRMED_NOT_EXECUTED
        ):
            outcome = ExecutionOutcome(
                status=LedgerStatus.FAILED_RETRYABLE,
                recorded_at=self._deps.clock(),
                retryable=True,
                error_code=GatewayReason.CONFIRMED_NOT_EXECUTED.value,
                retry_basis=LedgerRetryBasis.CONFIRMED_NOT_EXECUTED,
                verification={
                    "method": reconciled.method,
                    "matched": False,
                    "observed_ref": reconciled.observed_ref,
                },
                evidence_ref=reconciled.evidence_ref,
            )
            reason = GatewayReason.CONFIRMED_NOT_EXECUTED.value
        else:
            if reconciled.data is None:
                raise GatewayControlError(
                    GatewayReason.RECONCILIATION_UNAVAILABLE.value,
                    "verified reconciliation lacks result data",
                )
            authorization.definition.contract.validate_output(reconciled.data)
            assert_safe_projection(reconciled.data, field="tool_output")
            data, _ = authorization.enforced_policy.apply_output(reconciled.data)
            outcome = ExecutionOutcome(
                status=LedgerStatus.VERIFIED,
                recorded_at=self._deps.clock(),
                retryable=False,
                data=data,
                evidence_ref=reconciled.evidence_ref,
                verification={
                    "method": reconciled.method,
                    "matched": True,
                    "observed_ref": reconciled.observed_ref,
                },
            )
            reason = GatewayReason.RECONCILIATION_VERIFIED.value
        intent = record.intent
        return await self._complete_write(
            invocation=invocation,
            intent=intent,
            authorization=authorization,
            recorder=recorder,
            outcome=outcome,
            reason_code=reason,
        )

    async def _complete_write(
        self,
        *,
        invocation: GatewayInvocation,
        intent: ExecutionIntent,
        authorization: _Authorization,
        recorder: LifecycleRecorder,
        outcome: ExecutionOutcome,
        reason_code: str,
    ) -> GatewayExecution:
        audit = self._terminal_audit(
            invocation=invocation,
            execution_id=intent.tool_execution_id,
            outcome=outcome,
            authorization=authorization,
        )
        try:
            record = await self._record_outcome_with_audit(
                intent=intent,
                outcome=outcome,
                audit=audit,
            )
        except Exception:
            if outcome.status not in {
                LedgerStatus.FAILED_RETRYABLE,
                LedgerStatus.FAILED_FINAL,
            }:
                fallback = self._unknown_outcome(
                    recorded_at=self._deps.clock(),
                    error_code=GatewayReason.LEDGER_UNAVAILABLE.value,
                )
                try:
                    fallback_audit = self._terminal_audit(
                        invocation=invocation,
                        execution_id=intent.tool_execution_id,
                        outcome=fallback,
                        authorization=authorization,
                    )
                    record = await self._record_outcome_with_audit(
                        intent=intent,
                        outcome=fallback,
                        audit=fallback_audit,
                    )
                    await self._best_effort_audit(fallback_audit)
                    result = self._result_from_record(record)
                    return await self._finish(
                        recorder=recorder,
                        execution_id=intent.tool_execution_id,
                        result=result,
                        reason_code=GatewayReason.RESULT_UNKNOWN.value,
                    )
                except Exception:
                    await self._best_effort_audit(fallback_audit)
                    result = self._tool_result_from_outcome(intent, fallback)
                    return await self._finish(
                        recorder=recorder,
                        execution_id=intent.tool_execution_id,
                        result=result,
                        reason_code=GatewayReason.RESULT_UNKNOWN.value,
                    )
            await self._best_effort_audit(audit)
            result = self._tool_result_from_outcome(intent, outcome)
            return await self._finish(
                recorder=recorder,
                execution_id=intent.tool_execution_id,
                result=result,
                reason_code=GatewayReason.LEDGER_UNAVAILABLE.value,
            )
        await self._best_effort_audit(audit)
        await recorder.record(
            LifecycleStage.AUDIT,
            LifecycleOutcome.PASSED,
            GatewayReason.SIGNAL_RETAINED.value,
            evidence_refs=(f"audit:{audit.event_id}",),
        )
        result = self._result_from_record(record)
        lifecycle_outcome = (
            LifecycleOutcome.VERIFIED
            if outcome.status is LedgerStatus.VERIFIED
            else (
                LifecycleOutcome.UNKNOWN
                if outcome.status is LedgerStatus.UNKNOWN
                else LifecycleOutcome.FAILED
            )
        )
        await recorder.record(
            LifecycleStage.RESULT,
            lifecycle_outcome,
            reason_code,
        )
        return await self._finish(
            recorder=recorder,
            execution_id=intent.tool_execution_id,
            result=result,
            reason_code=reason_code,
            record_result_stage=False,
        )

    async def _reject(
        self,
        *,
        invocation: GatewayInvocation,
        execution_id: str,
        recorder: LifecycleRecorder,
        started_at: datetime,
        exc: Exception,
        policy: PolicyDecision | None,
        trusted_context: SecurityContextRef | None,
    ) -> GatewayExecution:
        code = self._exception_code(exc)
        result = ToolResult(
            execution_id=execution_id,
            request_id=invocation.request.request_id,
            operation=invocation.request.planned_action.tool.operation,
            status=ToolResultStatus.FAILED_FINAL,
            data=None,
            display_summary="Gateway rejected the tool request.",
            evidence_ref=None,
            output_classification=(
                invocation.request.planned_action.data_classification.value
            ),
            policy_decision_id=invocation.request.policy_decision_id,
            redaction_summary={},
            retryable=False,
            retry_basis=None,
            error_code=code,
            verification=None,
            reconciliation=None,
            started_at=started_at,
            finished_at=self._deps.clock(),
        )
        await recorder.record(
            LifecycleStage.RESULT,
            LifecycleOutcome.REJECTED,
            code,
        )
        if (
            code != GatewayReason.SIGNAL_UNAVAILABLE.value
            and self._requires_security_event(code)
        ):
            event_type, category = self._security_event(code)
            audit, security = build_blocked_pair(
                invocation=invocation,
                execution_id=execution_id,
                now=self._deps.clock(),
                reason_code=code,
                event_type=event_type,
                category=category,
                policy=policy,
                trusted_context=trusted_context,
            )
            try:
                await self._deps.signals.append_blocked_pair(audit, security)
                await recorder.record(
                    LifecycleStage.SECURITY,
                    LifecycleOutcome.PASSED,
                    GatewayReason.SIGNAL_RETAINED.value,
                    evidence_refs=(
                        f"audit:{audit.event_id}",
                        f"security:{security.event_id}",
                    ),
                )
            except Exception:
                await recorder.record(
                    LifecycleStage.SECURITY,
                    LifecycleOutcome.FAILED,
                    GatewayReason.SIGNAL_UNAVAILABLE.value,
                )
        elif code != GatewayReason.SIGNAL_UNAVAILABLE.value:
            audit = build_audit_draft(
                invocation=invocation,
                execution_id=execution_id,
                now=self._deps.clock(),
                reason_codes=(code,),
                result="failure",
                event_type="audit.tool.failed.v1",
                policy=policy,
                approval=None,
                trusted_context=trusted_context,
            )
            try:
                await self._deps.signals.append_audit(audit)
                await recorder.record(
                    LifecycleStage.AUDIT,
                    LifecycleOutcome.PASSED,
                    GatewayReason.SIGNAL_RETAINED.value,
                    evidence_refs=(f"audit:{audit.event_id}",),
                )
            except Exception:
                await recorder.record(
                    LifecycleStage.AUDIT,
                    LifecycleOutcome.FAILED,
                    GatewayReason.SIGNAL_UNAVAILABLE.value,
                )
        return await self._finish(
            recorder=recorder,
            execution_id=execution_id,
            result=result,
            reason_code=code,
            record_result_stage=False,
        )

    async def _finish(
        self,
        *,
        recorder: LifecycleRecorder,
        execution_id: str,
        result: ToolResult,
        reason_code: str,
        record_result_stage: bool = True,
    ) -> GatewayExecution:
        if record_result_stage:
            outcome = (
                LifecycleOutcome.VERIFIED
                if result.status is ToolResultStatus.VERIFIED
                else (
                    LifecycleOutcome.UNKNOWN
                    if result.status is ToolResultStatus.UNKNOWN
                    else LifecycleOutcome.FAILED
                )
            )
            await recorder.record(
                LifecycleStage.RESULT,
                outcome,
                reason_code,
            )
        projection = recorder.debug_projection(
            execution_id=execution_id,
            result_status=result.status.value,
            reason_code=reason_code,
        )
        return GatewayExecution(
            result=result,
            lifecycle=recorder.events,
            debug_projection=projection,
            stage_metrics=recorder.metrics(),
        )

    async def _issue_capability(
        self,
        *,
        invocation: GatewayInvocation,
        authorization: _Authorization,
    ) -> CapabilityHandle:
        now = self._deps.clock()
        authorization_limit = min(
            authorization.context.expires_at,
            authorization.policy.expires_at,
            invocation.workload.expires_at,
        )
        remaining_seconds = int(
            (authorization_limit - now).total_seconds()
        )
        if remaining_seconds < 1:
            raise SecurityError(
                SecurityErrorCode.CREDENTIAL_UNAVAILABLE,
                "authorized capability lifetime is exhausted",
            )
        ttl_seconds = min(
            authorization.enforced_policy.credential_ttl_seconds,
            remaining_seconds,
        )
        try:
            handle = await self._deps.credentials.issue(
                tenant_id=authorization.context.tenant_id,
                audience=authorization.definition.audience,
                scopes=authorization.definition.credential_scopes,
                subject_id=authorization.context.subject_id,
                subject_acl=authorization.subject_acl,
                workload_principal_ref=invocation.workload.principal_ref,
                purpose=authorization.context.purpose,
                data_classification_ceiling=(
                    invocation.request.planned_action.data_classification.value
                ),
                action_digest=invocation.request.action_digest,
                ttl_seconds=ttl_seconds,
                now=now,
            )
        except SecurityError:
            raise
        except Exception as exc:
            raise SecurityError(
                SecurityErrorCode.CREDENTIAL_UNAVAILABLE,
                "capability credential broker is unavailable",
            ) from exc
        if (
            handle.tenant_id != authorization.context.tenant_id
            or handle.audience != authorization.definition.audience
            or handle.scopes != authorization.definition.credential_scopes
            or handle.subject_id != authorization.context.subject_id
            or handle.subject_acl != authorization.subject_acl
            or (
                handle.workload_principal_ref
                != invocation.workload.principal_ref
            )
            or handle.purpose != authorization.context.purpose
            or (
                handle.data_classification_ceiling
                != invocation.request.planned_action.data_classification.value
            )
            or handle.action_digest != invocation.request.action_digest
            or now < handle.issued_at
            or now >= handle.expires_at
            or handle.expires_at > authorization_limit
            or handle.expires_at > now + timedelta(seconds=ttl_seconds)
        ):
            raise SecurityError(
                SecurityErrorCode.CREDENTIAL_UNAVAILABLE,
                "capability handle does not match the authorized action",
            )
        return handle

    def _execution_intent(
        self,
        *,
        invocation: GatewayInvocation,
        execution_id: str,
        authorization: _Authorization,
        created_at: datetime,
    ) -> ExecutionIntent:
        request = invocation.request
        approval = authorization.approval
        return ExecutionIntent(
            tool_execution_id=execution_id,
            request_id=request.request_id,
            tenant_id=authorization.context.tenant_id,
            task_id=request.planned_action.task_id,
            tool_name=request.planned_action.tool.name,
            idempotency_key=request.idempotency_key,
            action_id=request.planned_action.action_id,
            action_digest=request.action_digest,
            planned_action=request.planned_action.to_mapping(),
            planned_action_expires_at=request.planned_action.expires_at,
            policy_decision_id=authorization.policy.decision_id,
            policy_version=authorization.policy.policy_version,
            policy_decision=authorization.policy.to_mapping(),
            policy_expires_at=authorization.policy.expires_at,
            tool_schema_hash=request.planned_action.tool.schema_hash,
            approval_id=approval.approval_id if approval is not None else None,
            approval=approval.to_mapping() if approval is not None else None,
            approval_expires_at=(
                approval.expires_at if approval is not None else None
            ),
            created_at=created_at,
        )

    async def _prepare(self, intent: ExecutionIntent) -> ExecutionRecord:
        try:
            async with self._deps.data_uow() as uow:
                record = await uow.ledger.prepare(intent)
                await uow.commit()
                return record
        except PersistenceError:
            raise
        except Exception as exc:
            raise GatewayControlError(
                GatewayReason.LEDGER_UNAVAILABLE.value,
                "execution ledger is unavailable",
            ) from exc

    async def _get_record(
        self, tenant_id: str, execution_id: str
    ) -> ExecutionRecord | None:
        try:
            async with self._deps.data_uow() as uow:
                return await uow.ledger.get(tenant_id, execution_id)
        except PersistenceError:
            raise
        except Exception as exc:
            raise GatewayControlError(
                GatewayReason.LEDGER_UNAVAILABLE.value,
                "execution ledger is unavailable",
            ) from exc

    async def _mark_running(
        self, tenant_id: str, execution_id: str, *, now: datetime
    ) -> ExecutionRecord:
        try:
            async with self._deps.data_uow() as uow:
                record = await uow.ledger.mark_running(
                    tenant_id, execution_id, now=now
                )
                await uow.commit()
                return record
        except PersistenceError:
            raise
        except Exception as exc:
            raise GatewayControlError(
                GatewayReason.LEDGER_UNAVAILABLE.value,
                "execution ledger is unavailable",
            ) from exc

    async def _record_outcome_with_audit(
        self,
        *,
        intent: ExecutionIntent,
        outcome: ExecutionOutcome,
        audit: AuditDraft,
    ) -> ExecutionRecord:
        payload = audit.to_mapping()
        outbox = OutboxEvent(
            event_id=audit.event_id,
            tenant_id=intent.tenant_id,
            aggregate_type="audit_draft",
            aggregate_id=audit.event_id,
            sequence=1,
            event_type=audit.event_type,
            payload=payload,
            occurred_at=outcome.recorded_at,
            available_at=outcome.recorded_at,
        )
        async with self._deps.data_uow() as uow:
            record = await uow.ledger.record_outcome(
                intent.tenant_id,
                intent.tool_execution_id,
                outcome,
            )
            await uow.outbox.append(outbox)
            await uow.commit()
            return record

    async def _best_effort_audit(self, audit: AuditDraft) -> bool:
        try:
            await self._deps.signals.append_audit(audit)
        except Exception:
            # The transactionally stored outbox draft remains authoritative.
            return False
        return True

    def _terminal_audit(
        self,
        *,
        invocation: GatewayInvocation,
        execution_id: str,
        outcome: ExecutionOutcome,
        authorization: _Authorization,
    ) -> AuditDraft:
        if outcome.status is LedgerStatus.VERIFIED:
            result = "success"
            event_type = "audit.tool.verified.v1"
            reason = GatewayReason.RESULT_VERIFIED.value
        elif outcome.status is LedgerStatus.UNKNOWN:
            result = "unknown"
            event_type = "audit.tool.unknown.v1"
            reason = GatewayReason.RESULT_UNKNOWN.value
        else:
            result = "failure"
            event_type = "audit.tool.failed.v1"
            reason = outcome.error_code or GatewayReason.RESULT_FAILED.value
        return build_audit_draft(
            invocation=invocation,
            execution_id=execution_id,
            now=outcome.recorded_at,
            reason_codes=(reason,),
            result=result,
            event_type=event_type,
            policy=authorization.policy,
            approval=authorization.approval,
            trusted_context=authorization.context,
        )

    @staticmethod
    def _unknown_outcome(
        *, recorded_at: datetime, error_code: str
    ) -> ExecutionOutcome:
        return ExecutionOutcome(
            status=LedgerStatus.UNKNOWN,
            recorded_at=recorded_at,
            retryable=False,
            error_code=error_code,
            reconciliation={
                "state": "pending",
                "strategy": "upstream_idempotency_lookup",
                "next_action": "reconcile_only",
                "ref": None,
            },
        )

    def _result_from_record(self, record: ExecutionRecord) -> ToolResult:
        if record.outcome is None:
            raise GatewayControlError(
                GatewayReason.RECONCILIATION_REQUIRED.value,
                "ledger state does not have a public terminal result",
            )
        return self._tool_result_from_outcome(record.intent, record.outcome)

    @staticmethod
    def _tool_result_from_outcome(
        intent: ExecutionIntent, outcome: ExecutionOutcome
    ) -> ToolResult:
        status = ToolResultStatus(outcome.status.value)
        verification: Verification | None = None
        if outcome.verification is not None:
            method = VerificationMethod(str(outcome.verification["method"]))
            verification = Verification(
                method=method,
                matched=bool(outcome.verification["matched"]),
                observed_ref=(
                    str(outcome.verification["observed_ref"])
                    if outcome.verification.get("observed_ref") is not None
                    else None
                ),
            )
        reconciliation: Reconciliation | None = None
        if outcome.reconciliation is not None:
            reconciliation = Reconciliation(
                state=str(outcome.reconciliation["state"]),
                strategy=str(outcome.reconciliation["strategy"]),
                next_action=str(outcome.reconciliation["next_action"]),
                ref=(
                    str(outcome.reconciliation["ref"])
                    if outcome.reconciliation.get("ref") is not None
                    else None
                ),
            )
        retry_basis = (
            RetryBasis(outcome.retry_basis.value)
            if outcome.retry_basis is not None
            else None
        )
        output_classification = str(
            intent.planned_action["data_classification"]
        )
        return ToolResult(
            execution_id=intent.tool_execution_id,
            request_id=intent.request_id,
            operation=ToolOperation.WRITE,
            status=status,
            data=outcome.data,
            display_summary=(
                "Tool write verified by authoritative readback."
                if status is ToolResultStatus.VERIFIED
                else (
                    "Tool outcome is unknown; reconciliation is required."
                    if status is ToolResultStatus.UNKNOWN
                    else "Tool write was not completed."
                )
            ),
            evidence_ref=outcome.evidence_ref,
            output_classification=output_classification,
            policy_decision_id=intent.policy_decision_id,
            redaction_summary={},
            retryable=outcome.retryable,
            retry_basis=retry_basis,
            error_code=outcome.error_code,
            verification=verification,
            reconciliation=reconciliation,
            started_at=intent.created_at,
            finished_at=outcome.recorded_at,
        )

    @staticmethod
    def _exception_code(exc: Exception) -> str:
        if isinstance(exc, (SecurityError, PolicyError, GatewayControlError)):
            return exc.code.value if hasattr(exc.code, "value") else str(exc.code)
        if isinstance(exc, ToolContractError):
            return exc.code.value
        if isinstance(exc, PersistenceError):
            if exc.code is PersistenceErrorCode.IDEMPOTENCY_CONFLICT:
                return GatewayReason.IDEMPOTENCY_CONFLICT.value
            if exc.code is PersistenceErrorCode.RECONCILIATION_REQUIRED:
                return GatewayReason.RECONCILIATION_REQUIRED.value
            return GatewayReason.LEDGER_UNAVAILABLE.value
        if isinstance(exc, GatewayAdapterError):
            if exc.disposition is GatewayAdapterDisposition.NOT_SENT:
                return GatewayReason.UPSTREAM_NOT_SENT.value
            if exc.disposition is GatewayAdapterDisposition.REJECTED:
                return GatewayReason.UPSTREAM_REJECTED.value
            return GatewayReason.UPSTREAM_OUTCOME_UNKNOWN.value
        return GatewayReason.SIGNAL_UNAVAILABLE.value

    @staticmethod
    def _security_event(code: str) -> tuple[str, str]:
        if "TENANT" in code:
            return (
                "security.tenant_isolation.blocked.v1",
                "tenant_isolation",
            )
        if "SCHEMA" in code:
            return ("security.tool_schema.mismatch.v1", "tool_integrity")
        if "APPROVAL" in code or "DUTIES" in code:
            return ("security.approval.invalid.v1", "approval_integrity")
        if "IDEMPOTENCY" in code:
            return ("security.idempotency.conflict.v1", "idempotency")
        if "POLICY_UNAVAILABLE" in code:
            return ("security.policy.unavailable.v1", "authorization")
        if "UNSAFE" in code or "CREDENTIAL" in code:
            return ("security.secret.detected.v1", "credential_exposure")
        return ("security.authorization.denied.v1", "authorization")

    @staticmethod
    def _requires_security_event(code: str) -> bool:
        operational_codes = {
            GatewayReason.LEDGER_UNAVAILABLE.value,
            GatewayReason.RECONCILIATION_REQUIRED.value,
            GatewayReason.RECONCILIATION_UNAVAILABLE.value,
            GatewayReason.SIGNAL_UNAVAILABLE.value,
            GatewayReason.UPSTREAM_NOT_SENT.value,
            GatewayReason.UPSTREAM_OUTCOME_UNKNOWN.value,
            GatewayReason.UPSTREAM_REJECTED.value,
            GatewayReason.UPSTREAM_UNAVAILABLE.value,
        }
        return code not in operational_codes
