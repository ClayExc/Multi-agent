from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from flowpilot_domain import (
    ActorType,
    AssuranceLevel,
    AuthenticationMethod,
    AuthenticationRef,
    DataClassification,
    SecurityContextRef,
    TaskCommand,
    canonical_sha256,
)
from flowpilot_graph import GraphError, GraphErrorCode, GraphState
from flowpilot_security import (
    SecurityError,
    SecurityErrorCode,
    SecurityVerifier,
    TrustedSecurityContext,
    trusted_context_snapshot_hash,
)
from flowpilot_worker import (
    InMemoryExecutionQueue,
    RuntimeExecutionAdapter,
    RuntimeSecurityContextValidator,
    RuntimeWorker,
)
from identity_helpers import MutableSecurityContextValidator

NOW = datetime(2026, 8, 11, 8, 0, tzinfo=UTC)
ISSUER = "https://identity.fixture.local/realms/flowpilot"
AUTHORIZED_PARTY = "flowpilot-runtime"
ROLES = frozenset({"employee", "knowledge-reader"})
SCOPES = frozenset({"tasks:read", "tools:invoke"})
TOKEN_HASH = canonical_sha256({"credential": "user-fixture"})


@dataclass
class _ContextSource:
    trusted: TrustedSecurityContext
    error: Exception | None = None
    resolve_count: int = 0

    async def resolve(self, context_ref: str) -> TrustedSecurityContext:
        self.resolve_count += 1
        if self.error is not None:
            raise self.error
        if context_ref != self.trusted.context.context_ref:
            raise RuntimeError("unknown context")
        return self.trusted


class _LeaseProbe:
    def __init__(self) -> None:
        self.acquire_count = 0

    async def acquire(self, *_args: Any, **_kwargs: Any) -> Any:
        self.acquire_count += 1
        raise AssertionError("revoked identity must not acquire a lease")

    async def assert_valid(self, _lease: Any) -> None:
        raise AssertionError("revoked identity must not validate a lease")

    async def release(self, _lease: Any) -> None:
        raise AssertionError("revoked identity must not release a lease")


class _GraphProbe:
    def __init__(self) -> None:
        self.execute_count = 0

    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        self.execute_count += 1
        raise AssertionError("revoked identity must not enter graph recovery")


def _trusted_context(
    *,
    active: bool = True,
    expires_at: datetime | None = None,
) -> TrustedSecurityContext:
    issued_at = NOW - timedelta(hours=1)
    effective_expiry = expires_at or NOW + timedelta(hours=1)
    authentication = AuthenticationRef(
        method=AuthenticationMethod.OIDC,
        assurance_level=AssuranceLevel.HIGH,
        session_id_hash=canonical_sha256({"session": "runtime-fixture"}),
    )
    context_id = "secctx_runtime001"
    context_ref = "security-context://tenant-a/user-runtime"
    context_hash = trusted_context_snapshot_hash(
        context_id=context_id,
        context_ref=context_ref,
        tenant_id="tenant-a",
        subject_id="user-runtime",
        subject_type=ActorType.USER,
        issuer=ISSUER,
        authorized_party=AUTHORIZED_PARTY,
        roles=ROLES,
        scopes=SCOPES,
        authentication=authentication,
        purpose="it_support",
        data_classification_ceiling=DataClassification.CONFIDENTIAL,
        issued_at=issued_at,
        expires_at=effective_expiry,
        source_token_hash=TOKEN_HASH,
    )
    context = SecurityContextRef(
        context_id=context_id,
        context_ref=context_ref,
        context_hash=context_hash,
        tenant_id="tenant-a",
        subject_id="user-runtime",
        subject_type=ActorType.USER,
        purpose="it_support",
        authentication=authentication,
        data_classification_ceiling=DataClassification.CONFIDENTIAL,
        issued_at=issued_at,
        expires_at=effective_expiry,
    )
    return TrustedSecurityContext(
        context=context,
        active=active,
        roles=ROLES,
        scopes=SCOPES,
        issuer=ISSUER,
        authorized_party=AUTHORIZED_PARTY,
        identity_token_hash=TOKEN_HASH,
    )


def _validator(source: _ContextSource) -> RuntimeSecurityContextValidator:
    return RuntimeSecurityContextValidator(
        contexts=source,
        verifier=SecurityVerifier(),
        clock=lambda: NOW,
    )


def test_runtime_validator_accepts_complete_current_snapshot() -> None:
    async def scenario() -> None:
        source = _ContextSource(_trusted_context())

        current = await _validator(source).validate_current(
            source.trusted.context
        )

        assert current == source.trusted.context
        assert source.resolve_count == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["revoked", "expired", "roles"])
def test_runtime_validator_rejects_revoked_expired_or_tampered_snapshot(
    failure: str,
) -> None:
    async def scenario() -> None:
        trusted = (
            _trusted_context(active=False)
            if failure == "revoked"
            else _trusted_context(expires_at=NOW)
            if failure == "expired"
            else replace(_trusted_context(), roles=frozenset({"tenant-admin"}))
        )

        with pytest.raises(GraphError) as captured:
            await _validator(_ContextSource(trusted)).validate_current(
                trusted.context
            )

        assert captured.value.code is GraphErrorCode.SECURITY_BINDING_MISMATCH
        assert captured.value.retryable is False
        assert captured.value.safe_message == (
            "trusted security context is not current"
        )

    asyncio.run(scenario())


def test_runtime_validator_maps_identity_source_outage_to_retryable_error() -> None:
    async def scenario() -> None:
        trusted = _trusted_context()
        source = _ContextSource(
            trusted,
            error=SecurityError(
                SecurityErrorCode.CONTEXT_UNAVAILABLE,
                "identity database unavailable",
            ),
        )

        with pytest.raises(GraphError) as captured:
            await _validator(source).validate_current(trusted.context)

        assert captured.value.code is GraphErrorCode.SECURITY_BINDING_MISMATCH
        assert captured.value.retryable is True
        assert captured.value.safe_message == (
            "trusted security context is temporarily unavailable"
        )

    asyncio.run(scenario())


def test_worker_revalidates_context_before_acquiring_lease(
    command_factory: Any,
) -> None:
    async def scenario() -> None:
        command: TaskCommand = command_factory()
        queue = InMemoryExecutionQueue()
        await RuntimeExecutionAdapter(queue).submit(command)
        contexts = MutableSecurityContextValidator()
        contexts.active = False
        leases = _LeaseProbe()
        graph = _GraphProbe()
        worker = RuntimeWorker(
            worker_id="worker_identity_boundary",
            queue=queue,
            leases=leases,
            graph=graph,
            security_contexts=contexts,
        )

        with pytest.raises(GraphError) as captured:
            await worker.run_once()

        assert captured.value.code is GraphErrorCode.SECURITY_BINDING_MISMATCH
        assert len(contexts.calls) == 1
        assert leases.acquire_count == 0
        assert graph.execute_count == 0
        assert queue.acknowledged_count == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "field",
    ["access_token", "client_secret", "refresh_token", "session_token"],
)
def test_checkpoint_rejects_identity_credential_fields(
    command_factory: Any,
    field: str,
) -> None:
    command: TaskCommand = command_factory()
    state = GraphState.from_checkpoint(
        {
            "task_id": command.task_id,
            "tenant_id": command.tenant_id,
            "command_id": command.command_id,
            "command_digest": command.command_digest,
            "run_id": "run_identity001",
            "run_generation": 1,
            "graph_version": "graph-v1",
            "status": "RUNNING",
            "node": "intake",
            "security_context_ref": command.security_context.context_ref,
            "security_context_hash": command.security_context.context_hash,
            "purpose": command.security_context.purpose,
            "checkpoint_sequence": 0,
            "attempt_count": 0,
        }
    )
    checkpoint = state.to_checkpoint()
    checkpoint[field] = "credential-material-must-not-persist"

    with pytest.raises(GraphError) as captured:
        GraphState.from_checkpoint(checkpoint)

    assert captured.value.code is GraphErrorCode.STATE_INVALID
