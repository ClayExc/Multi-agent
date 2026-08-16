"""Closed, display-safe views for the governance query API.

The browser never receives these JSON documents.  The live shell validates the
closed API projection here and renders only the fields represented by these
immutable views.  Tenant, subject, role, raw policy input/output and credentials
therefore cannot become browser authority or display data.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .models import ShellContractError

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}$")
_BOUNDED = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_CURSOR = re.compile(r"^gcur_[A-Za-z0-9_-]{24,508}$")
_CORRELATION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_DECISION_ID = re.compile(r"^pd_[A-Za-z0-9_-]{8,128}$")
_EVENT_ID = re.compile(r"^evt_[A-Za-z0-9_-]{8,128}$")
_SECURITY_EVENT_ID = re.compile(r"^sevt_[A-Za-z0-9_-]{8,128}$")
_CREDENTIAL = re.compile(
    r"(?:sk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{8,}"
    r"|xox[baprs]-[A-Za-z0-9_-]{8,}"
    r"|xapp-[0-9]+-[A-Za-z0-9_-]{8,}"
    r"|gh[pousr]_[A-Za-z0-9_]{8,}"
    r"|github_pat_[A-Za-z0-9_]{8,}"
    r"|glpat-[A-Za-z0-9_-]{8,}"
    r"|hf_[A-Za-z0-9]{8,}"
    r"|AIza[A-Za-z0-9_-]{16,}"
    r"|(?:AKIA|ASIA)[A-Z0-9]{12,}"
    r"|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})",
    re.IGNORECASE,
)

_CLASSIFICATIONS = frozenset({"public", "internal", "confidential", "restricted"})
_POLICY_DECISIONS = frozenset({"allow", "deny", "require_approval"})
_AUDIT_DECISIONS = _POLICY_DECISIONS | {"not_applicable"}
_AUDIT_RESULTS = frozenset({"success", "failure", "blocked", "unknown"})
_SEVERITIES = frozenset({"info", "low", "medium", "high", "critical"})
_CONTROL_OUTCOMES = frozenset({"blocked", "allowed", "not_applicable", "unknown"})
_IMPACTS = frozenset({"none", "attempted", "suspected", "confirmed", "unknown"})
_DISPOSITIONS = frozenset(
    {"open", "contained", "escalated", "resolved", "false_positive"}
)
_TABS = frozenset({"versions", "decisions", "audit", "security"})
_QUERY_FIELDS = frozenset(
    {
        "tab",
        "limit",
        "cursor",
        "task_id",
        "correlation_id",
        "occurred_after",
        "occurred_before",
    }
)


@dataclass(frozen=True, slots=True)
class GovernanceQuery:
    tab: str = "versions"
    limit: int = 20
    cursor: str | None = None
    task_id: str | None = None
    correlation_id: str | None = None
    occurred_after: str | None = None
    occurred_before: str | None = None

    @classmethod
    def from_http_query(cls, query: dict[str, list[str]]) -> GovernanceQuery:
        if set(query) - _QUERY_FIELDS:
            raise ShellContractError("governance query contains unknown fields")
        if any(len(values) != 1 for values in query.values()):
            raise ShellContractError("governance query fields must be unique")
        flat = {name: values[0] for name, values in query.items()}
        tab = flat.get("tab", "versions")
        if tab not in _TABS:
            raise ShellContractError("governance query tab is invalid")
        raw_limit = flat.get("limit", "20")
        if not raw_limit.isascii() or not raw_limit.isdecimal():
            raise ShellContractError("governance query limit is invalid")
        limit = int(raw_limit)
        if not 1 <= limit <= 100:
            raise ShellContractError("governance query limit is invalid")
        cursor = flat.get("cursor")
        if cursor is not None:
            cursor = _pattern(cursor, _CURSOR, "governance query cursor")
        task_id = flat.get("task_id")
        if task_id is not None:
            task_id = _pattern(
                task_id,
                re.compile(r"^task_[A-Za-z0-9_-]{8,128}$"),
                "governance query task_id",
            )
        correlation_id = flat.get("correlation_id")
        if correlation_id is not None:
            correlation_id = _pattern(
                correlation_id, _CORRELATION, "governance query correlation_id"
            )
        occurred_after = flat.get("occurred_after")
        if occurred_after is not None:
            occurred_after = _timestamp(
                occurred_after, "governance query occurred_after"
            )
        occurred_before = flat.get("occurred_before")
        if occurred_before is not None:
            occurred_before = _timestamp(
                occurred_before, "governance query occurred_before"
            )
        if (
            occurred_after is not None
            and occurred_before is not None
            and datetime.fromisoformat(occurred_after.replace("Z", "+00:00"))
            >= datetime.fromisoformat(occurred_before.replace("Z", "+00:00"))
        ):
            raise ShellContractError(
                "governance query time range must be strictly increasing"
            )
        return cls(
            tab=tab,
            limit=limit,
            cursor=cursor,
            task_id=task_id,
            correlation_id=correlation_id,
            occurred_after=occurred_after,
            occurred_before=occurred_before,
        )

    def cursor_for(self, tab: str) -> str | None:
        return self.cursor if self.tab == tab else None

    def href(self, *, tab: str, cursor: str | None = None) -> str:
        if tab not in _TABS:
            raise ShellContractError("governance tab is invalid")
        values: dict[str, str | int] = {"tab": tab, "limit": self.limit}
        if cursor is not None:
            values["cursor"] = _pattern(cursor, _CURSOR, "governance cursor")
        if self.task_id is not None:
            values["task_id"] = self.task_id
        if self.correlation_id is not None:
            values["correlation_id"] = self.correlation_id
        if self.occurred_after is not None:
            values["occurred_after"] = self.occurred_after
        if self.occurred_before is not None:
            values["occurred_before"] = self.occurred_before
        return "#/governance?" + urllib.parse.urlencode(values)


def parse_correlation_id(value: str) -> str:
    return _pattern(value, _CORRELATION, "governance correlation id")


@dataclass(frozen=True, slots=True)
class PolicyVersionView:
    version: str
    bundle_digest: str
    active: bool
    parent_version: str | None
    published_at: str
    revoked_at: str | None
    rollback_of: str | None


@dataclass(frozen=True, slots=True)
class PolicyDecisionView:
    decision_id: str
    task_id: str
    decision: str
    policy_version: str
    reason_codes: tuple[str, ...]
    obligation_names: tuple[str, ...]
    action_digest: str
    evaluated_at: str
    expires_at: str


@dataclass(frozen=True, slots=True)
class AuditEventView:
    event_id: str
    event_type: str
    occurred_at: str
    trace_id: str
    thread_id: str
    task_id: str
    run_id: str | None
    correlation_id: str
    causation_id: str | None
    action: str
    decision: str
    reason_codes: tuple[str, ...]
    result: str
    data_classification: str
    stream_id: str
    sequence: int
    event_hash: str
    previous_hash: str | None
    policy_decision_id: str | None
    policy_version: str | None
    approval_id: str | None
    action_digest: str | None
    tool_execution_id: str | None
    security_event_id: str | None


@dataclass(frozen=True, slots=True)
class SecurityEventView:
    event_id: str
    event_type: str
    occurred_at: str
    trace_id: str
    thread_id: str | None
    task_id: str | None
    run_id: str | None
    correlation_id: str
    causation_id: str | None
    control_component: str
    control_rule_id: str
    control_rule_version: str
    reason_codes: tuple[str, ...]
    severity: str
    category: str
    control_outcome: str
    impact: str
    disposition: str
    data_classification: str
    policy_decision_id: str | None
    audit_event_id: str
    event_hash: str


@dataclass(frozen=True, slots=True)
class GovernanceSnapshot:
    policy_versions: tuple[PolicyVersionView, ...]
    policy_versions_cursor: str | None
    policy_decisions: tuple[PolicyDecisionView, ...]
    policy_decisions_cursor: str | None
    audit_events: tuple[AuditEventView, ...]
    audit_events_cursor: str | None
    security_events: tuple[SecurityEventView, ...]
    security_events_cursor: str | None

    def __post_init__(self) -> None:
        if sum(item.active for item in self.policy_versions) > 1:
            raise ShellContractError(
                "governance projection contains multiple active policy versions"
            )


@dataclass(frozen=True, slots=True)
class GovernanceCorrelationView:
    correlation_id: str
    policy_decisions: tuple[PolicyDecisionView, ...]
    audit_events: tuple[AuditEventView, ...]
    security_events: tuple[SecurityEventView, ...]


def parse_policy_version_page(
    payload: dict[str, Any],
) -> tuple[tuple[PolicyVersionView, ...], str | None]:
    items, cursor = _page(payload, "policy version page")
    return tuple(_policy_version(item) for item in items), cursor


def parse_policy_decision_page(
    payload: dict[str, Any],
) -> tuple[tuple[PolicyDecisionView, ...], str | None]:
    items, cursor = _page(payload, "policy decision page")
    return tuple(_policy_decision(item) for item in items), cursor


def parse_audit_event_page(
    payload: dict[str, Any],
) -> tuple[tuple[AuditEventView, ...], str | None]:
    items, cursor = _page(payload, "audit event page")
    return tuple(_audit_event(item) for item in items), cursor


def parse_security_event_page(
    payload: dict[str, Any],
) -> tuple[tuple[SecurityEventView, ...], str | None]:
    items, cursor = _page(payload, "security event page")
    return tuple(_security_event(item) for item in items), cursor


def parse_correlation(payload: dict[str, Any]) -> GovernanceCorrelationView:
    label = "governance correlation"
    _closed(
        payload,
        {"correlation_id", "policy_decisions", "audit_events", "security_events"},
        label,
    )
    correlation_id = _pattern(
        payload["correlation_id"], _CORRELATION, f"{label}.correlation_id"
    )
    decisions = tuple(
        _policy_decision(item)
        for item in _object_list(
            payload["policy_decisions"], f"{label}.policy_decisions"
        )
    )
    audits = tuple(
        _audit_event(item)
        for item in _object_list(payload["audit_events"], f"{label}.audit_events")
    )
    security = tuple(
        _security_event(item)
        for item in _object_list(payload["security_events"], f"{label}.security_events")
    )
    if any(item.correlation_id != correlation_id for item in audits) or any(
        item.correlation_id != correlation_id for item in security
    ):
        raise ShellContractError(
            "governance correlation contains an event from another correlation"
        )
    decision_ids = {item.decision_id for item in decisions}
    audit_ids = {item.event_id for item in audits}
    security_ids = {item.event_id for item in security}
    unresolved_audit_decision = any(
        item.policy_decision_id is not None
        and item.policy_decision_id not in decision_ids
        for item in audits
    )
    unresolved_security_decision = any(
        item.policy_decision_id is not None
        and item.policy_decision_id not in decision_ids
        for item in security
    )
    if unresolved_audit_decision or unresolved_security_decision:
        raise ShellContractError(
            "governance correlation contains an unresolved policy decision"
        )
    if any(item.audit_event_id not in audit_ids for item in security):
        raise ShellContractError(
            "governance correlation contains an unresolved audit event"
        )
    if any(
        item.security_event_id is not None
        and item.security_event_id not in security_ids
        for item in audits
    ):
        raise ShellContractError(
            "governance correlation contains an unresolved security event"
        )
    return GovernanceCorrelationView(
        correlation_id=correlation_id,
        policy_decisions=decisions,
        audit_events=audits,
        security_events=security,
    )


def _policy_version(value: dict[str, Any]) -> PolicyVersionView:
    label = "policy version"
    _closed(
        value,
        {
            "version",
            "bundle_digest",
            "active",
            "parent_version",
            "published_at",
            "revoked_at",
            "rollback_of",
        },
        label,
    )
    active = value["active"]
    if type(active) is not bool:
        raise ShellContractError(f"{label}.active must be a boolean")
    return PolicyVersionView(
        version=_bounded(value["version"], f"{label}.version"),
        bundle_digest=_digest(value["bundle_digest"], f"{label}.bundle_digest"),
        active=active,
        parent_version=_optional_bounded(
            value["parent_version"], f"{label}.parent_version"
        ),
        published_at=_timestamp(value["published_at"], f"{label}.published_at"),
        revoked_at=_optional_timestamp(value["revoked_at"], f"{label}.revoked_at"),
        rollback_of=_optional_bounded(value["rollback_of"], f"{label}.rollback_of"),
    )


def _policy_decision(value: dict[str, Any]) -> PolicyDecisionView:
    label = "policy decision"
    _closed(
        value,
        {
            "decision_id",
            "task_id",
            "decision",
            "policy_version",
            "reason_codes",
            "obligation_names",
            "action_digest",
            "evaluated_at",
            "expires_at",
        },
        label,
    )
    return PolicyDecisionView(
        decision_id=_pattern(
            value["decision_id"], _DECISION_ID, f"{label}.decision_id"
        ),
        task_id=_pattern(
            value["task_id"],
            re.compile(r"^task_[A-Za-z0-9_-]{8,128}$"),
            f"{label}.task_id",
        ),
        decision=_choice(value["decision"], _POLICY_DECISIONS, f"{label}.decision"),
        policy_version=_bounded(value["policy_version"], f"{label}.policy_version"),
        reason_codes=_bounded_list(value["reason_codes"], f"{label}.reason_codes"),
        obligation_names=_bounded_list(
            value["obligation_names"], f"{label}.obligation_names"
        ),
        action_digest=_digest(value["action_digest"], f"{label}.action_digest"),
        evaluated_at=_timestamp(value["evaluated_at"], f"{label}.evaluated_at"),
        expires_at=_timestamp(value["expires_at"], f"{label}.expires_at"),
    )


def _audit_event(value: dict[str, Any]) -> AuditEventView:
    label = "audit event"
    fields = {
        "event_id",
        "event_type",
        "occurred_at",
        "trace_id",
        "thread_id",
        "task_id",
        "run_id",
        "correlation_id",
        "causation_id",
        "action",
        "decision",
        "reason_codes",
        "result",
        "data_classification",
        "stream_id",
        "sequence",
        "event_hash",
        "previous_hash",
        "policy_decision_id",
        "policy_version",
        "approval_id",
        "action_digest",
        "tool_execution_id",
        "security_event_id",
    }
    _closed(value, fields, label)
    sequence = value["sequence"]
    if type(sequence) is not int or sequence < 1:
        raise ShellContractError(f"{label}.sequence must be a positive integer")
    return AuditEventView(
        event_id=_pattern(value["event_id"], _EVENT_ID, f"{label}.event_id"),
        event_type=_identifier(value["event_type"], f"{label}.event_type"),
        occurred_at=_timestamp(value["occurred_at"], f"{label}.occurred_at"),
        trace_id=_bounded(value["trace_id"], f"{label}.trace_id"),
        thread_id=_pattern(
            value["thread_id"],
            re.compile(r"^thread_[A-Za-z0-9_-]{8,128}$"),
            f"{label}.thread_id",
        ),
        task_id=_pattern(
            value["task_id"],
            re.compile(r"^task_[A-Za-z0-9_-]{8,128}$"),
            f"{label}.task_id",
        ),
        run_id=_optional_pattern(
            value["run_id"],
            re.compile(r"^run_[A-Za-z0-9_-]{8,128}$"),
            f"{label}.run_id",
        ),
        correlation_id=_pattern(
            value["correlation_id"], _CORRELATION, f"{label}.correlation_id"
        ),
        causation_id=_optional_bounded(value["causation_id"], f"{label}.causation_id"),
        action=_identifier(value["action"], f"{label}.action"),
        decision=_choice(value["decision"], _AUDIT_DECISIONS, f"{label}.decision"),
        reason_codes=_bounded_list(value["reason_codes"], f"{label}.reason_codes"),
        result=_choice(value["result"], _AUDIT_RESULTS, f"{label}.result"),
        data_classification=_choice(
            value["data_classification"],
            _CLASSIFICATIONS,
            f"{label}.data_classification",
        ),
        stream_id=_identifier(value["stream_id"], f"{label}.stream_id"),
        sequence=sequence,
        event_hash=_digest(value["event_hash"], f"{label}.event_hash"),
        previous_hash=_optional_digest(
            value["previous_hash"], f"{label}.previous_hash"
        ),
        policy_decision_id=_optional_pattern(
            value["policy_decision_id"], _DECISION_ID, f"{label}.policy_decision_id"
        ),
        policy_version=_optional_bounded(
            value["policy_version"], f"{label}.policy_version"
        ),
        approval_id=_optional_pattern(
            value["approval_id"],
            re.compile(r"^apr_[A-Za-z0-9_-]{8,128}$"),
            f"{label}.approval_id",
        ),
        action_digest=_optional_digest(
            value["action_digest"], f"{label}.action_digest"
        ),
        tool_execution_id=_optional_pattern(
            value["tool_execution_id"],
            re.compile(r"^tex_[A-Za-z0-9_-]{8,128}$"),
            f"{label}.tool_execution_id",
        ),
        security_event_id=_optional_pattern(
            value["security_event_id"], _SECURITY_EVENT_ID, f"{label}.security_event_id"
        ),
    )


def _security_event(value: dict[str, Any]) -> SecurityEventView:
    label = "security event"
    fields = {
        "event_id",
        "event_type",
        "occurred_at",
        "trace_id",
        "thread_id",
        "task_id",
        "run_id",
        "correlation_id",
        "causation_id",
        "control_component",
        "control_rule_id",
        "control_rule_version",
        "reason_codes",
        "severity",
        "category",
        "control_outcome",
        "impact",
        "disposition",
        "data_classification",
        "policy_decision_id",
        "audit_event_id",
        "event_hash",
    }
    _closed(value, fields, label)
    return SecurityEventView(
        event_id=_pattern(value["event_id"], _SECURITY_EVENT_ID, f"{label}.event_id"),
        event_type=_identifier(value["event_type"], f"{label}.event_type"),
        occurred_at=_timestamp(value["occurred_at"], f"{label}.occurred_at"),
        trace_id=_bounded(value["trace_id"], f"{label}.trace_id"),
        thread_id=_optional_pattern(
            value["thread_id"],
            re.compile(r"^thread_[A-Za-z0-9_-]{8,128}$"),
            f"{label}.thread_id",
        ),
        task_id=_optional_pattern(
            value["task_id"],
            re.compile(r"^task_[A-Za-z0-9_-]{8,128}$"),
            f"{label}.task_id",
        ),
        run_id=_optional_pattern(
            value["run_id"],
            re.compile(r"^run_[A-Za-z0-9_-]{8,128}$"),
            f"{label}.run_id",
        ),
        correlation_id=_pattern(
            value["correlation_id"], _CORRELATION, f"{label}.correlation_id"
        ),
        causation_id=_optional_bounded(value["causation_id"], f"{label}.causation_id"),
        control_component=_bounded(
            value["control_component"], f"{label}.control_component"
        ),
        control_rule_id=_identifier(
            value["control_rule_id"], f"{label}.control_rule_id"
        ),
        control_rule_version=_bounded(
            value["control_rule_version"], f"{label}.control_rule_version"
        ),
        reason_codes=_bounded_list(value["reason_codes"], f"{label}.reason_codes"),
        severity=_choice(value["severity"], _SEVERITIES, f"{label}.severity"),
        category=_bounded(value["category"], f"{label}.category"),
        control_outcome=_choice(
            value["control_outcome"], _CONTROL_OUTCOMES, f"{label}.control_outcome"
        ),
        impact=_choice(value["impact"], _IMPACTS, f"{label}.impact"),
        disposition=_choice(
            value["disposition"], _DISPOSITIONS, f"{label}.disposition"
        ),
        data_classification=_choice(
            value["data_classification"],
            _CLASSIFICATIONS,
            f"{label}.data_classification",
        ),
        policy_decision_id=_optional_pattern(
            value["policy_decision_id"], _DECISION_ID, f"{label}.policy_decision_id"
        ),
        audit_event_id=_pattern(
            value["audit_event_id"], _EVENT_ID, f"{label}.audit_event_id"
        ),
        event_hash=_digest(value["event_hash"], f"{label}.event_hash"),
    )


def _page(value: dict[str, Any], label: str) -> tuple[list[dict[str, Any]], str | None]:
    _closed(value, {"items", "next_cursor"}, label)
    cursor = value["next_cursor"]
    if cursor is not None:
        cursor = _pattern(cursor, _CURSOR, f"{label}.next_cursor")
    return _object_list(value["items"], f"{label}.items"), cursor


def _closed(value: dict[str, Any], fields: set[str], label: str) -> None:
    if set(value) != fields:
        raise ShellContractError(f"{label} does not match the closed projection")


def _object_list(value: object, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ShellContractError(f"{label} must be a list")
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict) or not all(isinstance(key, str) for key in item):
            raise ShellContractError(f"{label} entries must be objects")
        result.append(item)
    return result


def _bounded_list(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ShellContractError(f"{label} must be a list")
    return tuple(_bounded(item, label) for item in value)


def _bounded(value: object, label: str) -> str:
    return _pattern(value, _BOUNDED, label)


def _identifier(value: object, label: str) -> str:
    return _pattern(value, _IDENTIFIER, label)


def _digest(value: object, label: str) -> str:
    return _pattern(value, _DIGEST, label)


def _optional_bounded(value: object, label: str) -> str | None:
    return None if value is None else _bounded(value, label)


def _optional_digest(value: object, label: str) -> str | None:
    return None if value is None else _digest(value, label)


def _optional_pattern(
    value: object, pattern: re.Pattern[str], label: str
) -> str | None:
    return None if value is None else _pattern(value, pattern, label)


def _pattern(value: object, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ShellContractError(f"{label} is invalid")
    if _CREDENTIAL.search(value):
        raise ShellContractError(f"{label} contains prohibited credential material")
    return value


def _choice(value: object, choices: frozenset[str], label: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ShellContractError(f"{label} is invalid")
    return value


def _timestamp(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise ShellContractError(f"{label} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ShellContractError(f"{label} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ShellContractError(f"{label} must include a timezone")
    return value


def _optional_timestamp(value: object, label: str) -> str | None:
    return None if value is None else _timestamp(value, label)
