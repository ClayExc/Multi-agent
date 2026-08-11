from __future__ import annotations

import asyncio
import hashlib
import os
import selectors
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import psycopg
from flowpilot_domain import AssuranceLevel, DataClassification
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[3]
for package in (
    "domain",
    "tool-contracts",
    "security",
    "application",
    "persistence",
):
    sys.path.insert(0, str(ROOT / "packages" / package / "src"))

from flowpilot_persistence import (  # noqa: E402
    CoordinationRebuilder,
    CoordinationSignal,
    DataUnitOfWorkFactory,
    MemoryRedisClient,
    PersistenceError,
    PersistenceErrorCode,
    PostgresContextBoundDataUnitOfWorkFactory,
    PostgresSecurityContextSource,
    RedisCoordinationAdapter,
)
from flowpilot_security import (  # noqa: E402
    SecurityContextReference,
    SecurityError,
    SecurityErrorCode,
    TrustedContextMapper,
    TrustedContextMappingPolicy,
    TrustedSecurityContext,
    VerifiedUserIdentity,
)

NOW = datetime.now(UTC)


class PsycopgConnection:
    def __init__(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        *,
        close_underlying: bool = True,
    ) -> None:
        self.connection = connection
        self.close_underlying = close_underlying

    async def execute(
        self,
        statement: str,
        parameters: Mapping[str, object] | None = None,
    ) -> int:
        cursor = await self.connection.execute(statement, parameters)
        return cursor.rowcount

    async def fetch_one(
        self,
        statement: str,
        parameters: Mapping[str, object] | None = None,
    ) -> Mapping[str, Any] | None:
        cursor = await self.connection.execute(statement, parameters)
        return await cursor.fetchone()

    async def fetch_all(
        self,
        statement: str,
        parameters: Mapping[str, object] | None = None,
    ) -> Sequence[Mapping[str, Any]]:
        cursor = await self.connection.execute(statement, parameters)
        return await cursor.fetchall()

    async def commit(self) -> None:
        await self.connection.commit()

    async def rollback(self) -> None:
        await self.connection.rollback()

    async def close(self) -> None:
        if self.close_underlying:
            await self.connection.close()


def trusted_context(
    *,
    tenant_id: str,
    subject_id: str,
    suffix: str,
) -> TrustedSecurityContext:
    identity = VerifiedUserIdentity(
        issuer="http://127.0.0.1:8081/realms/flowpilot-local",
        subject_id=subject_id,
        tenant_id=tenant_id,
        authorized_party="flowpilot-web",
        roles=frozenset({"flowpilot-user"}),
        scopes=frozenset({"openid", "tasks:read"}),
        assurance_level=AssuranceLevel.SUBSTANTIAL,
        session_id_hash="sha256:" + "a" * 64,
        token_hash="sha256:" + hashlib.sha256(suffix.encode("utf-8")).hexdigest(),
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
    return mapper.map_user(
        identity=identity,
        reference=SecurityContextReference(
            context_id=f"secctx_{suffix}_12345678",
            context_ref=f"security-context://{tenant_id}/{subject_id}/{suffix}",
        ),
        purpose="task_execution",
        now=NOW,
        ttl_seconds=600,
    )


async def main() -> None:
    database_url = os.environ["FLOWPILOT_TEST_DATABASE_URL"]

    async def connect(role: str | None) -> PsycopgConnection:
        connection = await psycopg.AsyncConnection.connect(
            database_url,
            row_factory=dict_row,
        )
        if role is not None:
            await connection.execute(f"SET ROLE {role}")
        return PsycopgConnection(connection)

    async def api_factory() -> PsycopgConnection:
        return await connect("flowpilot_api")

    async def worker_factory() -> PsycopgConnection:
        return await connect("flowpilot_worker")

    async def unsafe_factory() -> PsycopgConnection:
        return await connect(None)

    context_a = trusted_context(
        tenant_id="tenant-a",
        subject_id="tenant-a-user",
        suffix="tenant_a",
    )
    context_b = trusted_context(
        tenant_id="tenant-b",
        subject_id="tenant-b-user",
        suffix="tenant_b",
    )
    source = PostgresSecurityContextSource(api_factory)
    await source.store(context_a)
    await source.store(context_b)
    await source.store(context_a)
    if await source.resolve(context_a.context.context_ref) != context_a:
        raise AssertionError("tenant-a security context did not round-trip")

    with pytest_raises_persistence(PersistenceErrorCode.UNSAFE_DATABASE_ROLE):
        await PostgresSecurityContextSource(unsafe_factory).resolve(
            context_a.context.context_ref
        )

    shared = await psycopg.AsyncConnection.connect(database_url, row_factory=dict_row)
    await shared.execute("SET ROLE flowpilot_api")
    shared_wrapper = PsycopgConnection(shared, close_underlying=False)

    async def shared_factory() -> PsycopgConnection:
        return shared_wrapper

    bound_a = PostgresContextBoundDataUnitOfWorkFactory(
        shared_factory,
        context_a,
        clock=lambda: NOW,
    )
    async with bound_a() as data:
        if await data.tasks.get_version("tenant-a", "missing-task") is not None:
            raise AssertionError("missing tenant-a task unexpectedly exists")
        try:
            await data.tasks.get_version("tenant-b", "missing-task")
        except PersistenceError as exc:
            if exc.code is not PersistenceErrorCode.TENANT_MISMATCH:
                raise
        else:
            raise AssertionError("cross-tenant repository access succeeded")

    row = await (
        await shared.execute(
            """
            SELECT current_setting('flowpilot.tenant_id', true) AS tenant_id,
                   current_setting('flowpilot.context_ref', true) AS context_ref,
                   current_setting('flowpilot.context_hash', true) AS context_hash,
                   current_setting('flowpilot.subject_id', true) AS subject_id
            """
        )
    ).fetchone()
    if row is None or any(value not in (None, "") for value in row.values()):
        raise AssertionError("connection retained tenant or security context state")
    await shared.close()

    redis_client = MemoryRedisClient()
    redis = RedisCoordinationAdapter(redis_client, namespace="flowpilot:wp084")
    await redis.signal(
        CoordinationSignal(
            tenant_id="tenant-a",
            task_id="stale-redis-task",
            run_generation=1,
            available_at=NOW,
        )
    )
    await redis.clear()
    if redis_client.values:
        raise AssertionError("Redis loss fixture retained coordination state")
    worker_context = await source.resolve(context_a.context.context_ref)
    rebuilt = await CoordinationRebuilder(
        cast(
            DataUnitOfWorkFactory,
            PostgresContextBoundDataUnitOfWorkFactory(
                worker_factory,
                worker_context,
                clock=lambda: NOW,
            ),
        ),
        redis,
    ).rebuild(("tenant-a",), now=NOW)
    if rebuilt != 0 or redis_client.values:
        raise AssertionError("Redis recovery invented non-durable task facts")

    await source.revoke(
        context_a.context.context_ref,
        revoked_at=NOW + timedelta(minutes=1),
        reason_code="session_logout",
    )
    revoked = await source.resolve(context_a.context.context_ref)
    if revoked.active:
        raise AssertionError("revoked security context remained active")
    with pytest_raises_persistence(PersistenceErrorCode.SECURITY_CONTEXT_UNTRUSTED):
        async with PostgresContextBoundDataUnitOfWorkFactory(
            worker_factory,
            revoked,
            clock=lambda: NOW + timedelta(minutes=2),
        )():
            pass
    with pytest_raises_persistence(PersistenceErrorCode.SECURITY_CONTEXT_UNTRUSTED):
        async with PostgresContextBoundDataUnitOfWorkFactory(
            worker_factory,
            context_b,
            clock=lambda: context_b.context.expires_at,
        )():
            pass

    missing_ref = "security-context://tenant-a/missing/context"
    try:
        await source.resolve(missing_ref)
    except SecurityError as security_exc:
        if security_exc.code is not SecurityErrorCode.CONTEXT_UNAVAILABLE:
            raise
    else:
        raise AssertionError("missing security context resolved")

    print(
        "SECURITY_CONTEXT_POSTGRES_OK "
        "stored=2 idempotent=1 cross_tenant_success=0 "
        "unsafe_role_rejected=1 pool_residual=0 revoked=1 expired=1 "
        "redis_rebuilt=0"
    )


class pytest_raises_persistence:
    def __init__(self, code: PersistenceErrorCode) -> None:
        self.code = code

    def __enter__(self) -> None:
        return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> bool:
        del traceback
        if exc_type is None or not isinstance(exc, PersistenceError):
            raise AssertionError(f"expected persistence error {self.code}")
        if exc.code is not self.code:
            raise AssertionError(
                f"expected persistence error {self.code}, got {exc.code}"
            )
        return True


if __name__ == "__main__":
    asyncio.run(
        main(),
        loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
    )
