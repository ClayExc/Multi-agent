from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Protocol, Self

from flowpilot_security import SecurityError, assert_safe_projection

from .errors import ApplicationError, ErrorCode

GOVERNANCE_QUERY_PORT_VERSION = "flowpilot.governance-query.m9.v1"
_CURSOR = re.compile(r"^gcur_[A-Za-z0-9_-]{24,508}$")
_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,511}$")
_AUDIT_ID = re.compile(r"^evt_[A-Za-z0-9_-]{8,128}$")
_APPROVAL_ID = re.compile(r"^apr_[A-Za-z0-9_-]{8,128}$")
_POLICY_DECISION_ID = re.compile(r"^pd_[A-Za-z0-9_-]{8,128}$")
_SECURITY_EVENT_ID = re.compile(r"^sevt_[A-Za-z0-9_-]{8,128}$")
_TASK_ID = re.compile(r"^task_[A-Za-z0-9_-]{8,128}$")
_THREAD_ID = re.compile(r"^thread_[A-Za-z0-9_-]{8,128}$")
_TOOL_EXECUTION_ID = re.compile(r"^tex_[A-Za-z0-9_-]{8,128}$")
_RUN_ID = re.compile(r"^run_[A-Za-z0-9_-]{8,128}$")


def _text(value: str, field: str, *, maximum: int = 512) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or _IDENTIFIER.fullmatch(value) is None
    ):
        raise ValueError(f"{field} is not a safe bounded identifier")
    return value


def _optional_text(
    value: str | None,
    field: str,
    *,
    maximum: int = 512,
) -> str | None:
    if value is None:
        return None
    return _text(value, field, maximum=maximum)


def _bounded_text(value: str, field: str, *, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"{field} is not safe bounded text")
    return value


def _digest(value: str | None, field: str) -> str | None:
    if value is not None and _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{field} must be a SHA-256 digest")
    return value


def _required_digest(value: str, field: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{field} must be a SHA-256 digest")
    return value


def _matches(value: str | None, pattern: re.Pattern[str], field: str) -> None:
    if value is not None and pattern.fullmatch(value) is None:
        raise ValueError(f"{field} is not a public identifier")


def _utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _optional_utc(value: datetime | None, field: str) -> datetime | None:
    if value is None:
        return None
    return _utc(value, field)


def _codes(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    if len(values) != len(set(values)) or len(values) > 32:
        raise ValueError(f"{field} must be unique and bounded")
    for value in values:
        _text(value, field, maximum=128)
    return values


@dataclass(frozen=True, slots=True)
class GovernanceQueryContext:
    """Trusted request facts used to bind the read transaction and RLS."""

    tenant_id: str
    subject_id: str
    purpose: str
    security_context_ref: str
    security_context_hash: str

    def __post_init__(self) -> None:
        _bounded_text(self.tenant_id, "context.tenant_id", maximum=128)
        _bounded_text(self.subject_id, "context.subject_id", maximum=256)
        _bounded_text(self.purpose, "context.purpose", maximum=256)
        _bounded_text(
            self.security_context_ref,
            "context.security_context_ref",
            maximum=512,
        )
        _required_digest(self.security_context_hash, "context.security_context_hash")


@dataclass(frozen=True, slots=True)
class GovernancePageRequest:
    limit: int = 50
    cursor: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.limit, bool) or not 1 <= self.limit <= 100:
            raise ValueError("governance page limit must be within 1..100")
        if self.cursor is not None and _CURSOR.fullmatch(self.cursor) is None:
            raise ApplicationError(
                ErrorCode.GOVERNANCE_CURSOR_INVALID,
                "governance cursor is invalid",
            )


@dataclass(frozen=True, slots=True)
class GovernanceTimeWindow:
    occurred_after: datetime | None = None
    occurred_before: datetime | None = None

    def __post_init__(self) -> None:
        after = _optional_utc(self.occurred_after, "occurred_after")
        before = _optional_utc(self.occurred_before, "occurred_before")
        if after is not None and before is not None and after > before:
            raise ValueError("governance time window is reversed")
        object.__setattr__(self, "occurred_after", after)
        object.__setattr__(self, "occurred_before", before)


@dataclass(frozen=True, slots=True)
class PolicyDecisionQuery:
    page: GovernancePageRequest
    task_id: str | None = None

    def __post_init__(self) -> None:
        _optional_text(self.task_id, "policy_decision.task_id", maximum=133)


@dataclass(frozen=True, slots=True)
class EventQuery:
    page: GovernancePageRequest
    window: GovernanceTimeWindow = GovernanceTimeWindow()
    task_id: str | None = None
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        _optional_text(self.task_id, "event.task_id", maximum=133)
        _optional_text(self.correlation_id, "event.correlation_id", maximum=128)


@dataclass(frozen=True, slots=True)
class PolicyVersionView:
    version: str
    bundle_digest: str
    active: bool
    parent_version: str | None
    published_at: datetime
    revoked_at: datetime | None = None
    rollback_of: str | None = None

    def __post_init__(self) -> None:
        _text(self.version, "policy.version", maximum=128)
        _required_digest(self.bundle_digest, "policy.bundle_digest")
        _optional_text(self.parent_version, "policy.parent_version", maximum=128)
        _optional_text(self.rollback_of, "policy.rollback_of", maximum=128)
        object.__setattr__(
            self, "published_at", _utc(self.published_at, "published_at")
        )
        object.__setattr__(
            self, "revoked_at", _optional_utc(self.revoked_at, "revoked_at")
        )
        if self.active == (self.revoked_at is not None):
            raise ValueError("policy active flag does not match revocation state")


@dataclass(frozen=True, slots=True)
class PolicyDecisionView:
    tenant_id: str
    decision_id: str
    task_id: str
    decision: str
    policy_version: str
    reason_codes: tuple[str, ...]
    obligation_names: tuple[str, ...]
    action_digest: str
    evaluated_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        _text(self.tenant_id, "decision.tenant_id", maximum=128)
        _text(self.decision_id, "decision.decision_id", maximum=131)
        _text(self.task_id, "decision.task_id", maximum=133)
        _matches(
            self.decision_id,
            _POLICY_DECISION_ID,
            "decision.decision_id",
        )
        _matches(self.task_id, _TASK_ID, "decision.task_id")
        if self.decision not in {"allow", "deny", "require_approval"}:
            raise ValueError("decision is not a supported policy outcome")
        _text(self.policy_version, "decision.policy_version", maximum=128)
        _codes(self.reason_codes, "decision.reason_codes")
        _codes(self.obligation_names, "decision.obligation_names")
        _required_digest(self.action_digest, "decision.action_digest")
        object.__setattr__(
            self, "evaluated_at", _utc(self.evaluated_at, "evaluated_at")
        )
        object.__setattr__(self, "expires_at", _utc(self.expires_at, "expires_at"))


@dataclass(frozen=True, slots=True)
class AuditEventView:
    tenant_id: str
    event_id: str
    event_type: str
    occurred_at: datetime
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
    previous_hash: str | None = None
    policy_decision_id: str | None = None
    policy_version: str | None = None
    approval_id: str | None = None
    action_digest: str | None = None
    tool_execution_id: str | None = None
    security_event_id: str | None = None

    def __post_init__(self) -> None:
        for field, value, maximum in (
            ("tenant_id", self.tenant_id, 128),
            ("event_id", self.event_id, 133),
            ("event_type", self.event_type, 256),
            ("trace_id", self.trace_id, 128),
            ("thread_id", self.thread_id, 135),
            ("task_id", self.task_id, 133),
            ("correlation_id", self.correlation_id, 128),
            ("action", self.action, 256),
            ("stream_id", self.stream_id, 256),
        ):
            _text(value, f"audit.{field}", maximum=maximum)
        for field, optional_value, maximum in (
            ("run_id", self.run_id, 132),
            ("causation_id", self.causation_id, 128),
            ("policy_decision_id", self.policy_decision_id, 256),
            ("policy_version", self.policy_version, 128),
            ("approval_id", self.approval_id, 133),
            ("tool_execution_id", self.tool_execution_id, 133),
            ("security_event_id", self.security_event_id, 134),
        ):
            _optional_text(optional_value, f"audit.{field}", maximum=maximum)
        _matches(self.event_id, _AUDIT_ID, "audit.event_id")
        _matches(self.thread_id, _THREAD_ID, "audit.thread_id")
        _matches(self.task_id, _TASK_ID, "audit.task_id")
        _matches(self.run_id, _RUN_ID, "audit.run_id")
        _matches(
            self.policy_decision_id,
            _POLICY_DECISION_ID,
            "audit.policy_decision_id",
        )
        _matches(
            self.security_event_id,
            _SECURITY_EVENT_ID,
            "audit.security_event_id",
        )
        _matches(self.approval_id, _APPROVAL_ID, "audit.approval_id")
        _matches(
            self.tool_execution_id,
            _TOOL_EXECUTION_ID,
            "audit.tool_execution_id",
        )
        if self.decision not in {"allow", "deny", "require_approval", "not_applicable"}:
            raise ValueError("audit decision is invalid")
        if self.result not in {"success", "failure", "blocked", "unknown"}:
            raise ValueError("audit result is invalid")
        if self.data_classification not in {
            "public",
            "internal",
            "confidential",
            "restricted",
        }:
            raise ValueError("audit classification is invalid")
        if isinstance(self.sequence, bool) or self.sequence < 1:
            raise ValueError("audit sequence must be positive")
        _codes(self.reason_codes, "audit.reason_codes")
        _required_digest(self.event_hash, "audit.event_hash")
        _digest(self.previous_hash, "audit.previous_hash")
        _digest(self.action_digest, "audit.action_digest")
        object.__setattr__(self, "occurred_at", _utc(self.occurred_at, "occurred_at"))


@dataclass(frozen=True, slots=True)
class SecurityEventView:
    tenant_id: str
    event_id: str
    event_type: str
    occurred_at: datetime
    trace_id: str
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
    audit_event_id: str
    event_hash: str
    thread_id: str | None = None
    task_id: str | None = None
    run_id: str | None = None
    policy_decision_id: str | None = None

    def __post_init__(self) -> None:
        for field, value, maximum in (
            ("tenant_id", self.tenant_id, 128),
            ("event_id", self.event_id, 134),
            ("event_type", self.event_type, 256),
            ("trace_id", self.trace_id, 128),
            ("correlation_id", self.correlation_id, 128),
            ("control_component", self.control_component, 128),
            ("control_rule_id", self.control_rule_id, 256),
            ("control_rule_version", self.control_rule_version, 128),
            ("audit_event_id", self.audit_event_id, 133),
        ):
            _text(value, f"security_event.{field}", maximum=maximum)
        for field, optional_value, maximum in (
            ("causation_id", self.causation_id, 128),
            ("thread_id", self.thread_id, 135),
            ("task_id", self.task_id, 133),
            ("run_id", self.run_id, 132),
            ("policy_decision_id", self.policy_decision_id, 131),
        ):
            _optional_text(
                optional_value,
                f"security_event.{field}",
                maximum=maximum,
            )
        _matches(
            self.event_id,
            _SECURITY_EVENT_ID,
            "security_event.event_id",
        )
        _matches(self.thread_id, _THREAD_ID, "security_event.thread_id")
        _matches(self.task_id, _TASK_ID, "security_event.task_id")
        _matches(self.run_id, _RUN_ID, "security_event.run_id")
        _matches(
            self.policy_decision_id,
            _POLICY_DECISION_ID,
            "security_event.policy_decision_id",
        )
        _matches(
            self.audit_event_id,
            _AUDIT_ID,
            "security_event.audit_event_id",
        )
        if self.severity not in {"info", "low", "medium", "high", "critical"}:
            raise ValueError("security event severity is invalid")
        if self.control_outcome not in {
            "blocked",
            "allowed",
            "not_applicable",
            "unknown",
        }:
            raise ValueError("security event control outcome is invalid")
        if self.impact not in {
            "none",
            "attempted",
            "suspected",
            "confirmed",
            "unknown",
        }:
            raise ValueError("security event impact is invalid")
        if self.disposition not in {
            "open",
            "contained",
            "escalated",
            "resolved",
            "false_positive",
        }:
            raise ValueError("security event disposition is invalid")
        if self.data_classification not in {
            "public",
            "internal",
            "confidential",
            "restricted",
        }:
            raise ValueError("security event classification is invalid")
        _codes(self.reason_codes, "security_event.reason_codes")
        _required_digest(self.event_hash, "security_event.event_hash")
        object.__setattr__(self, "occurred_at", _utc(self.occurred_at, "occurred_at"))


@dataclass(frozen=True, slots=True)
class GovernancePage[T]:
    items: tuple[T, ...]
    next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class CorrelationChainView:
    tenant_id: str
    correlation_id: str
    policy_decisions: tuple[PolicyDecisionView, ...]
    audit_events: tuple[AuditEventView, ...]
    security_events: tuple[SecurityEventView, ...]

    def __post_init__(self) -> None:
        _text(self.tenant_id, "correlation.tenant_id", maximum=128)
        _text(self.correlation_id, "correlation.correlation_id", maximum=128)
        if (
            sum(
                len(items)
                for items in (
                    self.policy_decisions,
                    self.audit_events,
                    self.security_events,
                )
            )
            > 100
        ):
            raise ValueError("correlation chain exceeds the safe projection limit")


class GovernanceQueryPort(Protocol):
    async def list_policy_versions(
        self, page: GovernancePageRequest
    ) -> GovernancePage[PolicyVersionView]: ...

    async def list_policy_decisions(
        self, query: PolicyDecisionQuery
    ) -> GovernancePage[PolicyDecisionView]: ...

    async def list_audit_events(
        self, query: EventQuery
    ) -> GovernancePage[AuditEventView]: ...

    async def list_security_events(
        self, query: EventQuery
    ) -> GovernancePage[SecurityEventView]: ...

    async def get_correlation_chain(
        self, correlation_id: str
    ) -> CorrelationChainView | None: ...


class GovernanceQueryUnitOfWork(Protocol):
    @property
    def governance(self) -> GovernanceQueryPort: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


class GovernanceQueryUnitOfWorkFactory(Protocol):
    def __call__(
        self, context: GovernanceQueryContext
    ) -> GovernanceQueryUnitOfWork: ...


class GovernanceQueryService:
    """Tenant-bound governance reads with protocol and DLP verification."""

    def __init__(self, unit_of_work: GovernanceQueryUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def list_policy_versions(
        self,
        context: GovernanceQueryContext,
        page: GovernancePageRequest,
    ) -> GovernancePage[PolicyVersionView]:
        return await self._page(
            context,
            page,
            lambda port: port.list_policy_versions(page),
            identifier=lambda item: item.version,
            expected_type=PolicyVersionView,
        )

    async def list_policy_decisions(
        self,
        context: GovernanceQueryContext,
        query: PolicyDecisionQuery,
    ) -> GovernancePage[PolicyDecisionView]:
        return await self._page(
            context,
            query.page,
            lambda port: port.list_policy_decisions(query),
            identifier=lambda item: item.decision_id,
            expected_type=PolicyDecisionView,
        )

    async def list_audit_events(
        self,
        context: GovernanceQueryContext,
        query: EventQuery,
    ) -> GovernancePage[AuditEventView]:
        return await self._page(
            context,
            query.page,
            lambda port: port.list_audit_events(query),
            identifier=lambda item: item.event_id,
            expected_type=AuditEventView,
        )

    async def list_security_events(
        self,
        context: GovernanceQueryContext,
        query: EventQuery,
    ) -> GovernancePage[SecurityEventView]:
        return await self._page(
            context,
            query.page,
            lambda port: port.list_security_events(query),
            identifier=lambda item: item.event_id,
            expected_type=SecurityEventView,
        )

    async def get_correlation_chain(
        self,
        context: GovernanceQueryContext,
        correlation_id: str,
    ) -> CorrelationChainView:
        _text(correlation_id, "correlation_id", maximum=128)
        try:
            async with self._unit_of_work(context) as transaction:
                result = await transaction.governance.get_correlation_chain(
                    correlation_id
                )
        except ApplicationError:
            raise
        except Exception:
            raise self._unavailable() from None
        if result is None:
            raise ApplicationError(
                ErrorCode.GOVERNANCE_NOT_FOUND,
                "governance correlation chain was not found",
            )
        if type(result) is not CorrelationChainView:
            raise self._protocol_error()
        if (
            any(
                type(item) is not PolicyDecisionView for item in result.policy_decisions
            )
            or any(type(item) is not AuditEventView for item in result.audit_events)
            or any(
                type(item) is not SecurityEventView for item in result.security_events
            )
        ):
            raise self._protocol_error()
        if (
            result.tenant_id != context.tenant_id
            or result.correlation_id != correlation_id
        ):
            raise self._protocol_error()
        if (
            any(item.tenant_id != context.tenant_id for item in result.policy_decisions)
            or any(item.tenant_id != context.tenant_id for item in result.audit_events)
            or any(
                item.tenant_id != context.tenant_id for item in result.security_events
            )
        ):
            raise self._protocol_error()
        if any(
            item.correlation_id != correlation_id for item in result.audit_events
        ) or any(
            item.correlation_id != correlation_id for item in result.security_events
        ):
            raise self._protocol_error()
        nested_ids = (
            *(item.decision_id for item in result.policy_decisions),
            *(item.event_id for item in result.audit_events),
            *(item.event_id for item in result.security_events),
        )
        if len(nested_ids) != len(set(nested_ids)):
            raise self._protocol_error()
        self._assert_projection(result)
        return result

    async def _page[T](
        self,
        context: GovernanceQueryContext,
        request: GovernancePageRequest,
        load: Callable[[GovernanceQueryPort], Awaitable[GovernancePage[T]]],
        *,
        identifier: Callable[[T], str],
        expected_type: type[T],
    ) -> GovernancePage[T]:
        try:
            async with self._unit_of_work(context) as transaction:
                page = await load(transaction.governance)
        except ApplicationError:
            raise
        except Exception:
            raise self._unavailable() from None
        try:
            if not isinstance(page, GovernancePage) or len(page.items) > request.limit:
                raise self._protocol_error()
            if any(type(item) is not expected_type for item in page.items):
                raise self._protocol_error()
            identifiers = tuple(identifier(item) for item in page.items)
            if len(identifiers) != len(set(identifiers)):
                raise self._protocol_error()
            if (
                page.next_cursor is not None
                and _CURSOR.fullmatch(page.next_cursor) is None
            ):
                raise self._protocol_error()
            for item in page.items:
                tenant_id = getattr(item, "tenant_id", context.tenant_id)
                if tenant_id != context.tenant_id:
                    raise self._protocol_error()
                self._assert_projection(item)
        except ApplicationError:
            raise
        except Exception:
            raise self._protocol_error() from None
        return page

    @staticmethod
    def _assert_projection(value: Any) -> None:
        try:
            assert_safe_projection(asdict(value), field="governance_projection")
        except (SecurityError, TypeError, ValueError):
            raise ApplicationError(
                ErrorCode.GOVERNANCE_UNSAFE_PROJECTION,
                "governance repository returned an unsafe projection",
            ) from None

    @staticmethod
    def _protocol_error() -> ApplicationError:
        return ApplicationError(
            ErrorCode.GOVERNANCE_REPOSITORY_PROTOCOL_ERROR,
            "governance repository violated the query protocol",
        )

    @staticmethod
    def _unavailable() -> ApplicationError:
        return ApplicationError(
            ErrorCode.GOVERNANCE_REPOSITORY_UNAVAILABLE,
            "governance repository is unavailable",
            retryable=True,
        )
