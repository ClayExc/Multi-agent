from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from flowpilot_api import (
    IdentityBoundKnowledgeAccessControlFactory,
    KnowledgeAccessKind,
    KnowledgeAccessPolicy,
    KnowledgeApiServices,
    KnowledgeGatewayConfig,
    TrustedRequestIdentity,
    compose_postgres_knowledge_gateway,
    create_app,
)
from flowpilot_api.testing import StaticRequestSecurity
from flowpilot_application import (
    ApplicationError,
    ErrorCode,
    KnowledgeCommandService,
    KnowledgeDiagnostic,
    KnowledgeDocumentProjection,
    KnowledgeImportRequest,
    KnowledgeIndexState,
    KnowledgeLifecycleRequest,
    KnowledgeOperation,
    KnowledgeOperationDisposition,
    KnowledgeOperationReceipt,
    KnowledgeQueryService,
    KnowledgeReadRequest,
    KnowledgeRebuildRequest,
    KnowledgeUpdateRequest,
)
from flowpilot_domain import (
    AclPrincipal,
    AclPrincipalType,
    ActorType,
    AssuranceLevel,
    AuthenticationMethod,
    AuthenticationRef,
    DataClassification,
    DocumentVersion,
    KnowledgeAccessControl,
    KnowledgeContent,
    KnowledgeDocument,
    KnowledgeSource,
    KnowledgeSourceType,
    SecurityContextRef,
)
from flowpilot_mcp_gateway import GatewayDependencies, McpGateway
from flowpilot_mcp_knowledge import (
    KNOWLEDGE_CONTRACT,
    KNOWLEDGE_SCHEMA_PIN,
    RetrievalKnowledgeMcpAdapter,
)
from flowpilot_persistence import (
    PostgresKnowledgeCandidateRepository,
)
from flowpilot_retrieval import HybridRetrievalEngine
from flowpilot_security import TrustedSecurityContext

NOW = datetime(2026, 8, 16, 8, 0, tzinfo=UTC)
TENANT = "tenant-knowledge-a"
DOCUMENT_ID = "doc_knowledge0001"
IDEMPOTENCY_KEY = "sha256:" + "3" * 64


def _trusted(
    *,
    roles: frozenset[str] = frozenset(
        {"knowledge-manager", "knowledge-reader", "knowledge-diagnostics"}
    ),
) -> TrustedSecurityContext:
    context = SecurityContextRef(
        context_id="secctx_knowledge0001",
        context_ref="security-context://knowledge/one",
        context_hash="sha256:" + "1" * 64,
        tenant_id=TENANT,
        subject_id="user-knowledge-owner",
        subject_type=ActorType.USER,
        purpose="support_resolution",
        authentication=AuthenticationRef(
            method=AuthenticationMethod.OIDC,
            assurance_level=AssuranceLevel.SUBSTANTIAL,
            session_id_hash="sha256:" + "2" * 64,
        ),
        data_classification_ceiling=DataClassification.CONFIDENTIAL,
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(hours=1),
    )
    return TrustedSecurityContext(
        context=context,
        active=True,
        roles=roles,
        scopes=frozenset({"knowledge:read", "knowledge:write"}),
    )


def _identity(trusted: TrustedSecurityContext | None = None) -> TrustedRequestIdentity:
    value = trusted or _trusted()
    context = value.context
    return TrustedRequestIdentity(
        tenant_id=context.tenant_id,
        subject_id=context.subject_id,
        subject_type=context.subject_type,
        purpose=context.purpose,
        security_context_id=context.context_id,
        security_context_ref=context.context_ref,
        security_context_hash=context.context_hash,
        security_context=context,
        trusted_security_context=value,
        roles=value.roles,
        scopes=value.scopes,
    )


def _acl() -> KnowledgeAccessControl:
    return KnowledgeAccessControl(
        principals=(AclPrincipal(AclPrincipalType.SUBJECT, "user-knowledge-owner"),),
        allowed_purposes=("support_resolution",),
    )


def _projection() -> KnowledgeDocumentProjection:
    source = KnowledgeSource.build(
        source_type=KnowledgeSourceType.FILE,
        source_ref="source://private/runbook",
        source_version="source-v1",
    )
    content = KnowledgeContent.from_text("Approved local recovery runbook.")
    version = DocumentVersion(
        tenant_id=TENANT,
        document_id=DOCUMENT_ID,
        version=0,
        source=source,
        access_control=_acl(),
        data_classification=DataClassification.CONFIDENTIAL,
        effective_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(days=30),
        content_ref="knowledge-content://" + "a" * 64,
        content_hash=content.content_hash,
        created_at=NOW,
    )
    return KnowledgeDocumentProjection(
        document=KnowledgeDocument.start(version),
        version=version,
    )


def _receipt(
    operation: KnowledgeOperation,
    *,
    disposition: KnowledgeOperationDisposition = KnowledgeOperationDisposition.APPLIED,
) -> KnowledgeOperationReceipt:
    return KnowledgeOperationReceipt(
        tenant_id=TENANT,
        document_id=DOCUMENT_ID,
        operation=operation,
        revision=0,
        document_version=0,
        disposition=disposition,
        event_id="kevt_knowledge0001",
        index_job_id="kjob_knowledge0001",
    )


@dataclass(slots=True)
class _Commands:
    calls: list[object] = field(default_factory=list)
    failure: ApplicationError | None = None

    async def _accept(
        self,
        request: object,
        operation: KnowledgeOperation,
    ) -> KnowledgeOperationReceipt:
        if self.failure is not None:
            raise self.failure
        duplicate = any(
            getattr(item, "idempotency_key", None)
            == getattr(request, "idempotency_key", None)
            for item in self.calls
        )
        self.calls.append(request)
        return _receipt(
            operation,
            disposition=(
                KnowledgeOperationDisposition.DUPLICATE
                if duplicate
                else KnowledgeOperationDisposition.APPLIED
            ),
        )

    async def import_document(
        self, request: KnowledgeImportRequest
    ) -> KnowledgeOperationReceipt:
        return await self._accept(request, KnowledgeOperation.IMPORT)

    async def update_document(
        self, request: KnowledgeUpdateRequest
    ) -> KnowledgeOperationReceipt:
        return await self._accept(request, KnowledgeOperation.UPDATE)

    async def retire_document(
        self, request: KnowledgeLifecycleRequest
    ) -> KnowledgeOperationReceipt:
        return await self._accept(request, KnowledgeOperation.RETIRE)

    async def delete_document(
        self, request: KnowledgeLifecycleRequest
    ) -> KnowledgeOperationReceipt:
        return await self._accept(request, KnowledgeOperation.DELETE)

    async def rebuild_document(
        self, request: KnowledgeRebuildRequest
    ) -> KnowledgeOperationReceipt:
        return await self._accept(request, KnowledgeOperation.REBUILD)


@dataclass(slots=True)
class _Queries:
    reads: list[KnowledgeReadRequest] = field(default_factory=list)

    async def get_document(
        self, request: KnowledgeReadRequest
    ) -> KnowledgeDocumentProjection:
        self.reads.append(request)
        return _projection()

    async def diagnose(self, request: KnowledgeReadRequest) -> KnowledgeDiagnostic:
        self.reads.append(request)
        projection = _projection()
        return KnowledgeDiagnostic(
            tenant_id=TENANT,
            document_id=DOCUMENT_ID,
            document_version=0,
            document_revision=0,
            content_hash=projection.version.content_hash,
            index_state=KnowledgeIndexState.READY,
            last_job_id="kjob_knowledge0001",
            indexed_at=NOW,
        )


@dataclass(slots=True)
class _Services:
    commands: _Commands = field(default_factory=_Commands)
    queries: _Queries = field(default_factory=_Queries)
    trusted: list[TrustedSecurityContext] = field(default_factory=list)

    def create(self, trusted_context: TrustedSecurityContext) -> KnowledgeApiServices:
        self.trusted.append(trusted_context)
        return KnowledgeApiServices(commands=self.commands, queries=self.queries)


def _access_policy() -> KnowledgeAccessPolicy:
    return KnowledgeAccessPolicy(
        management_roles=frozenset({"knowledge-manager"}),
        read_roles=frozenset({"knowledge-reader"}),
        diagnostic_roles=frozenset({"knowledge-diagnostics"}),
        allowed_purposes=frozenset({"support_resolution"}),
    )


def _app(
    *,
    identity: TrustedRequestIdentity | None = None,
) -> tuple[FastAPI, _Services, StaticRequestSecurity]:
    services = _Services()
    security = StaticRequestSecurity(identity or _identity())
    return (
        create_app(
            request_security=security,
            knowledge_services=services,
            knowledge_access=_access_policy(),
            knowledge_access_control=IdentityBoundKnowledgeAccessControlFactory(),
        ),
        services,
        security,
    )


def _request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    body: object | None = None,
    idempotency_key: str | None = None,
) -> httpx.Response:
    async def send() -> httpx.Response:
        headers = (
            {"Idempotency-Key": idempotency_key}
            if idempotency_key is not None
            else None
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://flowpilot.test",
        ) as client:
            return await client.request(method, path, json=body, headers=headers)

    return asyncio.run(send())


def _import_body() -> dict[str, object]:
    return {
        "document_id": DOCUMENT_ID,
        "source_type": "file",
        "source_ref": "source://private/runbook",
        "source_version": "source-v1",
        "data_classification": "confidential",
        "effective_at": (NOW - timedelta(minutes=1)).isoformat(),
        "expires_at": (NOW + timedelta(days=30)).isoformat(),
        "content": "Approved local recovery runbook.",
    }


def test_import_uses_reverified_context_server_acl_and_replays() -> None:
    app, services, security = _app()

    first = _request(
        app,
        "POST",
        "/v1/knowledge/documents",
        body=_import_body(),
        idempotency_key=IDEMPOTENCY_KEY,
    )
    replay = _request(
        app,
        "POST",
        "/v1/knowledge/documents",
        body=_import_body(),
        idempotency_key=IDEMPOTENCY_KEY,
    )

    assert first.status_code == 201
    assert first.json()["disposition"] == "applied"
    assert replay.status_code == 201
    assert replay.json()["disposition"] == "duplicate"
    command = cast(KnowledgeImportRequest, services.commands.calls[0])
    assert command.request_digest == command.recompute_digest()
    assert command.context.tenant_id == TENANT
    assert command.access_control.tenant_wide is False
    assert command.access_control.principals == (
        AclPrincipal(AclPrincipalType.ROLE, "knowledge-diagnostics"),
        AclPrincipal(AclPrincipalType.ROLE, "knowledge-manager"),
        AclPrincipal(AclPrincipalType.ROLE, "knowledge-reader"),
        AclPrincipal(AclPrincipalType.SUBJECT, "user-knowledge-owner"),
    )
    assert services.trusted == [_identity().trusted_security_context] * 2
    assert security.knowledge_access_calls == [
        (TENANT, KnowledgeAccessKind.MANAGE),
        (TENANT, KnowledgeAccessKind.MANAGE),
    ]


@pytest.mark.parametrize(
    ("method", "path", "body", "operation"),
    (
        (
            "PUT",
            f"/v1/knowledge/documents/{DOCUMENT_ID}",
            {**_import_body(), "expected_revision": 0},
            KnowledgeOperation.UPDATE,
        ),
        (
            "POST",
            f"/v1/knowledge/documents/{DOCUMENT_ID}/retire",
            {"expected_revision": 0},
            KnowledgeOperation.RETIRE,
        ),
        (
            "DELETE",
            f"/v1/knowledge/documents/{DOCUMENT_ID}",
            {"expected_revision": 0},
            KnowledgeOperation.DELETE,
        ),
        (
            "POST",
            f"/v1/knowledge/documents/{DOCUMENT_ID}/rebuild",
            {"expected_revision": 0, "document_version": 0},
            KnowledgeOperation.REBUILD,
        ),
    ),
)
def test_management_routes_bind_digests(
    method: str,
    path: str,
    body: dict[str, object],
    operation: KnowledgeOperation,
) -> None:
    app, services, _security = _app()
    if operation is KnowledgeOperation.UPDATE:
        body = {key: value for key, value in body.items() if key != "document_id"}

    response = _request(
        app,
        method,
        path,
        body=body,
        idempotency_key=IDEMPOTENCY_KEY,
    )

    assert response.status_code == 200
    assert response.json()["operation"] == operation.value
    command = services.commands.calls[0]
    expected_digest = (
        command.recompute_digest(operation)
        if isinstance(command, KnowledgeLifecycleRequest)
        else command.recompute_digest()
    )
    assert command.request_digest == expected_digest


def test_reads_return_only_safe_document_and_diagnostic_projections() -> None:
    app, services, security = _app()

    document = _request(
        app,
        "GET",
        f"/v1/knowledge/documents/{DOCUMENT_ID}?document_version=0",
    )
    diagnostic = _request(
        app,
        "GET",
        f"/v1/knowledge/documents/{DOCUMENT_ID}/diagnostic?document_version=0",
    )

    assert document.status_code == 200
    assert diagnostic.status_code == 200
    assert document.headers["cache-control"] == "no-store"
    assert document.headers["vary"] == "Cookie"
    assert diagnostic.json()["index_state"] == "ready"
    forbidden = {
        "tenant_id",
        "source_ref",
        "content_ref",
        "content",
        "excerpt",
        "principals",
    }
    assert forbidden.isdisjoint(document.json())
    assert forbidden.isdisjoint(diagnostic.json())
    assert [item.document_version for item in services.queries.reads] == [0, 0]
    assert security.knowledge_access_calls[-2:] == [
        (TENANT, KnowledgeAccessKind.READ),
        (TENANT, KnowledgeAccessKind.DIAGNOSTIC),
    ]


@pytest.mark.parametrize(
    "forged_field",
    ("tenant_id", "acl", "capability", "security_context", "content_ref"),
)
def test_write_body_rejects_client_authority_fields(forged_field: str) -> None:
    app, services, security = _app()
    body = {**_import_body(), forged_field: "forged"}

    response = _request(
        app,
        "POST",
        "/v1/knowledge/documents",
        body=body,
        idempotency_key=IDEMPOTENCY_KEY,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == ErrorCode.KNOWLEDGE_CONTRACT_INVALID
    assert services.commands.calls == []
    assert security.knowledge_access_calls == []


def test_missing_trusted_context_and_wrong_duty_fail_before_services() -> None:
    untrusted = _identity()
    untrusted = replace(
        untrusted,
        security_context=None,
        trusted_security_context=None,
    )
    missing_app, missing_services, _security = _app(identity=untrusted)
    wrong_app, wrong_services, _wrong_security = _app(
        identity=_identity(_trusted(roles=frozenset({"knowledge-reader"})))
    )

    missing = _request(
        missing_app,
        "POST",
        "/v1/knowledge/documents",
        body=_import_body(),
        idempotency_key=IDEMPOTENCY_KEY,
    )
    denied = _request(
        wrong_app,
        "POST",
        "/v1/knowledge/documents",
        body=_import_body(),
        idempotency_key=IDEMPOTENCY_KEY,
    )

    assert missing.status_code == 403
    assert denied.status_code == 403
    assert missing_services.commands.calls == []
    assert wrong_services.commands.calls == []


@pytest.mark.parametrize(
    ("code", "status"),
    (
        (ErrorCode.KNOWLEDGE_CONTRACT_INVALID, 400),
        (ErrorCode.KNOWLEDGE_AUTHORIZATION_DENIED, 403),
        (ErrorCode.KNOWLEDGE_NOT_FOUND, 404),
        (ErrorCode.KNOWLEDGE_VERSION_CONFLICT, 409),
        (ErrorCode.KNOWLEDGE_REPOSITORY_UNAVAILABLE, 503),
        (ErrorCode.KNOWLEDGE_REPOSITORY_PROTOCOL_ERROR, 502),
    ),
)
def test_knowledge_errors_have_stable_http_mapping(
    code: ErrorCode,
    status: int,
) -> None:
    app, services, _security = _app()
    services.commands.failure = ApplicationError(code, "safe knowledge failure")

    response = _request(
        app,
        "POST",
        "/v1/knowledge/documents",
        body=_import_body(),
        idempotency_key=IDEMPOTENCY_KEY,
    )

    assert response.status_code == status
    assert response.json()["error"]["code"] == code.value


def test_knowledge_dependencies_are_all_or_none() -> None:
    with pytest.raises(ValueError, match="configured together"):
        create_app(
            knowledge_services=_Services(),
            knowledge_access=_access_policy(),
        )


def test_postgres_composition_uses_retrieval_adapter_and_pinned_gateway() -> None:
    trusted = _trusted()
    candidates = PostgresKnowledgeCandidateRepository(cast(Any, object()))
    dependencies = GatewayDependencies(
        registry=cast(Any, object()),
        security_contexts=cast(Any, object()),
        security=cast(Any, object()),
        policies=cast(Any, object()),
        policy=cast(Any, object()),
        approvals=cast(Any, object()),
        approval=cast(Any, object()),
        approvers=cast(Any, object()),
        credentials=cast(Any, object()),
        data_uow=cast(Any, object()),
        signals=cast(Any, object()),
        clock=lambda: NOW,
    )

    composition = compose_postgres_knowledge_gateway(
        trusted_context=trusted,
        connection_factory=cast(Any, object()),
        authorization=cast(Any, object()),
        content_safety=cast(Any, object()),
        candidates=candidates,
        gateway_dependencies=dependencies,
        config=KnowledgeGatewayConfig(
            allowed_agents=frozenset({"knowledge-agent"}),
            allowed_tenants=frozenset({TENANT}),
            allowed_purposes=frozenset({"support_resolution"}),
        ),
        clock=lambda: NOW,
    )

    assert isinstance(composition.services.commands, KnowledgeCommandService)
    assert isinstance(composition.services.queries, KnowledgeQueryService)
    assert isinstance(composition.retrieval, HybridRetrievalEngine)
    assert type(composition.adapter) is RetrievalKnowledgeMcpAdapter
    assert isinstance(composition.gateway, McpGateway)
    assert KNOWLEDGE_CONTRACT.schema_hash == KNOWLEDGE_SCHEMA_PIN
