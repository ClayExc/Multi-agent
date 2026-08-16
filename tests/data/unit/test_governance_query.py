from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from flowpilot_application import (
    ApplicationError,
    ErrorCode,
    GovernanceQueryContext,
)
from flowpilot_persistence import (
    GovernanceCursorCodec,
    PostgresGovernanceQueryUnitOfWorkFactory,
)

DIGEST = "sha256:" + "a" * 64
SECRET = b"cursor-signing-secret-is-at-least-32-bytes"


def context(tenant: str = "tenant-a") -> GovernanceQueryContext:
    return GovernanceQueryContext(
        tenant_id=tenant,
        subject_id="subject-01",
        purpose="security_review",
        security_context_ref="security-context/context01",
        security_context_hash=DIGEST,
    )


def test_cursor_is_signed_and_bound_to_tenant_resource_filter_and_sort() -> None:
    codec = GovernanceCursorCodec(SECRET)
    binding = {
        "tenant": "tenant-a",
        "resource": "audit_events",
        "filters": {"task_id": "task_task0001"},
        "sort": ["occurred_at", "event_id"],
        "version": 1,
    }
    cursor = codec.encode(binding, ("2026-08-16T09:00:00+00:00", "evt_event0001"))
    assert cursor.startswith("gcur_")
    assert codec.decode(cursor, binding)[1] == "evt_event0001"

    for forged in (
        cursor[:-1] + ("A" if cursor[-1] != "A" else "B"),
        codec.encode({**binding, "tenant": "tenant-b"}, ("x", "y")),
        codec.encode({**binding, "resource": "security_events"}, ("x", "y")),
    ):
        with pytest.raises(ApplicationError) as raised:
            codec.decode(forged, binding)
        assert raised.value.code is ErrorCode.GOVERNANCE_CURSOR_INVALID


class Connection:
    def __init__(self, *, validated: bool = True) -> None:
        self.validated = validated
        self.statements: list[tuple[str, Mapping[str, object] | None]] = []
        self.rolled_back = self.committed = self.closed = False

    async def execute(
        self, statement: str, parameters: Mapping[str, object] | None = None
    ) -> int:
        self.statements.append((statement, parameters))
        return 0

    async def fetch_one(
        self, statement: str, parameters: Mapping[str, object] | None = None
    ) -> Mapping[str, Any] | None:
        self.statements.append((statement, parameters))
        return {"validated": True} if self.validated else None

    async def fetch_all(
        self, statement: str, parameters: Mapping[str, object] | None = None
    ) -> Sequence[Mapping[str, Any]]:
        self.statements.append((statement, parameters))
        return ()

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def close(self) -> None:
        self.closed = True


def test_uow_binds_all_trusted_dimensions_and_cleans_connection() -> None:
    asyncio.run(_uow_binds_all_trusted_dimensions_and_cleans_connection())


async def _uow_binds_all_trusted_dimensions_and_cleans_connection() -> None:
    connection = Connection()

    async def factory() -> Connection:
        return connection

    async with PostgresGovernanceQueryUnitOfWorkFactory(factory, SECRET)(context()):
        pass
    bind = connection.statements[0]
    assert bind[1] == {
        "tenant_id": "tenant-a",
        "context_ref": "security-context/context01",
        "context_hash": DIGEST,
        "subject_id": "subject-01",
        "purpose": "security_review",
    }
    assert "validate_governance_query_context" in connection.statements[1][0]
    assert any(statement == "RESET ALL" for statement, _ in connection.statements)
    assert connection.rolled_back and connection.committed and connection.closed


def test_uow_fails_closed_when_context_is_not_in_postgres() -> None:
    asyncio.run(_uow_fails_closed_when_context_is_not_in_postgres())


async def _uow_fails_closed_when_context_is_not_in_postgres() -> None:
    connection = Connection(validated=False)

    async def factory() -> Connection:
        return connection

    with pytest.raises(ApplicationError) as raised:
        async with PostgresGovernanceQueryUnitOfWorkFactory(factory, SECRET)(context()):
            pass
    assert raised.value.code is ErrorCode.GOVERNANCE_REPOSITORY_UNAVAILABLE
    assert connection.rolled_back and connection.closed


def test_migration_is_linear_rls_append_only_and_down_guarded() -> None:
    up = Path("migrations/0005_governance_audit_query.sql").read_text(encoding="utf-8")
    down = Path("migrations/0005_governance_audit_query.down.sql").read_text(
        encoding="utf-8"
    )
    assert "requires 0004_security_context_rls_binding" in up
    assert "validate_governance_query_context" in up
    assert "sc.purpose = flowpilot.session_purpose()" in up
    assert "FORCE ROW LEVEL SECURITY" in up
    assert "governance facts are append-only" in up
    assert "append_security_event" in up
    assert "security and audit event association is invalid" in up
    assert "FOR SHARE" in up
    assert "security_barrier=true" in up
    assert "cannot remove non-empty governance facts" in down
    assert down.index("cannot remove non-empty") < down.index("DROP TABLE")
