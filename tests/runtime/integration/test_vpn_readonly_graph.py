from __future__ import annotations

import asyncio
import functools
import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flowpilot_application import (
    RequestObservation,
    RequestObservationService,
    RequestReferenceQuery,
    ResolvedRequestReference,
    ResultArtifactService,
)
from flowpilot_application.testing import (
    FakeRequestReferenceResolver,
    FakeResultArtifactPort,
)
from flowpilot_context import ContextBuilder, LayerName
from flowpilot_domain import (
    DataClassification,
    TaskCommand,
    ToolOperation,
    canonical_sha256,
)
from flowpilot_graph import (
    GraphStatus,
    InMemoryCheckpointStore,
    InMemoryLeaseStore,
    assert_checkpoint_safe,
    assert_same_graph_factory,
)
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
    RuntimeExecutionAdapter,
    RuntimeWorker,
    VpnGraphConfig,
    VpnReadOnlyGraph,
    build_vpn_gateway_call,
    vpn_debug_projection,
)
from flowpilot_worker.studio import create_studio_graph_definition
from langgraph.checkpoint.memory import InMemorySaver

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXED_NOW = datetime(2026, 7, 28, 8, 30, tzinfo=UTC)


def _async_test(function: Callable[..., Any]) -> Callable[..., None]:
    @functools.wraps(function)
    def run(*args: Any, **kwargs: Any) -> None:
        asyncio.run(function(*args, **kwargs))

    return run


def _fixture(name: str) -> dict[str, Any]:
    return json.loads(
        (REPOSITORY_ROOT / "domain-packs" / "it-service" / "evals" / name).read_text(
            encoding="utf-8"
        )
    )


def _resolved(value: Mapping[str, Any]) -> ResolvedRequestReference:
    return ResolvedRequestReference(
        query=RequestReferenceQuery(**value["query"]),
        observation_ref=str(value["observation_ref"]),
        source_digest=str(value["source_digest"]),
        intent=str(value["intent"]),
        fields=dict(value["fields"]),
        data_classification=DataClassification(value["data_classification"]),
        observation_digest=str(value["observation_digest"]),
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
    request_id: str,
    policy_decision_id: str,
) -> ToolResult:
    knowledge = json.loads(
        (
            REPOSITORY_ROOT
            / "domain-packs"
            / "it-service"
            / "knowledge"
            / "vpn-691-current.json"
        ).read_text(encoding="utf-8")
    )
    return ToolResult(
        execution_id="tex_vpnread01",
        request_id=request_id,
        operation=ToolOperation.READ,
        status=ToolResultStatus.VERIFIED,
        data={
            "records": [
                {
                    "source_ref": knowledge["source_ref"],
                    "document_version": knowledge["document_version"],
                    "section": knowledge["section"],
                    "redacted_summary": knowledge["content_summary"],
                    "content_hash": knowledge["content_hash"],
                    "classification": knowledge["data_classification"],
                }
            ],
            "returned_count": 1,
        },
        display_summary="One authorized VPN SOP matched.",
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
        started_at=FIXED_NOW,
        finished_at=FIXED_NOW,
    )


def _resume_command(
    create: TaskCommand,
    *,
    message_ref: str,
) -> TaskCommand:
    value = {
        "command_id": "cmd_vpnresume1",
        "command_type": "task.message.submit.v1",
        "tenant_id": create.tenant_id,
        "task_id": create.task_id,
        "actor": create.actor.to_mapping(),
        "security_context": create.security_context.to_mapping(),
        "expected_task_version": 1,
        "idempotency_key": canonical_sha256({"resume": create.task_id}),
        "command_digest": "sha256:" + "0" * 64,
        "correlation_id": "corr-vpn-resume-01",
        "payload": {
            "message_id": "msg_vpnresume1",
            "message_ref": message_ref,
        },
        "issued_at": "2026-07-28T08:10:00Z",
    }
    unsigned = TaskCommand.from_mapping(value)
    value["command_digest"] = unsigned.recompute_digest()
    return TaskCommand.from_mapping(value)


async def _make_graph(
    *,
    command: TaskCommand,
    resolved_records: dict[str, ResolvedRequestReference],
    checkpoints: InMemoryCheckpointStore,
    gateway: DeterministicGatewayClientFake | None = None,
    artifacts: FakeResultArtifactPort | None = None,
    checkpointer: InMemorySaver | None = None,
) -> tuple[
    VpnReadOnlyGraph,
    DeterministicGatewayClientFake,
    FakeResultArtifactPort,
]:
    resolver = FakeRequestReferenceResolver(resolved_records)
    observations = RequestObservationService(
        resolver=resolver,
        required_fields={"vpn_support": ("environment",)},
    )
    config = VpnGraphConfig()
    first_resolved = next(
        item
        for item in resolved_records.values()
        if not item.query.message_ref.endswith("missing-environment")
    )
    preview = build_vpn_gateway_call(
        config=config,
        command=command,
        observation=_observation(first_resolved),
    )
    effective_gateway = gateway or DeterministicGatewayClientFake(
        schema_pins={KNOWLEDGE_TOOL_NAME: KNOWLEDGE_SCHEMA_PIN},
        results_by_request_id={
            preview.request.request_id: _verified_result(
                preview.request.request_id,
                preview.request.policy_decision_id,
            )
        },
    )
    effective_artifacts = artifacts or FakeResultArtifactPort()
    return (
        VpnReadOnlyGraph(
            requests=observations,
            artifacts=ResultArtifactService(effective_artifacts),
            gateway=effective_gateway,
            checkpoints=checkpoints,
            context_builder=ContextBuilder(clock=lambda: FIXED_NOW),
            config=config,
            clock=lambda: FIXED_NOW,
            checkpointer=checkpointer,
        ),
        effective_gateway,
        effective_artifacts,
    )


@_async_test
async def test_complete_vpn_request_uses_one_gateway_read_and_opaque_result(
    fixed_clock: Callable[[], datetime],
) -> None:
    case = _fixture("minimal-vpn-request.json")
    command = TaskCommand.from_mapping(case["command"])
    resolved = _resolved(case["resolved_request"])
    leases = InMemoryLeaseStore(clock=fixed_clock)
    checkpoints = InMemoryCheckpointStore(leases=leases)
    graph, gateway, artifacts = await _make_graph(
        command=command,
        resolved_records={resolved.query.message_ref: resolved},
        checkpoints=checkpoints,
    )
    lease = await leases.acquire(command.tenant_id, command.task_id, "run_vpnread01")

    outcome = await graph.execute(
        command, execution_ref="execution://vpn/1", lease=lease
    )
    await leases.release(lease)

    assert outcome.state.status is GraphStatus.COMPLETED
    assert outcome.state.result_ref is not None
    assert outcome.state.knowledge_call_count == 1
    assert outcome.state.citation_count == 1
    assert outcome.state.service_read_skipped is True
    assert gateway.logical_execution_count == 1
    assert len(gateway.calls) == 1
    assert len(artifacts.calls) == 1
    assert artifacts.calls[0].citations[0].source_ref in outcome.state.reference_refs
    assert len(graph.built_contexts) == 2
    assert all(
        tuple(layer.name for layer in context.layers)
        == (LayerName.SYSTEM_POLICY, LayerName.SECURITY_VIEW, LayerName.TASK_STATE)
        for context in graph.built_contexts
    )
    assert_checkpoint_safe(outcome.state.to_checkpoint())
    serialized = json.dumps(outcome.state.to_checkpoint(), sort_keys=True)
    assert "Recommended steps" not in serialized
    assert "acl_subjects" not in serialized
    assert "content_summary" not in serialized
    assert_same_graph_factory(graph.definition, create_studio_graph_definition())


@_async_test
async def test_missing_environment_interrupts_then_resumes_after_worker_restart(
    fixed_clock: Callable[[], datetime],
) -> None:
    missing_case = _fixture("vpn-missing-environment.json")
    complete_case = _fixture("minimal-vpn-request.json")
    create = TaskCommand.from_mapping(missing_case["command"])
    missing = _resolved(missing_case["resolved_request"])
    resume = _resume_command(create, message_ref="message://vpn/resume/environment")
    complete_mapping = dict(complete_case["resolved_request"])
    complete_mapping["query"] = {
        "tenant_id": create.tenant_id,
        "task_id": create.task_id,
        "message_id": "msg_vpnresume1",
        "message_ref": "message://vpn/resume/environment",
        "purpose": create.security_context.purpose,
        "security_context_ref": create.security_context.context_ref,
    }
    complete_mapping["observation_ref"] = "observation://tenant-a/vpn-resumed"
    complete_mapping["observation_digest"] = "sha256:" + "0" * 64
    unsigned_complete = _resolved(complete_mapping)
    complete_mapping["observation_digest"] = unsigned_complete.recompute_digest()
    complete = _resolved(complete_mapping)
    records = {
        missing.query.message_ref: missing,
        complete.query.message_ref: complete,
    }
    leases = InMemoryLeaseStore(clock=fixed_clock)
    checkpoints = InMemoryCheckpointStore(leases=leases)
    saver = InMemorySaver()
    graph, gateway, artifacts = await _make_graph(
        command=resume,
        resolved_records=records,
        checkpoints=checkpoints,
        checkpointer=saver,
    )
    queue = InMemoryExecutionQueue()
    submission = RuntimeExecutionAdapter(queue)
    await submission.submit(create)
    first_worker = RuntimeWorker(
        worker_id="worker-vpn-before-restart",
        queue=queue,
        leases=leases,
        graph=graph,
        run_id_factory=lambda: "run_vpnmiss01",
    )

    first_run = await first_worker.run_once()
    waiting = first_run.graph_outcome

    assert waiting is not None
    assert waiting.state.status is GraphStatus.WAITING_USER
    assert gateway.logical_execution_count == 0
    assert len(artifacts.calls) == 0
    assert graph.last_safe_state is not None
    assert len(graph.last_safe_state.get("__interrupt__", ())) == 1

    restarted, _, _ = await _make_graph(
        command=resume,
        resolved_records=records,
        checkpoints=checkpoints,
        gateway=gateway,
        artifacts=artifacts,
        checkpointer=saver,
    )
    await submission.submit(resume)
    restarted_worker = RuntimeWorker(
        worker_id="worker-vpn-after-restart",
        queue=queue,
        leases=leases,
        graph=restarted,
        run_id_factory=lambda: "run_vpnresume1",
    )
    restarted_run = await restarted_worker.run_once()
    completed = restarted_run.graph_outcome

    assert completed is not None
    assert completed.state.status is GraphStatus.COMPLETED
    assert completed.state.knowledge_call_count == 1
    assert gateway.logical_execution_count == 1
    assert len(artifacts.artifacts_by_ref) == 1

    replay_graph, _, _ = await _make_graph(
        command=resume,
        resolved_records=records,
        checkpoints=checkpoints,
        gateway=gateway,
        artifacts=artifacts,
    )
    replay_lease = await leases.acquire(
        resume.tenant_id,
        resume.task_id,
        "run_vpnreplay1",
    )
    replay = await replay_graph.execute(
        resume,
        execution_ref="execution://vpn/replay",
        lease=replay_lease,
    )
    await leases.release(replay_lease)

    assert replay.state.result_ref == completed.state.result_ref
    assert gateway.logical_execution_count == 1
    assert len(gateway.calls) == 1


@_async_test
async def test_artifact_retry_reenters_knowledge_idempotently(
    fixed_clock: Callable[[], datetime],
) -> None:
    case = _fixture("minimal-vpn-request.json")
    command = TaskCommand.from_mapping(case["command"])
    resolved = _resolved(case["resolved_request"])
    leases = InMemoryLeaseStore(clock=fixed_clock)
    checkpoints = InMemoryCheckpointStore(leases=leases)
    artifacts = FakeResultArtifactPort()
    artifacts.failure = RuntimeError("artifact backend unavailable")
    graph, gateway, _ = await _make_graph(
        command=command,
        resolved_records={resolved.query.message_ref: resolved},
        checkpoints=checkpoints,
        artifacts=artifacts,
    )
    first_lease = await leases.acquire(
        command.tenant_id, command.task_id, "run_vpnretry1"
    )

    pending = await graph.execute(
        command,
        execution_ref="execution://vpn/retry",
        lease=first_lease,
    )
    await leases.release(first_lease)

    assert pending.state.status is GraphStatus.RETRY_PENDING
    assert pending.should_retry is True
    assert gateway.logical_execution_count == 1
    artifacts.failure = None

    second_lease = await leases.acquire(
        command.tenant_id, command.task_id, "run_vpnretry2"
    )
    completed = await graph.execute(
        command,
        execution_ref="execution://vpn/retry",
        lease=second_lease,
    )
    await leases.release(second_lease)

    assert completed.state.status is GraphStatus.COMPLETED
    assert completed.state.knowledge_call_count == 1
    assert gateway.logical_execution_count == 1
    assert len(gateway.calls) == 2
    assert len(artifacts.artifacts_by_ref) == 1


@_async_test
async def test_zero_result_fails_closed_without_artifact(
    fixed_clock: Callable[[], datetime],
) -> None:
    case = _fixture("minimal-vpn-request.json")
    command = TaskCommand.from_mapping(case["command"])
    resolved = _resolved(case["resolved_request"])
    config = VpnGraphConfig()
    preview = build_vpn_gateway_call(
        config=config,
        command=command,
        observation=_observation(resolved),
    )
    empty = replace(
        _verified_result(
            preview.request.request_id,
            preview.request.policy_decision_id,
        ),
        data={"records": [], "returned_count": 0},
    )
    gateway = DeterministicGatewayClientFake(
        schema_pins={KNOWLEDGE_TOOL_NAME: KNOWLEDGE_SCHEMA_PIN},
        results_by_request_id={preview.request.request_id: empty},
    )
    leases = InMemoryLeaseStore(clock=fixed_clock)
    checkpoints = InMemoryCheckpointStore(leases=leases)
    graph, _, artifacts = await _make_graph(
        command=command,
        resolved_records={resolved.query.message_ref: resolved},
        checkpoints=checkpoints,
        gateway=gateway,
    )
    lease = await leases.acquire(command.tenant_id, command.task_id, "run_vpnempty01")

    outcome = await graph.execute(
        command,
        execution_ref="execution://vpn/empty",
        lease=lease,
    )
    await leases.release(lease)

    assert outcome.state.status is GraphStatus.FAILED
    assert outcome.state.failure_code == "RUNTIME_KNOWLEDGE_NO_RESULT"
    assert outcome.state.knowledge_call_count == 1
    assert gateway.logical_execution_count == 1
    assert artifacts.calls == []


def test_vpn_schema_pin_and_debug_projection_fail_closed() -> None:
    assert VpnGraphConfig().knowledge_schema_pin == KNOWLEDGE_SCHEMA_PIN
    try:
        VpnGraphConfig(knowledge_schema_pin="sha256:" + "0" * 64)
    except ValueError as exc:
        assert "accepted Knowledge Schema Pin" in str(exc)
    else:
        raise AssertionError("schema drift must fail closed")

    projection = vpn_debug_projection(
        {
            "current_node": "knowledge_read",
            "status": "RUNNING",
            "knowledge_call_count": 1,
            "citation_count": 1,
            "service_read_skipped": True,
            "request_body": "must-not-appear",
            "answer_body": "must-not-appear",
            "acl_subjects": ["must-not-appear"],
            "credential": "must-not-appear",
        }
    )
    serialized = json.dumps(projection, sort_keys=True)
    assert projection["knowledge"] == {
        "call_count": 1,
        "citation_count": 1,
        "service_read_skipped": True,
    }
    assert "must-not-appear" not in serialized
    assert "request_body" not in serialized
    assert "answer_body" not in serialized
    assert "acl_subjects" not in serialized
