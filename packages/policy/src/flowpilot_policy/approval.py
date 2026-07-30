from __future__ import annotations

from datetime import datetime
from typing import Protocol

from flowpilot_domain import (
    Approval,
    ApprovalStatus,
    DomainViolation,
    PlannedAction,
    SecurityContextRef,
)

from .errors import PolicyError, PolicyErrorCode
from .models import PolicyDecision, PolicyDecisionKind


class ApprovalSource(Protocol):
    async def resolve(self, approval_id: str) -> Approval: ...


class ApproverDirectoryPort(Protocol):
    async def has_any_role(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        roles: frozenset[str],
        now: datetime,
    ) -> bool: ...


class ApprovalVerifier:
    async def verify(
        self,
        *,
        approval: Approval,
        policy: PolicyDecision,
        action: PlannedAction,
        context: SecurityContextRef,
        approvers: ApproverDirectoryPort,
        now: datetime,
    ) -> None:
        if (
            policy.decision is not PolicyDecisionKind.REQUIRE_APPROVAL
            or policy.approval_requirements is None
        ):
            raise PolicyError(
                PolicyErrorCode.APPROVAL_INVALID,
                "approval was supplied for a policy that does not require it",
            )
        if approval.status is not ApprovalStatus.APPROVED:
            raise PolicyError(
                PolicyErrorCode.APPROVAL_REQUIRED,
                "policy requires an approved record",
            )
        if now >= approval.expires_at:
            raise PolicyError(
                PolicyErrorCode.APPROVAL_EXPIRED,
                "approval has expired",
            )
        if approval.decided_at is None or approval.decided_at > now:
            raise PolicyError(
                PolicyErrorCode.APPROVAL_INVALID,
                "approval decision time is not valid for execution",
            )
        try:
            approval.assert_action_binding(action)
        except DomainViolation as exc:
            raise PolicyError(
                PolicyErrorCode.APPROVAL_INVALID,
                "approval does not match the planned action",
            ) from exc
        if (
            approval.policy_decision_id != policy.decision_id
            or approval.policy_version != policy.policy_version
            or approval.expires_at != policy.expires_at
            or approval.requester_id != context.subject_id
            or approval.tenant_id != context.tenant_id
            or approval.approver_id is None
            or approval.approver_id == approval.requester_id
            or approval.separation_of_duties_result is not True
        ):
            raise PolicyError(
                PolicyErrorCode.APPROVAL_INVALID,
                "approval bindings do not match policy and identity",
            )
        authorized = await approvers.has_any_role(
            tenant_id=approval.tenant_id,
            subject_id=approval.approver_id,
            roles=frozenset(policy.approval_requirements.roles),
            now=now,
        )
        if not authorized:
            raise PolicyError(
                PolicyErrorCode.SEPARATION_OF_DUTIES,
                "approver does not hold a required current role",
            )
