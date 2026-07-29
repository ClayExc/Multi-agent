from __future__ import annotations

import copy
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOTS = (
    REPOSITORY_ROOT / "packages" / "domain" / "src",
    REPOSITORY_ROOT / "packages" / "application" / "src",
    REPOSITORY_ROOT / "packages" / "context" / "src",
    REPOSITORY_ROOT / "packages" / "agent-runtime" / "src",
    REPOSITORY_ROOT / "packages" / "model-gateway" / "src",
    REPOSITORY_ROOT / "packages" / "graph" / "src",
    REPOSITORY_ROOT / "apps" / "worker" / "src",
)
for source_root in reversed(SOURCE_ROOTS):
    sys.path.insert(0, str(source_root))

from flowpilot_agent_runtime import (  # noqa: E402
    AgentMode,
    AgentProfile,
    AgentRunRequest,
    AllowedTool,
    FakeAgentRuntime,
    OutputSchemaRef,
    ProviderSelection,
    RuntimeBudget,
    ToolOperation,
)
from flowpilot_context import (  # noqa: E402
    ContextBuilder,
    ContextBuildRequest,
    ContextPolicy,
)
from flowpilot_domain import (  # noqa: E402
    DataClassification,
    TaskCommand,
)
from flowpilot_graph import (  # noqa: E402
    InMemoryCheckpointStore,
    InMemoryLeaseStore,
    RuntimeGraphConfig,
    RuntimeGraphKernel,
)
from flowpilot_graph.langgraph_runtime import LangGraphRuntime  # noqa: E402

FIXED_NOW = datetime(2026, 7, 28, 8, 30, tzinfo=UTC)


def _load_case(case_id: str) -> dict[str, Any]:
    case_file = REPOSITORY_ROOT / "contracts" / "conformance" / "rc2-cases.json"
    content = json.loads(case_file.read_text(encoding="utf-8"))
    for case in content["cases"]:
        if case["case_id"] == case_id:
            return copy.deepcopy(case["instance"])
    raise LookupError(case_id)


@pytest.fixture
def fixed_clock() -> Callable[[], datetime]:
    return lambda: FIXED_NOW


@pytest.fixture
def command_factory() -> Callable[..., TaskCommand]:
    valid = _load_case("task_command.create.valid")

    def factory(
        *,
        command_id: str = "cmd_12345678",
        task_id: str = "task_12345678",
        tenant_id: str = "tenant-a",
        security_tenant_id: str | None = None,
        purpose: str = "it_support",
        security_purpose: str | None = None,
    ) -> TaskCommand:
        value = copy.deepcopy(valid)
        value["command_id"] = command_id
        value["task_id"] = task_id
        value["tenant_id"] = tenant_id
        value["security_context"]["tenant_id"] = (
            security_tenant_id or tenant_id
        )
        value["payload"]["purpose"] = purpose
        value["security_context"]["purpose"] = security_purpose or purpose
        value["command_digest"] = "sha256:" + "0" * 64
        unsigned = TaskCommand.from_mapping(value)
        value["command_digest"] = unsigned.recompute_digest()
        return TaskCommand.from_mapping(value)

    return factory


@pytest.fixture
def context_policy() -> ContextPolicy:
    return ContextPolicy(
        context_policy_version="ctx-policy-v1",
        data_classification_ceiling=DataClassification.CONFIDENTIAL,
        provider_allowlist=("test-provider",),
        token_budget=4096,
    )


@pytest.fixture
def agent_profile() -> AgentProfile:
    return AgentProfile(
        id="knowledge-agent",
        version="1.0.0",
        prompt_version="prompt-v1",
        mode=AgentMode.BOUNDED_AGENT_LOOP,
        output_schema=OutputSchemaRef(
            id="schema://knowledge-answer/v1",
            hash="sha256:" + "a" * 64,
        ),
        allowed_tools=(
            AllowedTool(
                name="knowledge.search.v1",
                schema_hash="sha256:" + "b" * 64,
                operation=ToolOperation.READ,
            ),
        ),
        maximum_handoffs=1,
    )


@pytest.fixture
def provider_selection() -> ProviderSelection:
    return ProviderSelection(
        provider="test-provider",
        model="deterministic-fake",
        data_policy_id="data-policy-v1",
        routing_reason_code="TEST_CONFORMANCE",
    )


@pytest.fixture
def runtime_budget() -> RuntimeBudget:
    return RuntimeBudget(
        maximum_turns=4,
        maximum_tool_calls=2,
        maximum_input_tokens=4096,
        maximum_output_tokens=1024,
        maximum_total_tokens=5120,
        maximum_cost_microunits=1000,
        timeout_ms=30_000,
    )


@pytest.fixture
def request_factory(
    command_factory: Callable[..., TaskCommand],
    fixed_clock: Callable[[], datetime],
    context_policy: ContextPolicy,
    agent_profile: AgentProfile,
    provider_selection: ProviderSelection,
    runtime_budget: RuntimeBudget,
) -> Callable[..., AgentRunRequest]:
    def factory(
        *,
        command: TaskCommand | None = None,
        request_tenant_id: str | None = None,
        context_agent_id: str | None = None,
        provider: ProviderSelection | None = None,
        budget: RuntimeBudget | None = None,
        optional_layers: tuple[Any, ...] = (),
    ) -> AgentRunRequest:
        effective_command = command or command_factory()
        context = ContextBuilder(clock=fixed_clock).build(
            ContextBuildRequest(
                context_id="ctx_12345678",
                task_id=effective_command.task_id,
                agent_id=context_agent_id or agent_profile.id,
                purpose=effective_command.security_context.purpose,
                security_context=effective_command.security_context,
                task_state={"status": "RUNNING"},
                task_state_ref=f"task://{effective_command.task_id}/v1",
                system_policy_ref="policy://runtime/v1",
                policy=context_policy,
                optional_layers=optional_layers,
            )
        )
        return AgentRunRequest(
            request_id="arq_12345678",
            task_id=effective_command.task_id,
            tenant_id=request_tenant_id or effective_command.tenant_id,
            trace_id="0123456789abcdef0123456789abcdef",
            run_id="run_12345678",
            agent=agent_profile,
            context=context,
            security_context=effective_command.security_context,
            provider_selection=provider or provider_selection,
            budget=budget or runtime_budget,
            session_ref=None,
            issued_at=fixed_clock(),
        )

    return factory


@pytest.fixture
def graph_factory(
    fixed_clock: Callable[[], datetime],
    context_policy: ContextPolicy,
    agent_profile: AgentProfile,
    provider_selection: ProviderSelection,
    runtime_budget: RuntimeBudget,
) -> Callable[..., tuple[
    LangGraphRuntime,
    FakeAgentRuntime,
    InMemoryCheckpointStore,
    InMemoryLeaseStore,
]]:
    def factory(
        *,
        runtime: FakeAgentRuntime | None = None,
        graph_version: str = "graph-v1",
        maximum_attempts: int = 2,
    ) -> tuple[
        LangGraphRuntime,
        FakeAgentRuntime,
        InMemoryCheckpointStore,
        InMemoryLeaseStore,
    ]:
        leases = InMemoryLeaseStore(clock=fixed_clock)
        checkpoints = InMemoryCheckpointStore(leases=leases)
        effective_runtime = runtime or FakeAgentRuntime(clock=fixed_clock)
        kernel = RuntimeGraphKernel(
            config=RuntimeGraphConfig(
                graph_version=graph_version,
                context_policy=context_policy,
                agent=agent_profile,
                provider=provider_selection,
                budget=runtime_budget,
                maximum_attempts=maximum_attempts,
            ),
            context_builder=ContextBuilder(clock=fixed_clock),
            runtime=effective_runtime,
            checkpoints=checkpoints,
            clock=fixed_clock,
        )
        graph = LangGraphRuntime(kernel)
        return graph, effective_runtime, checkpoints, leases

    return factory
