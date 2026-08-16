from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from fastapi import FastAPI
from flowpilot_application import (
    ApprovalDecisionService,
    ExecutionPort,
    GovernanceQueryService,
    GovernanceQueryUnitOfWorkFactory,
    TaskEventStreamConfig,
    TaskEventSubscriptionService,
    TaskEventUnitOfWorkFactory,
    TaskInitializationConfig,
    TaskQueryUnitOfWorkFactory,
    ThreadIdFactory,
    UnitOfWorkFactory,
    compose_core_application,
)

from .app import create_app
from .oidc import OidcApiSecurityBundle, OidcBffService
from .security import GovernanceAccessPolicy, RequestSecurityPort
from .stream import InMemoryEventStream


def create_product_app(
    *,
    command_unit_of_work: UnitOfWorkFactory,
    task_query_unit_of_work: TaskQueryUnitOfWorkFactory,
    task_event_unit_of_work: TaskEventUnitOfWorkFactory,
    execution: ExecutionPort,
    task_initialization: TaskInitializationConfig,
    thread_id_factory: ThreadIdFactory,
    request_security: RequestSecurityPort | None = None,
    approval_decisions: ApprovalDecisionService | None = None,
    event_stream: InMemoryEventStream | None = None,
    event_stream_config: TaskEventStreamConfig | None = None,
    clock: Callable[[], datetime] | None = None,
    oidc_bff: OidcBffService | None = None,
    oidc_security: OidcApiSecurityBundle | None = None,
    governance_query_unit_of_work: GovernanceQueryUnitOfWorkFactory | None = None,
    governance_access: GovernanceAccessPolicy | None = None,
) -> FastAPI:
    """Create the fully port-bound local-product API.

    The composition root accepts only S5 application protocols.  Provider,
    Worker, queue, database, Redis, MCP and identity implementations remain
    outside this package and must be supplied by their owning adapters.
    """

    if oidc_security is not None:
        if request_security is not None or oidc_bff is not None:
            raise ValueError(
                "OIDC security bundle cannot be mixed with separate adapters"
            )
        request_security = oidc_security.request_security
        oidc_bff = oidc_security.bff
    if request_security is None:
        raise ValueError("product request security must be configured")
    if (governance_query_unit_of_work is None) != (governance_access is None):
        raise ValueError(
            "governance query transaction and access policy must be configured together"
        )

    services = compose_core_application(
        command_unit_of_work=command_unit_of_work,
        task_query_unit_of_work=task_query_unit_of_work,
        execution=execution,
        task_initialization=task_initialization,
        thread_id_factory=thread_id_factory,
        clock=clock,
    )
    effective_stream = event_stream or InMemoryEventStream()
    subscription = TaskEventSubscriptionService(
        unit_of_work=task_event_unit_of_work,
        stream=effective_stream,
        config=event_stream_config,
        clock=clock,
    )
    return create_app(
        command_intake=services.command_intake,
        task_query=services.task_query,
        request_security=request_security,
        task_event_subscription=subscription,
        event_stream=effective_stream,
        approval_decisions=approval_decisions,
        oidc_bff=oidc_bff,
        governance_queries=(
            GovernanceQueryService(governance_query_unit_of_work)
            if governance_query_unit_of_work is not None
            else None
        ),
        governance_access=governance_access,
    )
