from __future__ import annotations

import asyncio
import copy
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from flowpilot_agent_runtime import (
    FakeAgentRuntime,
    FakeOutcome,
    FakeScenario,
)
from flowpilot_api import TrustedRequestIdentity
from flowpilot_api.testing import StaticRequestSecurity
from flowpilot_application import (
    RequestObservation,
    RequestReferenceQuery,
    ResolvedRequestReference,
    TaskInitializationConfig,
)
from flowpilot_application.testing import (
    FakeRequestReferenceResolver,
    FakeResultArtifactPort,
)
from flowpilot_domain import (
    ActorType,
    DataClassification,
    ReleaseRef,
    TaskCommand,
    ToolOperation,
    canonical_sha256,
)
from flowpilot_graph import GraphStatus
from flowpilot_persistence import (
    MemoryDatabase,
    MemoryDataUnitOfWorkFactory,
    MemoryRedisClient,
    PostgresDataUnitOfWorkFactory,
    RedisCoordinationAdapter,
)
from flowpilot_persistence.serialization import task_command_to_mapping
from flowpilot_tool_contracts import (
    DeterministicGatewayClientFake,
    ToolResult,
    ToolResultStatus,
    Verification,
    VerificationMethod,
)
from flowpilot_worker import (
    KNOWLEDGE_SCHEMA_PIN,
    KNOWLEDGE_TOOL_NAME,
    InMemoryExecutionQueue,
    KnowledgeGraphConfig,
    LocalProductRuntime,
    TrustedTenantInventory,
    build_knowledge_gateway_call,
    compose_local_product_runtime,
    compose_postgres_local_product_runtime,
)
from langgraph.checkpoint.memory import InMemorySaver


class _ThreadFactory:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        return f"thread_product{self.calls:02d}"


@dataclass(slots=True)
class _Harness:
    command: TaskCommand
    body: dict[str, Any]
    database: MemoryDatabase
    data_unit_of_work: MemoryDataUnitOfWorkFactory
    queue: InMemoryExecutionQueue
    gateway: DeterministicGatewayClientFake
    runtime: FakeAgentRuntime
    artifacts: FakeResultArtifactPort
    thread_factory: _ThreadFactory
    checkpointer: InMemorySaver
    product: LocalProductRuntime


def _resolved_request(
    command: TaskCommand,
    *,
    question: str,
    include_question: bool = True,
) -> ResolvedRequestReference:
    payload = command.payload
    query = RequestReferenceQuery(
        tenant_id=command.tenant_id,
        task_id=command.task_id,
        message_id=str(payload["initial_message_id"]),
        message_ref=str(payload["initial_message_ref"]),
        purpose=command.security_context.purpose,
        security_context_ref=command.security_context.context_ref,
    )
    source_digest = canonical_sha256(
        {"message_ref": query.message_ref, "question": question}
    )
    fields = {"question": question} if include_question else {}
    provisional = ResolvedRequestReference(
        query=query,
        observation_ref=(
            f"observation://{command.tenant_id}/{command.task_id}/knowledge"
        ),
        source_digest=source_digest,
        intent="knowledge_question",
        fields=fields,
        data_classification=DataClassification.INTERNAL,
        observation_digest="sha256:" + "0" * 64,
    )
    return ResolvedRequestReference(
        query=query,
        observation_ref=provisional.observation_ref,
        source_digest=source_digest,
        intent=provisional.intent,
        fields=provisional.fields,
        data_classification=provisional.data_classification,
        observation_digest=provisional.recompute_digest(),
    )


def _observation(resolved: ResolvedRequestReference) -> RequestObservation:
    return RequestObservation(
        tenant_id=resolved.query.tenant_id,
        task_id=resolved.query.task_id,
        message_id=resolved.query.message_id,
        observation_ref=resolved.observation_ref,
        source_digest=resolved.source_digest,
        intent=resolved.intent,
        fields=resolved.fields,
        missing_fields=(),
        data_classification=resolved.data_classification,
    )


def _verified_result(
    *,
    request_id: str,
    policy_decision_id: str,
    tenant_id: str,
    now: datetime,
) -> ToolResult:
    return ToolResult(
        execution_id="tex_knowledge01",
        request_id=request_id,
        operation=ToolOperation.READ,
        status=ToolResultStatus.VERIFIED,
        data={
            "records": [
                {
                    "source_ref": (
                        f"knowledge://{tenant_id}/employee-handbook/leave/v3"
                    ),
                    "document_version": "3.0",
                    "section": "annual-leave",
                    "redacted_summary": "年假申请应由直属经理审批。",
                    "content_hash": "sha256:" + "a" * 64,
                    "classification": "internal",
                }
            ],
            "returned_count": 1,
        },
        display_summary="One authorized knowledge section matched.",
        output_classification="internal",
        policy_decision_id=policy_decision_id,
        retryable=False,
        retry_basis=None,
        error_code=None,
        verification=Verification(
            method=VerificationMethod.NOT_APPLICABLE,
            matched=True,
        ),
        reconciliation=None,
        started_at=now,
        finished_at=now,
    )


def _identity(command: TaskCommand) -> TrustedRequestIdentity:
    return TrustedRequestIdentity(
        tenant_id=command.tenant_id,
        subject_id=command.actor.id,
        subject_type=ActorType(command.actor.type),
        purpose=command.security_context.purpose,
        security_context_id=command.security_context.context_id,
        security_context_ref=command.security_context.context_ref,
        security_context_hash=command.security_context.context_hash,
    )


def _task_initialization(config: KnowledgeGraphConfig) -> TaskInitializationConfig:
    return TaskInitializationConfig(
        release=ReleaseRef(
            graph_version=config.graph_version,
            domain_pack_version=config.domain_pack_version,
            context_policy_version=config.context_policy.context_policy_version,
            policy_version=config.policy_version,
            tool_schema_set=config.tool_schema_set,
        ),
        data_classification=DataClassification.INTERNAL,
    )


def _make_harness(
    *,
    command: TaskCommand,
    now: datetime,
    scenario: FakeScenario | None = None,
    database: MemoryDatabase | None = None,
    queue: InMemoryExecutionQueue | None = None,
    gateway: DeterministicGatewayClientFake | None = None,
    checkpointer: InMemorySaver | None = None,
    record_tenant_id: str | None = None,
    missing_question: bool = False,
) -> _Harness:
    config = KnowledgeGraphConfig()
    resolved = _resolved_request(
        command,
        question="公司的年假申请流程是什么？",
        include_question=not missing_question,
    )
    preview_resolved = _resolved_request(
        command,
        question="公司的年假申请流程是什么？",
    )
    preview = build_knowledge_gateway_call(
        config=config,
        command=command,
        observation=_observation(preview_resolved),
        run_id="run_product0001",
    )
    effective_gateway = gateway or DeterministicGatewayClientFake(
        schema_pins={KNOWLEDGE_TOOL_NAME: KNOWLEDGE_SCHEMA_PIN},
        results_by_request_id={
            preview.request.request_id: _verified_result(
                request_id=preview.request.request_id,
                policy_decision_id=preview.request.policy_decision_id,
                tenant_id=record_tenant_id or command.tenant_id,
                now=now,
            )
        },
    )
    source_ref = f"knowledge://{command.tenant_id}/employee-handbook/leave/v3"
    runtime = FakeAgentRuntime(
        default=scenario
        or FakeScenario(
            structured_output={
                "answer_markdown": "请先提交年假申请，再由直属经理审批。",
                "citation_source_refs": [source_ref],
            },
            session_ref="provider-session://opaque/product01",
        ),
        clock=lambda: now,
    )
    artifacts = FakeResultArtifactPort()
    effective_database = database or MemoryDatabase()
    data_unit_of_work = MemoryDataUnitOfWorkFactory(effective_database)
    effective_queue = queue or InMemoryExecutionQueue()
    thread_factory = _ThreadFactory()
    effective_checkpointer = checkpointer or InMemorySaver()
    product = compose_local_product_runtime(
        worker_id="worker_product01",
        data_unit_of_work=data_unit_of_work,
        coordination=RedisCoordinationAdapter(MemoryRedisClient()),
        tenants=TrustedTenantInventory((command.tenant_id,)),
        queue=effective_queue,
        request_security=StaticRequestSecurity(_identity(command)),
        task_initialization=_task_initialization(config),
        thread_id_factory=thread_factory,
        request_resolver=FakeRequestReferenceResolver(
            {resolved.query.message_ref: resolved}
        ),
        result_artifacts=artifacts,
        gateway=effective_gateway,
        agent_runtime=runtime,
        control_checkpointer=effective_checkpointer,
        graph_config=config,
        clock=lambda: now,
        run_id_factory=lambda: "run_product0001",
    )
    return _Harness(
        command=command,
        body=task_command_to_mapping(command),
        database=effective_database,
        data_unit_of_work=data_unit_of_work,
        queue=effective_queue,
        gateway=effective_gateway,
        runtime=runtime,
        artifacts=artifacts,
        thread_factory=thread_factory,
        checkpointer=effective_checkpointer,
        product=product,
    )


async def _post(app: Any, body: Mapping[str, Any]) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://flowpilot.test",
    ) as client:
        return await client.post("/v1/task-commands", json=body)


def test_api_to_worker_completes_enterprise_knowledge_chain_once(
    command_factory: Callable[..., TaskCommand],
    fixed_clock: Callable[[], datetime],
) -> None:
    async def scenario() -> None:
        harness = _make_harness(
            command=command_factory(),
            now=fixed_clock(),
        )

        accepted = await _post(harness.product.app, harness.body)
        replayed = await _post(harness.product.app, harness.body)

        assert accepted.status_code == 202
        assert replayed.status_code == 202
        assert replayed.json()["replayed"] is True
        assert harness.thread_factory.calls == 1
        assert harness.queue.pending_count == 1
        assert harness.database.state.outbox_by_id == {}
        task = harness.database.state.tasks[
            (harness.command.tenant_id, harness.command.task_id)
        ]
        assert task.status.value == "RECEIVED"
        assert task.version == 0
        assert task.thread_id == "thread_product01"

        run = await harness.product.worker.run_once()
        idle = await harness.product.worker.run_once()

        assert run.graph_outcome is not None
        assert run.graph_outcome.state.status is GraphStatus.COMPLETED
        assert run.graph_outcome.state.result_ref is not None
        assert idle.idle is True
        assert harness.queue.acknowledged_count == 1
        assert harness.gateway.logical_execution_count == 1
        assert len(harness.runtime.calls) == 1
        assert "公司的年假申请流程是什么" in repr(
            harness.runtime.calls[0].context.to_mapping()
        )
        assert len(harness.artifacts.calls) == 1
        assert harness.artifacts.calls[0].content.startswith("请先提交")
        events = sorted(
            (
                delivery.event
                for delivery in harness.database.state.outbox_by_id.values()
            ),
            key=lambda event: event.sequence,
        )
        assert [event.event_type for event in events] == [
            "task.created.v1",
            "task.completed.v1",
        ]
        assert [event.sequence for event in events] == [1, 2]
        assert sum(event.event_type == "task.created.v1" for event in events) == 1
        durable_evidence = repr(
            (
                harness.database.state.checkpoints,
                harness.database.state.outbox_by_id,
                harness.artifacts.calls,
            )
        )
        assert "provider-session://opaque/product01" not in durable_evidence
        assert "公司的年假申请流程是什么" not in repr(
            (
                harness.database.state.checkpoints,
                harness.database.state.outbox_by_id,
            )
        )

    asyncio.run(scenario())


def test_browser_tenant_forgery_fails_before_task_or_runtime(
    command_factory: Callable[..., TaskCommand],
    fixed_clock: Callable[[], datetime],
) -> None:
    async def scenario() -> None:
        harness = _make_harness(
            command=command_factory(),
            now=fixed_clock(),
        )
        forged = copy.deepcopy(harness.body)
        forged["tenant_id"] = "tenant-b"
        forged["security_context"]["tenant_id"] = "tenant-b"
        forged["command_digest"] = "sha256:" + "0" * 64
        forged["command_digest"] = TaskCommand.from_mapping(
            forged
        ).recompute_digest()

        response = await _post(harness.product.app, forged)

        assert response.status_code == 403
        assert response.json()["error"]["code"] == (
            "API_REQUEST_IDENTITY_MISMATCH"
        )
        assert harness.database.state.tasks == {}
        assert harness.database.state.outbox_by_id == {}
        assert harness.queue.pending_count == 0
        assert harness.gateway.calls == []
        assert harness.runtime.calls == []

    asyncio.run(scenario())


def test_missing_question_interrupts_before_gateway_or_model(
    command_factory: Callable[..., TaskCommand],
    fixed_clock: Callable[[], datetime],
) -> None:
    async def scenario() -> None:
        harness = _make_harness(
            command=command_factory(),
            now=fixed_clock(),
            missing_question=True,
        )
        assert (await _post(harness.product.app, harness.body)).status_code == 202

        run = await harness.product.worker.run_once()

        assert run.graph_outcome is not None
        assert run.graph_outcome.state.status is GraphStatus.WAITING_USER
        assert run.graph_outcome.state.pending_reason == "user_input:question"
        assert harness.gateway.calls == []
        assert harness.runtime.calls == []
        assert harness.artifacts.calls == []
        events = sorted(
            (
                delivery.event
                for delivery in harness.database.state.outbox_by_id.values()
            ),
            key=lambda event: event.sequence,
        )
        assert [event.event_type for event in events] == [
            "task.created.v1",
            "task.input.required.v1",
        ]

    asyncio.run(scenario())


def test_provider_retry_survives_worker_recomposition_without_duplicate_read(
    command_factory: Callable[..., TaskCommand],
    fixed_clock: Callable[[], datetime],
) -> None:
    async def scenario() -> None:
        command = command_factory()
        first = _make_harness(
            command=command,
            now=fixed_clock(),
            scenario=FakeScenario(outcome=FakeOutcome.PROVIDER_UNAVAILABLE),
        )
        assert (await _post(first.product.app, first.body)).status_code == 202

        retry = await first.product.worker.run_once()

        assert retry.graph_outcome is not None
        assert retry.graph_outcome.state.status is GraphStatus.RETRY_PENDING
        assert retry.graph_outcome.should_retry is True
        assert first.queue.pending_count == 1
        assert first.gateway.logical_execution_count == 1

        restarted = _make_harness(
            command=command,
            now=fixed_clock(),
            database=first.database,
            queue=first.queue,
            gateway=first.gateway,
            checkpointer=first.checkpointer,
        )
        completed = await restarted.product.worker.run_once()

        assert completed.graph_outcome is not None
        assert completed.graph_outcome.state.status is GraphStatus.COMPLETED
        assert restarted.queue.acknowledged_count == 1
        assert restarted.gateway.logical_execution_count == 1
        events = [
            delivery.event
            for delivery in restarted.database.state.outbox_by_id.values()
        ]
        assert sum(event.event_type == "task.created.v1" for event in events) == 1

    asyncio.run(scenario())


def test_gateway_cross_tenant_record_fails_closed_before_model(
    command_factory: Callable[..., TaskCommand],
    fixed_clock: Callable[[], datetime],
) -> None:
    async def scenario() -> None:
        harness = _make_harness(
            command=command_factory(),
            now=fixed_clock(),
            record_tenant_id="tenant-b",
        )
        assert (await _post(harness.product.app, harness.body)).status_code == 202

        run = await harness.product.worker.run_once()

        assert run.graph_outcome is not None
        assert run.graph_outcome.state.status is GraphStatus.FAILED
        assert run.graph_outcome.state.failure_code == (
            "RUNTIME_KNOWLEDGE_RESULT_INVALID"
        )
        assert harness.runtime.calls == []
        assert harness.artifacts.calls == []
        assert harness.queue.acknowledged_count == 1
        assert all(
            "tenant-b" not in repr(checkpoint.state)
            for checkpoint in harness.database.state.checkpoints.values()
        )

    asyncio.run(scenario())


def test_postgres_product_root_creates_the_accepted_data_factory(
    command_factory: Callable[..., TaskCommand],
    fixed_clock: Callable[[], datetime],
) -> None:
    harness = _make_harness(
        command=command_factory(),
        now=fixed_clock(),
    )

    async def connection_factory() -> Any:
        raise AssertionError("composition must not connect eagerly")

    product = compose_postgres_local_product_runtime(
        connection_factory=connection_factory,
        worker_id="worker_postgres01",
        coordination=RedisCoordinationAdapter(MemoryRedisClient()),
        tenants=TrustedTenantInventory((harness.command.tenant_id,)),
        queue=InMemoryExecutionQueue(),
        request_security=StaticRequestSecurity(_identity(harness.command)),
        task_initialization=_task_initialization(KnowledgeGraphConfig()),
        thread_id_factory=_ThreadFactory(),
        request_resolver=FakeRequestReferenceResolver(),
        result_artifacts=FakeResultArtifactPort(),
        gateway=harness.gateway,
        agent_runtime=harness.runtime,
        control_checkpointer=InMemorySaver(),
        clock=fixed_clock,
    )

    assert isinstance(
        product.data_unit_of_work,
        PostgresDataUnitOfWorkFactory,
    )
