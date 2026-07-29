from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from flowpilot_domain import (
    Approval,
    ApprovalStatus,
    DomainViolation,
    PlannedAction,
)

from .errors import PersistenceError, PersistenceErrorCode

JsonScalar = str | int | float | bool | None
FrozenJson = JsonScalar | tuple["FrozenJson", ...] | Mapping[str, "FrozenJson"]
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

_SHA256 = re.compile(r"^sha256:[a-f0-9]{64}$")
_SECRET_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "cookie",
        "password",
        "private_key",
        "refresh_token",
        "secret",
        "session_token",
    }
)


def utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def format_utc(value: datetime) -> str:
    return utc(value, "timestamp").isoformat().replace("+00:00", "Z")


def json_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an RFC 3339 timestamp")
    try:
        return utc(
            datetime.fromisoformat(value.replace("Z", "+00:00")),
            field,
        )
    except ValueError as exc:
        raise ValueError(f"{field} must be an RFC 3339 timestamp") from exc


def freeze_json(value: Any, field: str = "value") -> FrozenJson:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError(f"{field} keys must be strings")
        return MappingProxyType(
            {key: freeze_json(item, field) for key, item in value.items()}
        )
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return tuple(freeze_json(item, field) for item in value)
    raise ValueError(f"{field} must contain JSON values")


def thaw_json(value: FrozenJson) -> JsonValue:
    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


def canonical_json(value: FrozenJson | Mapping[str, Any]) -> str:
    return json.dumps(
        thaw_json(freeze_json(value)),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def assert_no_secret_material(value: FrozenJson, field: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key.casefold() in _SECRET_KEYS:
                raise PersistenceError(
                    PersistenceErrorCode.SECRET_MATERIAL,
                    f"{field} contains a forbidden secret field",
                )
            assert_no_secret_material(item, field)
    elif isinstance(value, tuple):
        for item in value:
            assert_no_secret_material(item, field)


def require_text(value: str, field: str, *, maximum: int = 512) -> None:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"{field} must contain between 1 and {maximum} characters")


def require_sha256(value: str, field: str) -> None:
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase sha256 digest")


class LedgerStatus(StrEnum):
    PREPARED = "prepared"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    VERIFIED = "verified"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_FINAL = "failed_final"
    UNKNOWN = "unknown"


class RetryBasis(StrEnum):
    NOT_SENT = "not_sent"
    CONFIRMED_NOT_EXECUTED = "confirmed_not_executed"


@dataclass(frozen=True, slots=True)
class ExecutionIntent:
    tool_execution_id: str
    request_id: str
    tenant_id: str
    task_id: str
    tool_name: str
    idempotency_key: str
    action_id: str
    action_digest: str
    planned_action: Mapping[str, FrozenJson]
    planned_action_expires_at: datetime
    policy_decision_id: str
    policy_version: str
    policy_decision: Mapping[str, FrozenJson]
    policy_expires_at: datetime
    tool_schema_hash: str
    created_at: datetime
    approval_id: str | None = None
    approval: Mapping[str, FrozenJson] | None = None
    approval_expires_at: datetime | None = None

    def __post_init__(self) -> None:
        for field, value in (
            ("tool_execution_id", self.tool_execution_id),
            ("request_id", self.request_id),
            ("tenant_id", self.tenant_id),
            ("task_id", self.task_id),
            ("tool_name", self.tool_name),
            ("action_id", self.action_id),
            ("policy_decision_id", self.policy_decision_id),
            ("policy_version", self.policy_version),
        ):
            require_text(value, field, maximum=256)
        for field, value in (
            ("idempotency_key", self.idempotency_key),
            ("action_digest", self.action_digest),
            ("tool_schema_hash", self.tool_schema_hash),
        ):
            require_sha256(value, field)
        planned = freeze_json(self.planned_action, "planned_action")
        if not isinstance(planned, Mapping):
            raise ValueError("planned_action must be an object")
        planned_value = thaw_json(planned)
        if not isinstance(planned_value, dict):
            raise AssertionError("planned action was frozen from an object")
        try:
            planned_domain = PlannedAction.from_mapping(planned_value)
        except DomainViolation as exc:
            raise PersistenceError(
                PersistenceErrorCode.CONFLICT,
                "planned action snapshot violates the public contract",
            ) from exc
        object.__setattr__(self, "planned_action", planned)
        object.__setattr__(
            self,
            "planned_action_expires_at",
            utc(self.planned_action_expires_at, "planned_action_expires_at"),
        )
        policy_decision = freeze_json(self.policy_decision, "policy_decision")
        if not isinstance(policy_decision, Mapping):
            raise ValueError("policy_decision must be an object")
        policy_value = thaw_json(policy_decision)
        if not isinstance(policy_value, dict):
            raise AssertionError("policy decision was frozen from an object")
        policy_expires_at = utc(self.policy_expires_at, "policy_expires_at")
        policy_action = policy_value.get("action")
        policy_agent = policy_value.get("agent")
        if (
            planned_domain.tenant_id != self.tenant_id
            or planned_domain.task_id != self.task_id
            or planned_domain.action_id != self.action_id
            or planned_domain.digest() != self.action_digest
            or planned_domain.tool.name != self.tool_name
            or planned_domain.tool.schema_hash != self.tool_schema_hash
            or planned_domain.policy_version != self.policy_version
            or planned_domain.expires_at != self.planned_action_expires_at
            or policy_value.get("decision_id") != self.policy_decision_id
            or policy_value.get("tenant_id") != self.tenant_id
            or policy_value.get("task_id") != self.task_id
            or policy_value.get("policy_version") != self.policy_version
            or json_timestamp(policy_value.get("expires_at"), "policy.expires_at")
            != policy_expires_at
            or not isinstance(policy_action, dict)
            or policy_action.get("tool") != self.tool_name
            or policy_action.get("operation") != planned_domain.tool.operation.value
            or policy_action.get("action_digest") != self.action_digest
            or not isinstance(policy_agent, dict)
            or policy_agent.get("id") != planned_domain.agent.id
            or policy_agent.get("version") != planned_domain.agent.version
            or policy_expires_at != self.planned_action_expires_at
        ):
            raise PersistenceError(
                PersistenceErrorCode.CONFLICT,
                "planned action and policy bindings do not match",
            )
        policy_outcome = policy_value.get("decision")
        if policy_outcome not in {"allow", "require_approval"}:
            raise PersistenceError(
                PersistenceErrorCode.CONFLICT,
                "policy decision does not authorize execution preparation",
            )
        object.__setattr__(self, "policy_decision", policy_decision)
        object.__setattr__(self, "policy_expires_at", policy_expires_at)
        object.__setattr__(self, "created_at", utc(self.created_at, "created_at"))
        if self.approval_id is None:
            if self.approval is not None or self.approval_expires_at is not None:
                raise PersistenceError(
                    PersistenceErrorCode.CONFLICT,
                    "approval fields must be absent together",
                )
            if policy_outcome == "require_approval":
                raise PersistenceError(
                    PersistenceErrorCode.CONFLICT,
                    "policy requires a bound approved record",
                )
            return
        require_text(self.approval_id, "approval_id", maximum=256)
        if self.approval is None or self.approval_expires_at is None:
            raise PersistenceError(
                PersistenceErrorCode.CONFLICT,
                "approval fields must be present together",
            )
        approval = freeze_json(self.approval, "approval")
        if not isinstance(approval, Mapping):
            raise ValueError("approval must be an object")
        approval_value = thaw_json(approval)
        if not isinstance(approval_value, dict):
            raise AssertionError("approval was frozen from an object")
        try:
            approval_domain = Approval.from_mapping(approval_value)
        except DomainViolation as exc:
            raise PersistenceError(
                PersistenceErrorCode.CONFLICT,
                "approval snapshot violates the public contract",
            ) from exc
        approval_expires_at = utc(
            self.approval_expires_at, "approval_expires_at"
        )
        if (
            approval_domain.status is not ApprovalStatus.APPROVED
            or approval_domain.approval_id != self.approval_id
            or approval_domain.policy_decision_id != self.policy_decision_id
            or approval_domain.tenant_id != planned_domain.tenant_id
            or approval_domain.task_id != planned_domain.task_id
            or approval_domain.requester_id != planned_domain.requester_id
            or approval_domain.action_id != planned_domain.action_id
            or approval_domain.action_digest != self.action_digest
            or approval_domain.tool_schema_hash
            != planned_domain.tool.schema_hash
            or approval_domain.policy_version != planned_domain.policy_version
            or approval_domain.expires_at != approval_expires_at
            or approval_expires_at != self.planned_action_expires_at
        ):
            raise PersistenceError(
                PersistenceErrorCode.CONFLICT,
                "approval and planned action bindings do not match",
            )
        object.__setattr__(self, "approval", approval)
        object.__setattr__(
            self, "approval_expires_at", approval_expires_at
        )

    def binding_mapping(self) -> dict[str, JsonValue]:
        return {
            "tool_execution_id": self.tool_execution_id,
            "request_id": self.request_id,
            "tenant_id": self.tenant_id,
            "task_id": self.task_id,
            "tool_name": self.tool_name,
            "idempotency_key": self.idempotency_key,
            "action_id": self.action_id,
            "action_digest": self.action_digest,
            "planned_action": thaw_json(self.planned_action),
            "planned_action_expires_at": format_utc(
                self.planned_action_expires_at
            ),
            "policy_decision_id": self.policy_decision_id,
            "policy_version": self.policy_version,
            "policy_decision": thaw_json(self.policy_decision),
            "policy_expires_at": format_utc(self.policy_expires_at),
            "tool_schema_hash": self.tool_schema_hash,
            "approval_id": self.approval_id,
            "approval": (
                thaw_json(self.approval) if self.approval is not None else None
            ),
            "approval_expires_at": (
                format_utc(self.approval_expires_at)
                if self.approval_expires_at is not None
                else None
            ),
        }

    def fingerprint(self) -> str:
        return canonical_json(self.binding_mapping())


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    status: LedgerStatus
    recorded_at: datetime
    retryable: bool
    data: Mapping[str, FrozenJson] | None = None
    error_code: str | None = None
    retry_basis: RetryBasis | None = None
    evidence_ref: str | None = None
    verification: Mapping[str, FrozenJson] | None = None
    reconciliation: Mapping[str, FrozenJson] | None = None

    def __post_init__(self) -> None:
        if self.status in {LedgerStatus.PREPARED, LedgerStatus.RUNNING}:
            raise ValueError("execution outcome must be a terminal attempt status")
        object.__setattr__(
            self, "recorded_at", utc(self.recorded_at, "recorded_at")
        )
        for field in ("data", "verification", "reconciliation"):
            value = getattr(self, field)
            if value is None:
                continue
            frozen = freeze_json(value, field)
            if not isinstance(frozen, Mapping):
                raise ValueError(f"{field} must be an object")
            object.__setattr__(self, field, frozen)
        if self.status is LedgerStatus.VERIFIED:
            matched = (
                self.verification.get("matched")
                if self.verification is not None
                else None
            )
            observed_ref = (
                self.verification.get("observed_ref")
                if self.verification is not None
                else None
            )
            if (
                not self.data
                or not self.evidence_ref
                or matched is not True
                or not isinstance(observed_ref, str)
                or not observed_ref
                or self.retryable
                or self.error_code is not None
                or self.reconciliation is not None
            ):
                raise PersistenceError(
                    PersistenceErrorCode.INVALID_TRANSITION,
                    "verified outcome lacks authoritative readback evidence",
                )
        elif self.status is LedgerStatus.UNKNOWN:
            if (
                self.data is not None
                or self.verification is not None
                or not self.error_code
                or self.retryable
                or self.retry_basis is not None
                or not self.reconciliation
            ):
                raise PersistenceError(
                    PersistenceErrorCode.INVALID_TRANSITION,
                    "unknown outcome must be non-retryable and reconcilable",
                )
        elif self.status is LedgerStatus.SUCCEEDED:
            if (
                not self.data
                or self.retryable
                or self.error_code is not None
                or self.retry_basis is not None
                or self.reconciliation is not None
            ):
                raise PersistenceError(
                    PersistenceErrorCode.INVALID_TRANSITION,
                    "succeeded outcome must carry result data and await verification",
                )
        elif self.status is LedgerStatus.FAILED_RETRYABLE:
            if not self.retryable or self.retry_basis is None or not self.error_code:
                raise PersistenceError(
                    PersistenceErrorCode.INVALID_TRANSITION,
                    "retryable failure requires a proven retry basis",
                )
            if (
                self.retry_basis is RetryBasis.NOT_SENT
                and self.verification is not None
            ):
                raise PersistenceError(
                    PersistenceErrorCode.INVALID_TRANSITION,
                    "not-sent retry basis cannot carry readback verification",
                )
            if self.retry_basis is RetryBasis.CONFIRMED_NOT_EXECUTED:
                matched = (
                    self.verification.get("matched")
                    if self.verification is not None
                    else None
                )
                observed_ref = (
                    self.verification.get("observed_ref")
                    if self.verification is not None
                    else None
                )
                if matched is not False or not observed_ref:
                    raise PersistenceError(
                        PersistenceErrorCode.INVALID_TRANSITION,
                        "confirmed-not-executed requires negative readback evidence",
                    )
        elif self.status is LedgerStatus.FAILED_FINAL:
            if self.retryable or self.retry_basis is not None or not self.error_code:
                raise PersistenceError(
                    PersistenceErrorCode.INVALID_TRANSITION,
                    "final failure cannot be retryable",
                )


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    intent: ExecutionIntent
    status: LedgerStatus
    attempt_count: int
    updated_at: datetime
    outcome: ExecutionOutcome | None = None

    def __post_init__(self) -> None:
        if self.attempt_count < 0:
            raise ValueError("attempt_count cannot be negative")
        object.__setattr__(
            self, "updated_at", utc(self.updated_at, "updated_at")
        )


@dataclass(frozen=True, slots=True)
class LeaseFence:
    tenant_id: str
    task_id: str
    holder_id: str
    lease_token: str
    run_generation: int
    acquired_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for field, value in (
            ("tenant_id", self.tenant_id),
            ("task_id", self.task_id),
            ("holder_id", self.holder_id),
            ("lease_token", self.lease_token),
        ):
            require_text(value, field, maximum=256)
        if self.run_generation < 1:
            raise ValueError("run_generation must be positive")
        acquired_at = utc(self.acquired_at, "acquired_at")
        expires_at = utc(self.expires_at, "expires_at")
        if expires_at <= acquired_at:
            raise ValueError("lease must expire after acquisition")
        object.__setattr__(self, "acquired_at", acquired_at)
        object.__setattr__(self, "expires_at", expires_at)

    def is_active(self, now: datetime) -> bool:
        return self.expires_at > utc(now, "now")


@dataclass(frozen=True, slots=True)
class CheckpointRecord:
    checkpoint_id: str
    tenant_id: str
    task_id: str
    thread_id: str
    run_generation: int
    checkpoint_sequence: int
    graph_version: str
    state: Mapping[str, FrozenJson]
    security_context_ref: str
    security_context_hash: str
    created_at: datetime

    def __post_init__(self) -> None:
        for field, value in (
            ("checkpoint_id", self.checkpoint_id),
            ("tenant_id", self.tenant_id),
            ("task_id", self.task_id),
            ("thread_id", self.thread_id),
            ("graph_version", self.graph_version),
            ("security_context_ref", self.security_context_ref),
        ):
            require_text(value, field, maximum=512)
        require_sha256(self.security_context_hash, "security_context_hash")
        if self.run_generation < 1:
            raise ValueError("run_generation must be positive")
        if (
            isinstance(self.checkpoint_sequence, bool)
            or not isinstance(self.checkpoint_sequence, int)
            or self.checkpoint_sequence < 0
        ):
            raise ValueError("checkpoint_sequence must be a non-negative integer")
        state = freeze_json(self.state, "state")
        if not isinstance(state, Mapping):
            raise ValueError("state must be an object")
        assert_no_secret_material(state, "checkpoint state")
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "created_at", utc(self.created_at, "created_at"))


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    event_id: str
    tenant_id: str
    aggregate_type: str
    aggregate_id: str
    sequence: int
    event_type: str
    payload: Mapping[str, FrozenJson]
    occurred_at: datetime
    available_at: datetime

    def __post_init__(self) -> None:
        for field, value in (
            ("event_id", self.event_id),
            ("tenant_id", self.tenant_id),
            ("aggregate_type", self.aggregate_type),
            ("aggregate_id", self.aggregate_id),
            ("event_type", self.event_type),
        ):
            require_text(value, field, maximum=256)
        if self.sequence < 1:
            raise ValueError("outbox sequence must be positive")
        payload = freeze_json(self.payload, "payload")
        if not isinstance(payload, Mapping):
            raise ValueError("payload must be an object")
        assert_no_secret_material(payload, "outbox payload")
        object.__setattr__(self, "payload", payload)
        object.__setattr__(
            self, "occurred_at", utc(self.occurred_at, "occurred_at")
        )
        object.__setattr__(
            self, "available_at", utc(self.available_at, "available_at")
        )

    def fingerprint(self) -> str:
        return canonical_json(
            {
                "event_id": self.event_id,
                "tenant_id": self.tenant_id,
                "aggregate_type": self.aggregate_type,
                "aggregate_id": self.aggregate_id,
                "sequence": self.sequence,
                "event_type": self.event_type,
                "payload": thaw_json(self.payload),
                "occurred_at": format_utc(self.occurred_at),
            }
        )


@dataclass(frozen=True, slots=True)
class OutboxDelivery:
    event: OutboxEvent
    publish_attempts: int = 0
    published_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.publish_attempts < 0:
            raise ValueError("publish_attempts cannot be negative")
        if self.published_at is not None:
            object.__setattr__(
                self, "published_at", utc(self.published_at, "published_at")
            )


@dataclass(frozen=True, slots=True)
class CoordinationSignal:
    tenant_id: str
    task_id: str
    run_generation: int
    available_at: datetime

    def __post_init__(self) -> None:
        require_text(self.tenant_id, "tenant_id", maximum=128)
        require_text(self.task_id, "task_id", maximum=256)
        if self.run_generation < 0:
            raise ValueError("run_generation cannot be negative")
        object.__setattr__(
            self, "available_at", utc(self.available_at, "available_at")
        )
