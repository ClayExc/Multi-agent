from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from .actions import PlannedAction
from .errors import DomainErrorCode, DomainViolation
from .primitives import (
    ensure_utc,
    format_utc,
    require_exact_keys,
    require_identifier,
    require_sha256,
    require_text,
)


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class Approval:
    approval_id: str
    tenant_id: str
    task_id: str
    requester_id: str
    action_id: str
    action_digest: str
    tool_schema_hash: str
    policy_decision_id: str
    policy_version: str
    status: ApprovalStatus
    approver_id: str | None
    decision_reason: str | None
    separation_of_duties_result: bool | None
    requested_at: datetime
    decided_at: datetime | None
    expires_at: datetime

    def __post_init__(self) -> None:
        require_identifier(
            self.approval_id, "approval_id", r"^apr_[A-Za-z0-9_-]{8,128}$"
        )
        require_text(self.tenant_id, "tenant_id", maximum=128)
        require_identifier(
            self.task_id, "task_id", r"^task_[A-Za-z0-9_-]{8,128}$"
        )
        require_text(self.requester_id, "requester_id", maximum=256)
        require_identifier(
            self.action_id, "action_id", r"^act_[A-Za-z0-9_-]{8,128}$"
        )
        require_sha256(self.action_digest, "action_digest")
        require_sha256(self.tool_schema_hash, "tool_schema_hash")
        require_identifier(
            self.policy_decision_id,
            "policy_decision_id",
            r"^pd_[A-Za-z0-9_-]{8,128}$",
        )
        require_text(self.policy_version, "policy_version", maximum=128)
        if self.approver_id is not None:
            require_text(self.approver_id, "approver_id", maximum=256)
        if self.decision_reason is not None and len(self.decision_reason) > 2000:
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "decision_reason exceeds 2000 characters",
            )
        requested_at = ensure_utc(self.requested_at, "requested_at")
        expires_at = ensure_utc(self.expires_at, "expires_at")
        decided_at = (
            ensure_utc(self.decided_at, "decided_at")
            if self.decided_at is not None
            else None
        )
        if expires_at <= requested_at:
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "approval must expire after it is requested",
            )
        if decided_at is not None and decided_at < requested_at:
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "approval cannot be decided before it is requested",
            )
        object.__setattr__(self, "requested_at", requested_at)
        object.__setattr__(self, "expires_at", expires_at)
        object.__setattr__(self, "decided_at", decided_at)
        self._validate_decision_fields()

    def _validate_decision_fields(self) -> None:
        if self.status is ApprovalStatus.PENDING:
            if any(
                value is not None
                for value in (
                    self.approver_id,
                    self.decision_reason,
                    self.separation_of_duties_result,
                    self.decided_at,
                )
            ):
                raise DomainViolation(
                    DomainErrorCode.INVALID_STATE,
                    "pending approval cannot carry decision fields",
                )
            return
        if self.decided_at is None:
            raise DomainViolation(
                DomainErrorCode.INVALID_STATE,
                "non-pending approval requires decided_at",
            )
        if self.status is ApprovalStatus.APPROVED:
            if (
                self.approver_id is None
                or self.separation_of_duties_result is not True
                or self.approver_id == self.requester_id
            ):
                raise DomainViolation(
                    DomainErrorCode.APPROVAL_BINDING_MISMATCH,
                    "approved record fails separation of duties",
                )
        elif self.status is ApprovalStatus.REJECTED and (
            self.approver_id is None
            or not self.decision_reason
            or self.separation_of_duties_result is None
        ):
            raise DomainViolation(
                DomainErrorCode.INVALID_STATE,
                "rejected approval requires complete decision fields",
            )

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> Approval:
        require_exact_keys(
            value,
            required={
                "approval_id",
                "tenant_id",
                "task_id",
                "requester_id",
                "action_id",
                "action_digest",
                "tool_schema_hash",
                "policy_decision_id",
                "policy_version",
                "status",
                "approver_id",
                "decision_reason",
                "separation_of_duties_result",
                "requested_at",
                "decided_at",
                "expires_at",
            },
            optional=set(),
            field="approval",
        )
        try:
            status = ApprovalStatus(value["status"])
        except ValueError as exc:
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "approval status is not part of the v1 contract",
            ) from exc
        return cls(
            approval_id=value["approval_id"],
            tenant_id=value["tenant_id"],
            task_id=value["task_id"],
            requester_id=value["requester_id"],
            action_id=value["action_id"],
            action_digest=value["action_digest"],
            tool_schema_hash=value["tool_schema_hash"],
            policy_decision_id=value["policy_decision_id"],
            policy_version=value["policy_version"],
            status=status,
            approver_id=value["approver_id"],
            decision_reason=value["decision_reason"],
            separation_of_duties_result=value["separation_of_duties_result"],
            requested_at=ensure_utc(value["requested_at"], "requested_at"),
            decided_at=(
                ensure_utc(value["decided_at"], "decided_at")
                if value["decided_at"] is not None
                else None
            ),
            expires_at=ensure_utc(value["expires_at"], "expires_at"),
        )

    def assert_action_binding(self, action: PlannedAction) -> None:
        approval_expires_at = ensure_utc(
            self.expires_at, "approval.expires_at"
        )
        action_expires_at = ensure_utc(
            action.expires_at, "planned_action.expires_at"
        )
        if (
            self.tenant_id != action.tenant_id
            or self.task_id != action.task_id
            or self.requester_id != action.requester_id
            or self.action_id != action.action_id
            or self.action_digest != action.digest()
            or self.tool_schema_hash != action.tool.schema_hash
            or self.policy_version != action.policy_version
            or approval_expires_at != action_expires_at
        ):
            raise DomainViolation(
                DomainErrorCode.APPROVAL_BINDING_MISMATCH,
                "approval does not match the planned action",
            )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "tenant_id": self.tenant_id,
            "task_id": self.task_id,
            "requester_id": self.requester_id,
            "action_id": self.action_id,
            "action_digest": self.action_digest,
            "tool_schema_hash": self.tool_schema_hash,
            "policy_decision_id": self.policy_decision_id,
            "policy_version": self.policy_version,
            "status": self.status.value,
            "approver_id": self.approver_id,
            "decision_reason": self.decision_reason,
            "separation_of_duties_result": self.separation_of_duties_result,
            "requested_at": format_utc(self.requested_at),
            "decided_at": (
                format_utc(self.decided_at) if self.decided_at is not None else None
            ),
            "expires_at": format_utc(self.expires_at),
        }
