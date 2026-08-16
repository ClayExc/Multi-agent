from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from flowpilot_application import (
    KnowledgeAuthorizationPort,
    KnowledgeCommandService,
    KnowledgeContentSafetyPort,
    KnowledgeDiagnostic,
    KnowledgeDocumentProjection,
    KnowledgeImportRequest,
    KnowledgeLifecycleRequest,
    KnowledgeOperationReceipt,
    KnowledgeQueryService,
    KnowledgeReadRequest,
    KnowledgeRebuildRequest,
    KnowledgeUpdateRequest,
)
from flowpilot_domain import (
    AclPrincipal,
    AclPrincipalType,
    KnowledgeAccessControl,
    ToolOperation,
)
from flowpilot_mcp_gateway import (
    GatewayDependencies,
    McpGateway,
    ToolDefinition,
    ToolRegistry,
)
from flowpilot_mcp_knowledge import (
    KNOWLEDGE_CONTRACT,
    KNOWLEDGE_MCP_AUDIENCE,
    KNOWLEDGE_SEARCH_SCOPE,
    RetrievalKnowledgeMcpAdapter,
)
from flowpilot_persistence import (
    AsyncPostgresConnectionFactory,
    DeterministicEmbeddingPort,
    HashEmbeddingAdapter,
    PostgresKnowledgeCandidateRepository,
    PostgresKnowledgeUnitOfWorkFactory,
)
from flowpilot_retrieval import HybridRetrievalEngine
from flowpilot_security import TrustedSecurityContext


class KnowledgeAccessKind(StrEnum):
    READ = "read"
    DIAGNOSTIC = "diagnostic"
    MANAGE = "manage"


@dataclass(frozen=True, slots=True)
class KnowledgeAccessPolicy:
    management_roles: frozenset[str]
    read_roles: frozenset[str]
    diagnostic_roles: frozenset[str]
    allowed_purposes: frozenset[str]

    def __post_init__(self) -> None:
        values = (
            self.management_roles,
            self.read_roles,
            self.diagnostic_roles,
            self.allowed_purposes,
        )
        if any(
            not collection or any(not item or len(item) > 256 for item in collection)
            for collection in values
        ):
            raise ValueError("knowledge access allowlists must be non-empty")

    def roles_for(self, kind: KnowledgeAccessKind) -> frozenset[str]:
        if kind is KnowledgeAccessKind.MANAGE:
            return self.management_roles
        if kind is KnowledgeAccessKind.DIAGNOSTIC:
            return self.diagnostic_roles
        return self.read_roles


class KnowledgeCommandPort(Protocol):
    async def import_document(
        self, request: KnowledgeImportRequest
    ) -> KnowledgeOperationReceipt: ...

    async def update_document(
        self, request: KnowledgeUpdateRequest
    ) -> KnowledgeOperationReceipt: ...

    async def retire_document(
        self, request: KnowledgeLifecycleRequest
    ) -> KnowledgeOperationReceipt: ...

    async def delete_document(
        self, request: KnowledgeLifecycleRequest
    ) -> KnowledgeOperationReceipt: ...

    async def rebuild_document(
        self, request: KnowledgeRebuildRequest
    ) -> KnowledgeOperationReceipt: ...


class KnowledgeQueryPort(Protocol):
    async def get_document(
        self, request: KnowledgeReadRequest
    ) -> KnowledgeDocumentProjection: ...

    async def diagnose(self, request: KnowledgeReadRequest) -> KnowledgeDiagnostic: ...


@dataclass(frozen=True, slots=True)
class KnowledgeApiServices:
    commands: KnowledgeCommandPort
    queries: KnowledgeQueryPort


class KnowledgeApiServiceFactory(Protocol):
    def create(
        self, trusted_context: TrustedSecurityContext
    ) -> KnowledgeApiServices: ...


class KnowledgeAccessControlFactory(Protocol):
    def create(
        self, trusted_context: TrustedSecurityContext
    ) -> KnowledgeAccessControl: ...


class IdentityBoundKnowledgeAccessControlFactory:
    """Derive an ACL from verified identity, never from the request body."""

    def create(self, trusted_context: TrustedSecurityContext) -> KnowledgeAccessControl:
        if not trusted_context.active:
            raise ValueError("trusted knowledge context must be active")
        context = trusted_context.context
        principals = {
            AclPrincipal(AclPrincipalType.SUBJECT, context.subject_id),
            *(
                AclPrincipal(AclPrincipalType.ROLE, role)
                for role in trusted_context.roles
            ),
        }
        return KnowledgeAccessControl(
            principals=tuple(principals),
            allowed_purposes=(context.purpose,),
            tenant_wide=False,
        )


class PostgresKnowledgeServiceFactory:
    """Create request-bound services over one verified PostgreSQL tenant context."""

    def __init__(
        self,
        *,
        connection_factory: AsyncPostgresConnectionFactory,
        authorization: KnowledgeAuthorizationPort,
        content_safety: KnowledgeContentSafetyPort,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._connections = connection_factory
        self._authorization = authorization
        self._content_safety = content_safety
        self._clock = clock

    def create(self, trusted_context: TrustedSecurityContext) -> KnowledgeApiServices:
        if not trusted_context.active:
            raise ValueError("trusted knowledge context must be active")
        unit_of_work = PostgresKnowledgeUnitOfWorkFactory(
            self._connections,
            trusted_context,
            clock=self._clock,
        )
        return KnowledgeApiServices(
            commands=KnowledgeCommandService(
                unit_of_work=unit_of_work,
                authorization=self._authorization,
                content_safety=self._content_safety,
                clock=self._clock,
            ),
            queries=KnowledgeQueryService(
                unit_of_work=unit_of_work,
                authorization=self._authorization,
                clock=self._clock,
            ),
        )


@dataclass(frozen=True, slots=True)
class KnowledgeGatewayConfig:
    allowed_agents: frozenset[str]
    allowed_tenants: frozenset[str]
    allowed_purposes: frozenset[str]
    additional_tool_definitions: tuple[ToolDefinition, ...] = ()

    def __post_init__(self) -> None:
        if (
            not self.allowed_agents
            or not self.allowed_tenants
            or not self.allowed_purposes
        ):
            raise ValueError("knowledge Gateway allowlists must be non-empty")
        if any(
            definition.contract.name == KNOWLEDGE_CONTRACT.name
            for definition in self.additional_tool_definitions
        ):
            raise ValueError("knowledge Gateway definition must not be overridden")


@dataclass(frozen=True, slots=True)
class PostgresKnowledgeComposition:
    services: KnowledgeApiServices
    retrieval: HybridRetrievalEngine
    adapter: RetrievalKnowledgeMcpAdapter
    gateway: McpGateway


def compose_postgres_knowledge_gateway(
    *,
    trusted_context: TrustedSecurityContext,
    connection_factory: AsyncPostgresConnectionFactory,
    authorization: KnowledgeAuthorizationPort,
    content_safety: KnowledgeContentSafetyPort,
    candidates: PostgresKnowledgeCandidateRepository,
    gateway_dependencies: GatewayDependencies,
    config: KnowledgeGatewayConfig,
    embedding: DeterministicEmbeddingPort | None = None,
    clock: Callable[[], datetime] | None = None,
) -> PostgresKnowledgeComposition:
    """Compose only the M10 PostgreSQL/Retrieval/Gateway production path."""

    if not isinstance(candidates, PostgresKnowledgeCandidateRepository):
        raise ValueError("M10 production composition requires PostgreSQL candidates")
    services = PostgresKnowledgeServiceFactory(
        connection_factory=connection_factory,
        authorization=authorization,
        content_safety=content_safety,
        clock=clock,
    ).create(trusted_context)
    if not isinstance(services.queries, KnowledgeQueryService):
        raise ValueError("M10 production composition requires KnowledgeQueryService")
    retrieval = HybridRetrievalEngine(
        embedding=embedding or HashEmbeddingAdapter(),
        candidates=candidates,
        citations=services.queries,
    )
    adapter = RetrievalKnowledgeMcpAdapter(
        retrieval,
        expected_audience=KNOWLEDGE_MCP_AUDIENCE,
        clock=clock or gateway_dependencies.clock,
    )
    definition = ToolDefinition(
        contract=KNOWLEDGE_CONTRACT,
        operation=ToolOperation.READ,
        audience=KNOWLEDGE_MCP_AUDIENCE,
        upstream_provider="flowpilot-mcp-knowledge",
        allowed_agents=config.allowed_agents,
        allowed_tenants=config.allowed_tenants,
        allowed_purposes=config.allowed_purposes,
        credential_scopes=frozenset({KNOWLEDGE_SEARCH_SCOPE}),
        adapter=adapter,
    )
    dependencies = replace(
        gateway_dependencies,
        registry=ToolRegistry((*config.additional_tool_definitions, definition)),
    )
    return PostgresKnowledgeComposition(
        services=services,
        retrieval=retrieval,
        adapter=adapter,
        gateway=McpGateway(dependencies),
    )
