from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from fastapi import FastAPI
from flowpilot_agent_runtime import AgentRuntimePort
from flowpilot_api import RequestSecurityPort, create_product_app
from flowpilot_api.stream import InMemoryEventStream
from flowpilot_application import (
    RequestObservationService,
    RequestReferenceResolverPort,
    ResultArtifactPort,
    ResultArtifactService,
    TaskEventStreamConfig,
    TaskInitializationConfig,
    ThreadIdFactory,
)
from flowpilot_domain import DataClassification
from flowpilot_graph import SecurityContextValidationPort
from flowpilot_persistence import (
    ApplicationUnitOfWorkFactories,
    AsyncPostgresConnectionFactory,
    CoordinationPort,
    CoordinationRebuilder,
    DataUnitOfWorkFactory,
    PostgresDataUnitOfWorkFactory,
    PostgresSecurityContextSource,
    compose_application_unit_of_work_factories,
)
from flowpilot_security import SecurityVerifier
from flowpilot_tool_contracts import GatewayClientPort

from .adapter import RuntimeExecutionAdapter
from .durable import DurableRuntime, build_durable_runtime
from .events import TaskEventPublisher
from .identity import RuntimeSecurityContextValidator
from .knowledge import (
    EnterpriseKnowledgeDurableGraphFactory,
    KnowledgeGraphConfig,
)
from .persistence import PersistenceRuntimeConfig, TrustedTenantInventory
from .queue import ExecutionQueuePort


@dataclass(frozen=True, slots=True)
class LocalProductRuntime:
    """Explicit API/Worker composition over one durable persistence factory."""

    app: FastAPI
    worker: DurableRuntime
    execution: RuntimeExecutionAdapter
    event_stream: InMemoryEventStream
    data_unit_of_work: DataUnitOfWorkFactory
    application_unit_of_work: ApplicationUnitOfWorkFactories


def compose_local_product_runtime(
    *,
    worker_id: str,
    data_unit_of_work: DataUnitOfWorkFactory,
    coordination: CoordinationPort,
    tenants: TrustedTenantInventory,
    queue: ExecutionQueuePort,
    request_security: RequestSecurityPort,
    task_initialization: TaskInitializationConfig,
    thread_id_factory: ThreadIdFactory,
    request_resolver: RequestReferenceResolverPort,
    result_artifacts: ResultArtifactPort,
    gateway: GatewayClientPort,
    agent_runtime: AgentRuntimePort,
    security_contexts: SecurityContextValidationPort,
    control_checkpointer: object,
    graph_config: KnowledgeGraphConfig | None = None,
    runtime_config: PersistenceRuntimeConfig | None = None,
    event_stream_config: TaskEventStreamConfig | None = None,
    clock: Callable[[], datetime] | None = None,
    run_id_factory: Callable[[], str] | None = None,
) -> LocalProductRuntime:
    """Compose the formal enterprise-knowledge product over owned ports.

    ``data_unit_of_work`` is reused only as a factory. Every S5 application
    transaction and every Worker lease/checkpoint operation creates a fresh
    underlying unit of work.
    """

    if control_checkpointer is None:
        raise ValueError("a control checkpointer must be explicitly configured")
    config = graph_config or KnowledgeGraphConfig()
    _validate_release(task_initialization, config)

    application_uow = compose_application_unit_of_work_factories(
        data_unit_of_work
    )
    execution = RuntimeExecutionAdapter(queue)
    event_stream = InMemoryEventStream()
    app = create_product_app(
        command_unit_of_work=application_uow.command_unit_of_work,
        task_query_unit_of_work=application_uow.task_query_unit_of_work,
        task_event_unit_of_work=application_uow.task_event_unit_of_work,
        execution=execution,
        task_initialization=task_initialization,
        thread_id_factory=thread_id_factory,
        request_security=request_security,
        event_stream=event_stream,
        event_stream_config=event_stream_config,
        clock=clock,
    )

    requests = RequestObservationService(
        resolver=request_resolver,
        required_fields={config.intent: (config.question_field,)},
    )
    graph_factory = EnterpriseKnowledgeDurableGraphFactory(
        requests=requests,
        artifacts=ResultArtifactService(result_artifacts),
        gateway=gateway,
        runtime=agent_runtime,
        security_contexts=security_contexts,
        config=config,
        clock=clock,
    )
    worker = build_durable_runtime(
        worker_id=worker_id,
        queue=queue,
        unit_of_work=data_unit_of_work,
        coordination_rebuilder=CoordinationRebuilder(
            data_unit_of_work,
            coordination,
        ),
        tenants=tenants,
        graph_factory=graph_factory,
        security_contexts=security_contexts,
        control_checkpointer=control_checkpointer,
        runtime_config=runtime_config,
        clock=clock,
        run_id_factory=run_id_factory,
        event_publisher=TaskEventPublisher(clock=clock),
    )
    return LocalProductRuntime(
        app=app,
        worker=worker,
        execution=execution,
        event_stream=event_stream,
        data_unit_of_work=data_unit_of_work,
        application_unit_of_work=application_uow,
    )


def compose_postgres_local_product_runtime(
    *,
    connection_factory: AsyncPostgresConnectionFactory,
    worker_id: str,
    coordination: CoordinationPort,
    tenants: TrustedTenantInventory,
    queue: ExecutionQueuePort,
    request_security: RequestSecurityPort,
    task_initialization: TaskInitializationConfig,
    thread_id_factory: ThreadIdFactory,
    request_resolver: RequestReferenceResolverPort,
    result_artifacts: ResultArtifactPort,
    gateway: GatewayClientPort,
    agent_runtime: AgentRuntimePort,
    control_checkpointer: object,
    graph_config: KnowledgeGraphConfig | None = None,
    runtime_config: PersistenceRuntimeConfig | None = None,
    event_stream_config: TaskEventStreamConfig | None = None,
    clock: Callable[[], datetime] | None = None,
    run_id_factory: Callable[[], str] | None = None,
) -> LocalProductRuntime:
    """Create the accepted PostgreSQL UoW and compose the local product."""

    data_unit_of_work = cast(
        DataUnitOfWorkFactory,
        PostgresDataUnitOfWorkFactory(connection_factory),
    )
    security_contexts = RuntimeSecurityContextValidator(
        contexts=PostgresSecurityContextSource(connection_factory),
        verifier=SecurityVerifier(),
        clock=clock,
    )
    return compose_local_product_runtime(
        worker_id=worker_id,
        data_unit_of_work=data_unit_of_work,
        coordination=coordination,
        tenants=tenants,
        queue=queue,
        request_security=request_security,
        task_initialization=task_initialization,
        thread_id_factory=thread_id_factory,
        request_resolver=request_resolver,
        result_artifacts=result_artifacts,
        gateway=gateway,
        agent_runtime=agent_runtime,
        security_contexts=security_contexts,
        control_checkpointer=control_checkpointer,
        graph_config=graph_config,
        runtime_config=runtime_config,
        event_stream_config=event_stream_config,
        clock=clock,
        run_id_factory=run_id_factory,
    )


def _validate_release(
    task_initialization: TaskInitializationConfig,
    config: KnowledgeGraphConfig,
) -> None:
    release = task_initialization.release
    classification_rank = {
        DataClassification.PUBLIC: 0,
        DataClassification.INTERNAL: 1,
        DataClassification.CONFIDENTIAL: 2,
        DataClassification.RESTRICTED: 3,
    }
    if (
        release.graph_version != config.graph_version
        or release.domain_pack_version != config.domain_pack_version
        or release.context_policy_version
        != config.context_policy.context_policy_version
        or release.policy_version != config.policy_version
        or release.tool_schema_set != config.tool_schema_set
    ):
        raise ValueError(
            "Task initialization release does not match the knowledge runtime"
        )
    if (
        classification_rank[task_initialization.data_classification]
        > classification_rank[
            config.context_policy.data_classification_ceiling
        ]
    ):
        raise ValueError(
            "Task initialization classification exceeds the context policy"
        )


__all__ = [
    "LocalProductRuntime",
    "compose_local_product_runtime",
    "compose_postgres_local_product_runtime",
]
