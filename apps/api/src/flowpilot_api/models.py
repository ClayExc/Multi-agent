from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Sha256 = Annotated[str, StringConstraints(pattern=r"^sha256:[a-f0-9]{64}$")]
CommandId = Annotated[str, StringConstraints(pattern=r"^cmd_[A-Za-z0-9_-]{8,128}$")]
TaskId = Annotated[str, StringConstraints(pattern=r"^task_[A-Za-z0-9_-]{8,128}$")]
DocumentId = Annotated[str, StringConstraints(pattern=r"^doc_[A-Za-z0-9_-]{8,128}$")]
ThreadId = Annotated[str, StringConstraints(pattern=r"^thread_[A-Za-z0-9_-]{8,128}$")]
RunId = Annotated[str, StringConstraints(pattern=r"^run_[A-Za-z0-9_-]{8,128}$")]
MessageId = Annotated[str, StringConstraints(pattern=r"^msg_[A-Za-z0-9_-]{8,128}$")]
ApprovalId = Annotated[str, StringConstraints(pattern=r"^apr_[A-Za-z0-9_-]{8,128}$")]
SecurityContextId = Annotated[
    str, StringConstraints(pattern=r"^secctx_[A-Za-z0-9_-]{8,128}$")
]
TenantId = Annotated[str, StringConstraints(min_length=1, max_length=128)]
SubjectId = Annotated[str, StringConstraints(min_length=1, max_length=256)]
Purpose = Annotated[str, StringConstraints(min_length=1, max_length=256)]
Reference = Annotated[str, StringConstraints(min_length=1, max_length=512)]
Bounded128 = Annotated[str, StringConstraints(min_length=1, max_length=128)]
Reason = Annotated[str, StringConstraints(max_length=2000)]
SafeVersion = Annotated[int, Field(ge=0, le=2**53 - 1, strict=True)]
AttachmentRefs = Annotated[
    list[Reference], Field(json_schema_extra={"uniqueItems": True})
]

type ActorType = Literal["user", "service", "administrator"]
type DataClassification = Literal["public", "internal", "confidential", "restricted"]
type TaskStatus = Literal[
    "RECEIVED",
    "RUNNABLE",
    "RUNNING",
    "WAITING_USER",
    "WAITING_APPROVAL",
    "VERIFYING",
    "COMPLETED",
    "CANCELLED",
    "ESCALATED",
    "FAILED",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AuthenticationBody(StrictModel):
    method: Literal["oidc", "workload_identity", "break_glass"]
    assurance_level: Literal["low", "substantial", "high"]
    session_id_hash: Sha256 | None = None


class SecurityContextBody(StrictModel):
    context_id: SecurityContextId
    context_ref: Reference
    context_hash: Sha256
    tenant_id: TenantId
    subject_id: SubjectId
    subject_type: ActorType
    purpose: Purpose
    authentication: AuthenticationBody
    delegation_id: Annotated[str, StringConstraints(max_length=256)] | None = None
    data_classification_ceiling: DataClassification
    issued_at: datetime
    expires_at: datetime


class CommandActorBody(StrictModel):
    type: ActorType
    id: SubjectId


class CreateTaskPayload(StrictModel):
    initial_message_id: MessageId
    initial_message_ref: Reference
    attachment_refs: AttachmentRefs = Field(default_factory=list)
    channel: Literal["web", "api", "service_desk"]
    purpose: Purpose


class SubmitMessagePayload(StrictModel):
    message_id: MessageId
    message_ref: Reference
    attachment_refs: AttachmentRefs = Field(default_factory=list)


class DecideApprovalPayload(StrictModel):
    approval_id: ApprovalId
    action_digest: Sha256
    decision: Literal["approve", "reject"]
    reason: Reason | None = None


class CancelTaskPayload(StrictModel):
    reason: Reason | None = None


class RetryTaskPayload(StrictModel):
    failed_run_id: RunId
    reason: Reason | None = None


class _CommandBase(StrictModel):
    command_id: CommandId
    tenant_id: TenantId
    task_id: TaskId
    actor: CommandActorBody
    security_context: SecurityContextBody
    idempotency_key: Sha256
    command_digest: Sha256
    correlation_id: Annotated[str, StringConstraints(max_length=128)] | None = None
    issued_at: datetime


class CreateTaskCommandBody(_CommandBase):
    command_type: Literal["task.create.v1"]
    expected_task_version: None
    payload: CreateTaskPayload


class SubmitMessageCommandBody(_CommandBase):
    command_type: Literal["task.message.submit.v1"]
    expected_task_version: SafeVersion
    payload: SubmitMessagePayload


class DecideApprovalCommandBody(_CommandBase):
    command_type: Literal["task.approval.decide.v1"]
    expected_task_version: SafeVersion
    payload: DecideApprovalPayload


class CancelTaskCommandBody(_CommandBase):
    command_type: Literal["task.cancel.request.v1"]
    expected_task_version: SafeVersion
    payload: CancelTaskPayload


class RetryTaskCommandBody(_CommandBase):
    command_type: Literal["task.retry.request.v1"]
    expected_task_version: SafeVersion
    payload: RetryTaskPayload


type TaskCommandBody = Annotated[
    CreateTaskCommandBody
    | SubmitMessageCommandBody
    | DecideApprovalCommandBody
    | CancelTaskCommandBody
    | RetryTaskCommandBody,
    Field(discriminator="command_type"),
]


class ExecutionReceiptBody(StrictModel):
    command_id: CommandId
    tenant_id: TenantId
    task_id: TaskId
    disposition: Literal["accepted", "duplicate"]
    execution_ref: Annotated[str, StringConstraints(min_length=1, max_length=512)]


class CommandAcceptanceBody(StrictModel):
    command_id: CommandId
    tenant_id: TenantId
    task_id: TaskId
    accepted_at: datetime
    replayed: bool
    execution_receipt: ExecutionReceiptBody


class ApprovalDecisionBody(StrictModel):
    approval_id: ApprovalId
    tenant_id: TenantId
    task_id: TaskId
    status: Literal["approved", "rejected", "revoked"]
    action_digest: Sha256
    decided_at: datetime


class ReleaseBody(StrictModel):
    graph_version: Bounded128
    domain_pack_version: Bounded128
    context_policy_version: Bounded128
    policy_version: Bounded128
    tool_schema_set: Bounded128


class WaitingOnBody(StrictModel):
    type: Literal["user_input", "approval"]
    request_id: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    expires_at: datetime | None


class TaskFailureBody(StrictModel):
    code: Bounded128
    retryable: bool
    detail_ref: Annotated[str, StringConstraints(max_length=512)] | None = None


class TaskBody(StrictModel):
    task_id: TaskId
    thread_id: ThreadId
    tenant_id: TenantId
    status: TaskStatus
    version: SafeVersion
    run_generation: SafeVersion
    active_run_id: RunId | None = None
    latest_checkpoint_id: Annotated[str, StringConstraints(max_length=256)] | None = (
        None
    )
    domain: Annotated[str, StringConstraints(max_length=128)] | None = None
    intent: Annotated[str, StringConstraints(max_length=128)] | None = None
    risk_level: Literal["low", "medium", "high", "critical"] | None = None
    purpose: Purpose
    data_classification: DataClassification
    security_context: SecurityContextBody
    release: ReleaseBody
    waiting_on: WaitingOnBody | None
    result_ref: Annotated[str, StringConstraints(max_length=512)] | None
    error: TaskFailureBody | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class HealthBody(StrictModel):
    status: Literal["ok"]
    service: Literal["flowpilot-api"]
    version: Literal["0.1.0"]
    configured: bool


class AuthSessionBody(StrictModel):
    status: Literal["active"]
    expires_at: datetime


class PolicyVersionBody(StrictModel):
    version: Bounded128
    bundle_digest: Sha256
    active: bool
    parent_version: Bounded128 | None
    published_at: datetime
    revoked_at: datetime | None
    rollback_of: Bounded128 | None


class GovernancePolicyDecisionBody(StrictModel):
    decision_id: Annotated[str, StringConstraints(pattern=r"^pd_[A-Za-z0-9_-]{8,128}$")]
    task_id: TaskId
    decision: Literal["allow", "deny", "require_approval"]
    policy_version: Bounded128
    reason_codes: list[Bounded128]
    obligation_names: list[Bounded128]
    action_digest: Sha256
    evaluated_at: datetime
    expires_at: datetime


class GovernanceAuditEventBody(StrictModel):
    event_id: Annotated[str, StringConstraints(pattern=r"^evt_[A-Za-z0-9_-]{8,128}$")]
    event_type: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    occurred_at: datetime
    trace_id: Bounded128
    thread_id: ThreadId
    task_id: TaskId
    run_id: RunId | None
    correlation_id: Bounded128
    causation_id: Bounded128 | None
    action: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    decision: Literal["allow", "deny", "require_approval", "not_applicable"]
    reason_codes: list[Bounded128]
    result: Literal["success", "failure", "blocked", "unknown"]
    data_classification: DataClassification
    stream_id: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    sequence: Annotated[int, Field(ge=1, strict=True)]
    event_hash: Sha256
    previous_hash: Sha256 | None
    policy_decision_id: (
        Annotated[str, StringConstraints(pattern=r"^pd_[A-Za-z0-9_-]{8,128}$")] | None
    )
    policy_version: Bounded128 | None
    approval_id: ApprovalId | None
    action_digest: Sha256 | None
    tool_execution_id: (
        Annotated[str, StringConstraints(pattern=r"^tex_[A-Za-z0-9_-]{8,128}$")] | None
    )
    security_event_id: (
        Annotated[str, StringConstraints(pattern=r"^sevt_[A-Za-z0-9_-]{8,128}$")] | None
    )


class GovernanceSecurityEventBody(StrictModel):
    event_id: Annotated[str, StringConstraints(pattern=r"^sevt_[A-Za-z0-9_-]{8,128}$")]
    event_type: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    occurred_at: datetime
    trace_id: Bounded128
    thread_id: ThreadId | None
    task_id: TaskId | None
    run_id: RunId | None
    correlation_id: Bounded128
    causation_id: Bounded128 | None
    control_component: Bounded128
    control_rule_id: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    control_rule_version: Bounded128
    reason_codes: list[Bounded128]
    severity: Literal["info", "low", "medium", "high", "critical"]
    category: Bounded128
    control_outcome: Literal["blocked", "allowed", "not_applicable", "unknown"]
    impact: Literal["none", "attempted", "suspected", "confirmed", "unknown"]
    disposition: Literal["open", "contained", "escalated", "resolved", "false_positive"]
    data_classification: DataClassification
    policy_decision_id: (
        Annotated[str, StringConstraints(pattern=r"^pd_[A-Za-z0-9_-]{8,128}$")] | None
    )
    audit_event_id: Annotated[
        str, StringConstraints(pattern=r"^evt_[A-Za-z0-9_-]{8,128}$")
    ]
    event_hash: Sha256


class PolicyVersionPageBody(StrictModel):
    items: list[PolicyVersionBody]
    next_cursor: (
        Annotated[str, StringConstraints(pattern=r"^gcur_[A-Za-z0-9_-]{24,508}$")]
        | None
    )


class GovernancePolicyDecisionPageBody(StrictModel):
    items: list[GovernancePolicyDecisionBody]
    next_cursor: (
        Annotated[str, StringConstraints(pattern=r"^gcur_[A-Za-z0-9_-]{24,508}$")]
        | None
    )


class GovernanceAuditEventPageBody(StrictModel):
    items: list[GovernanceAuditEventBody]
    next_cursor: (
        Annotated[str, StringConstraints(pattern=r"^gcur_[A-Za-z0-9_-]{24,508}$")]
        | None
    )


class GovernanceSecurityEventPageBody(StrictModel):
    items: list[GovernanceSecurityEventBody]
    next_cursor: (
        Annotated[str, StringConstraints(pattern=r"^gcur_[A-Za-z0-9_-]{24,508}$")]
        | None
    )


class GovernanceCorrelationBody(StrictModel):
    correlation_id: Bounded128
    policy_decisions: list[GovernancePolicyDecisionBody]
    audit_events: list[GovernanceAuditEventBody]
    security_events: list[GovernanceSecurityEventBody]


class KnowledgeVersionWriteBody(StrictModel):
    source_type: Literal["file", "uri", "connector", "manual"]
    source_ref: Annotated[str, StringConstraints(min_length=1, max_length=1024)]
    source_version: (
        Annotated[str, StringConstraints(min_length=1, max_length=256)] | None
    ) = None
    data_classification: DataClassification
    effective_at: datetime
    expires_at: datetime | None = None
    content: Annotated[
        str, StringConstraints(min_length=1, max_length=20 * 1024 * 1024)
    ]


class KnowledgeImportBody(KnowledgeVersionWriteBody):
    document_id: DocumentId


class KnowledgeUpdateBody(KnowledgeVersionWriteBody):
    expected_revision: SafeVersion


class KnowledgeLifecycleBody(StrictModel):
    expected_revision: SafeVersion


class KnowledgeRebuildBody(StrictModel):
    expected_revision: SafeVersion
    document_version: SafeVersion


class KnowledgeOperationReceiptBody(StrictModel):
    document_id: DocumentId
    operation: Literal["import", "update", "retire", "delete", "rebuild"]
    revision: SafeVersion
    document_version: SafeVersion
    disposition: Literal["applied", "duplicate"]
    event_id: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    index_job_id: Annotated[str, StringConstraints(min_length=1, max_length=256)]


class KnowledgeDocumentBody(StrictModel):
    document_id: DocumentId
    revision: SafeVersion
    current_version: SafeVersion
    lifecycle: Literal["active", "retired", "deleted"]
    document_version: SafeVersion
    source_type: Literal["file", "uri", "connector", "manual"]
    source_version: (
        Annotated[str, StringConstraints(min_length=1, max_length=256)] | None
    )
    source_digest: Sha256
    acl_digest: Sha256
    data_classification: DataClassification
    effective_at: datetime
    expires_at: datetime | None
    content_hash: Sha256
    created_at: datetime
    updated_at: datetime


class KnowledgeDiagnosticBody(StrictModel):
    document_id: DocumentId
    document_version: SafeVersion
    document_revision: SafeVersion
    content_hash: Sha256
    index_state: Literal["missing", "pending", "ready", "failed", "stale", "removed"]
    last_job_id: Annotated[str, StringConstraints(min_length=1, max_length=256)] | None
    indexed_at: datetime | None
    failure_code: Annotated[str, StringConstraints(min_length=1, max_length=128)] | None


class ErrorBody(StrictModel):
    code: str
    message: str
    retryable: bool
    detail_ref: str | None = None


class ErrorEnvelope(StrictModel):
    error: ErrorBody
