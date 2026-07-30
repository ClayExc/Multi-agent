from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from flowpilot_domain import (
    DomainViolation,
    PlannedAction,
    SecurityContextRef,
    ToolOperation,
)

from .errors import ToolContractError, ToolContractErrorCode
from .schema import FrozenJson, freeze_json, thaw_json

_SHA256 = re.compile(r"^sha256:[a-f0-9]{64}$")
_REQUEST_ID = re.compile(r"^treq_[A-Za-z0-9_-]{8,128}$")
_EXECUTION_ID = re.compile(r"^tex_[A-Za-z0-9_-]{8,128}$")
_POLICY_ID = re.compile(r"^pd_[A-Za-z0-9_-]{8,128}$")
_APPROVAL_ID = re.compile(r"^apr_[A-Za-z0-9_-]{8,128}$")


def _utc(value: object, field: str) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ToolContractError(
                ToolContractErrorCode.CONTRACT_INVALID,
                f"{field} must be an RFC 3339 timestamp",
            ) from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise ToolContractError(
            ToolContractErrorCode.CONTRACT_INVALID,
            f"{field} must be an RFC 3339 timestamp",
        )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ToolContractError(
            ToolContractErrorCode.CONTRACT_INVALID,
            f"{field} must be timezone-aware",
        )
    return parsed.astimezone(UTC)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _exact_keys(
    value: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str],
    field: str,
) -> None:
    keys = set(value)
    if keys != required | (keys & optional):
        raise ToolContractError(
            ToolContractErrorCode.CONTRACT_INVALID,
            f"{field} fields do not match the public v1 contract",
        )
    missing = required - keys
    if missing:
        raise ToolContractError(
            ToolContractErrorCode.CONTRACT_INVALID,
            f"{field} is missing required fields",
        )


def _require_text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ToolContractError(
            ToolContractErrorCode.CONTRACT_INVALID,
            f"{field} must contain between 1 and {maximum} characters",
        )
    return value


def _require_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ToolContractError(
            ToolContractErrorCode.CONTRACT_INVALID,
            f"{field} must be a lowercase sha256 digest",
        )
    return value


@dataclass(frozen=True, slots=True)
class AgentPrincipal:
    id: str
    version: str
    principal_ref: str

    def __post_init__(self) -> None:
        _require_text(self.id, "agent_principal.id", 128)
        _require_text(self.version, "agent_principal.version", 128)
        _require_text(
            self.principal_ref, "agent_principal.principal_ref", 512
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> AgentPrincipal:
        _exact_keys(
            value,
            required={"id", "version", "principal_ref"},
            optional=set(),
            field="agent_principal",
        )
        return cls(
            id=_require_text(value["id"], "agent_principal.id", 128),
            version=_require_text(
                value["version"], "agent_principal.version", 128
            ),
            principal_ref=_require_text(
                value["principal_ref"], "agent_principal.principal_ref", 512
            ),
        )

    def to_mapping(self) -> dict[str, str]:
        return {
            "id": self.id,
            "version": self.version,
            "principal_ref": self.principal_ref,
        }


@dataclass(frozen=True, slots=True)
class ToolRequest:
    request_id: str
    trace_id: str
    security_context: SecurityContextRef
    agent_principal: AgentPrincipal
    planned_action: PlannedAction
    action_digest: str
    policy_decision_id: str
    idempotency_key: str
    requested_at: datetime
    approval_id: str | None = None

    def __post_init__(self) -> None:
        if _REQUEST_ID.fullmatch(self.request_id) is None:
            raise ToolContractError(
                ToolContractErrorCode.CONTRACT_INVALID,
                "request_id is not a public v1 identifier",
            )
        if not 16 <= len(self.trace_id) <= 128:
            raise ToolContractError(
                ToolContractErrorCode.CONTRACT_INVALID,
                "trace_id must contain between 16 and 128 characters",
            )
        if _POLICY_ID.fullmatch(self.policy_decision_id) is None:
            raise ToolContractError(
                ToolContractErrorCode.CONTRACT_INVALID,
                "policy_decision_id is not a public v1 identifier",
            )
        _require_sha256(self.action_digest, "action_digest")
        _require_sha256(self.idempotency_key, "idempotency_key")
        if self.planned_action.digest() != self.action_digest:
            raise ToolContractError(
                ToolContractErrorCode.ACTION_DIGEST_MISMATCH,
                "planned action digest does not match the request",
            )
        if (
            self.approval_id is not None
            and _APPROVAL_ID.fullmatch(self.approval_id) is None
        ):
            raise ToolContractError(
                ToolContractErrorCode.CONTRACT_INVALID,
                "approval_id is not a public v1 identifier",
            )
        object.__setattr__(
            self, "requested_at", _utc(self.requested_at, "requested_at")
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ToolRequest:
        _exact_keys(
            value,
            required={
                "request_id",
                "trace_id",
                "security_context",
                "agent_principal",
                "planned_action",
                "action_digest",
                "policy_decision_id",
                "idempotency_key",
                "requested_at",
            },
            optional={"approval_id"},
            field="tool_request",
        )
        for field in (
            "security_context",
            "agent_principal",
            "planned_action",
        ):
            if not isinstance(value[field], Mapping):
                raise ToolContractError(
                    ToolContractErrorCode.CONTRACT_INVALID,
                    f"{field} must be an object",
                )
        try:
            context = SecurityContextRef.from_mapping(
                dict(value["security_context"])
            )
            action = PlannedAction.from_mapping(dict(value["planned_action"]))
        except DomainViolation as exc:
            raise ToolContractError(
                ToolContractErrorCode.CONTRACT_INVALID,
                "tool request contains an invalid public object",
            ) from exc
        action_digest = _require_sha256(
            value["action_digest"], "action_digest"
        )
        if action.digest() != action_digest:
            raise ToolContractError(
                ToolContractErrorCode.ACTION_DIGEST_MISMATCH,
                "planned action digest does not match the request",
            )
        approval_id = value.get("approval_id")
        if approval_id is not None:
            _require_text(approval_id, "approval_id", 128)
        return cls(
            request_id=_require_text(value["request_id"], "request_id", 133),
            trace_id=_require_text(value["trace_id"], "trace_id", 128),
            security_context=context,
            agent_principal=AgentPrincipal.from_mapping(
                value["agent_principal"]
            ),
            planned_action=action,
            action_digest=action_digest,
            policy_decision_id=_require_text(
                value["policy_decision_id"], "policy_decision_id", 133
            ),
            idempotency_key=_require_sha256(
                value["idempotency_key"], "idempotency_key"
            ),
            approval_id=approval_id,
            requested_at=_utc(value["requested_at"], "requested_at"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "security_context": self.security_context.to_mapping(),
            "agent_principal": self.agent_principal.to_mapping(),
            "planned_action": self.planned_action.to_mapping(),
            "action_digest": self.action_digest,
            "policy_decision_id": self.policy_decision_id,
            "idempotency_key": self.idempotency_key,
            "approval_id": self.approval_id,
            "requested_at": _format_utc(self.requested_at),
        }


class ToolResultStatus(StrEnum):
    VERIFIED = "verified"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_FINAL = "failed_final"
    UNKNOWN = "unknown"


class RetryBasis(StrEnum):
    NOT_SENT = "not_sent"
    CONFIRMED_NOT_EXECUTED = "confirmed_not_executed"


class VerificationMethod(StrEnum):
    READ_BACK = "read_back"
    UPSTREAM_IDEMPOTENCY_LOOKUP = "upstream_idempotency_lookup"
    BUSINESS_KEY_LOOKUP = "business_key_lookup"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class Verification:
    method: VerificationMethod
    matched: bool
    observed_ref: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.matched, bool):
            raise ToolContractError(
                ToolContractErrorCode.CONTRACT_INVALID,
                "verification matched must be boolean",
            )
        if self.observed_ref is not None and len(self.observed_ref) > 512:
            raise ToolContractError(
                ToolContractErrorCode.CONTRACT_INVALID,
                "verification observed_ref exceeds 512 characters",
            )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "method": self.method.value,
            "matched": self.matched,
            "observed_ref": self.observed_ref,
        }


@dataclass(frozen=True, slots=True)
class Reconciliation:
    state: str
    strategy: str
    next_action: str
    ref: str | None

    def __post_init__(self) -> None:
        if self.state not in {"pending", "manual_required"}:
            raise ToolContractError(
                ToolContractErrorCode.CONTRACT_INVALID,
                "reconciliation state is not part of v1",
            )
        if self.strategy not in {
            "upstream_idempotency_lookup",
            "business_key_lookup",
            "manual",
        }:
            raise ToolContractError(
                ToolContractErrorCode.CONTRACT_INVALID,
                "reconciliation strategy is not part of v1",
            )
        if self.next_action != "reconcile_only":
            raise ToolContractError(
                ToolContractErrorCode.CONTRACT_INVALID,
                "unknown outcomes can only be reconciled",
            )
        if self.ref is not None and len(self.ref) > 512:
            raise ToolContractError(
                ToolContractErrorCode.CONTRACT_INVALID,
                "reconciliation ref exceeds 512 characters",
            )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "strategy": self.strategy,
            "next_action": self.next_action,
            "ref": self.ref,
        }


@dataclass(frozen=True, slots=True)
class ToolResult:
    execution_id: str
    request_id: str
    operation: ToolOperation
    status: ToolResultStatus
    data: Mapping[str, FrozenJson] | None
    display_summary: str
    output_classification: str
    policy_decision_id: str
    retryable: bool
    retry_basis: RetryBasis | None
    error_code: str | None
    verification: Verification | None
    reconciliation: Reconciliation | None
    started_at: datetime
    finished_at: datetime
    evidence_ref: str | None = None
    redaction_summary: Mapping[str, FrozenJson] | None = None

    def __post_init__(self) -> None:
        if _EXECUTION_ID.fullmatch(self.execution_id) is None:
            raise ToolContractError(
                ToolContractErrorCode.CONTRACT_INVALID,
                "execution_id is not a public v1 identifier",
            )
        if _REQUEST_ID.fullmatch(self.request_id) is None:
            raise ToolContractError(
                ToolContractErrorCode.CONTRACT_INVALID,
                "request_id is not a public v1 identifier",
            )
        if len(self.display_summary) > 4000:
            raise ToolContractError(
                ToolContractErrorCode.CONTRACT_INVALID,
                "display_summary exceeds 4000 characters",
            )
        if self.output_classification not in {
            "public",
            "internal",
            "confidential",
            "restricted",
        }:
            raise ToolContractError(
                ToolContractErrorCode.CONTRACT_INVALID,
                "output classification is not part of v1",
            )
        _require_text(
            self.policy_decision_id, "policy_decision_id", maximum=256
        )
        for field, value, maximum in (
            ("evidence_ref", self.evidence_ref, 512),
            ("error_code", self.error_code, 128),
        ):
            if value is not None and len(value) > maximum:
                raise ToolContractError(
                    ToolContractErrorCode.CONTRACT_INVALID,
                    f"{field} exceeds {maximum} characters",
                )
        started = _utc(self.started_at, "started_at")
        finished = _utc(self.finished_at, "finished_at")
        if finished < started:
            raise ToolContractError(
                ToolContractErrorCode.CONTRACT_INVALID,
                "tool result cannot finish before it starts",
            )
        object.__setattr__(self, "started_at", started)
        object.__setattr__(self, "finished_at", finished)
        if self.data is not None:
            frozen = freeze_json(self.data, "data")
            if not isinstance(frozen, Mapping):
                raise ToolContractError(
                    ToolContractErrorCode.CONTRACT_INVALID,
                    "tool result data must be an object",
                )
            object.__setattr__(self, "data", frozen)
        redactions = freeze_json(
            self.redaction_summary or {}, "redaction_summary"
        )
        if not isinstance(redactions, Mapping):
            raise ToolContractError(
                ToolContractErrorCode.CONTRACT_INVALID,
                "redaction summary must be an object",
            )
        object.__setattr__(self, "redaction_summary", redactions)
        self._validate_status()

    def _validate_status(self) -> None:
        if self.status is ToolResultStatus.VERIFIED:
            if (
                self.verification is None
                or self.verification.matched is not True
                or self.retryable
                or self.retry_basis is not None
                or self.error_code is not None
                or self.reconciliation is not None
            ):
                raise ToolContractError(
                    ToolContractErrorCode.CONTRACT_INVALID,
                    "verified result fields are inconsistent",
                )
            if self.operation is ToolOperation.WRITE and (
                not self.data
                or not self.evidence_ref
                or self.verification.method
                is VerificationMethod.NOT_APPLICABLE
                or not self.verification.observed_ref
            ):
                raise ToolContractError(
                    ToolContractErrorCode.CONTRACT_INVALID,
                    "verified write lacks authoritative readback evidence",
                )
            return
        if self.status is ToolResultStatus.UNKNOWN:
            if (
                self.data is not None
                or self.verification is not None
                or self.retryable
                or self.retry_basis is not None
                or not self.error_code
                or self.reconciliation is None
            ):
                raise ToolContractError(
                    ToolContractErrorCode.CONTRACT_INVALID,
                    "unknown result fields are inconsistent",
                )
            return
        if self.status is ToolResultStatus.FAILED_RETRYABLE:
            if (
                self.data is not None
                or not self.retryable
                or self.retry_basis is None
                or not self.error_code
                or self.reconciliation is not None
            ):
                raise ToolContractError(
                    ToolContractErrorCode.CONTRACT_INVALID,
                    "retryable failure fields are inconsistent",
                )
            if (
                self.retry_basis is RetryBasis.NOT_SENT
                and self.verification is not None
            ):
                raise ToolContractError(
                    ToolContractErrorCode.CONTRACT_INVALID,
                    "not-sent failure cannot include verification",
                )
            if self.retry_basis is RetryBasis.CONFIRMED_NOT_EXECUTED and (
                self.verification is None
                or self.verification.matched is not False
                or not self.verification.observed_ref
                or self.verification.method
                not in {
                    VerificationMethod.UPSTREAM_IDEMPOTENCY_LOOKUP,
                    VerificationMethod.BUSINESS_KEY_LOOKUP,
                }
            ):
                raise ToolContractError(
                    ToolContractErrorCode.CONTRACT_INVALID,
                    "confirmed-not-executed lacks authoritative evidence",
                )
            return
        if (
            self.status is not ToolResultStatus.FAILED_FINAL
            or self.data is not None
            or self.retryable
            or self.retry_basis is not None
            or not self.error_code
            or self.reconciliation is not None
        ):
            raise ToolContractError(
                ToolContractErrorCode.CONTRACT_INVALID,
                "final failure fields are inconsistent",
            )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "request_id": self.request_id,
            "operation": self.operation.value,
            "status": self.status.value,
            "data": thaw_json(self.data) if self.data is not None else None,
            "display_summary": self.display_summary,
            "evidence_ref": self.evidence_ref,
            "output_classification": self.output_classification,
            "policy_decision_id": self.policy_decision_id,
            "redaction_summary": thaw_json(self.redaction_summary or {}),
            "retryable": self.retryable,
            "retry_basis": (
                self.retry_basis.value if self.retry_basis is not None else None
            ),
            "error_code": self.error_code,
            "verification": (
                self.verification.to_mapping()
                if self.verification is not None
                else None
            ),
            "reconciliation": (
                self.reconciliation.to_mapping()
                if self.reconciliation is not None
                else None
            ),
            "started_at": _format_utc(self.started_at),
            "finished_at": _format_utc(self.finished_at),
        }
