"""M7 enterprise-knowledge product executor for fixed-denominator acceptance.

The executor runs the real local API -> Worker -> LangGraph composition over
the repository's synthetic knowledge fixture. Fake Gateway and AgentRuntime
transports keep the run offline; they do not replace application, persistence,
queue, graph, Context, result-artifact, or event behavior.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx
from flowpilot_agent_runtime import FakeAgentRuntime, FakeScenario
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
    AssuranceLevel,
    AuthenticationMethod,
    AuthenticationRef,
    DataClassification,
    ReleaseRef,
    SecurityContextRef,
    TaskCommand,
    ToolOperation,
    canonical_sha256,
)
from flowpilot_persistence import (
    DataUnitOfWorkFactory,
    MemoryDatabase,
    MemoryDataUnitOfWorkFactory,
    MemoryRedisClient,
    RedisCoordinationAdapter,
)
from flowpilot_security import (
    InMemorySecurityContextSource,
    SecurityContextSource,
    SecurityVerifier,
    TrustedSecurityContext,
    trusted_context_snapshot_hash,
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
    KnowledgeGraphConfig,
    LocalProductRuntime,
    RuntimeSecurityContextValidator,
    TrustedTenantInventory,
    build_knowledge_gateway_call,
    compose_local_product_runtime,
)
from langgraph.checkpoint.memory import InMemorySaver

from .canonical import (
    canonical_digest,
    load_json_strict,
    sha256_file,
    stable_json_bytes,
)
from .execution import CaseExecutionResult, CaseExecutorRegistry, ExecutionState

M7_PRODUCT_EXECUTOR_ID = "flowpilot.m7.enterprise-knowledge"
M7_PRODUCT_EXECUTOR_VERSION = "1.0.0"
M7_SUPPORTED_CASE_COUNT = 24

_FIXED_NOW = datetime(2026, 8, 9, 8, 0, tzinfo=UTC)
_TENANT_ID = "tenant-a"
_ACTOR_ID = "user-m7-evaluator"
_PROVIDER_SESSION = "provider-session://opaque/m7-evaluation"
_IDENTITY_ISSUER = "https://identity.evaluation.local/realms/flowpilot"
_AUTHORIZED_PARTY = "flowpilot-evaluation"
_CONTEXT_ROLES = frozenset({"employee", "knowledge-reader"})
_CONTEXT_SCOPES = frozenset({"tasks:read", "tools:invoke"})
_SOURCE_TOKEN_HASH = canonical_sha256({"credential": "m7-evaluation-fixture"})
_SUPPORTED_ASSERTIONS = frozenset(
    {
        "assert.task.terminal_status.v1",
        "assert.citation.valid.v1",
        "assert.tool.allowed.v1",
    }
)
_CLASSIFICATION = {
    "公开": "public",
    "内部": "internal",
    "机密": "confidential",
    "受限": "restricted",
}
_SCENARIO_DOCUMENT_IDS: dict[str, tuple[str, ...]] = {
    "password_reset_policy": ("KB-DOC-0001",),
    "vpn_access_conditions": ("KB-DOC-0002",),
    "software_catalog": ("KB-DOC-0003",),
    "severity_definitions": ("KB-DOC-0004",),
    "sla_matrix": ("KB-DOC-0005",),
    "approval_threshold": ("KB-DOC-0006",),
    "data_classification": ("KB-DOC-0007",),
    "change_window_policy": ("KB-DOC-0008",),
    "network_zone_rules": ("KB-DOC-0009",),
    "hardware_lifecycle": ("KB-DOC-0010",),
    "multi_doc_synthesis": ("KB-DOC-0011",),
    "citation_with_doc_id": ("KB-DOC-0001",),
    "zero_result": (),
    "scope_denied_restricted": ("KB-DOC-0007",),
    "cross_tenant_knowledge_denied": ("KB-DOC-0008",),
    "citation_from_retrieval_only": ("KB-DOC-0005",),
    "synonym_query": ("KB-DOC-0001",),
    "conditional_query_environment": ("KB-DOC-0012",),
    "summary_query": ("KB-DOC-0005",),
    "numeric_threshold": ("KB-DOC-0006",),
    "procedure_with_ttl": ("KB-DOC-0012",),
    "version_binding": ("KB-DOC-0001",),
    "tenant_window_difference": ("KB-DOC-0008",),
    "speculative_not_answerable": (),
}


@dataclass(slots=True)
class _ThreadFactory:
    suffix: str
    calls: int = 0

    def __call__(self) -> str:
        self.calls += 1
        return f"thread_m7eval{self.suffix}"


@dataclass(slots=True)
class _CountingSecurityContextSource(SecurityContextSource):
    backing: InMemorySecurityContextSource
    trusted: TrustedSecurityContext
    resolve_count: int = 0

    async def resolve(self, context_ref: str) -> TrustedSecurityContext:
        self.resolve_count += 1
        return await self.backing.resolve(context_ref)


@dataclass(slots=True)
class _Harness:
    command: TaskCommand
    body: dict[str, Any]
    resolved: ResolvedRequestReference
    database: MemoryDatabase
    queue: InMemoryExecutionQueue
    gateway: DeterministicGatewayClientFake
    runtime: FakeAgentRuntime
    artifacts: FakeResultArtifactPort
    checkpointer: InMemorySaver
    security_contexts: _CountingSecurityContextSource
    product: LocalProductRuntime
    run_id: str


class M7EnterpriseKnowledgeExecutor:
    """Execute the immutable M7 knowledge subset through the product root."""

    executor_id = M7_PRODUCT_EXECUTOR_ID
    executor_version = M7_PRODUCT_EXECUTOR_VERSION

    def __init__(self, repository_root: Path) -> None:
        self._root = repository_root.resolve()
        self._case_pins = self._load_case_pins()
        fixture = load_json_strict(
            self._root / "evals" / "fixtures" / "synthetic-knowledge-corpus.v1.json"
        )
        if not isinstance(fixture, dict) or fixture.get("synthetic") is not True:
            raise ValueError(
                "M7 knowledge fixture must be an explicit synthetic object"
            )
        raw_documents = fixture.get("documents")
        if not isinstance(raw_documents, list):
            raise ValueError("M7 knowledge fixture documents must be a list")
        documents: dict[str, dict[str, Any]] = {}
        for raw in raw_documents:
            if not isinstance(raw, dict):
                raise ValueError("M7 knowledge fixture document must be an object")
            doc_id = raw.get("doc_id")
            if not isinstance(doc_id, str) or doc_id in documents:
                raise ValueError("M7 knowledge fixture document IDs must be unique")
            documents[doc_id] = dict(raw)
        referenced = {
            doc_id for values in _SCENARIO_DOCUMENT_IDS.values() for doc_id in values
        }
        if not referenced <= set(documents):
            raise ValueError("M7 executor references an unknown knowledge document")
        self._documents = documents

    @property
    def supported_case_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._case_pins))

    def registration(self) -> dict[str, Any]:
        """Return the exact executor and case-digest registration evidence."""

        return {
            "schema": "flowpilot.m7-executor-registration.v1",
            "executor_id": self.executor_id,
            "executor_version": self.executor_version,
            "match_policy": "exact_case_digest",
            "product_boundary": "API->Worker->LangGraph",
            "transport_profile": "offline-synthetic",
            "supported_case_count": len(self._case_pins),
            "supported_cases": [
                {
                    "case_id": case_id,
                    "case_input_digest": self._case_pins[case_id],
                }
                for case_id in sorted(self._case_pins)
            ],
        }

    def supports(self, case: Mapping[str, Any]) -> bool:
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or case_id not in self._case_pins:
            return False
        try:
            digest = canonical_digest(dict(case))
        except (TypeError, ValueError):
            return False
        return digest == self._case_pins[case_id]

    def execute(
        self, case: Mapping[str, Any], evidence_root: Path
    ) -> CaseExecutionResult:
        if not self.supports(case):
            raise ValueError("case does not match an immutable M7 product pin")
        case_value = dict(case)
        observation = asyncio.run(self._execute_product(case_value))
        assertions = self._assertions(case_value, observation)
        evidence = {
            "schema": "flowpilot.m7-product-observation.v1",
            "case_id": case_value["case_id"],
            "case_input_digest": canonical_digest(case_value),
            "executor_id": self.executor_id,
            "executor_version": self.executor_version,
            "product_boundary": "API->Worker->LangGraph",
            "transport_profile": "offline-synthetic",
            "terminal_status": observation["terminal_status"],
            "failure_code": observation["failure_code"],
            "result_ref_present": observation["result_ref_present"],
            "citation_count": observation["citation_count"],
            "citation_binding_valid": observation["citation_binding_valid"],
            "observed_tools": observation["observed_tools"],
            "logical_tool_calls": observation["logical_tool_calls"],
            "tool_transport_attempts": observation["tool_transport_attempts"],
            "tool_write_count": observation["tool_write_count"],
            "logical_model_calls": observation["logical_model_calls"],
            "model_transport_attempts": observation["model_transport_attempts"],
            "event_types": observation["event_types"],
            "event_sequences": observation["event_sequences"],
            "api_replay_count": observation["api_replay_count"],
            "restart_replay_model_delta": observation["restart_replay_model_delta"],
            "restart_replay_tool_delta": observation["restart_replay_tool_delta"],
            "cross_tenant_success_count": observation["cross_tenant_success_count"],
            "provider_session_exposure_count": observation[
                "provider_session_exposure_count"
            ],
            "request_content_durable_exposure_count": observation[
                "request_content_durable_exposure_count"
            ],
            "security_context_validation_count": observation[
                "security_context_validation_count"
            ],
            "restart_replay_security_validation_delta": observation[
                "restart_replay_security_validation_delta"
            ],
            "assertion_results": dict(sorted(assertions.items())),
        }
        relative = Path("cases") / f"{case_value['case_id']}.json"
        target = evidence_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(stable_json_bytes(evidence))
        return CaseExecutionResult(
            case_id=str(case_value["case_id"]),
            executor_id=self.executor_id,
            executor_version=self.executor_version,
            state=ExecutionState.COMPLETED,
            input_digest=canonical_digest(case_value),
            output_digest=sha256_file(target),
            assertion_results=assertions,
            judge_scores={},
            evidence_refs=(relative.as_posix(),),
        )

    async def observe_product_scenario(
        self,
        case: Mapping[str, Any],
        *,
        scenario: str,
    ) -> dict[str, Any]:
        """Run a supported synthetic product profile without changing case pins."""

        if scenario not in _SCENARIO_DOCUMENT_IDS:
            raise ValueError("product observation scenario is not registered")
        case_value = dict(case)
        tags = case_value.get("tags")
        if not isinstance(tags, list):
            raise ValueError("product observation case tags must be a list")
        case_value["tags"] = [
            f"scenario:{scenario}"
            if isinstance(item, str) and item.startswith("scenario:")
            else item
            for item in tags
        ]
        return await self._execute_product(case_value)

    async def _execute_product(self, case: dict[str, Any]) -> dict[str, Any]:
        scenario = _scenario(case)
        question = case.get("input")
        if not isinstance(question, str) or not question.strip():
            raise ValueError("M7 knowledge case input must be non-empty text")
        harness = await self._make_harness(case, scenario, question)
        accepted = await _post(harness.product.app, harness.body)
        replayed = await _post(harness.product.app, harness.body)
        outcome = await harness.product.worker.run_once()
        idle = await harness.product.worker.run_once()
        if (
            accepted.status_code != 202
            or replayed.status_code != 202
            or replayed.json().get("replayed") is not True
            or outcome.graph_outcome is None
            or idle.idle is not True
        ):
            raise RuntimeError(
                "M7 product execution did not reach an auditable outcome"
            )

        state = outcome.graph_outcome.state
        model_before = len(harness.runtime.calls)
        tool_before = harness.gateway.logical_execution_count
        security_validation_before = harness.security_contexts.resolve_count
        restarted_runtime = self._runtime_for(scenario)
        restarted = self._compose_product(
            command=harness.command,
            resolved=harness.resolved,
            database=harness.database,
            queue=harness.queue,
            gateway=harness.gateway,
            runtime=restarted_runtime,
            artifacts=harness.artifacts,
            checkpointer=harness.checkpointer,
            security_contexts=harness.security_contexts,
            run_id=harness.run_id,
        )
        restart_replay = await _post(restarted.app, harness.body)
        restart_idle = await restarted.worker.run_once()
        if (
            restart_replay.status_code != 202
            or restart_replay.json().get("replayed") is not True
            or restart_idle.idle is not True
        ):
            raise RuntimeError("M7 restart replay was not idempotently idle")

        events = sorted(
            (
                delivery.event
                for delivery in harness.database.state.outbox_by_id.values()
            ),
            key=lambda item: item.sequence,
        )
        observed_tools = sorted(
            {call.request.planned_action.tool.name for call in harness.gateway.calls}
        )
        tool_writes = sum(
            call.request.planned_action.tool.operation is ToolOperation.WRITE
            for call in harness.gateway.calls
        )
        citations = tuple(
            citation
            for draft in harness.artifacts.calls
            for citation in draft.citations
        )
        cross_tenant = sum(
            not citation.source_ref.startswith(f"knowledge://{_TENANT_ID}/")
            for citation in citations
        )
        durable = repr(
            (
                harness.database.state.checkpoints,
                harness.database.state.outbox_by_id,
            )
        )
        model_request_ids = {
            request.request_id
            for request in (*harness.runtime.calls, *restarted_runtime.calls)
        }
        return {
            "terminal_status": state.status.value,
            "failure_code": state.failure_code,
            "result_ref_present": state.result_ref is not None,
            "citation_count": len(citations),
            "citation_binding_valid": _citations_are_valid(
                citations, state.result_ref is not None
            ),
            "observed_tools": observed_tools,
            "logical_tool_calls": harness.gateway.logical_execution_count,
            "tool_transport_attempts": len(harness.gateway.calls),
            "tool_write_count": tool_writes,
            "logical_model_calls": len(model_request_ids),
            "model_transport_attempts": (
                len(harness.runtime.calls) + len(restarted_runtime.calls)
            ),
            "event_types": [event.event_type for event in events],
            "event_sequences": [event.sequence for event in events],
            "api_replay_count": 2,
            "restart_replay_model_delta": (
                len(harness.runtime.calls) + len(restarted_runtime.calls) - model_before
            ),
            "restart_replay_tool_delta": (
                harness.gateway.logical_execution_count - tool_before
            ),
            "cross_tenant_success_count": cross_tenant,
            "provider_session_exposure_count": durable.count(_PROVIDER_SESSION),
            "request_content_durable_exposure_count": durable.count(question),
            "security_context_validation_count": (
                harness.security_contexts.resolve_count
            ),
            "restart_replay_security_validation_delta": (
                harness.security_contexts.resolve_count
                - security_validation_before
            ),
        }

    async def _make_harness(
        self, case: Mapping[str, Any], scenario: str, question: str
    ) -> _Harness:
        suffix = hashlib.sha256(str(case["case_id"]).encode()).hexdigest()[:16]
        trusted = _trusted_identity_snapshot(suffix)
        command, body = _command(suffix, trusted)
        resolved = _resolved_request(command, question)
        config = KnowledgeGraphConfig()
        run_id = f"run_m7eval{suffix}"
        preview = build_knowledge_gateway_call(
            config=config,
            command=command,
            observation=_observation(resolved),
            run_id=run_id,
        )
        result = self._tool_result(
            scenario=scenario,
            request_id=preview.request.request_id,
            policy_decision_id=preview.request.policy_decision_id,
            suffix=suffix,
        )
        gateway = DeterministicGatewayClientFake(
            schema_pins={KNOWLEDGE_TOOL_NAME: KNOWLEDGE_SCHEMA_PIN},
            results_by_request_id={preview.request.request_id: result},
        )
        runtime = self._runtime_for(scenario)
        artifacts = FakeResultArtifactPort()
        database = MemoryDatabase()
        queue = InMemoryExecutionQueue()
        checkpointer = InMemorySaver()
        backing_security_contexts = InMemorySecurityContextSource()
        await backing_security_contexts.store(trusted)
        security_contexts = _CountingSecurityContextSource(
            backing=backing_security_contexts,
            trusted=trusted,
        )
        product = self._compose_product(
            command=command,
            resolved=resolved,
            database=database,
            queue=queue,
            gateway=gateway,
            runtime=runtime,
            artifacts=artifacts,
            checkpointer=checkpointer,
            security_contexts=security_contexts,
            run_id=run_id,
        )
        return _Harness(
            command=command,
            body=body,
            resolved=resolved,
            database=database,
            queue=queue,
            gateway=gateway,
            runtime=runtime,
            artifacts=artifacts,
            checkpointer=checkpointer,
            security_contexts=security_contexts,
            product=product,
            run_id=run_id,
        )

    def _compose_product(
        self,
        *,
        command: TaskCommand,
        resolved: ResolvedRequestReference,
        database: MemoryDatabase,
        queue: InMemoryExecutionQueue,
        gateway: DeterministicGatewayClientFake,
        runtime: FakeAgentRuntime,
        artifacts: FakeResultArtifactPort,
        checkpointer: InMemorySaver,
        security_contexts: _CountingSecurityContextSource,
        run_id: str,
    ) -> LocalProductRuntime:
        config = KnowledgeGraphConfig()
        suffix = command.task_id.removeprefix("task_")
        return compose_local_product_runtime(
            worker_id=f"worker_m7eval{suffix}",
            data_unit_of_work=cast(
                DataUnitOfWorkFactory,
                MemoryDataUnitOfWorkFactory(database),
            ),
            coordination=RedisCoordinationAdapter(MemoryRedisClient()),
            tenants=TrustedTenantInventory((_TENANT_ID,)),
            queue=queue,
            request_security=StaticRequestSecurity(
                _identity(command, security_contexts.trusted)
            ),
            task_initialization=_task_initialization(config),
            thread_id_factory=_ThreadFactory(suffix),
            request_resolver=FakeRequestReferenceResolver(
                {resolved.query.message_ref: resolved}
            ),
            result_artifacts=artifacts,
            gateway=gateway,
            agent_runtime=runtime,
            security_contexts=RuntimeSecurityContextValidator(
                contexts=security_contexts,
                verifier=SecurityVerifier(),
                clock=lambda: _FIXED_NOW,
            ),
            control_checkpointer=checkpointer,
            graph_config=config,
            clock=lambda: _FIXED_NOW,
            run_id_factory=lambda: run_id,
        )

    def _runtime_for(self, scenario: str) -> FakeAgentRuntime:
        records = self._records_for(scenario)
        refs = [str(record["source_ref"]) for record in records]
        answer = "；".join(
            str(self._documents[doc_id]["content"])
            for doc_id in _SCENARIO_DOCUMENT_IDS[scenario]
        )
        if not answer:
            answer = "No authorized knowledge result was available."
        return FakeAgentRuntime(
            default=FakeScenario(
                structured_output={
                    "answer_markdown": answer,
                    "citation_source_refs": refs,
                },
                session_ref=_PROVIDER_SESSION,
            ),
            clock=lambda: _FIXED_NOW,
        )

    def _tool_result(
        self,
        *,
        scenario: str,
        request_id: str,
        policy_decision_id: str,
        suffix: str,
    ) -> ToolResult:
        records = self._records_for(scenario)
        output_classification = (
            "restricted" if scenario == "scope_denied_restricted" else "internal"
        )
        return ToolResult(
            execution_id=f"tex_m7eval{suffix}",
            request_id=request_id,
            operation=ToolOperation.READ,
            status=ToolResultStatus.VERIFIED,
            data=cast(
                Mapping[str, Any],
                {"records": records, "returned_count": len(records)},
            ),
            display_summary="Authorized synthetic knowledge lookup completed.",
            output_classification=output_classification,
            policy_decision_id=policy_decision_id,
            retryable=False,
            retry_basis=None,
            error_code=None,
            verification=Verification(
                method=VerificationMethod.NOT_APPLICABLE,
                matched=True,
            ),
            reconciliation=None,
            started_at=_FIXED_NOW,
            finished_at=_FIXED_NOW,
        )

    def _records_for(self, scenario: str) -> list[dict[str, Any]]:
        record_tenant = (
            "tenant-b" if scenario == "cross_tenant_knowledge_denied" else _TENANT_ID
        )
        records: list[dict[str, Any]] = []
        for doc_id in _SCENARIO_DOCUMENT_IDS[scenario]:
            document = self._documents[doc_id]
            content = str(document["content"])
            classification = _CLASSIFICATION.get(str(document["classification"]))
            if classification is None:
                raise ValueError("unsupported synthetic document classification")
            if scenario == "scope_denied_restricted":
                classification = "restricted"
            records.append(
                {
                    "source_ref": (
                        f"knowledge://{record_tenant}/{doc_id.lower()}/"
                        f"v{document['version']}"
                    ),
                    "document_version": str(document["version"]),
                    "section": "synthetic-summary",
                    "redacted_summary": content,
                    "content_hash": "sha256:"
                    + hashlib.sha256(content.encode()).hexdigest(),
                    "classification": classification,
                }
            )
        return records

    def _assertions(
        self,
        case: Mapping[str, Any],
        observation: Mapping[str, Any],
    ) -> dict[str, bool]:
        outcomes: dict[str, bool] = {}
        raw_assertions = case.get("deterministic_assertions")
        if not isinstance(raw_assertions, list):
            raise ValueError("M7 case assertions must be a list")
        for raw in raw_assertions:
            if not isinstance(raw, dict):
                raise ValueError("M7 assertion must be an object")
            assertion_id = raw.get("assertion_id")
            parameters = raw.get("parameters")
            if not isinstance(assertion_id, str) or not isinstance(parameters, dict):
                raise ValueError("M7 assertion identity and parameters are required")
            if assertion_id == "assert.task.terminal_status.v1":
                outcomes[assertion_id] = (
                    observation["terminal_status"] == parameters.get("expected")
                )
            elif assertion_id == "assert.citation.valid.v1":
                outcomes[assertion_id] = bool(observation["citation_binding_valid"])
            elif assertion_id == "assert.tool.allowed.v1":
                allowed = parameters.get("tools")
                outcomes[assertion_id] = (
                    isinstance(allowed, list)
                    and set(cast(list[str], allowed))
                    >= set(cast(list[str], observation["observed_tools"]))
                    and observation["tool_write_count"] == 0
                )
            else:
                outcomes[assertion_id] = False
        return outcomes

    def _load_case_pins(self) -> dict[str, str]:
        pins: dict[str, str] = {}
        scenarios: set[str] = set()
        pattern = "m6-incremental-*/cases/functional/*.json"
        for path in sorted((self._root / "evals" / "datasets").glob(pattern)):
            value = load_json_strict(path)
            if not isinstance(value, dict):
                raise ValueError("M7 evaluation case must be a JSON object")
            if value.get("category") != "knowledge_qa_citation":
                continue
            case_id = value.get("case_id")
            scenario = _scenario(value)
            assertions = {
                item.get("assertion_id")
                for item in value.get("deterministic_assertions", [])
                if isinstance(item, dict)
            }
            if (
                not isinstance(case_id, str)
                or case_id in pins
                or scenario not in _SCENARIO_DOCUMENT_IDS
                or assertions != _SUPPORTED_ASSERTIONS
            ):
                raise ValueError("M7 knowledge case registry is not uniquely supported")
            pins[case_id] = canonical_digest(value)
            scenarios.add(scenario)
        if (
            len(pins) != M7_SUPPORTED_CASE_COUNT
            or scenarios != set(_SCENARIO_DOCUMENT_IDS)
        ):
            raise ValueError("M7 executor must pin exactly 24 knowledge scenarios")
        return pins


def build_m7_executor_registry(repository_root: Path) -> CaseExecutorRegistry:
    """Return the single authorized M7 product executor registry."""

    return CaseExecutorRegistry([M7EnterpriseKnowledgeExecutor(repository_root)])


def _scenario(case: Mapping[str, Any]) -> str:
    tags = case.get("tags")
    if not isinstance(tags, list):
        raise ValueError("M7 case tags must be a list")
    scenarios = [
        item.removeprefix("scenario:")
        for item in tags
        if isinstance(item, str) and item.startswith("scenario:")
    ]
    if len(scenarios) != 1:
        raise ValueError("M7 case must declare exactly one scenario tag")
    return scenarios[0]


def _trusted_identity_snapshot(suffix: str) -> TrustedSecurityContext:
    authentication = AuthenticationRef(
        method=AuthenticationMethod.OIDC,
        assurance_level=AssuranceLevel.SUBSTANTIAL,
        session_id_hash=canonical_sha256({"session": suffix}),
    )
    context_id = f"secctx_m7eval{suffix}"
    context_ref = f"security-context://{_TENANT_ID}/m7eval{suffix}"
    expires_at = _FIXED_NOW + timedelta(days=1)
    context_hash = trusted_context_snapshot_hash(
        context_id=context_id,
        context_ref=context_ref,
        tenant_id=_TENANT_ID,
        subject_id=_ACTOR_ID,
        subject_type=ActorType.USER,
        issuer=_IDENTITY_ISSUER,
        authorized_party=_AUTHORIZED_PARTY,
        roles=_CONTEXT_ROLES,
        scopes=_CONTEXT_SCOPES,
        authentication=authentication,
        purpose="it_support",
        data_classification_ceiling=DataClassification.CONFIDENTIAL,
        issued_at=_FIXED_NOW,
        expires_at=expires_at,
        source_token_hash=_SOURCE_TOKEN_HASH,
    )
    return TrustedSecurityContext(
        context=SecurityContextRef(
            context_id=context_id,
            context_ref=context_ref,
            context_hash=context_hash,
            tenant_id=_TENANT_ID,
            subject_id=_ACTOR_ID,
            subject_type=ActorType.USER,
            purpose="it_support",
            authentication=authentication,
            data_classification_ceiling=DataClassification.CONFIDENTIAL,
            issued_at=_FIXED_NOW,
            expires_at=expires_at,
        ),
        active=True,
        roles=_CONTEXT_ROLES,
        scopes=_CONTEXT_SCOPES,
        issuer=_IDENTITY_ISSUER,
        authorized_party=_AUTHORIZED_PARTY,
        identity_token_hash=_SOURCE_TOKEN_HASH,
    )


def _command(
    suffix: str,
    trusted: TrustedSecurityContext,
) -> tuple[TaskCommand, dict[str, Any]]:
    issued = _FIXED_NOW.isoformat().replace("+00:00", "Z")
    body: dict[str, Any] = {
        "command_id": f"cmd_m7eval{suffix}",
        "command_type": "task.create.v1",
        "tenant_id": _TENANT_ID,
        "task_id": f"task_m7eval{suffix}",
        "actor": {"type": "user", "id": _ACTOR_ID},
        "security_context": trusted.context.to_mapping(),
        "expected_task_version": None,
        "idempotency_key": canonical_sha256({"idempotency": suffix}),
        "command_digest": "sha256:" + "0" * 64,
        "correlation_id": f"corr-m7eval-{suffix}",
        "payload": {
            "initial_message_id": f"msg_m7eval{suffix}",
            "initial_message_ref": f"message://{_TENANT_ID}/m7eval{suffix}",
            "attachment_refs": [],
            "channel": "api",
            "purpose": "it_support",
        },
        "issued_at": issued,
    }
    provisional = TaskCommand.from_mapping(body)
    body["command_digest"] = provisional.recompute_digest()
    command = TaskCommand.from_mapping(body)
    command.assert_digest()
    command.assert_security_binding()
    return command, body


def _resolved_request(
    command: TaskCommand, question: str
) -> ResolvedRequestReference:
    query = RequestReferenceQuery(
        tenant_id=command.tenant_id,
        task_id=command.task_id,
        message_id=str(command.payload["initial_message_id"]),
        message_ref=str(command.payload["initial_message_ref"]),
        purpose=command.security_context.purpose,
        security_context_ref=command.security_context.context_ref,
    )
    source_digest = canonical_sha256(
        {"message_ref": query.message_ref, "question": question}
    )
    provisional = ResolvedRequestReference(
        query=query,
        observation_ref=f"observation://{_TENANT_ID}/{command.task_id}/knowledge",
        source_digest=source_digest,
        intent="knowledge_question",
        fields={"question": question},
        data_classification=DataClassification.INTERNAL,
        observation_digest="sha256:" + "0" * 64,
    )
    return ResolvedRequestReference(
        query=query,
        observation_ref=provisional.observation_ref,
        source_digest=provisional.source_digest,
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


def _identity(
    command: TaskCommand,
    trusted: TrustedSecurityContext,
) -> TrustedRequestIdentity:
    return TrustedRequestIdentity(
        tenant_id=command.tenant_id,
        subject_id=command.actor.id,
        subject_type=ActorType(command.actor.type),
        purpose=command.security_context.purpose,
        security_context_id=command.security_context.context_id,
        security_context_ref=command.security_context.context_ref,
        security_context_hash=command.security_context.context_hash,
        security_context=trusted.context,
        roles=trusted.roles,
        scopes=trusted.scopes,
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


async def _post(app: Any, body: Mapping[str, Any]) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://flowpilot.test",
    ) as client:
        return await client.post("/v1/task-commands", json=body)


def _citations_are_valid(citations: tuple[Any, ...], has_result: bool) -> bool:
    if not has_result:
        return not citations
    return bool(citations) and all(
        isinstance(item.source_ref, str)
        and item.source_ref.startswith(f"knowledge://{_TENANT_ID}/")
        and isinstance(item.document_version, str)
        and bool(item.document_version)
        and isinstance(item.section, str)
        and bool(item.section)
        and isinstance(item.content_hash, str)
        and item.content_hash.startswith("sha256:")
        for item in citations
    )


__all__ = [
    "M7EnterpriseKnowledgeExecutor",
    "M7_PRODUCT_EXECUTOR_ID",
    "M7_PRODUCT_EXECUTOR_VERSION",
    "M7_SUPPORTED_CASE_COUNT",
    "build_m7_executor_registry",
]
