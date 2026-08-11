from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from fastapi import FastAPI
from flowpilot_application import (
    ApprovalDecisionService,
    ExecutionPort,
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
from .oidc import OidcBffService
from .security import RequestSecurityPort
from .stream import InMemoryEventStream


def create_product_app(
    *,
    command_unit_of_work: UnitOfWorkFactory,
    task_query_unit_of_work: TaskQueryUnitOfWorkFactory,
    task_event_unit_of_work: TaskEventUnitOfWorkFactory,
    execution: ExecutionPort,
    task_initialization: TaskInitializationConfig,
    thread_id_factory: ThreadIdFactory,
    request_security: RequestSecurityPort,
    approval_decisions: ApprovalDecisionService | None = None,
    event_stream: InMemoryEventStream | None = None,
    event_stream_config: TaskEventStreamConfig | None = None,
    clock: Callable[[], datetime] | None = None,
    oidc_bff: OidcBffService | None = None,
) -> FastAPI:
    """Create the fully port-bound local-product API.

    The composition root accepts only S5 application protocols.  Provider,
    Worker, queue, database, Redis, MCP and identity implementations remain
    outside this package and must be supplied by their owning adapters.
    """

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
    )
