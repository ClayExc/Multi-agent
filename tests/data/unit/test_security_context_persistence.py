from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from flowpilot_domain import AssuranceLevel, DataClassification
from flowpilot_persistence import (
    PersistenceError,
    PersistenceErrorCode,
    PostgresContextBoundDataUnitOfWorkFactory,
    PostgresSecurityContextSource,
)
from flowpilot_security import (
    SecurityContextReference,
    SecurityError,
    SecurityErrorCode,
    TrustedContextMapper,
    TrustedContextMappingPolicy,
    TrustedSecurityContext,
    VerifiedUserIdentity,
)

NOW = datetime(2026, 8, 11, 8, 0, tzinfo=UTC)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def async_test(
    function: Callable[[], Coroutine[Any, Any, None]],
) -> Callable[[], None]:
    def run() -> None:
        asyncio.run(function())

    return run


def connection_factory(
    connection: ContextConnection,
) -> Callable[[], Coroutine[Any, Any, ContextConnection]]:
    async def factory() -> ContextConnection:
        return connection

    return factory


def fixed_clock(value: datetime) -> Callable[[], datetime]:
    return lambda: value


def trusted_context(
    *,
    tenant_id: str = "tenant-a",
    subject_id: str = "user-a",
) -> TrustedSecurityContext:
    identity = VerifiedUserIdentity(
        issuer="http://127.0.0.1:8081/realms/flowpilot-local",
        subject_id=subject_id,
        tenant_id=tenant_id,
        authorized_party="flowpilot-web",
        roles=frozenset({"flowpilot-user"}),
        scopes=frozenset({"openid", "tasks:read"}),
        assurance_level=AssuranceLevel.SUBSTANTIAL,
        session_id_hash=HASH_A,
        token_hash=HASH_B,
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=15),
    )
    mapper = TrustedContextMapper(
        TrustedContextMappingPolicy(
            allowed_purposes=frozenset({"task_execution"}),
            data_classification_ceiling=DataClassification.CONFIDENTIAL,
            maximum_ttl_seconds=900,
        )
    )
    suffix = tenant_id.replace("-", "_")
    return mapper.map_user(
        identity=identity,
        reference=SecurityContextReference(
            context_id=f"secctx_{suffix}_12345678",
            context_ref=f"security-context://{tenant_id}/{subject_id}/active",
        ),
        purpose="task_execution",
        now=NOW,
        ttl_seconds=600,
    )


def context_row(context: TrustedSecurityContext) -> dict[str, object]:
    value = context.context
    return {
        "tenant_id": value.tenant_id,
        "context_id": value.context_id,
        "context_ref": value.context_ref,
        "context_hash": value.context_hash,
        "subject_id": value.subject_id,
        "expires_at": value.expires_at,
        "context_snapshot": value.to_mapping(),
        "roles": sorted(context.roles),
        "scopes": sorted(context.scopes),
        "issuer": context.issuer,
        "authorized_party": context.authorized_party,
        "identity_token_hash": context.identity_token_hash,
        "active": context.active,
    }


class ContextConnection:
    def __init__(
        self,
        context: TrustedSecurityContext,
        *,
        safe_role: bool = True,
        insert_affected: int = 1,
        update_affected: int = 1,
        validation: bool = True,
    ) -> None:
        self.context = context
        self.safe_role = safe_role
        self.insert_affected = insert_affected
        self.update_affected = update_affected
        self.validation = validation
        self.statements: list[tuple[str, Mapping[str, object] | None]] = []
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0

    async def execute(
        self,
        statement: str,
        parameters: Mapping[str, object] | None = None,
    ) -> int:
        self.statements.append((statement, parameters))
        if "INSERT INTO flowpilot.security_contexts" in statement:
            return self.insert_affected
        if "UPDATE flowpilot.security_contexts" in statement:
            return self.update_affected
        return 1

    async def fetch_one(
        self,
        statement: str,
        parameters: Mapping[str, object] | None = None,
    ) -> Mapping[str, Any] | None:
        self.statements.append((statement, parameters))
        if "FROM pg_roles" in statement:
            return {
                "rolname": "flowpilot_api",
                "rolsuper": not self.safe_role,
                "rolbypassrls": False,
            }
        if "validate_security_context" in statement:
            if not self.validation:
                return None
            value = self.context.context
            return {
                "tenant_id": value.tenant_id,
                "context_ref": value.context_ref,
                "context_hash": value.context_hash,
                "subject_id": value.subject_id,
            }
        if "SELECT version" in statement:
            return {"version": 7}
        if "SELECT active" in statement:
            return {"active": False}
        if "FROM flowpilot.security_contexts" in statement:
            return context_row(self.context)
        return None

    async def fetch_all(
        self,
        statement: str,
        parameters: Mapping[str, object] | None = None,
    ) -> Sequence[Mapping[str, Any]]:
        self.statements.append((statement, parameters))
        return ()

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def close(self) -> None:
        self.closes += 1


@async_test
async def test_security_context_store_resolve_and_revoke() -> None:
    trusted = trusted_context()
    store_connection = ContextConnection(trusted)
    resolve_connection = ContextConnection(trusted)
    revoke_connection = ContextConnection(trusted)
    connections = iter((store_connection, resolve_connection, revoke_connection))

    async def factory() -> ContextConnection:
        return next(connections)

    source = PostgresSecurityContextSource(factory)
    await source.store(trusted)
    assert await source.resolve(trusted.context.context_ref) == trusted
    await source.revoke(
        trusted.context.context_ref,
        revoked_at=NOW + timedelta(minutes=1),
        reason_code="session_logout",
    )

    assert store_connection.commits == 1
    assert resolve_connection.rollbacks == 1
    assert revoke_connection.commits == 1
    assert all(item.closes == 1 for item in (
        store_connection,
        resolve_connection,
        revoke_connection,
    ))


@async_test
async def test_security_context_store_is_idempotent_and_conflict_safe() -> None:
    trusted = trusted_context()
    same = ContextConnection(trusted, insert_affected=0)

    async def same_factory() -> ContextConnection:
        return same

    await PostgresSecurityContextSource(same_factory).store(trusted)

    conflicting = trusted_context(subject_id="different-user")
    conflict_connection = ContextConnection(conflicting, insert_affected=0)

    async def conflict_factory() -> ContextConnection:
        return conflict_connection

    with pytest.raises(SecurityError) as raised:
        await PostgresSecurityContextSource(conflict_factory).store(trusted)
    assert raised.value.code is SecurityErrorCode.CONTEXT_UNTRUSTED
    assert conflict_connection.rollbacks == 1


@async_test
async def test_context_bound_uow_binds_all_dimensions_and_cleans_connection() -> None:
    trusted = trusted_context()
    connection = ContextConnection(trusted)

    async def factory() -> ContextConnection:
        return connection

    uow_factory = PostgresContextBoundDataUnitOfWorkFactory(
        factory,
        trusted,
        clock=lambda: NOW,
    )
    async with uow_factory() as data:
        assert await data.tasks.get_version("tenant-a", "task_12345678") == 7
        with pytest.raises(PersistenceError) as raised:
            await data.tasks.get_version("tenant-b", "task_12345678")
        assert raised.value.code is PersistenceErrorCode.TENANT_MISMATCH
        await data.commit()
        with pytest.raises(RuntimeError, match="already finished"):
            await data.tasks.get_version("tenant-a", "task_12345678")

    statements = [statement for statement, _ in connection.statements]
    binding = next(item for item in statements if "flowpilot.context_hash" in item)
    assert "flowpilot.tenant_id" in binding
    assert "flowpilot.context_ref" in binding
    assert "flowpilot.subject_id" in binding
    assert "validate_security_context" in "\n".join(statements)
    assert "RESET ALL" in statements
    assert connection.commits == 2
    assert connection.closes == 1


@async_test
async def test_context_bound_uow_rejects_database_mismatch_and_unsafe_role() -> None:
    trusted = trusted_context()
    mismatch = ContextConnection(trusted, validation=False)
    unsafe = ContextConnection(trusted, safe_role=False)
    for connection, expected in (
        (mismatch, PersistenceErrorCode.SECURITY_CONTEXT_MISMATCH),
        (unsafe, PersistenceErrorCode.UNSAFE_DATABASE_ROLE),
    ):
        with pytest.raises(PersistenceError) as raised:
            async with PostgresContextBoundDataUnitOfWorkFactory(
                connection_factory(connection),
                trusted,
                clock=lambda: NOW,
            )():
                pass
        assert raised.value.code is expected
        assert connection.rollbacks == 1
        assert connection.closes == 1


@async_test
async def test_context_bound_uow_rejects_revoked_expired_and_forged_context() -> None:
    trusted = trusted_context()
    cases = (
        replace(trusted, active=False),
        trusted,
        replace(
            trusted,
            context=replace(trusted.context, context_hash="sha256:" + "0" * 64),
        ),
    )
    clocks = (NOW, trusted.context.expires_at, NOW)
    for context, clock_value in zip(cases, clocks, strict=True):
        connection = ContextConnection(context)

        with pytest.raises(PersistenceError) as raised:
            async with PostgresContextBoundDataUnitOfWorkFactory(
                connection_factory(connection),
                context,
                clock=fixed_clock(clock_value),
            )():
                pass
        assert raised.value.code is PersistenceErrorCode.SECURITY_CONTEXT_UNTRUSTED
        assert connection.rollbacks == 1
        assert connection.closes == 1
