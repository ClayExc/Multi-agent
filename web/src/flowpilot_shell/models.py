"""Contract-adapted view models for the web shell.

Each view validates the exact shape the apps/api v1 contracts emit and
rejects unknown fields, mirroring the API's StrictModel discipline. This is
the shell-side contract adaptation boundary; the official JSON schemas and
the application/domain constructors remain the authoritative conformance
check (see tests/experience/test_fixture_contract.py).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, overload

_TASK_STATUSES = frozenset(
    {
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
    }
)
_EVENT_TYPES = frozenset(
    {
        "task.created.v1",
        "task.status.changed.v1",
        "task.input.required.v1",
        "task.approval.required.v1",
        "task.approval.decided.v1",
        "task.tool_execution.updated.v1",
        "task.completed.v1",
        "task.failed.v1",
        "task.escalated.v1",
    }
)
_APPROVAL_STATUSES = frozenset(
    {"pending", "approved", "rejected", "expired", "revoked"}
)
_CLASSIFICATIONS = frozenset({"public", "internal", "confidential", "restricted"})
_TASK_ID_PATTERN = re.compile(r"^task_[A-Za-z0-9_-]{8,128}$")
_EVT_ID_PATTERN = re.compile(r"^evt_[A-Za-z0-9_-]{8,128}$")
_APR_ID_PATTERN = re.compile(r"^apr_[A-Za-z0-9_-]{8,128}$")
_ACT_ID_PATTERN = re.compile(r"^act_[A-Za-z0-9_-]{8,128}$")
_SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")


class ShellError(Exception):
    """Base class for shell adapter errors."""


class ShellContractError(ShellError):
    """A payload does not match the v1 contract shape the shell adapts."""


class ShellNotFoundError(ShellError):
    """The API answered 404 for a tenant-scoped resource."""


class ShellUnavailableError(ShellError):
    """The API/SSE source is unavailable; retry is meaningful."""


class ShellServerError(ShellError):
    """The API answered a non-retryable server error."""

    def __init__(self, message: str, *, code: str, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class WaitingOnView:
    type: str
    request_id: str
    expires_at: datetime | None

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any] | None
    ) -> WaitingOnView | None:
        if value is None:
            return None
        _require_keys(value, {"type", "request_id", "expires_at"}, "waiting_on")
        wait_type = value["type"]
        if wait_type not in {"user_input", "approval"}:
            raise ShellContractError("waiting_on.type is not a v1 value")
        expires = _parse_dt(value["expires_at"], "waiting_on.expires_at", nullable=True)
        return cls(
            type=wait_type,
            request_id=_text(value["request_id"], "waiting_on.request_id", 256),
            expires_at=expires,
        )


@dataclass(frozen=True, slots=True)
class TaskErrorView:
    code: str
    retryable: bool
    detail_ref: str | None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> TaskErrorView | None:
        if value is None:
            return None
        _require_keys(value, {"code", "retryable"}, "error", optional={"detail_ref"})
        return cls(
            code=_text(value["code"], "error.code", 128),
            retryable=_require_bool(value["retryable"], "error.retryable"),
            detail_ref=_optional_text(value.get("detail_ref"), "error.detail_ref", 512),
        )


@dataclass(frozen=True, slots=True)
class TaskView:
    task_id: str
    thread_id: str
    tenant_id: str
    status: str
    version: int
    run_generation: int
    purpose: str
    data_classification: str
    risk_level: str | None
    waiting_on: WaitingOnView | None
    result_ref: str | None
    error: TaskErrorView | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    active_run_id: str | None
    intent: str | None

    _REQUIRED = {
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
    _OPTIONAL = {
        "active_run_id",
        "latest_checkpoint_id",
        "domain",
        "intent",
        "risk_level",
    }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> TaskView:
        _require_keys(value, cls._REQUIRED, "task", optional=cls._OPTIONAL)
        status = value["status"]
        if status not in _TASK_STATUSES:
            raise ShellContractError("task.status is not a v1 value")
        classification = value["data_classification"]
        if classification not in _CLASSIFICATIONS:
            raise ShellContractError("task.data_classification is not a v1 value")
        risk = value.get("risk_level")
        if risk is not None and risk not in {
            "low",
            "medium",
            "high",
            "critical",
        }:
            raise ShellContractError("task.risk_level is not a v1 value")
        return cls(
            task_id=_identifier(value["task_id"], "task_id", _TASK_ID_PATTERN),
            thread_id=_text(value["thread_id"], "thread_id", 128),
            tenant_id=_text(value["tenant_id"], "tenant_id", 128),
            status=status,
            version=_safe_int(value["version"], "version"),
            run_generation=_safe_int(value["run_generation"], "run_generation"),
            purpose=_text(value["purpose"], "purpose", 256),
            data_classification=classification,
            risk_level=risk,
            waiting_on=WaitingOnView.from_mapping(value["waiting_on"]),
            result_ref=_optional_text(value["result_ref"], "result_ref", 512),
            error=TaskErrorView.from_mapping(value["error"]),
            created_at=_parse_dt(value["created_at"], "created_at"),
            updated_at=_parse_dt(value["updated_at"], "updated_at"),
            completed_at=_parse_dt(
                value["completed_at"], "completed_at", nullable=True
            ),
            active_run_id=_optional_text(
                value.get("active_run_id"), "active_run_id", 128
            ),
            intent=_optional_text(value.get("intent"), "intent", 128),
        )


@dataclass(frozen=True, slots=True)
class EventView:
    event_id: str
    event_type: str
    tenant_id: str
    task_id: str
    thread_id: str
    task_version: int
    sequence: int
    trace_id: str
    run_id: str
    producer: str
    correlation_id: str
    data_classification: str
    payload: Mapping[str, Any]
    occurred_at: datetime

    _REQUIRED = {
        "event_id",
        "event_type",
        "tenant_id",
        "task_id",
        "thread_id",
        "task_version",
        "sequence",
        "trace_id",
        "run_id",
        "producer",
        "producer_principal_ref",
        "correlation_id",
        "causation_id",
        "data_classification",
        "payload",
        "occurred_at",
    }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> EventView:
        _require_keys(value, cls._REQUIRED, "event")
        event_type = value["event_type"]
        if event_type not in _EVENT_TYPES:
            raise ShellContractError("event.event_type is not a v1 value")
        classification = value["data_classification"]
        if classification not in _CLASSIFICATIONS:
            raise ShellContractError("event.data_classification is not a v1 value")
        payload = value["payload"]
        if not isinstance(payload, Mapping):
            raise ShellContractError("event.payload must be an object")
        return cls(
            event_id=_identifier(value["event_id"], "event_id", _EVT_ID_PATTERN),
            event_type=event_type,
            tenant_id=_text(value["tenant_id"], "tenant_id", 128),
            task_id=_identifier(value["task_id"], "task_id", _TASK_ID_PATTERN),
            thread_id=_text(value["thread_id"], "thread_id", 128),
            task_version=_safe_int(value["task_version"], "task_version"),
            sequence=_positive_int(value["sequence"], "sequence"),
            trace_id=_text(value["trace_id"], "trace_id", 128),
            run_id=_text(value["run_id"], "run_id", 128),
            producer=_text(value["producer"], "producer", 64),
            correlation_id=_text(value["correlation_id"], "correlation_id", 128),
            data_classification=classification,
            payload=dict(payload),
            occurred_at=_parse_dt(value["occurred_at"], "occurred_at"),
        )


@dataclass(frozen=True, slots=True)
class ApprovalView:
    approval_id: str
    tenant_id: str
    task_id: str
    requester_id: str
    action_id: str
    action_digest: str
    policy_decision_id: str
    policy_version: str
    status: str
    approver_id: str | None
    decision_reason: str | None
    separation_of_duties_result: bool | None
    requested_at: datetime
    decided_at: datetime | None
    expires_at: datetime

    _REQUIRED = {
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
    }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ApprovalView:
        _require_keys(value, cls._REQUIRED, "approval")
        status = value["status"]
        if status not in _APPROVAL_STATUSES:
            raise ShellContractError("approval.status is not a v1 value")
        return cls(
            approval_id=_identifier(
                value["approval_id"], "approval_id", _APR_ID_PATTERN
            ),
            tenant_id=_text(value["tenant_id"], "tenant_id", 128),
            task_id=_identifier(value["task_id"], "task_id", _TASK_ID_PATTERN),
            requester_id=_text(value["requester_id"], "requester_id", 256),
            action_id=_identifier(value["action_id"], "action_id", _ACT_ID_PATTERN),
            action_digest=_sha256(value["action_digest"], "action_digest"),
            policy_decision_id=_text(
                value["policy_decision_id"], "policy_decision_id", 128
            ),
            policy_version=_text(value["policy_version"], "policy_version", 128),
            status=status,
            approver_id=_optional_text(value["approver_id"], "approver_id", 256),
            decision_reason=_optional_text(
                value["decision_reason"], "decision_reason", 2000
            ),
            separation_of_duties_result=_optional_bool(
                value["separation_of_duties_result"], "separation_of_duties_result"
            ),
            requested_at=_parse_dt(value["requested_at"], "requested_at"),
            decided_at=_parse_dt(value["decided_at"], "decided_at", nullable=True),
            expires_at=_parse_dt(value["expires_at"], "expires_at"),
        )


@dataclass(frozen=True, slots=True)
class PlannedActionView:
    action_id: str
    tenant_id: str
    task_id: str
    requester_id: str
    agent_id: str
    agent_version: str
    tool_name: str
    tool_schema_hash: str
    tool_operation: str
    arguments: Mapping[str, Any]
    resource_type: str
    resource_id: str | None
    resource_owner_id: str | None
    purpose: str
    data_classification: str
    policy_version: str
    expires_at: datetime

    _REQUIRED = {
        "action_id",
        "tenant_id",
        "task_id",
        "requester_id",
        "agent",
        "tool",
        "arguments",
        "resource",
        "purpose",
        "data_classification",
        "policy_version",
        "expires_at",
    }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> PlannedActionView:
        _require_keys(value, cls._REQUIRED, "planned action")
        agent = value["agent"]
        tool = value["tool"]
        resource = value["resource"]
        if not isinstance(agent, Mapping) or not isinstance(tool, Mapping):
            raise ShellContractError("planned action agent/tool must be objects")
        if not isinstance(resource, Mapping):
            raise ShellContractError("planned action resource must be an object")
        arguments = value["arguments"]
        if not isinstance(arguments, Mapping):
            raise ShellContractError("planned action arguments must be an object")
        classification = value["data_classification"]
        if classification not in _CLASSIFICATIONS:
            raise ShellContractError(
                "planned action data_classification is not a v1 value"
            )
        operation = tool.get("operation")
        if operation not in {"read", "write"}:
            raise ShellContractError("planned action tool.operation is not a v1 value")
        return cls(
            action_id=_identifier(value["action_id"], "action_id", _ACT_ID_PATTERN),
            tenant_id=_text(value["tenant_id"], "tenant_id", 128),
            task_id=_identifier(value["task_id"], "task_id", _TASK_ID_PATTERN),
            requester_id=_text(value["requester_id"], "requester_id", 256),
            agent_id=_text(agent.get("id"), "agent.id", 128),
            agent_version=_text(agent.get("version"), "agent.version", 128),
            tool_name=_text(tool.get("name"), "tool.name", 128),
            tool_schema_hash=_sha256(tool.get("schema_hash"), "tool.schema_hash"),
            tool_operation=operation,
            arguments=dict(arguments),
            resource_type=_text(resource.get("type"), "resource.type", 128),
            resource_id=_optional_text(resource.get("id"), "resource.id", 256),
            resource_owner_id=_optional_text(
                resource.get("owner_id"), "resource.owner_id", 256
            ),
            purpose=_text(value["purpose"], "purpose", 256),
            data_classification=classification,
            policy_version=_text(value["policy_version"], "policy_version", 128),
            expires_at=_parse_dt(value["expires_at"], "expires_at"),
        )


@dataclass(frozen=True, slots=True)
class CitationView:
    source_ref: str
    document_version: str
    section: str
    content_hash: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> CitationView:
        _require_keys(
            value,
            {"source_ref", "document_version", "section", "content_hash"},
            "citation",
        )
        return cls(
            source_ref=_text(value["source_ref"], "source_ref", 512),
            document_version=_text(value["document_version"], "document_version", 128),
            section=_text(value["section"], "section", 256),
            content_hash=_sha256(value["content_hash"], "content_hash"),
        )


@dataclass(frozen=True, slots=True)
class ResultArtifactView:
    result_ref: str
    media_type: str
    content: str
    citations: tuple[CitationView, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ResultArtifactView:
        _require_keys(
            value,
            {"result_ref", "media_type", "content", "citations"},
            "result artifact",
        )
        citations = value["citations"]
        if not isinstance(citations, list) or not citations:
            raise ShellContractError("result artifact citations must be non-empty")
        return cls(
            result_ref=_text(value["result_ref"], "result_ref", 512),
            media_type=_text(value["media_type"], "media_type", 64),
            content=_text(value["content"], "content", 65536),
            citations=tuple(CitationView.from_mapping(item) for item in citations),
        )


def _require_keys(
    value: Mapping[str, Any],
    required: set[str],
    label: str,
    optional: set[str] | None = None,
) -> None:
    if not isinstance(value, Mapping):
        raise ShellContractError(f"{label} must be an object")
    missing = required - set(value)
    if missing:
        raise ShellContractError(
            f"{label} is missing required fields: {sorted(missing)}"
        )
    known = required | (optional or set())
    unknown = set(value) - known
    if unknown:
        raise ShellContractError(f"{label} carries unknown fields: {sorted(unknown)}")


def _text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ShellContractError(f"{field} must be a bounded non-empty string")
    return value


def _optional_text(value: object, field: str, maximum: int) -> str | None:
    if value is None:
        return None
    return _text(value, field, maximum)


def _identifier(value: object, field: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ShellContractError(f"{field} has an invalid v1 identifier format")
    return value


def _sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ShellContractError(f"{field} must be a lowercase sha256 digest")
    return value


def _safe_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ShellContractError(f"{field} must be a non-negative integer")
    return value


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ShellContractError(f"{field} must be a positive integer")
    return value


def _require_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ShellContractError(f"{field} must be a boolean")
    return value


def _optional_bool(value: object, field: str) -> bool | None:
    if value is None:
        return None
    return _require_bool(value, field)


@overload
def _parse_dt(
    value: object, field: str, *, nullable: Literal[False] = False
) -> datetime: ...


@overload
def _parse_dt(
    value: object, field: str, *, nullable: Literal[True]
) -> datetime | None: ...


def _parse_dt(value: object, field: str, *, nullable: bool = False) -> datetime | None:
    if value is None:
        if nullable:
            return None
        raise ShellContractError(f"{field} must be a date-time")
    if not isinstance(value, str):
        raise ShellContractError(f"{field} must be a date-time string")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ShellContractError(f"{field} is not a valid date-time") from exc
    if parsed.tzinfo is None:
        raise ShellContractError(f"{field} must be timezone-aware")
    return parsed
