from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from types import TracebackType
from typing import Any, Self

from flowpilot_application import (
    ApplicationError,
    AuditEventView,
    CorrelationChainView,
    ErrorCode,
    EventQuery,
    GovernancePage,
    GovernancePageRequest,
    GovernanceQueryContext,
    PolicyDecisionQuery,
    PolicyDecisionView,
    PolicyVersionView,
    SecurityEventView,
)

from .postgres import AsyncPostgresConnection, AsyncPostgresConnectionFactory

Row = Mapping[str, Any]


def _json_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("governance projection contains an invalid code list")
    return tuple(value)


def _optional(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


class GovernanceCursorCodec:
    """Opaque HMAC cursor bound to tenant, resource, filters, sort and version."""

    def __init__(self, secret: bytes) -> None:
        if len(secret) < 32:
            raise ValueError("governance cursor secret must contain at least 32 bytes")
        self._secret = secret

    def encode(self, binding: Mapping[str, object], last: Sequence[object]) -> str:
        payload = {"v": 1, "binding": binding, "last": list(last)}
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        signature = hmac.new(self._secret, canonical, hashlib.sha256).hexdigest()
        envelope = json.dumps(
            {"payload": payload, "signature": signature},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return "gcur_" + base64.urlsafe_b64encode(envelope).rstrip(b"=").decode()

    def decode(self, token: str, binding: Mapping[str, object]) -> tuple[object, ...]:
        try:
            encoded = token.removeprefix("gcur_")
            raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            envelope = json.loads(raw)
            payload = envelope["payload"]
            signature = envelope["signature"]
            canonical = json.dumps(
                payload, sort_keys=True, separators=(",", ":")
            ).encode()
            expected = hmac.new(self._secret, canonical, hashlib.sha256).hexdigest()
            if (
                not isinstance(signature, str)
                or not hmac.compare_digest(signature, expected)
                or payload.get("v") != 1
                or payload.get("binding") != binding
                or not isinstance(payload.get("last"), list)
            ):
                raise ValueError
            return tuple(payload["last"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise ApplicationError(
                ErrorCode.GOVERNANCE_CURSOR_INVALID,
                "governance cursor is invalid",
            ) from None


def _policy_version(row: Row) -> PolicyVersionView:
    return PolicyVersionView(
        version=str(row["version"]),
        bundle_digest=str(row["bundle_digest"]),
        active=bool(row["active"]),
        parent_version=_optional(row.get("parent_version")),
        published_at=row["published_at"],
        revoked_at=row.get("revoked_at"),
        rollback_of=_optional(row.get("rollback_of")),
    )


def _policy_decision(row: Row) -> PolicyDecisionView:
    return PolicyDecisionView(
        tenant_id=str(row["tenant_id"]),
        decision_id=str(row["decision_id"]),
        task_id=str(row["task_id"]),
        decision=str(row["decision"]),
        policy_version=str(row["policy_version"]),
        reason_codes=_json_tuple(row["reason_codes"]),
        obligation_names=_json_tuple(row["obligation_names"]),
        action_digest=str(row["action_digest"]),
        evaluated_at=row["evaluated_at"],
        expires_at=row["expires_at"],
    )


def _audit(row: Row) -> AuditEventView:
    return AuditEventView(
        tenant_id=str(row["tenant_id"]),
        event_id=str(row["event_id"]),
        event_type=str(row["event_type"]),
        occurred_at=row["occurred_at"],
        trace_id=str(row["trace_id"]),
        thread_id=str(row["thread_id"]),
        task_id=str(row["task_id"]),
        run_id=_optional(row.get("run_id")),
        correlation_id=str(row["correlation_id"]),
        causation_id=_optional(row.get("causation_id")),
        action=str(row["action"]),
        decision=str(row["decision"]),
        reason_codes=_json_tuple(row["reason_codes"]),
        result=str(row["result"]),
        data_classification=str(row["data_classification"]),
        stream_id=str(row["stream_id"]),
        sequence=int(row["sequence"]),
        event_hash=str(row["event_hash"]),
        previous_hash=_optional(row.get("previous_hash")),
        policy_decision_id=_optional(row.get("policy_decision_id")),
        policy_version=_optional(row.get("policy_version")),
        approval_id=_optional(row.get("approval_id")),
        action_digest=_optional(row.get("action_digest")),
        tool_execution_id=_optional(row.get("tool_execution_id")),
        security_event_id=_optional(row.get("security_event_id")),
    )


def _security(row: Row) -> SecurityEventView:
    return SecurityEventView(
        tenant_id=str(row["tenant_id"]),
        event_id=str(row["event_id"]),
        event_type=str(row["event_type"]),
        occurred_at=row["occurred_at"],
        trace_id=str(row["trace_id"]),
        correlation_id=str(row["correlation_id"]),
        causation_id=_optional(row.get("causation_id")),
        control_component=str(row["control_component"]),
        control_rule_id=str(row["control_rule_id"]),
        control_rule_version=str(row["control_rule_version"]),
        reason_codes=_json_tuple(row["reason_codes"]),
        severity=str(row["severity"]),
        category=str(row["category"]),
        control_outcome=str(row["control_outcome"]),
        impact=str(row["impact"]),
        disposition=str(row["disposition"]),
        data_classification=str(row["data_classification"]),
        audit_event_id=str(row["audit_event_id"]),
        event_hash=str(row["event_hash"]),
        thread_id=_optional(row.get("thread_id")),
        task_id=_optional(row.get("task_id")),
        run_id=_optional(row.get("run_id")),
        policy_decision_id=_optional(row.get("policy_decision_id")),
    )


_AUDIT_COLUMNS = """tenant_id,event_id,event_type,occurred_at,trace_id,
thread_id,task_id,run_id,correlation_id,causation_id,action,decision,
reason_codes,result,data_classification,stream_id,sequence,event_hash,
previous_hash,policy_decision_id,policy_version,approval_id,action_digest,
tool_execution_id,security_event_id"""
_SECURITY_COLUMNS = """tenant_id,event_id,event_type,occurred_at,trace_id,
correlation_id,causation_id,control_component,control_rule_id,
control_rule_version,reason_codes,severity,category,control_outcome,impact,
disposition,data_classification,audit_event_id,event_hash,thread_id,task_id,
run_id,policy_decision_id"""


class PostgresGovernanceQueryRepository:
    def __init__(
        self,
        connection: AsyncPostgresConnection,
        context: GovernanceQueryContext,
        codec: GovernanceCursorCodec,
    ) -> None:
        self._connection, self._context, self._codec = connection, context, codec

    async def _page(
        self,
        resource: str,
        request: GovernancePageRequest,
        filters: Mapping[str, object],
        sql: str,
        mapper: Callable[[Row], Any],
        sort_fields: tuple[str, str],
    ) -> GovernancePage[Any]:
        binding = {
            "tenant": self._context.tenant_id,
            "resource": resource,
            "filters": filters,
            "sort": list(sort_fields),
            "version": 1,
        }
        last: tuple[object, ...] = (
            ()
            if request.cursor is None
            else self._codec.decode(request.cursor, binding)
        )
        if last and len(last) != 2:
            raise ApplicationError(
                ErrorCode.GOVERNANCE_CURSOR_INVALID, "governance cursor is invalid"
            )
        params: dict[str, object] = {
            **filters,
            "limit": request.limit + 1,
            "last_time": last[0] if last else None,
            "last_id": last[1] if last else None,
        }
        rows = list(await self._connection.fetch_all(sql, params))
        visible = rows[: request.limit]
        cursor = None
        if len(rows) > request.limit and visible:
            tail = visible[-1]
            time_value = tail[sort_fields[0]]
            cursor = self._codec.encode(
                binding,
                (
                    time_value.isoformat()
                    if isinstance(time_value, datetime)
                    else time_value,
                    tail[sort_fields[1]],
                ),
            )
        return GovernancePage(tuple(mapper(row) for row in visible), cursor)

    async def list_policy_versions(
        self, page: GovernancePageRequest
    ) -> GovernancePage[PolicyVersionView]:
        return await self._page(
            "policy_versions",
            page,
            {},
            """SELECT version,bundle_digest,active,parent_version,published_at,
                       revoked_at,rollback_of
                FROM flowpilot.policy_versions
                WHERE (%(last_time)s IS NULL OR (published_at,version) <
                      (%(last_time)s::timestamptz,%(last_id)s))
                ORDER BY published_at DESC,version DESC LIMIT %(limit)s""",
            _policy_version,
            ("published_at", "version"),
        )

    async def list_policy_decisions(
        self, query: PolicyDecisionQuery
    ) -> GovernancePage[PolicyDecisionView]:
        filters = {"task_id": query.task_id}
        return await self._page(
            "policy_decisions",
            query.page,
            filters,
            """SELECT tenant_id,policy_decision_id AS decision_id,task_id,
                       policy_decision->>'decision' AS decision,policy_version,
                       COALESCE(policy_decision->'reason_codes','[]') reason_codes,
                       COALESCE(policy_decision->'obligations','[]') obligation_names,
                       action_digest,created_at AS evaluated_at,expires_at
                FROM flowpilot.policy_decisions
                WHERE (%(task_id)s IS NULL OR task_id=%(task_id)s)
                  AND (%(last_time)s IS NULL OR (created_at,policy_decision_id) <
                      (%(last_time)s::timestamptz,%(last_id)s))
                ORDER BY created_at DESC,policy_decision_id DESC LIMIT %(limit)s""",
            _policy_decision,
            ("evaluated_at", "decision_id"),
        )

    async def list_audit_events(
        self, query: EventQuery
    ) -> GovernancePage[AuditEventView]:
        filters = {
            "task_id": query.task_id,
            "correlation_id": query.correlation_id,
            "after": query.window.occurred_after.isoformat()
            if query.window.occurred_after
            else None,
            "before": query.window.occurred_before.isoformat()
            if query.window.occurred_before
            else None,
        }
        return await self._page(
            "audit_events",
            query.page,
            filters,
            f"""SELECT {_AUDIT_COLUMNS}
                FROM flowpilot.governance_audit_events
                WHERE (%(task_id)s IS NULL OR task_id=%(task_id)s)
                  AND (%(correlation_id)s IS NULL OR
                       correlation_id=%(correlation_id)s)
                  AND (%(after)s IS NULL OR occurred_at>=%(after)s::timestamptz)
                  AND (%(before)s IS NULL OR occurred_at<=%(before)s::timestamptz)
                  AND (%(last_time)s IS NULL OR (occurred_at,event_id) <
                       (%(last_time)s::timestamptz,%(last_id)s))
                ORDER BY occurred_at DESC,event_id DESC LIMIT %(limit)s""",
            _audit,
            ("occurred_at", "event_id"),
        )

    async def list_security_events(
        self, query: EventQuery
    ) -> GovernancePage[SecurityEventView]:
        filters = {
            "task_id": query.task_id,
            "correlation_id": query.correlation_id,
            "after": query.window.occurred_after.isoformat()
            if query.window.occurred_after
            else None,
            "before": query.window.occurred_before.isoformat()
            if query.window.occurred_before
            else None,
        }
        return await self._page(
            "security_events",
            query.page,
            filters,
            f"""SELECT {_SECURITY_COLUMNS} FROM flowpilot.security_events
                WHERE (%(task_id)s IS NULL OR task_id=%(task_id)s)
                  AND (%(correlation_id)s IS NULL OR
                       correlation_id=%(correlation_id)s)
                  AND (%(after)s IS NULL OR occurred_at>=%(after)s::timestamptz)
                  AND (%(before)s IS NULL OR occurred_at<=%(before)s::timestamptz)
                  AND (%(last_time)s IS NULL OR (occurred_at,event_id) <
                       (%(last_time)s::timestamptz,%(last_id)s))
                ORDER BY occurred_at DESC,event_id DESC LIMIT %(limit)s""",
            _security,
            ("occurred_at", "event_id"),
        )

    async def get_correlation_chain(
        self, correlation_id: str
    ) -> CorrelationChainView | None:
        query = EventQuery(
            GovernancePageRequest(limit=100), correlation_id=correlation_id
        )
        audits = await self.list_audit_events(query)
        security = await self.list_security_events(query)
        decisions_rows = await self._connection.fetch_all(
            """SELECT DISTINCT pd.tenant_id,
                       pd.policy_decision_id AS decision_id,pd.task_id,
                       pd.policy_decision->>'decision' AS decision,
                       pd.policy_version,
                       COALESCE(pd.policy_decision->'reason_codes','[]') reason_codes,
                       COALESCE(
                           pd.policy_decision->'obligations','[]'
                       ) obligation_names,
                       pd.action_digest,pd.created_at AS evaluated_at,pd.expires_at
                FROM flowpilot.policy_decisions pd
                JOIN flowpilot.governance_audit_events ae
                  ON ae.policy_decision_id=pd.policy_decision_id
                WHERE ae.correlation_id=%(correlation_id)s
                ORDER BY evaluated_at DESC LIMIT 100""",
            {"correlation_id": correlation_id},
        )
        decisions = tuple(_policy_decision(row) for row in decisions_rows)
        if not audits.items and not security.items and not decisions:
            return None
        return CorrelationChainView(
            self._context.tenant_id,
            correlation_id,
            decisions,
            audits.items,
            security.items,
        )


class PostgresGovernanceQueryUnitOfWork:
    def __init__(
        self,
        factory: AsyncPostgresConnectionFactory,
        context: GovernanceQueryContext,
        codec: GovernanceCursorCodec,
    ) -> None:
        self._factory, self._context, self._codec = factory, context, codec
        self._connection: AsyncPostgresConnection | None = None
        self.governance: PostgresGovernanceQueryRepository

    async def __aenter__(self) -> Self:
        connection = await self._factory()
        self._connection = connection
        try:
            await connection.execute(
                """SELECT set_config('flowpilot.tenant_id',%(tenant_id)s,true),
                          set_config('flowpilot.context_ref',%(context_ref)s,true),
                          set_config('flowpilot.context_hash',%(context_hash)s,true),
                          set_config('flowpilot.subject_id',%(subject_id)s,true),
                          set_config('flowpilot.purpose',%(purpose)s,true)""",
                {
                    "tenant_id": self._context.tenant_id,
                    "context_ref": self._context.security_context_ref,
                    "context_hash": self._context.security_context_hash,
                    "subject_id": self._context.subject_id,
                    "purpose": self._context.purpose,
                },
            )
            row = await connection.fetch_one(
                "SELECT validated FROM flowpilot.validate_governance_query_context()"
            )
            if row is None or row.get("validated") is not True:
                raise ApplicationError(
                    ErrorCode.GOVERNANCE_REPOSITORY_UNAVAILABLE,
                    "governance repository is unavailable",
                )
            self.governance = PostgresGovernanceQueryRepository(
                connection, self._context, self._codec
            )
            return self
        except BaseException:
            await connection.rollback()
            await connection.close()
            self._connection = None
            raise

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        if self._connection is not None:
            try:
                await self._connection.rollback()
                await self._connection.execute("RESET ALL")
                await self._connection.commit()
            finally:
                await self._connection.close()
                self._connection = None


class PostgresGovernanceQueryUnitOfWorkFactory:
    def __init__(
        self, connection_factory: AsyncPostgresConnectionFactory, cursor_secret: bytes
    ) -> None:
        self._connection_factory = connection_factory
        self._codec = GovernanceCursorCodec(cursor_secret)

    def __call__(
        self, context: GovernanceQueryContext
    ) -> PostgresGovernanceQueryUnitOfWork:
        return PostgresGovernanceQueryUnitOfWork(
            self._connection_factory, context, self._codec
        )
