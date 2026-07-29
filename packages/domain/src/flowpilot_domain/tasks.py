from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from .errors import DomainErrorCode, DomainViolation
from .primitives import (
    MAX_SAFE_INTEGER,
    ensure_utc,
    format_utc,
    require_exact_keys,
    require_identifier,
    require_text,
)
from .security import DataClassification, SecurityContextRef


class TaskStatus(StrEnum):
    RECEIVED = "RECEIVED"
    RUNNABLE = "RUNNABLE"
    RUNNING = "RUNNING"
    WAITING_USER = "WAITING_USER"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    ESCALATED = "ESCALATED"
    FAILED = "FAILED"


class WaitingType(StrEnum):
    USER_INPUT = "user_input"
    APPROVAL = "approval"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


TERMINAL_STATUSES = frozenset(
    {
        TaskStatus.COMPLETED,
        TaskStatus.CANCELLED,
        TaskStatus.ESCALATED,
        TaskStatus.FAILED,
    }
)

_ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.RECEIVED: frozenset({TaskStatus.RUNNABLE, TaskStatus.CANCELLED}),
    TaskStatus.RUNNABLE: frozenset({TaskStatus.RUNNING}),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.WAITING_USER,
            TaskStatus.WAITING_APPROVAL,
            TaskStatus.VERIFYING,
            TaskStatus.ESCALATED,
            TaskStatus.FAILED,
        }
    ),
    TaskStatus.WAITING_USER: frozenset(
        {TaskStatus.RUNNABLE, TaskStatus.CANCELLED}
    ),
    TaskStatus.WAITING_APPROVAL: frozenset(
        {TaskStatus.RUNNABLE, TaskStatus.CANCELLED}
    ),
    TaskStatus.VERIFYING: frozenset(
        {TaskStatus.COMPLETED, TaskStatus.RUNNABLE, TaskStatus.ESCALATED}
    ),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
    TaskStatus.ESCALATED: frozenset(),
    TaskStatus.FAILED: frozenset(),
}


def assert_task_transition(source: TaskStatus, target: TaskStatus) -> None:
    if target not in _ALLOWED_TRANSITIONS[source]:
        raise DomainViolation(
            DomainErrorCode.INVALID_TRANSITION,
            f"task transition {source.value}->{target.value} is not allowed",
        )


@dataclass(frozen=True, slots=True)
class ReleaseRef:
    graph_version: str
    domain_pack_version: str
    context_policy_version: str
    policy_version: str
    tool_schema_set: str

    def __post_init__(self) -> None:
        for field, value in (
            ("release.graph_version", self.graph_version),
            ("release.domain_pack_version", self.domain_pack_version),
            ("release.context_policy_version", self.context_policy_version),
            ("release.policy_version", self.policy_version),
            ("release.tool_schema_set", self.tool_schema_set),
        ):
            require_text(value, field, maximum=128)

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> ReleaseRef:
        require_exact_keys(
            value,
            required={
                "graph_version",
                "domain_pack_version",
                "context_policy_version",
                "policy_version",
                "tool_schema_set",
            },
            optional=set(),
            field="release",
        )
        return cls(**value)

    def to_mapping(self) -> dict[str, str]:
        return {
            "graph_version": self.graph_version,
            "domain_pack_version": self.domain_pack_version,
            "context_policy_version": self.context_policy_version,
            "policy_version": self.policy_version,
            "tool_schema_set": self.tool_schema_set,
        }


@dataclass(frozen=True, slots=True)
class WaitingOn:
    type: WaitingType
    request_id: str
    expires_at: datetime | None

    def __post_init__(self) -> None:
        require_text(self.request_id, "waiting_on.request_id", maximum=256)
        if self.expires_at is not None:
            object.__setattr__(
                self,
                "expires_at",
                ensure_utc(self.expires_at, "waiting_on.expires_at"),
            )

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> WaitingOn:
        require_exact_keys(
            value,
            required={"type", "request_id", "expires_at"},
            optional=set(),
            field="waiting_on",
        )
        try:
            waiting_type = WaitingType(value["type"])
        except ValueError as exc:
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "waiting_on.type is not part of the v1 contract",
            ) from exc
        expires_at = value["expires_at"]
        return cls(
            type=waiting_type,
            request_id=value["request_id"],
            expires_at=(
                ensure_utc(expires_at, "waiting_on.expires_at")
                if expires_at is not None
                else None
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "request_id": self.request_id,
            "expires_at": (
                format_utc(self.expires_at) if self.expires_at is not None else None
            ),
        }


@dataclass(frozen=True, slots=True)
class TaskFailure:
    code: str
    retryable: bool
    detail_ref: str | None = None

    def __post_init__(self) -> None:
        require_text(self.code, "error.code", maximum=128)
        if self.detail_ref is not None and len(self.detail_ref) > 512:
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "error.detail_ref exceeds 512 characters",
            )

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> TaskFailure:
        require_exact_keys(
            value,
            required={"code", "retryable"},
            optional={"detail_ref"},
            field="error",
        )
        if not isinstance(value["retryable"], bool):
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "error.retryable must be a boolean",
            )
        return cls(
            code=value["code"],
            retryable=value["retryable"],
            detail_ref=value.get("detail_ref"),
        )

    def to_mapping(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.code,
            "retryable": self.retryable,
        }
        if self.detail_ref is not None:
            result["detail_ref"] = self.detail_ref
        return result


@dataclass(frozen=True, slots=True)
class Task:
    task_id: str
    thread_id: str
    tenant_id: str
    status: TaskStatus
    version: int
    run_generation: int
    purpose: str
    data_classification: DataClassification
    security_context: SecurityContextRef
    release: ReleaseRef
    waiting_on: WaitingOn | None
    result_ref: str | None
    error: TaskFailure | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    active_run_id: str | None = None
    latest_checkpoint_id: str | None = None
    domain: str | None = None
    intent: str | None = None
    risk_level: RiskLevel | None = None

    def __post_init__(self) -> None:
        require_identifier(
            self.task_id, "task_id", r"^task_[A-Za-z0-9_-]{8,128}$"
        )
        require_identifier(
            self.thread_id, "thread_id", r"^thread_[A-Za-z0-9_-]{8,128}$"
        )
        require_text(self.tenant_id, "tenant_id", maximum=128)
        require_text(self.purpose, "purpose", maximum=256)
        for field, integer_value in (
            ("version", self.version),
            ("run_generation", self.run_generation),
        ):
            if (
                isinstance(integer_value, bool)
                or not isinstance(integer_value, int)
                or not 0 <= integer_value <= MAX_SAFE_INTEGER
            ):
                raise DomainViolation(
                    DomainErrorCode.CONTRACT_VIOLATION,
                    f"{field} must be a safe non-negative integer",
                )
        if self.active_run_id is not None:
            require_identifier(
                self.active_run_id,
                "active_run_id",
                r"^run_[A-Za-z0-9_-]{8,128}$",
            )
        for field, optional_text, maximum in (
            ("latest_checkpoint_id", self.latest_checkpoint_id, 256),
            ("domain", self.domain, 128),
            ("intent", self.intent, 128),
            ("result_ref", self.result_ref, 512),
        ):
            if optional_text is not None and (
                not isinstance(optional_text, str)
                or len(optional_text) > maximum
            ):
                raise DomainViolation(
                    DomainErrorCode.CONTRACT_VIOLATION,
                    f"{field} exceeds {maximum} characters",
                )
        if (
            self.tenant_id != self.security_context.tenant_id
            or self.purpose != self.security_context.purpose
        ):
            raise DomainViolation(
                DomainErrorCode.SECURITY_BINDING_MISMATCH,
                "task does not match its trusted security context",
            )
        created_at = ensure_utc(self.created_at, "created_at")
        updated_at = ensure_utc(self.updated_at, "updated_at")
        completed_at = (
            ensure_utc(self.completed_at, "completed_at")
            if self.completed_at is not None
            else None
        )
        if updated_at < created_at:
            raise DomainViolation(
                DomainErrorCode.INVALID_STATE,
                "updated_at cannot precede created_at",
            )
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)
        object.__setattr__(self, "completed_at", completed_at)
        self._validate_state_projection()

    def _validate_state_projection(self) -> None:
        expected_wait = {
            TaskStatus.WAITING_USER: WaitingType.USER_INPUT,
            TaskStatus.WAITING_APPROVAL: WaitingType.APPROVAL,
        }.get(self.status)
        if expected_wait is None:
            if self.waiting_on is not None:
                raise DomainViolation(
                    DomainErrorCode.INVALID_STATE,
                    "non-waiting task cannot carry waiting_on",
                )
        elif self.waiting_on is None or self.waiting_on.type is not expected_wait:
            raise DomainViolation(
                DomainErrorCode.INVALID_STATE,
                "waiting_on does not match the task status",
            )
        if self.status is TaskStatus.COMPLETED:
            if not self.result_ref or self.error is not None:
                raise DomainViolation(
                    DomainErrorCode.INVALID_STATE,
                    "completed task requires a result and no error",
                )
        elif self.result_ref is not None:
            raise DomainViolation(
                DomainErrorCode.INVALID_STATE,
                "only completed tasks can carry result_ref",
            )
        if self.status is TaskStatus.FAILED and self.error is None:
            raise DomainViolation(
                DomainErrorCode.INVALID_STATE,
                "failed task requires an error",
            )
        if (
            self.status not in {TaskStatus.FAILED, TaskStatus.ESCALATED}
            and self.error is not None
        ):
            raise DomainViolation(
                DomainErrorCode.INVALID_STATE,
                "this task status cannot carry an error",
            )
        if (self.status in TERMINAL_STATUSES) != (self.completed_at is not None):
            raise DomainViolation(
                DomainErrorCode.INVALID_STATE,
                "completed_at does not match terminal task status",
            )

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> Task:
        required = {
            "task_id",
            "thread_id",
            "tenant_id",
            "status",
            "version",
            "run_generation",
            "purpose",
            "data_classification",
            "security_context",
            "release",
            "waiting_on",
            "result_ref",
            "error",
            "created_at",
            "updated_at",
            "completed_at",
        }
        require_exact_keys(
            value,
            required=required,
            optional={
                "active_run_id",
                "latest_checkpoint_id",
                "domain",
                "intent",
                "risk_level",
            },
            field="task",
        )
        try:
            status = TaskStatus(value["status"])
            classification = DataClassification(value["data_classification"])
            risk_level = (
                RiskLevel(value["risk_level"])
                if value.get("risk_level") is not None
                else None
            )
        except ValueError as exc:
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "task enum is not part of the v1 contract",
            ) from exc
        waiting = value["waiting_on"]
        error = value["error"]
        security_context = value["security_context"]
        release = value["release"]
        if waiting is not None and not isinstance(waiting, dict):
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "waiting_on must be an object or null",
            )
        if error is not None and not isinstance(error, dict):
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "error must be an object or null",
            )
        if not isinstance(security_context, dict) or not isinstance(release, dict):
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "security_context and release must be objects",
            )
        return cls(
            task_id=value["task_id"],
            thread_id=value["thread_id"],
            tenant_id=value["tenant_id"],
            status=status,
            version=value["version"],
            run_generation=value["run_generation"],
            active_run_id=value.get("active_run_id"),
            latest_checkpoint_id=value.get("latest_checkpoint_id"),
            domain=value.get("domain"),
            intent=value.get("intent"),
            risk_level=risk_level,
            purpose=value["purpose"],
            data_classification=classification,
            security_context=SecurityContextRef.from_mapping(security_context),
            release=ReleaseRef.from_mapping(release),
            waiting_on=WaitingOn.from_mapping(waiting) if waiting else None,
            result_ref=value["result_ref"],
            error=TaskFailure.from_mapping(error) if error else None,
            created_at=ensure_utc(value["created_at"], "created_at"),
            updated_at=ensure_utc(value["updated_at"], "updated_at"),
            completed_at=(
                ensure_utc(value["completed_at"], "completed_at")
                if value["completed_at"] is not None
                else None
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "task_id": self.task_id,
            "thread_id": self.thread_id,
            "tenant_id": self.tenant_id,
            "status": self.status.value,
            "version": self.version,
            "run_generation": self.run_generation,
            "purpose": self.purpose,
            "data_classification": self.data_classification.value,
            "security_context": self.security_context.to_mapping(),
            "release": self.release.to_mapping(),
            "waiting_on": (
                self.waiting_on.to_mapping() if self.waiting_on is not None else None
            ),
            "result_ref": self.result_ref,
            "error": self.error.to_mapping() if self.error is not None else None,
            "created_at": format_utc(self.created_at),
            "updated_at": format_utc(self.updated_at),
            "completed_at": (
                format_utc(self.completed_at)
                if self.completed_at is not None
                else None
            ),
        }
        for field in (
            "active_run_id",
            "latest_checkpoint_id",
            "domain",
            "intent",
        ):
            value = getattr(self, field)
            if value is not None:
                result[field] = value
        if self.risk_level is not None:
            result["risk_level"] = self.risk_level.value
        return result
