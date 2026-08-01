from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol

from flowpilot_domain import (
    Approval,
    ApprovalStatus,
    CommandType,
    DomainErrorCode,
    DomainViolation,
    TaskCommand,
)

from .errors import ApplicationError, ErrorCode


class ApprovalRepositoryPort(Protocol):
    """Tenant-scoped approval record boundary implemented by S6 persistence."""

    async def get(self, tenant_id: str, approval_id: str) -> Approval | None:
        """Return the exact tenant/approval record, or None when absent."""

    async def save(self, approval: Approval) -> None:
        """Persist the approval record (create or decision update)."""


class ApprovalEventPort(Protocol):
    """Publish ``task.approval.decided.v1`` events from the approval service."""

    async def publish_decided(self, *, approval: Approval, decision: str) -> None:
        """Publish the decided event with the public v1 payload mapping."""


@dataclass(frozen=True, slots=True)
class ApprovalDecisionResult:
    approval_id: str
    tenant_id: str
    task_id: str
    status: ApprovalStatus
    action_digest: str
    decided_at: datetime


class ApprovalDecisionService:
    """Deterministic approval decision use case (producer ``approval_service``).

    The service binds the decision command to the pending approval record:
    digest binding (FP-APR-001), separation of duties (FP-APR-002) and
    expiry. Execution-time authorization (role revocation, FP-APR-003)
    remains the Gateway ApprovalVerifier's authoritative check.
    """

    def __init__(
        self,
        *,
        approvals: ApprovalRepositoryPort,
        events: ApprovalEventPort,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._approvals = approvals
        self._events = events
        self._clock = clock or (lambda: datetime.now(UTC))

    async def decide(self, command: TaskCommand) -> ApprovalDecisionResult:
        if command.command_type is not CommandType.DECIDE_APPROVAL:
            raise ApplicationError(
                ErrorCode.CONTRACT_INVALID,
                "approval decision service requires a decide command",
            )
        self._assert_command_integrity(command)
        payload = command.payload
        approval = await self._load_pending(
            command.tenant_id, str(payload["approval_id"])
        )
        self._assert_task_binding(command, approval)
        if payload["action_digest"] != approval.action_digest:
            raise ApplicationError(
                ErrorCode.APPROVAL_BINDING_MISMATCH,
                "approval decision digest does not match the approval record",
            )
        if command.actor.id == approval.requester_id:
            raise ApplicationError(
                ErrorCode.APPROVAL_DUTIES_VIOLATION,
                "approval requester cannot decide their own approval",
            )
        now = self._clock()
        if now >= approval.expires_at:
            raise ApplicationError(
                ErrorCode.APPROVAL_EXPIRED,
                "approval expired before a decision could be recorded",
            )
        decision = str(payload["decision"])
        if decision == "approve":
            status = ApprovalStatus.APPROVED
            reason = "approved by approver"
        elif decision == "reject":
            status = ApprovalStatus.REJECTED
            reason = (
                str(payload["reason"])
                if payload.get("reason") is not None
                else "rejected by approver"
            )
        else:
            raise ApplicationError(
                ErrorCode.CONTRACT_INVALID,
                "approval decision is not part of the v1 contract",
            )
        decided = replace(
            approval,
            status=status,
            approver_id=command.actor.id,
            decision_reason=reason,
            separation_of_duties_result=True,
            decided_at=now,
        )
        try:
            await self._approvals.save(decided)
        except ApplicationError:
            raise
        except Exception as exc:
            raise ApplicationError(
                ErrorCode.REPOSITORY_UNAVAILABLE,
                "approval repository is unavailable",
                retryable=True,
            ) from exc
        try:
            await self._events.publish_decided(
                approval=decided, decision=status.value
            )
        except Exception as exc:
            raise ApplicationError(
                ErrorCode.REPOSITORY_UNAVAILABLE,
                "approval decided event could not be published",
                retryable=True,
            ) from exc
        return ApprovalDecisionResult(
            approval_id=decided.approval_id,
            tenant_id=decided.tenant_id,
            task_id=decided.task_id,
            status=status,
            action_digest=decided.action_digest,
            decided_at=now,
        )

    async def revoke(
        self,
        *,
        tenant_id: str,
        approval_id: str,
        reason: str | None,
    ) -> ApprovalDecisionResult:
        approval = await self._load_decidable(tenant_id, approval_id)
        now = self._clock()
        revoked = replace(
            approval,
            status=ApprovalStatus.REVOKED,
            decision_reason=reason or "revoked by authorization change",
            decided_at=now,
        )
        try:
            await self._approvals.save(revoked)
        except ApplicationError:
            raise
        except Exception as exc:
            raise ApplicationError(
                ErrorCode.REPOSITORY_UNAVAILABLE,
                "approval repository is unavailable",
                retryable=True,
            ) from exc
        await self._events.publish_decided(
            approval=revoked, decision=ApprovalStatus.REVOKED.value
        )
        return ApprovalDecisionResult(
            approval_id=revoked.approval_id,
            tenant_id=revoked.tenant_id,
            task_id=revoked.task_id,
            status=ApprovalStatus.REVOKED,
            action_digest=revoked.action_digest,
            decided_at=now,
        )

    async def _load_pending(
        self, tenant_id: str, approval_id: str
    ) -> Approval:
        approval = await self._load(tenant_id, approval_id)
        if approval.status is not ApprovalStatus.PENDING:
            raise ApplicationError(
                ErrorCode.APPROVAL_CONFLICT,
                "approval has already been decided",
            )
        return approval

    async def _load_decidable(
        self, tenant_id: str, approval_id: str
    ) -> Approval:
        approval = await self._load(tenant_id, approval_id)
        if approval.status not in {
            ApprovalStatus.PENDING,
            ApprovalStatus.APPROVED,
        }:
            raise ApplicationError(
                ErrorCode.APPROVAL_CONFLICT,
                "approval is not in a revocable state",
            )
        return approval

    async def _load(self, tenant_id: str, approval_id: str) -> Approval:
        try:
            approval = await self._approvals.get(tenant_id, approval_id)
        except ApplicationError:
            raise
        except Exception as exc:
            raise ApplicationError(
                ErrorCode.REPOSITORY_UNAVAILABLE,
                "approval repository is unavailable",
                retryable=True,
            ) from exc
        if approval is None or approval.tenant_id != tenant_id:
            raise ApplicationError(
                ErrorCode.APPROVAL_NOT_FOUND, "approval was not found"
            )
        return approval

    @staticmethod
    def _assert_task_binding(
        command: TaskCommand, approval: Approval
    ) -> None:
        if (
            approval.task_id != command.task_id
            or approval.tenant_id != command.tenant_id
        ):
            raise ApplicationError(
                ErrorCode.APPROVAL_BINDING_MISMATCH,
                "approval does not match the decision command task",
            )

    @staticmethod
    def _assert_command_integrity(command: TaskCommand) -> None:
        try:
            command.assert_digest()
            command.assert_security_binding()
        except DomainViolation as exc:
            mapping = {
                DomainErrorCode.DIGEST_MISMATCH: ErrorCode.COMMAND_DIGEST_MISMATCH,
                DomainErrorCode.SECURITY_BINDING_MISMATCH: (
                    ErrorCode.SECURITY_BINDING_MISMATCH
                ),
            }
            raise ApplicationError(
                mapping.get(exc.code, ErrorCode.CONTRACT_INVALID),
                exc.safe_message,
            ) from exc
