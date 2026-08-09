from __future__ import annotations

import json
from collections.abc import Awaitable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from types import TracebackType
from typing import Any, Protocol, Self
from uuid import uuid4

from flowpilot_application import (
    ExecutionReceipt,
    StoredCommand,
    TaskInitializationDisposition,
    VersionSlotReservation,
)
from flowpilot_domain import DomainViolation, Task

from .errors import PersistenceError, PersistenceErrorCode
from .models import (
    CheckpointRecord,
    CoordinationSignal,
    ExecutionIntent,
    ExecutionOutcome,
    ExecutionRecord,
    LeaseFence,
    LedgerStatus,
    OutboxDelivery,
    OutboxEvent,
    RetryBasis,
    format_utc,
    thaw_json,
    utc,
)
from .serialization import (
    execution_receipt_to_mapping,
    is_initial_task_projection,
    stored_command_from_row,
    task_command_to_mapping,
)

Parameters = Mapping[str, object]
Row = Mapping[str, Any]


class AsyncPostgresConnection(Protocol):
    """Driver wrapper requested from S5; all statements are package constants."""

    async def execute(
        self, statement: str, parameters: Parameters | None = None
    ) -> int:
        """Execute and return affected row count."""

    async def fetch_one(
        self, statement: str, parameters: Parameters | None = None
    ) -> Row | None: ...

    async def fetch_all(
        self, statement: str, parameters: Parameters | None = None
    ) -> Sequence[Row]: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...

    async def close(self) -> None: ...


class AsyncPostgresConnectionFactory(Protocol):
    def __call__(self) -> Awaitable[AsyncPostgresConnection]: ...


def _json_dump(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _json_object(value: Any, field: str) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise PersistenceError(
            PersistenceErrorCode.DRIVER_PROTOCOL,
            f"{field} is not a JSON object",
        )
    return value


class _TenantTransaction:
    def __init__(self, connection: AsyncPostgresConnection) -> None:
        self.connection = connection
        self.tenant_id: str | None = None

    async def bind(self, tenant_id: str) -> None:
        if not tenant_id:
            raise PersistenceError(
                PersistenceErrorCode.TENANT_REQUIRED,
                "tenant context is required",
            )
        if self.tenant_id is not None:
            if self.tenant_id != tenant_id:
                raise PersistenceError(
                    PersistenceErrorCode.TENANT_MISMATCH,
                    "a transaction cannot switch tenant context",
                )
            return
        await self.connection.execute(
            "SELECT set_config('flowpilot.tenant_id', %(tenant_id)s, true)",
            {"tenant_id": tenant_id},
        )
        self.tenant_id = tenant_id


class PostgresTaskRepository:
    def __init__(self, transaction: _TenantTransaction) -> None:
        self._transaction = transaction

    async def get_version(self, tenant_id: str, task_id: str) -> int | None:
        await self._transaction.bind(tenant_id)
        row = await self._transaction.connection.fetch_one(
            """
            SELECT version
            FROM flowpilot.tasks
            WHERE tenant_id = %(tenant_id)s AND task_id = %(task_id)s
            """,
            {"tenant_id": tenant_id, "task_id": task_id},
        )
        return int(row["version"]) if row is not None else None

    async def get(self, tenant_id: str, task_id: str) -> Task | None:
        await self._transaction.bind(tenant_id)
        row = await self._transaction.connection.fetch_one(
            """
            SELECT tenant_id, task_id, projection
            FROM flowpilot.tasks
            WHERE tenant_id = %(tenant_id)s AND task_id = %(task_id)s
            """,
            {"tenant_id": tenant_id, "task_id": task_id},
        )
        if row is None:
            return None
        return _task_from_row(row, tenant_id=tenant_id, task_id=task_id)

    async def initialize(
        self, tenant_id: str, task: Task
    ) -> TaskInitializationDisposition:
        await self._transaction.bind(tenant_id)
        if task.tenant_id != tenant_id:
            return TaskInitializationDisposition.CONFLICT
        if not is_initial_task_projection(task):
            raise PersistenceError(
                PersistenceErrorCode.DRIVER_PROTOCOL,
                "task initialization requires a Task v0 projection",
            )
        affected = await self._transaction.connection.execute(
            """
            INSERT INTO flowpilot.tasks (
                tenant_id,
                task_id,
                thread_id,
                status,
                version,
                run_generation,
                projection,
                created_at,
                updated_at
            )
            VALUES (
                %(tenant_id)s,
                %(task_id)s,
                %(thread_id)s,
                %(status)s,
                %(version)s,
                %(run_generation)s,
                %(projection)s::jsonb,
                %(created_at)s,
                %(updated_at)s
            )
            ON CONFLICT DO NOTHING
            """,
            {
                "tenant_id": task.tenant_id,
                "task_id": task.task_id,
                "thread_id": task.thread_id,
                "status": task.status.value,
                "version": task.version,
                "run_generation": task.run_generation,
                "projection": _json_dump(task.to_mapping()),
                "created_at": task.created_at,
                "updated_at": task.updated_at,
            },
        )
        if affected == 1:
            return TaskInitializationDisposition.INITIALIZED
        return TaskInitializationDisposition.CONFLICT


def _task_from_row(row: Row, *, tenant_id: str, task_id: str) -> Task:
    try:
        projection = _json_object(row["projection"], "task.projection")
        task = Task.from_mapping(projection)
        row_generation = (
            int(row["run_generation"])
            if "run_generation" in row
            else task.run_generation
        )
    except (DomainViolation, KeyError, TypeError, ValueError) as exc:
        raise PersistenceError(
            PersistenceErrorCode.DRIVER_PROTOCOL,
            "stored task projection violates the Task v1 contract",
        ) from exc
    if (
        row.get("tenant_id") != tenant_id
        or row.get("task_id") != task_id
        or task.tenant_id != tenant_id
        or task.task_id != task_id
        or ("thread_id" in row and row["thread_id"] != task.thread_id)
        or ("status" in row and row["status"] != task.status.value)
        or row_generation != task.run_generation
    ):
        raise PersistenceError(
            PersistenceErrorCode.DRIVER_PROTOCOL,
            "stored task projection does not match its identity",
        )
    return task


class PostgresRecoverySignalRepository:
    def __init__(self, transaction: _TenantTransaction) -> None:
        self._transaction = transaction

    async def runnable_signals(
        self,
        tenant_id: str,
        *,
        now: datetime,
        limit: int,
    ) -> Sequence[CoordinationSignal]:
        await self._transaction.bind(tenant_id)
        if limit < 1:
            return ()
        rows = await self._transaction.connection.fetch_all(
            """
            WITH latest_task_event AS (
                SELECT DISTINCT ON (aggregate_id)
                       tenant_id,
                       aggregate_id AS task_id,
                       sequence,
                       available_at
                FROM flowpilot.outbox_events
                WHERE tenant_id = %(tenant_id)s
                  AND aggregate_type = 'task'
                ORDER BY aggregate_id, sequence DESC
            )
            SELECT task.tenant_id,
                   task.task_id,
                   task.thread_id,
                   task.status,
                   task.run_generation,
                   task.projection,
                   latest.available_at
            FROM latest_task_event AS latest
            JOIN flowpilot.tasks AS task
              ON task.tenant_id = latest.tenant_id
             AND task.task_id = latest.task_id
            WHERE task.tenant_id = %(tenant_id)s
              AND task.status = 'RUNNABLE'
              AND latest.available_at <= %(now)s
            ORDER BY latest.available_at, task.task_id
            LIMIT %(limit)s
            """,
            {
                "tenant_id": tenant_id,
                "now": utc(now, "now"),
                "limit": limit,
            },
        )
        signals: list[CoordinationSignal] = []
        for row in rows:
            task_id = row.get("task_id")
            if not isinstance(task_id, str):
                raise PersistenceError(
                    PersistenceErrorCode.DRIVER_PROTOCOL,
                    "durable recovery row has no task identity",
                )
            task = _task_from_row(
                row,
                tenant_id=tenant_id,
                task_id=task_id,
            )
            try:
                signal = CoordinationSignal(
                    tenant_id=tenant_id,
                    task_id=task.task_id,
                    run_generation=task.run_generation,
                    available_at=row["available_at"],
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise PersistenceError(
                    PersistenceErrorCode.DRIVER_PROTOCOL,
                    "durable recovery row has an invalid availability window",
                ) from exc
            signals.append(signal)
        return tuple(signals)


class PostgresCommandInbox:
    def __init__(self, transaction: _TenantTransaction) -> None:
        self._transaction = transaction

    async def get_by_idempotency_key(
        self, tenant_id: str, idempotency_key: str
    ) -> StoredCommand | None:
        await self._transaction.bind(tenant_id)
        row = await self._transaction.connection.fetch_one(
            """
            SELECT command, accepted_at, execution_receipt
            FROM flowpilot.task_commands
            WHERE tenant_id = %(tenant_id)s
              AND idempotency_key = %(idempotency_key)s
            """,
            {"tenant_id": tenant_id, "idempotency_key": idempotency_key},
        )
        return (
            stored_command_from_row(dict(row))
            if row is not None
            else None
        )

    async def get_by_command_id(
        self, tenant_id: str, command_id: str
    ) -> StoredCommand | None:
        await self._transaction.bind(tenant_id)
        row = await self._transaction.connection.fetch_one(
            """
            SELECT command, accepted_at, execution_receipt
            FROM flowpilot.task_commands
            WHERE tenant_id = %(tenant_id)s AND command_id = %(command_id)s
            """,
            {"tenant_id": tenant_id, "command_id": command_id},
        )
        return (
            stored_command_from_row(dict(row))
            if row is not None
            else None
        )

    async def reserve_version_slot(
        self,
        tenant_id: str,
        task_id: str,
        expected_task_version: int | None,
        command_id: str,
    ) -> VersionSlotReservation:
        await self._transaction.bind(tenant_id)
        slot_version = (
            -1 if expected_task_version is None else expected_task_version
        )
        parameters = {
            "tenant_id": tenant_id,
            "task_id": task_id,
            "slot_version": slot_version,
            "command_id": command_id,
        }
        affected = await self._transaction.connection.execute(
            """
            INSERT INTO flowpilot.task_command_slots (
                tenant_id, task_id, slot_version, command_id
            )
            VALUES (
                %(tenant_id)s, %(task_id)s, %(slot_version)s, %(command_id)s
            )
            ON CONFLICT (tenant_id, task_id, slot_version) DO NOTHING
            """,
            parameters,
        )
        if affected == 1:
            return VersionSlotReservation.RESERVED
        row = await self._transaction.connection.fetch_one(
            """
            SELECT command_id
            FROM flowpilot.task_command_slots
            WHERE tenant_id = %(tenant_id)s
              AND task_id = %(task_id)s
              AND slot_version = %(slot_version)s
            """,
            parameters,
        )
        if row is not None and row["command_id"] == command_id:
            return VersionSlotReservation.RESERVED
        return VersionSlotReservation.CONFLICT

    async def add(self, stored: StoredCommand) -> None:
        command = stored.command
        await self._transaction.bind(command.tenant_id)
        affected = await self._transaction.connection.execute(
            """
            INSERT INTO flowpilot.task_commands (
                command_id,
                tenant_id,
                task_id,
                command_type,
                expected_task_version,
                idempotency_key,
                command_digest,
                command,
                accepted_at
            )
            VALUES (
                %(command_id)s,
                %(tenant_id)s,
                %(task_id)s,
                %(command_type)s,
                %(expected_task_version)s,
                %(idempotency_key)s,
                %(command_digest)s,
                %(command)s::jsonb,
                %(accepted_at)s
            )
            ON CONFLICT DO NOTHING
            """,
            {
                "command_id": command.command_id,
                "tenant_id": command.tenant_id,
                "task_id": command.task_id,
                "command_type": command.command_type.value,
                "expected_task_version": command.expected_task_version,
                "idempotency_key": command.idempotency_key,
                "command_digest": command.command_digest,
                "command": _json_dump(task_command_to_mapping(command)),
                "accepted_at": stored.accepted_at,
            },
        )
        if affected != 1:
            raise PersistenceError(
                PersistenceErrorCode.CONFLICT,
                "command uniqueness constraint rejected the write",
            )

    async def record_execution(
        self, tenant_id: str, command_id: str, receipt: ExecutionReceipt
    ) -> StoredCommand:
        await self._transaction.bind(tenant_id)
        row = await self._transaction.connection.fetch_one(
            """
            UPDATE flowpilot.task_commands
            SET execution_receipt = %(execution_receipt)s::jsonb
            WHERE tenant_id = %(tenant_id)s
              AND command_id = %(command_id)s
              AND (
                  execution_receipt IS NULL
                  OR execution_receipt = %(execution_receipt)s::jsonb
              )
            RETURNING command, accepted_at, execution_receipt
            """,
            {
                "tenant_id": tenant_id,
                "command_id": command_id,
                "execution_receipt": _json_dump(
                    execution_receipt_to_mapping(receipt)
                ),
            },
        )
        if row is None:
            raise PersistenceError(
                PersistenceErrorCode.CONFLICT,
                "execution receipt is missing or conflicts with stored command",
            )
        return stored_command_from_row(dict(row))


def _intent_to_mapping(intent: ExecutionIntent) -> dict[str, Any]:
    result = intent.binding_mapping()
    result["created_at"] = format_utc(intent.created_at)
    return result


def _intent_from_mapping(value: dict[str, Any]) -> ExecutionIntent:
    planned = _json_object(value["planned_action"], "planned_action")
    approval_value = value.get("approval")
    approval = (
        _json_object(approval_value, "approval")
        if approval_value is not None
        else None
    )
    return ExecutionIntent(
        tool_execution_id=value["tool_execution_id"],
        request_id=value["request_id"],
        tenant_id=value["tenant_id"],
        task_id=value["task_id"],
        tool_name=value["tool_name"],
        idempotency_key=value["idempotency_key"],
        action_id=value["action_id"],
        action_digest=value["action_digest"],
        planned_action=planned,
        planned_action_expires_at=datetime.fromisoformat(
            value["planned_action_expires_at"].replace("Z", "+00:00")
        ),
        policy_decision_id=value["policy_decision_id"],
        policy_version=value["policy_version"],
        policy_decision=_json_object(
            value["policy_decision"], "policy_decision"
        ),
        policy_expires_at=datetime.fromisoformat(
            value["policy_expires_at"].replace("Z", "+00:00")
        ),
        tool_schema_hash=value["tool_schema_hash"],
        approval_id=value.get("approval_id"),
        approval=approval,
        approval_expires_at=(
            datetime.fromisoformat(
                value["approval_expires_at"].replace("Z", "+00:00")
            )
            if value.get("approval_expires_at") is not None
            else None
        ),
        created_at=datetime.fromisoformat(
            value["created_at"].replace("Z", "+00:00")
        ),
    )


def _outcome_to_mapping(outcome: ExecutionOutcome) -> dict[str, Any]:
    return {
        "status": outcome.status.value,
        "recorded_at": format_utc(outcome.recorded_at),
        "retryable": outcome.retryable,
        "data": thaw_json(outcome.data) if outcome.data is not None else None,
        "error_code": outcome.error_code,
        "retry_basis": (
            outcome.retry_basis.value if outcome.retry_basis is not None else None
        ),
        "evidence_ref": outcome.evidence_ref,
        "verification": (
            thaw_json(outcome.verification)
            if outcome.verification is not None
            else None
        ),
        "reconciliation": (
            thaw_json(outcome.reconciliation)
            if outcome.reconciliation is not None
            else None
        ),
    }


def _outcome_from_mapping(value: dict[str, Any]) -> ExecutionOutcome:
    return ExecutionOutcome(
        status=LedgerStatus(value["status"]),
        recorded_at=datetime.fromisoformat(
            value["recorded_at"].replace("Z", "+00:00")
        ),
        retryable=value["retryable"],
        data=(
            _json_object(value["data"], "outcome.data")
            if value.get("data") is not None
            else None
        ),
        error_code=value.get("error_code"),
        retry_basis=(
            RetryBasis(value["retry_basis"])
            if value.get("retry_basis") is not None
            else None
        ),
        evidence_ref=value.get("evidence_ref"),
        verification=(
            _json_object(value["verification"], "outcome.verification")
            if value.get("verification") is not None
            else None
        ),
        reconciliation=(
            _json_object(value["reconciliation"], "outcome.reconciliation")
            if value.get("reconciliation") is not None
            else None
        ),
    )


def _execution_from_row(row: Row) -> ExecutionRecord:
    intent = _intent_from_mapping(_json_object(row["intent"], "intent"))
    outcome_value = row.get("outcome")
    outcome = (
        _outcome_from_mapping(_json_object(outcome_value, "outcome"))
        if outcome_value is not None
        else None
    )
    updated_at = row["updated_at"]
    if not isinstance(updated_at, datetime):
        raise PersistenceError(
            PersistenceErrorCode.DRIVER_PROTOCOL,
            "updated_at is not a datetime",
        )
    return ExecutionRecord(
        intent=intent,
        status=LedgerStatus(row["status"]),
        attempt_count=int(row["attempt_count"]),
        updated_at=updated_at,
        outcome=outcome,
    )


class PostgresExecutionLedger:
    def __init__(self, transaction: _TenantTransaction) -> None:
        self._transaction = transaction

    async def prepare(self, intent: ExecutionIntent) -> ExecutionRecord:
        await self._transaction.bind(intent.tenant_id)
        planned_action = thaw_json(intent.planned_action)
        policy_decision = thaw_json(intent.policy_decision)
        if not isinstance(planned_action, dict) or not isinstance(
            policy_decision, dict
        ):
            raise AssertionError("execution bindings were frozen from objects")
        await self._transaction.connection.execute(
            """
            INSERT INTO flowpilot.planned_actions (
                action_id,
                tenant_id,
                task_id,
                requester_id,
                action_digest,
                tool_name,
                tool_schema_hash,
                policy_version,
                expires_at,
                planned_action,
                created_at
            )
            VALUES (
                %(action_id)s,
                %(tenant_id)s,
                %(task_id)s,
                %(requester_id)s,
                %(action_digest)s,
                %(tool_name)s,
                %(tool_schema_hash)s,
                %(policy_version)s,
                %(expires_at)s,
                %(planned_action)s::jsonb,
                %(created_at)s
            )
            ON CONFLICT DO NOTHING
            """,
            {
                "action_id": intent.action_id,
                "tenant_id": intent.tenant_id,
                "task_id": intent.task_id,
                "requester_id": planned_action["requester_id"],
                "action_digest": intent.action_digest,
                "tool_name": intent.tool_name,
                "tool_schema_hash": intent.tool_schema_hash,
                "policy_version": intent.policy_version,
                "expires_at": intent.planned_action_expires_at,
                "planned_action": _json_dump(planned_action),
                "created_at": intent.created_at,
            },
        )
        stored_action = await self._transaction.connection.fetch_one(
            """
            SELECT planned_action
            FROM flowpilot.planned_actions
            WHERE tenant_id = %(tenant_id)s AND action_id = %(action_id)s
            """,
            {"tenant_id": intent.tenant_id, "action_id": intent.action_id},
        )
        if (
            stored_action is None
            or _json_object(
                stored_action["planned_action"], "stored planned action"
            )
            != planned_action
        ):
            raise PersistenceError(
                PersistenceErrorCode.CONFLICT,
                "action_id is bound to another planned action snapshot",
            )
        await self._transaction.connection.execute(
            """
            INSERT INTO flowpilot.policy_decisions (
                policy_decision_id,
                tenant_id,
                task_id,
                action_digest,
                policy_version,
                expires_at,
                policy_decision,
                created_at
            )
            VALUES (
                %(policy_decision_id)s,
                %(tenant_id)s,
                %(task_id)s,
                %(action_digest)s,
                %(policy_version)s,
                %(expires_at)s,
                %(policy_decision)s::jsonb,
                %(created_at)s
            )
            ON CONFLICT DO NOTHING
            """,
            {
                "policy_decision_id": intent.policy_decision_id,
                "tenant_id": intent.tenant_id,
                "task_id": intent.task_id,
                "action_digest": intent.action_digest,
                "policy_version": intent.policy_version,
                "expires_at": intent.policy_expires_at,
                "policy_decision": _json_dump(policy_decision),
                "created_at": intent.created_at,
            },
        )
        stored_policy = await self._transaction.connection.fetch_one(
            """
            SELECT policy_decision
            FROM flowpilot.policy_decisions
            WHERE tenant_id = %(tenant_id)s
              AND policy_decision_id = %(policy_decision_id)s
            """,
            {
                "tenant_id": intent.tenant_id,
                "policy_decision_id": intent.policy_decision_id,
            },
        )
        if (
            stored_policy is None
            or _json_object(
                stored_policy["policy_decision"], "stored policy decision"
            )
            != policy_decision
        ):
            raise PersistenceError(
                PersistenceErrorCode.CONFLICT,
                "policy decision id is bound to another immutable snapshot",
            )
        if intent.approval is not None:
            approval = thaw_json(intent.approval)
            if not isinstance(approval, dict):
                raise AssertionError("approval was frozen from an object")
            await self._transaction.connection.execute(
                """
                INSERT INTO flowpilot.approvals (
                    approval_id,
                    tenant_id,
                    task_id,
                    requester_id,
                    action_id,
                    action_digest,
                    tool_schema_hash,
                    policy_decision_id,
                    policy_version,
                    status,
                    approver_id,
                    decision_reason,
                    separation_of_duties_result,
                    requested_at,
                    decided_at,
                    expires_at,
                    approval
                )
                VALUES (
                    %(approval_id)s,
                    %(tenant_id)s,
                    %(task_id)s,
                    %(requester_id)s,
                    %(action_id)s,
                    %(action_digest)s,
                    %(tool_schema_hash)s,
                    %(policy_decision_id)s,
                    %(policy_version)s,
                    %(status)s,
                    %(approver_id)s,
                    %(decision_reason)s,
                    %(separation_of_duties_result)s,
                    %(requested_at)s,
                    %(decided_at)s,
                    %(expires_at)s,
                    %(approval)s::jsonb
                )
                ON CONFLICT DO NOTHING
                """,
                {
                    "approval_id": intent.approval_id,
                    "tenant_id": intent.tenant_id,
                    "task_id": intent.task_id,
                    "requester_id": approval["requester_id"],
                    "action_id": intent.action_id,
                    "action_digest": intent.action_digest,
                    "tool_schema_hash": intent.tool_schema_hash,
                    "policy_decision_id": intent.policy_decision_id,
                    "policy_version": intent.policy_version,
                    "status": approval["status"],
                    "approver_id": approval["approver_id"],
                    "decision_reason": approval["decision_reason"],
                    "separation_of_duties_result": approval[
                        "separation_of_duties_result"
                    ],
                    "requested_at": approval["requested_at"],
                    "decided_at": approval["decided_at"],
                    "expires_at": intent.approval_expires_at,
                    "approval": _json_dump(approval),
                },
            )
            stored_approval = await self._transaction.connection.fetch_one(
                """
                SELECT approval
                FROM flowpilot.approvals
                WHERE tenant_id = %(tenant_id)s
                  AND approval_id = %(approval_id)s
                """,
                {
                    "tenant_id": intent.tenant_id,
                    "approval_id": intent.approval_id,
                },
            )
            if (
                stored_approval is None
                or _json_object(
                    stored_approval["approval"], "stored approval"
                )
                != approval
            ):
                raise PersistenceError(
                    PersistenceErrorCode.CONFLICT,
                    "approval id is bound to another immutable snapshot",
                )
        parameters = {
            "tool_execution_id": intent.tool_execution_id,
            "request_id": intent.request_id,
            "tenant_id": intent.tenant_id,
            "task_id": intent.task_id,
            "tool_name": intent.tool_name,
            "idempotency_key": intent.idempotency_key,
            "action_id": intent.action_id,
            "action_digest": intent.action_digest,
            "planned_action": _json_dump(planned_action),
            "planned_action_expires_at": intent.planned_action_expires_at,
            "policy_decision_id": intent.policy_decision_id,
            "policy_version": intent.policy_version,
            "policy_decision": _json_dump(policy_decision),
            "policy_expires_at": intent.policy_expires_at,
            "tool_schema_hash": intent.tool_schema_hash,
            "approval_id": intent.approval_id,
            "approval": (
                _json_dump(thaw_json(intent.approval))
                if intent.approval is not None
                else None
            ),
            "approval_expires_at": intent.approval_expires_at,
            "intent": _json_dump(_intent_to_mapping(intent)),
            "created_at": intent.created_at,
        }
        affected = await self._transaction.connection.execute(
            """
            INSERT INTO flowpilot.tool_executions (
                tool_execution_id,
                request_id,
                tenant_id,
                task_id,
                tool_name,
                idempotency_key,
                action_id,
                action_digest,
                planned_action,
                planned_action_expires_at,
                policy_decision_id,
                policy_version,
                policy_decision,
                policy_expires_at,
                tool_schema_hash,
                approval_id,
                approval,
                approval_expires_at,
                intent,
                status,
                attempt_count,
                created_at,
                updated_at
            )
            VALUES (
                %(tool_execution_id)s,
                %(request_id)s,
                %(tenant_id)s,
                %(task_id)s,
                %(tool_name)s,
                %(idempotency_key)s,
                %(action_id)s,
                %(action_digest)s,
                %(planned_action)s::jsonb,
                %(planned_action_expires_at)s,
                %(policy_decision_id)s,
                %(policy_version)s,
                %(policy_decision)s::jsonb,
                %(policy_expires_at)s,
                %(tool_schema_hash)s,
                %(approval_id)s,
                %(approval)s::jsonb,
                %(approval_expires_at)s,
                %(intent)s::jsonb,
                'prepared',
                0,
                %(created_at)s,
                %(created_at)s
            )
            ON CONFLICT DO NOTHING
            """,
            parameters,
        )
        row = await self._transaction.connection.fetch_one(
            """
            SELECT intent, status, attempt_count, updated_at, outcome
            FROM flowpilot.tool_executions
            WHERE tenant_id = %(tenant_id)s
              AND (
                  tool_execution_id = %(tool_execution_id)s
                  OR (
                      tool_name = %(tool_name)s
                      AND idempotency_key = %(idempotency_key)s
                  )
              )
            ORDER BY (tool_execution_id = %(tool_execution_id)s) DESC
            LIMIT 1
            """,
            parameters,
        )
        if row is None:
            raise PersistenceError(
                PersistenceErrorCode.DRIVER_PROTOCOL,
                "prepared execution could not be read back",
                retryable=True,
            )
        record = _execution_from_row(row)
        if affected == 0 and record.intent.fingerprint() != intent.fingerprint():
            raise PersistenceError(
                PersistenceErrorCode.IDEMPOTENCY_CONFLICT,
                "execution identity is bound to another immutable action",
            )
        return record

    async def get(
        self, tenant_id: str, tool_execution_id: str
    ) -> ExecutionRecord | None:
        await self._transaction.bind(tenant_id)
        row = await self._transaction.connection.fetch_one(
            """
            SELECT intent, status, attempt_count, updated_at, outcome
            FROM flowpilot.tool_executions
            WHERE tenant_id = %(tenant_id)s
              AND tool_execution_id = %(tool_execution_id)s
            """,
            {
                "tenant_id": tenant_id,
                "tool_execution_id": tool_execution_id,
            },
        )
        return _execution_from_row(row) if row is not None else None

    async def mark_running(
        self,
        tenant_id: str,
        tool_execution_id: str,
        *,
        now: datetime,
    ) -> ExecutionRecord:
        await self._transaction.bind(tenant_id)
        row = await self._transaction.connection.fetch_one(
            """
            UPDATE flowpilot.tool_executions
            SET status = 'running',
                attempt_count = attempt_count + 1,
                outcome = NULL,
                updated_at = %(now)s
            WHERE tenant_id = %(tenant_id)s
              AND tool_execution_id = %(tool_execution_id)s
              AND status IN ('prepared', 'failed_retryable')
            RETURNING intent, status, attempt_count, updated_at, outcome
            """,
            {
                "tenant_id": tenant_id,
                "tool_execution_id": tool_execution_id,
                "now": utc(now, "now"),
            },
        )
        if row is None:
            current = await self.get(tenant_id, tool_execution_id)
            code = (
                PersistenceErrorCode.RECONCILIATION_REQUIRED
                if current is not None and current.status is LedgerStatus.UNKNOWN
                else PersistenceErrorCode.INVALID_TRANSITION
            )
            raise PersistenceError(
                code,
                "execution cannot enter running from its current status",
            )
        return _execution_from_row(row)

    async def record_outcome(
        self,
        tenant_id: str,
        tool_execution_id: str,
        outcome: ExecutionOutcome,
    ) -> ExecutionRecord:
        await self._transaction.bind(tenant_id)
        row = await self._transaction.connection.fetch_one(
            """
            UPDATE flowpilot.tool_executions
            SET status = %(status)s,
                outcome = %(outcome)s::jsonb,
                updated_at = %(updated_at)s
            WHERE tenant_id = %(tenant_id)s
              AND tool_execution_id = %(tool_execution_id)s
            RETURNING intent, status, attempt_count, updated_at, outcome
            """,
            {
                "tenant_id": tenant_id,
                "tool_execution_id": tool_execution_id,
                "status": outcome.status.value,
                "outcome": _json_dump(_outcome_to_mapping(outcome)),
                "updated_at": outcome.recorded_at,
            },
        )
        if row is None:
            raise PersistenceError(
                PersistenceErrorCode.NOT_FOUND,
                "execution record was not found",
            )
        return _execution_from_row(row)

    async def pending_reconciliation(
        self, tenant_id: str, *, limit: int
    ) -> Sequence[ExecutionRecord]:
        await self._transaction.bind(tenant_id)
        if limit < 1:
            return ()
        rows = await self._transaction.connection.fetch_all(
            """
            SELECT intent, status, attempt_count, updated_at, outcome
            FROM flowpilot.tool_executions
            WHERE tenant_id = %(tenant_id)s AND status = 'unknown'
            ORDER BY updated_at, tool_execution_id
            LIMIT %(limit)s
            FOR UPDATE SKIP LOCKED
            """,
            {"tenant_id": tenant_id, "limit": limit},
        )
        return tuple(_execution_from_row(row) for row in rows)


def _lease_from_row(row: Row) -> LeaseFence:
    return LeaseFence(
        tenant_id=row["tenant_id"],
        task_id=row["task_id"],
        holder_id=row["holder_id"],
        lease_token=row["lease_token"],
        run_generation=int(row["run_generation"]),
        acquired_at=row["acquired_at"],
        expires_at=row["expires_at"],
    )


class PostgresLeaseRepository:
    def __init__(self, transaction: _TenantTransaction) -> None:
        self._transaction = transaction

    async def acquire(
        self,
        tenant_id: str,
        task_id: str,
        holder_id: str,
        *,
        now: datetime,
        ttl: timedelta,
    ) -> LeaseFence:
        await self._transaction.bind(tenant_id)
        if ttl <= timedelta(0):
            raise ValueError("lease ttl must be positive")
        normalized = utc(now, "now")
        parameters = {
            "tenant_id": tenant_id,
            "task_id": task_id,
            "holder_id": holder_id,
            "lease_token": f"lease_{uuid4().hex}",
            "acquired_at": normalized,
            "expires_at": normalized + ttl,
        }
        row = await self._transaction.connection.fetch_one(
            """
            INSERT INTO flowpilot.task_leases (
                tenant_id,
                task_id,
                holder_id,
                lease_token,
                run_generation,
                acquired_at,
                expires_at
            )
            VALUES (
                %(tenant_id)s,
                %(task_id)s,
                %(holder_id)s,
                %(lease_token)s,
                1,
                %(acquired_at)s,
                %(expires_at)s
            )
            ON CONFLICT (tenant_id, task_id) DO UPDATE
            SET holder_id = EXCLUDED.holder_id,
                lease_token = EXCLUDED.lease_token,
                run_generation = flowpilot.task_leases.run_generation + 1,
                acquired_at = EXCLUDED.acquired_at,
                expires_at = EXCLUDED.expires_at
            WHERE flowpilot.task_leases.expires_at <= %(acquired_at)s
            RETURNING tenant_id, task_id, holder_id, lease_token,
                      run_generation, acquired_at, expires_at
            """,
            parameters,
        )
        if row is not None:
            return _lease_from_row(row)
        current = await self._transaction.connection.fetch_one(
            """
            SELECT tenant_id, task_id, holder_id, lease_token,
                   run_generation, acquired_at, expires_at
            FROM flowpilot.task_leases
            WHERE tenant_id = %(tenant_id)s AND task_id = %(task_id)s
            """,
            parameters,
        )
        if current is not None and current["holder_id"] == holder_id:
            return _lease_from_row(current)
        raise PersistenceError(
            PersistenceErrorCode.LEASE_UNAVAILABLE,
            "task already has an active worker lease",
            retryable=True,
        )

    async def renew(
        self,
        fence: LeaseFence,
        *,
        now: datetime,
        ttl: timedelta,
    ) -> LeaseFence:
        await self._transaction.bind(fence.tenant_id)
        if ttl <= timedelta(0):
            raise ValueError("lease ttl must be positive")
        normalized = utc(now, "now")
        row = await self._transaction.connection.fetch_one(
            """
            UPDATE flowpilot.task_leases
            SET expires_at = %(expires_at)s
            WHERE tenant_id = %(tenant_id)s
              AND task_id = %(task_id)s
              AND holder_id = %(holder_id)s
              AND lease_token = %(lease_token)s
              AND run_generation = %(run_generation)s
              AND expires_at > %(now)s
            RETURNING tenant_id, task_id, holder_id, lease_token,
                      run_generation, acquired_at, expires_at
            """,
            {
                "tenant_id": fence.tenant_id,
                "task_id": fence.task_id,
                "holder_id": fence.holder_id,
                "lease_token": fence.lease_token,
                "run_generation": fence.run_generation,
                "now": normalized,
                "expires_at": normalized + ttl,
            },
        )
        if row is None:
            raise PersistenceError(
                PersistenceErrorCode.LEASE_LOST,
                "worker lease cannot be renewed",
            )
        return _lease_from_row(row)

    async def release(self, fence: LeaseFence) -> None:
        await self._transaction.bind(fence.tenant_id)
        affected = await self._transaction.connection.execute(
            """
            UPDATE flowpilot.task_leases
            SET lease_token = 'released_' || lease_token,
                acquired_at = acquired_at - INTERVAL '1 microsecond',
                expires_at = acquired_at
            WHERE tenant_id = %(tenant_id)s
              AND task_id = %(task_id)s
              AND holder_id = %(holder_id)s
              AND lease_token = %(lease_token)s
              AND run_generation = %(run_generation)s
            """,
            {
                "tenant_id": fence.tenant_id,
                "task_id": fence.task_id,
                "holder_id": fence.holder_id,
                "lease_token": fence.lease_token,
                "run_generation": fence.run_generation,
            },
        )
        if affected != 1:
            raise PersistenceError(
                PersistenceErrorCode.LEASE_LOST,
                "worker lease is no longer owned by this fence",
            )

    async def assert_fence(self, fence: LeaseFence, *, now: datetime) -> None:
        await self._transaction.bind(fence.tenant_id)
        row = await self._transaction.connection.fetch_one(
            """
            SELECT 1 AS valid
            FROM flowpilot.task_leases
            WHERE tenant_id = %(tenant_id)s
              AND task_id = %(task_id)s
              AND holder_id = %(holder_id)s
              AND lease_token = %(lease_token)s
              AND run_generation = %(run_generation)s
              AND expires_at > %(now)s
            """,
            {
                "tenant_id": fence.tenant_id,
                "task_id": fence.task_id,
                "holder_id": fence.holder_id,
                "lease_token": fence.lease_token,
                "run_generation": fence.run_generation,
                "now": utc(now, "now"),
            },
        )
        if row is None:
            raise PersistenceError(
                PersistenceErrorCode.STALE_FENCE,
                "worker fence is stale or expired",
            )


class PostgresCheckpointRepository:
    def __init__(
        self,
        transaction: _TenantTransaction,
        leases: PostgresLeaseRepository,
    ) -> None:
        self._transaction = transaction
        self._leases = leases

    async def put(
        self,
        checkpoint: CheckpointRecord,
        fence: LeaseFence,
        *,
        expected_sequence: int,
    ) -> CheckpointRecord:
        if (
            isinstance(expected_sequence, bool)
            or not isinstance(expected_sequence, int)
            or expected_sequence < 0
        ):
            raise ValueError(
                "expected_sequence must be a non-negative integer"
            )
        if checkpoint.checkpoint_sequence != expected_sequence:
            raise PersistenceError(
                PersistenceErrorCode.VERSION_CONFLICT,
                "checkpoint sequence does not match expected_sequence",
            )
        await self._transaction.bind(checkpoint.tenant_id)
        if (
            checkpoint.tenant_id != fence.tenant_id
            or checkpoint.task_id != fence.task_id
            or checkpoint.run_generation != fence.run_generation
        ):
            raise PersistenceError(
                PersistenceErrorCode.STALE_FENCE,
                "checkpoint does not match the worker fence",
            )
        fence_row = await self._transaction.connection.fetch_one(
            """
            SELECT lease.run_generation
            FROM flowpilot.task_leases AS lease
            JOIN flowpilot.tasks AS task
              ON task.tenant_id = lease.tenant_id
             AND task.task_id = lease.task_id
             AND task.thread_id = %(thread_id)s
            WHERE lease.tenant_id = %(tenant_id)s
              AND lease.task_id = %(task_id)s
              AND lease.holder_id = %(holder_id)s
              AND lease.lease_token = %(lease_token)s
              AND lease.run_generation = %(run_generation)s
              AND lease.expires_at > %(observed_at)s
            FOR UPDATE OF lease
            """,
            {
                "tenant_id": fence.tenant_id,
                "task_id": fence.task_id,
                "thread_id": checkpoint.thread_id,
                "holder_id": fence.holder_id,
                "lease_token": fence.lease_token,
                "run_generation": fence.run_generation,
                "observed_at": checkpoint.created_at,
            },
        )
        if fence_row is None:
            raise PersistenceError(
                PersistenceErrorCode.STALE_FENCE,
                "worker fence is stale, expired, or bound to another thread",
            )
        stored = replace(
            checkpoint,
            checkpoint_sequence=expected_sequence + 1,
        )
        parameters = {
            "checkpoint_id": stored.checkpoint_id,
            "tenant_id": stored.tenant_id,
            "task_id": stored.task_id,
            "thread_id": stored.thread_id,
            "run_generation": stored.run_generation,
            "checkpoint_sequence": stored.checkpoint_sequence,
            "expected_sequence": expected_sequence,
            "graph_version": stored.graph_version,
            "state": _json_dump(thaw_json(stored.state)),
            "security_context_ref": stored.security_context_ref,
            "security_context_hash": stored.security_context_hash,
            "created_at": stored.created_at,
        }
        existing_row = await self._transaction.connection.fetch_one(
            """
            SELECT checkpoint_id, tenant_id, task_id, thread_id,
                   run_generation, checkpoint_sequence, graph_version, state,
                   security_context_ref, security_context_hash, created_at,
                   (
                       SELECT max(latest.checkpoint_sequence)
                       FROM flowpilot.checkpoints AS latest
                       WHERE latest.tenant_id = %(tenant_id)s
                         AND latest.task_id = %(task_id)s
                   ) AS current_sequence
            FROM flowpilot.checkpoints
            WHERE tenant_id = %(tenant_id)s
              AND task_id = %(task_id)s
              AND checkpoint_id = %(checkpoint_id)s
            """,
            parameters,
        )
        if existing_row is not None:
            existing = _checkpoint_from_row(existing_row)
            if existing != stored:
                raise PersistenceError(
                    PersistenceErrorCode.CONFLICT,
                    "checkpoint identity is already bound to other state",
                )
            if int(existing_row["current_sequence"]) != stored.checkpoint_sequence:
                raise PersistenceError(
                    PersistenceErrorCode.VERSION_CONFLICT,
                    "checkpoint replay is stale relative to the latest sequence",
                )
            return existing
        affected = await self._transaction.connection.execute(
            """
            INSERT INTO flowpilot.checkpoints (
                checkpoint_id,
                tenant_id,
                task_id,
                thread_id,
                run_generation,
                checkpoint_sequence,
                graph_version,
                state,
                security_context_ref,
                security_context_hash,
                created_at
            )
            SELECT
                %(checkpoint_id)s,
                %(tenant_id)s,
                %(task_id)s,
                %(thread_id)s,
                %(run_generation)s,
                %(checkpoint_sequence)s,
                %(graph_version)s,
                %(state)s::jsonb,
                %(security_context_ref)s,
                %(security_context_hash)s,
                %(created_at)s
            WHERE COALESCE(
                (
                    SELECT max(current.checkpoint_sequence)
                    FROM flowpilot.checkpoints AS current
                    WHERE current.tenant_id = %(tenant_id)s
                      AND current.task_id = %(task_id)s
                ),
                0
            ) = %(expected_sequence)s
            ON CONFLICT DO NOTHING
            """,
            parameters,
        )
        if affected == 1:
            return stored
        raise PersistenceError(
            PersistenceErrorCode.VERSION_CONFLICT,
            "checkpoint compare-and-swap sequence does not match",
        )

    async def latest(
        self, tenant_id: str, task_id: str, thread_id: str
    ) -> CheckpointRecord | None:
        await self._transaction.bind(tenant_id)
        row = await self._transaction.connection.fetch_one(
            """
            SELECT checkpoint_id, tenant_id, task_id, thread_id,
                   run_generation, checkpoint_sequence, graph_version, state,
                   security_context_ref, security_context_hash, created_at
            FROM flowpilot.checkpoints
            WHERE tenant_id = %(tenant_id)s
              AND task_id = %(task_id)s
              AND thread_id = %(thread_id)s
            ORDER BY checkpoint_sequence DESC
            LIMIT 1
            """,
            {
                "tenant_id": tenant_id,
                "task_id": task_id,
                "thread_id": thread_id,
            },
        )
        if row is None:
            return None
        return _checkpoint_from_row(row)


def _checkpoint_from_row(row: Row) -> CheckpointRecord:
    return CheckpointRecord(
        checkpoint_id=row["checkpoint_id"],
        tenant_id=row["tenant_id"],
        task_id=row["task_id"],
        thread_id=row["thread_id"],
        run_generation=int(row["run_generation"]),
        checkpoint_sequence=int(row["checkpoint_sequence"]),
        graph_version=row["graph_version"],
        state=_json_object(row["state"], "checkpoint.state"),
        security_context_ref=row["security_context_ref"],
        security_context_hash=row["security_context_hash"],
        created_at=row["created_at"],
    )


def _event_to_mapping(event: OutboxEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "tenant_id": event.tenant_id,
        "aggregate_type": event.aggregate_type,
        "aggregate_id": event.aggregate_id,
        "sequence": event.sequence,
        "event_type": event.event_type,
        "payload": thaw_json(event.payload),
        "occurred_at": format_utc(event.occurred_at),
        "available_at": format_utc(event.available_at),
    }


def _delivery_from_row(row: Row) -> OutboxDelivery:
    event_value = _json_object(row["event"], "outbox.event")
    event = OutboxEvent(
        event_id=event_value["event_id"],
        tenant_id=event_value["tenant_id"],
        aggregate_type=event_value["aggregate_type"],
        aggregate_id=event_value["aggregate_id"],
        sequence=int(event_value["sequence"]),
        event_type=event_value["event_type"],
        payload=_json_object(event_value["payload"], "outbox.payload"),
        occurred_at=datetime.fromisoformat(
            event_value["occurred_at"].replace("Z", "+00:00")
        ),
        available_at=datetime.fromisoformat(
            event_value["available_at"].replace("Z", "+00:00")
        ),
    )
    return OutboxDelivery(
        event=event,
        publish_attempts=int(row["publish_attempts"]),
        published_at=row.get("published_at"),
    )


class PostgresOutboxRepository:
    def __init__(self, transaction: _TenantTransaction) -> None:
        self._transaction = transaction

    async def append(self, event: OutboxEvent) -> OutboxDelivery:
        await self._transaction.bind(event.tenant_id)
        parameters = {
            "event_id": event.event_id,
            "tenant_id": event.tenant_id,
            "aggregate_type": event.aggregate_type,
            "aggregate_id": event.aggregate_id,
            "sequence": event.sequence,
            "event_type": event.event_type,
            "event": _json_dump(_event_to_mapping(event)),
            "occurred_at": event.occurred_at,
            "available_at": event.available_at,
        }
        await self._transaction.connection.execute(
            """
            INSERT INTO flowpilot.outbox_events (
                event_id,
                tenant_id,
                aggregate_type,
                aggregate_id,
                sequence,
                event_type,
                event,
                occurred_at,
                available_at
            )
            VALUES (
                %(event_id)s,
                %(tenant_id)s,
                %(aggregate_type)s,
                %(aggregate_id)s,
                %(sequence)s,
                %(event_type)s,
                %(event)s::jsonb,
                %(occurred_at)s,
                %(available_at)s
            )
            ON CONFLICT DO NOTHING
            """,
            parameters,
        )
        row = await self._transaction.connection.fetch_one(
            """
            SELECT event, publish_attempts, published_at
            FROM flowpilot.outbox_events
            WHERE tenant_id = %(tenant_id)s AND event_id = %(event_id)s
            """,
            parameters,
        )
        if row is None:
            raise PersistenceError(
                PersistenceErrorCode.VERSION_CONFLICT,
                "outbox sequence is already occupied",
            )
        delivery = _delivery_from_row(row)
        if delivery.event.fingerprint() != event.fingerprint():
            raise PersistenceError(
                PersistenceErrorCode.CONFLICT,
                "event_id is bound to another outbox event",
            )
        return delivery

    async def unpublished(
        self, tenant_id: str, *, now: datetime, limit: int
    ) -> Sequence[OutboxDelivery]:
        await self._transaction.bind(tenant_id)
        if limit < 1:
            return ()
        rows = await self._transaction.connection.fetch_all(
            """
            SELECT event, publish_attempts, published_at
            FROM flowpilot.outbox_events
            WHERE tenant_id = %(tenant_id)s
              AND published_at IS NULL
              AND available_at <= %(now)s
            ORDER BY available_at, aggregate_type, aggregate_id, sequence
            LIMIT %(limit)s
            FOR UPDATE SKIP LOCKED
            """,
            {"tenant_id": tenant_id, "now": utc(now, "now"), "limit": limit},
        )
        return tuple(_delivery_from_row(row) for row in rows)

    async def mark_published(
        self, tenant_id: str, event_id: str, *, published_at: datetime
    ) -> OutboxDelivery:
        await self._transaction.bind(tenant_id)
        row = await self._transaction.connection.fetch_one(
            """
            UPDATE flowpilot.outbox_events
            SET publish_attempts = publish_attempts + 1,
                published_at = %(published_at)s
            WHERE tenant_id = %(tenant_id)s
              AND event_id = %(event_id)s
              AND published_at IS NULL
            RETURNING event, publish_attempts, published_at
            """,
            {
                "tenant_id": tenant_id,
                "event_id": event_id,
                "published_at": utc(published_at, "published_at"),
            },
        )
        if row is not None:
            return _delivery_from_row(row)
        existing = await self._transaction.connection.fetch_one(
            """
            SELECT event, publish_attempts, published_at
            FROM flowpilot.outbox_events
            WHERE tenant_id = %(tenant_id)s AND event_id = %(event_id)s
            """,
            {"tenant_id": tenant_id, "event_id": event_id},
        )
        if existing is None:
            raise PersistenceError(
                PersistenceErrorCode.NOT_FOUND, "outbox event was not found"
            )
        return _delivery_from_row(existing)

    async def sequence_gaps(
        self, tenant_id: str, aggregate_type: str, aggregate_id: str
    ) -> Sequence[int]:
        await self._transaction.bind(tenant_id)
        rows = await self._transaction.connection.fetch_all(
            """
            SELECT expected.sequence
            FROM generate_series(
                1,
                COALESCE(
                    (
                        SELECT MAX(sequence)
                        FROM flowpilot.outbox_events
                        WHERE tenant_id = %(tenant_id)s
                          AND aggregate_type = %(aggregate_type)s
                          AND aggregate_id = %(aggregate_id)s
                    ),
                    0
                )
            ) AS expected(sequence)
            LEFT JOIN flowpilot.outbox_events actual
              ON actual.tenant_id = %(tenant_id)s
             AND actual.aggregate_type = %(aggregate_type)s
             AND actual.aggregate_id = %(aggregate_id)s
             AND actual.sequence = expected.sequence
            WHERE actual.event_id IS NULL
            ORDER BY expected.sequence
            """,
            {
                "tenant_id": tenant_id,
                "aggregate_type": aggregate_type,
                "aggregate_id": aggregate_id,
            },
        )
        return tuple(int(row["sequence"]) for row in rows)


class PostgresConsumerInbox:
    def __init__(self, transaction: _TenantTransaction) -> None:
        self._transaction = transaction

    async def accept_once(
        self,
        tenant_id: str,
        consumer_id: str,
        event_id: str,
        payload_hash: str,
        *,
        processed_at: datetime,
    ) -> bool:
        await self._transaction.bind(tenant_id)
        parameters = {
            "tenant_id": tenant_id,
            "consumer_id": consumer_id,
            "event_id": event_id,
            "payload_hash": payload_hash,
            "processed_at": utc(processed_at, "processed_at"),
        }
        affected = await self._transaction.connection.execute(
            """
            INSERT INTO flowpilot.consumer_inbox (
                tenant_id, consumer_id, event_id, payload_hash, processed_at
            )
            VALUES (
                %(tenant_id)s,
                %(consumer_id)s,
                %(event_id)s,
                %(payload_hash)s,
                %(processed_at)s
            )
            ON CONFLICT (tenant_id, consumer_id, event_id) DO NOTHING
            """,
            parameters,
        )
        if affected == 1:
            return True
        row = await self._transaction.connection.fetch_one(
            """
            SELECT payload_hash
            FROM flowpilot.consumer_inbox
            WHERE tenant_id = %(tenant_id)s
              AND consumer_id = %(consumer_id)s
              AND event_id = %(event_id)s
            """,
            parameters,
        )
        if row is None or row["payload_hash"] != payload_hash:
            raise PersistenceError(
                PersistenceErrorCode.IDEMPOTENCY_CONFLICT,
                "redelivered event payload does not match its inbox record",
            )
        return False


class PostgresDataUnitOfWork:
    def __init__(self, connection_factory: AsyncPostgresConnectionFactory) -> None:
        self._connection_factory = connection_factory
        self._connection: AsyncPostgresConnection | None = None
        self._committed = False
        self.tasks: PostgresTaskRepository
        self.commands: PostgresCommandInbox
        self.ledger: PostgresExecutionLedger
        self.leases: PostgresLeaseRepository
        self.checkpoints: PostgresCheckpointRepository
        self.outbox: PostgresOutboxRepository
        self.consumer_inbox: PostgresConsumerInbox
        self.recovery: PostgresRecoverySignalRepository

    async def __aenter__(self) -> Self:
        self._connection = await self._connection_factory()
        transaction = _TenantTransaction(self._connection)
        self.tasks = PostgresTaskRepository(transaction)
        self.commands = PostgresCommandInbox(transaction)
        self.ledger = PostgresExecutionLedger(transaction)
        self.leases = PostgresLeaseRepository(transaction)
        self.checkpoints = PostgresCheckpointRepository(
            transaction, self.leases
        )
        self.outbox = PostgresOutboxRepository(transaction)
        self.consumer_inbox = PostgresConsumerInbox(transaction)
        self.recovery = PostgresRecoverySignalRepository(transaction)
        self._committed = False
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc, traceback
        connection = self._required_connection()
        try:
            if exc_type is not None or not self._committed:
                await connection.rollback()
        finally:
            await connection.close()
            self._connection = None

    async def commit(self) -> None:
        connection = self._required_connection()
        if self._committed:
            raise RuntimeError("unit of work was already committed")
        await connection.commit()
        self._committed = True

    def _required_connection(self) -> AsyncPostgresConnection:
        if self._connection is None:
            raise RuntimeError("unit of work has not been entered")
        return self._connection


class PostgresDataUnitOfWorkFactory:
    def __init__(self, connection_factory: AsyncPostgresConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def __call__(self) -> PostgresDataUnitOfWork:
        return PostgresDataUnitOfWork(self._connection_factory)
