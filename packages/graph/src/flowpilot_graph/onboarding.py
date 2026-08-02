"""Onboarding composite graph — AC-E2E-002 business slice (M5-1).

Deterministic composite graph for a new-employee provisioning request over
the stable FlowPilot topology plus the M5-1 third parallel read branch:

1. intake + clarification loop (WAITING_USER, multi-round until the five
   required fields arrive; every round charges the M4-2 ContextBudgetLedger
   against a hard cumulative budget, FP-CTX-004);
2. three parallel read-only branches — device standard, inventory,
   permission template — each isolated so a branch failure is localized by
   its own ``failure_code`` (FP-FLOW-003 via ``reduce_parallel``);
3. sub-action planning: one task, two ``PlannedAction`` writes (device
   allocation + permission grant) with distinct idempotency keys;
4. the permission action enters the manager approval interrupt; the card
   follows the FP-APR-001 contract (impact / arguments / basis / expires_at
   / tool+action_id summary);
5. approved-then-execute write closed loop (FP-MCP-003/004/005): action
   digest binding, idempotent replay, UNKNOWN-first-reconcile, write-then-
   read-back, per-action ledger records;
6. related ticket creation and a summary that lists only tickets that were
   actually created and read-back verified.

Partial failure semantics: a business failure of any write (e.g. inventory
insufficient) terminates as FAILED with a ``failure_code`` that names the
exact sub-action; already-verified sub-actions are never re-executed and
the terminal state is never a fake COMPLETED.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any, Protocol, TypedDict, cast

from flowpilot_context import (
    ContextBudgetLedger,
    ContextBuilder,
    ContextBuildRequest,
    ContextEnvelope,
    ContextError,
    ContextErrorCode,
    ContextPolicy,
    estimate_tokens,
)
from flowpilot_domain import (
    ActionAgent,
    ActionResource,
    ActionTool,
    Approval,
    ApprovalStatus,
    CommandType,
    DataClassification,
    DomainViolation,
    PlannedAction,
    TaskCommand,
    ToolOperation,
    canonical_sha256,
)
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, interrupt

from .engine import GraphExecutionPort, GraphRunOutcome
from .errors import GraphError, GraphErrorCode
from .factory import (
    FlowPilotGraphNodes,
    GraphDefinition,
    build_flowpilot_it_service_graph,
)
from .ports import CheckpointPort, LeaseToken
from .reducer import BranchResult, reduce_parallel
from .state import GraphNode, GraphState, GraphStatus

ONBOARDING_GRAPH_VERSION = "flowpilot.onboarding-composite.m5a.v1"
ONBOARDING_AGENT_ID = "onboarding-composite-agent"
ONBOARDING_AGENT_VERSION = "m5a.0"
ONBOARDING_AGENT_PRINCIPAL = "workload://flowpilot/onboarding/m5a"

# AC-E2E-002 required fields (姓名/部门/经理/地点/入职日期), mirrored by
# domain-packs/onboarding/required-fields.yaml.
ONBOARDING_REQUIRED_FIELDS = (
    "full_name",
    "department",
    "manager",
    "location",
    "start_date",
)

DEVICE_STANDARD_TOOL = "catalog.device-standard.read.v1"
INVENTORY_TOOL = "inventory.query.read.v1"
PERMISSION_TEMPLATE_TOOL = "permission.template.read.v1"
DEVICE_ALLOCATE_TOOL = "device.allocate.v1"
PERMISSION_GRANT_TOOL = "permission.grant.v1"
TICKET_CREATE_TOOL = "ticket.create.v1"

# Fixed schema pins for the M5-1 tool contracts (additive v1, computed the
# same way ToolContract.create hashes name+input_schema+output_schema; the
# drift guards below fail closed if the schemas change).
DEVICE_STANDARD_SCHEMA_PIN = (
    "sha256:1e93525c00c5c2041a36eb2cbe2e6f6af17e2a75525b06e7fb27a25f5c16364d"
)
INVENTORY_SCHEMA_PIN = (
    "sha256:6d4694f8c273d1def9c92dcbdc02c37bef83dc0c7d8f8e5d73ac5556ef819d20"
)
PERMISSION_TEMPLATE_SCHEMA_PIN = (
    "sha256:a968023d01853551b884db460304096e45c218f02bc32d2407b5564c52d739f7"
)
DEVICE_ALLOCATE_SCHEMA_PIN = (
    "sha256:7e3cda681608a1391ddb466e70b9fa89e5497bcf0f2d6b37745de33f2b4d90ad"
)
PERMISSION_GRANT_SCHEMA_PIN = (
    "sha256:51de1382ab8279a77f9f5682c40d47b8eabf1f91d94ad569d7a30bebf6e9e770"
)
TICKET_CREATE_SCHEMA_PIN = (
    "sha256:d8ddba879a3802dcb4d14030ef4d96b541569a5c979e7dfe1ad630df2499625b"
)

_SAFE_FIELD = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_SAFE_TEXT = re.compile(r"^[^\x00-\x1f\x7f]{1,2048}$")
_CLASSIFICATION_RANK = {
    DataClassification.PUBLIC: 0,
    DataClassification.INTERNAL: 1,
    DataClassification.CONFIDENTIAL: 2,
    DataClassification.RESTRICTED: 3,
}


class OnboardingResultStatus(StrEnum):
    VERIFIED = "verified"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_FINAL = "failed_final"
    UNKNOWN = "unknown"


class OnboardingLedgerStatus(StrEnum):
    PREPARED = "prepared"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    VERIFIED = "verified"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_FINAL = "failed_final"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class OnboardingObservation:
    tenant_id: str
    task_id: str
    message_id: str
    message_ref: str
    intent: str
    fields: Mapping[str, str]
    observation_ref: str
    source_digest: str


@dataclass(frozen=True, slots=True)
class OnboardingGatewayCall:
    request_id: str
    operation: ToolOperation
    action: PlannedAction
    action_digest: str
    policy_decision_id: str
    idempotency_key: str
    approval_id: str | None = None
    # UNKNOWN-first reconciliation (FP-MCP-005): a read-back issued for an
    # outcome-unknown write so the upstream result is identified before any
    # duplicate write is attempted.
    reconcile: bool = False
    trace_id: str = ""
    requested_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class OnboardingToolResult:
    request_id: str
    operation: ToolOperation
    status: OnboardingResultStatus
    data: Mapping[str, Any] | None
    display_summary: str
    output_classification: str
    policy_decision_id: str
    started_at: datetime
    finished_at: datetime
    error_code: str | None = None
    verification_matched: bool | None = None
    evidence_ref: str | None = None


@dataclass(frozen=True, slots=True)
class OnboardingLedgerEntry:
    tenant_id: str
    task_id: str
    execution_id: str
    action_digest: str
    idempotency_key: str
    tool: str
    status: OnboardingLedgerStatus
    started_at: datetime
    finished_at: datetime
    error_code: str | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class OnboardingArtifactDraft:
    tenant_id: str
    task_id: str
    idempotency_key: str
    media_type: str
    content: str
    result_digest: str
    citations: tuple[Mapping[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class OnboardingArtifactReceipt:
    result_ref: str | None


class OnboardingResolverPort(Protocol):
    async def resolve(self, command: TaskCommand) -> OnboardingObservation: ...


class OnboardingGatewayPort(Protocol):
    async def execute(self, call: OnboardingGatewayCall) -> OnboardingToolResult: ...


class OnboardingApprovalSourcePort(Protocol):
    async def resolve(self, approval_id: str) -> Approval: ...


class OnboardingLedgerPort(Protocol):
    async def record(self, entry: OnboardingLedgerEntry) -> None: ...


class OnboardingArtifactPort(Protocol):
    async def save(
        self, draft: OnboardingArtifactDraft
    ) -> OnboardingArtifactReceipt: ...


def _append_unique(
    left: Sequence[str] | None,
    right: Sequence[str] | None,
) -> list[str]:
    return list(dict.fromkeys([*(left or ()), *(right or ())]))


def _merge_reads(
    left: Mapping[str, Any] | None,
    right: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Merge per-branch read records written by the parallel fan-out.

    Each parallel branch updates exactly one key of the ``reads`` mapping,
    so concurrent updates combine without clobbering (FP-FLOW-003).
    """
    merged = dict(left or {})
    merged.update(right or {})
    return merged


class OnboardingGraphState(TypedDict, total=False):
    task_ref: str
    status: str
    route: str
    current_node: str
    visited_nodes: Annotated[list[str], _append_unique]
    observation_ref: str
    requester_id: str
    fields: dict[str, str]
    missing_fields: list[str]
    input_complete: bool
    # M4-2 (FP-CTX-004): cross-turn budget counters ride the checkpoint.
    conversation_round: int
    cumulative_input_tokens: int
    cumulative_output_tokens: int
    # Per-branch parallel read records (FP-FLOW-003): branch_id -> outcome,
    # merged across the concurrent branch updates.
    reads: Annotated[dict[str, dict[str, Any]], _merge_reads]
    reads_complete: bool
    read_facts: dict[str, Any]
    read_failures: dict[str, str]
    sub_actions: list[dict[str, Any]]
    permission_approval_id: str
    approval_decision: str
    write_results: dict[str, dict[str, Any]]
    write_failure: str
    writes_complete: bool
    ticket_refs: list[str]
    result_ref: str
    runtime_outcome: str
    terminal_reason: str
    failure_code: str
    # M5-2 recovery (AC-E2E-002 reliability face): control-plane inputs for
    # a crash-restart replay.  ``recovery_restored`` marks Checkpoint-
    # projected progress so ``prepare`` keeps it; ``resume_decision`` /
    # ``resume_confirmed`` carry the interrupted approval/clarification
    # decision into the replay so every validation still runs.
    recovery_restored: bool
    resume_decision: dict[str, Any]
    resume_confirmed: bool


@dataclass(frozen=True, slots=True)
class OnboardingGraphConfig:
    graph_version: str = ONBOARDING_GRAPH_VERSION
    required_fields: tuple[str, ...] = ONBOARDING_REQUIRED_FIELDS
    maximum_attempts: int = 2
    policy_version: str = "policy-onb-m5a.1"
    system_policy_ref: str = "policy://onboarding-composite/m5a"
    agent_id: str = ONBOARDING_AGENT_ID
    agent_version: str = ONBOARDING_AGENT_VERSION
    agent_principal_ref: str = ONBOARDING_AGENT_PRINCIPAL
    cumulative_token_budget: int = 4096
    maximum_conversation_rounds: int = 10
    context_policy: ContextPolicy = ContextPolicy(
        context_policy_version="context-onboarding-m5a",
        data_classification_ceiling=DataClassification.CONFIDENTIAL,
        provider_allowlist=("deterministic-no-provider",),
        token_budget=1024,
    )

    def __post_init__(self) -> None:
        if not self.required_fields:
            raise ValueError("onboarding required fields must not be empty")
        if not 1 <= self.maximum_attempts <= 5:
            raise ValueError("maximum_attempts must be within the graph contract")
        if self.cumulative_token_budget < 1:
            raise ValueError("cumulative token budget must be positive")
        if self.maximum_conversation_rounds < 1:
            raise ValueError("maximum conversation rounds must be positive")


@dataclass(frozen=True, slots=True)
class _Invocation:
    command: TaskCommand
    execution_ref: str
    lease: LeaseToken


class _OnboardingFailure(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


_ACTIVE_INVOCATION: ContextVar[_Invocation | None] = ContextVar(
    "flowpilot_onboarding_invocation",
    default=None,
)


class OnboardingCompositeGraph(GraphExecutionPort):
    """Deterministic AC-E2E-002 composite graph over the stable topology."""

    def __init__(
        self,
        *,
        resolver: OnboardingResolverPort,
        gateway: OnboardingGatewayPort,
        checkpoints: CheckpointPort,
        ledger: OnboardingLedgerPort,
        artifacts: OnboardingArtifactPort,
        context_builder: ContextBuilder,
        config: OnboardingGraphConfig | None = None,
        approvals: OnboardingApprovalSourcePort | None = None,
        clock: Callable[[], datetime] | None = None,
        checkpointer: Any | None = None,
    ) -> None:
        self._resolver = resolver
        self._gateway = gateway
        self._checkpoints = checkpoints
        self._ledger = ledger
        self._artifacts = artifacts
        self._context_builder = context_builder
        self._config = config or OnboardingGraphConfig()
        self._approvals = approvals
        self._clock = clock or (lambda: datetime.now(UTC))
        self._checkpointer = checkpointer or InMemorySaver()
        self._ledger_accounting = ContextBudgetLedger(
            cumulative_token_budget=self._config.cumulative_token_budget,
            maximum_rounds=self._config.maximum_conversation_rounds,
        )
        self.built_contexts: list[ContextEnvelope] = []
        # M5-1 (FP-FLOW-003): per-branch Trace records (started/finished)
        # used to assert parallel interval overlap deterministically.
        self._branch_traces: dict[str, dict[str, str]] = {}
        self.last_safe_state: Mapping[str, Any] | None = None
        # M5-2 recovery (FP-FLOW-005 / AC-E2E-002 reliability face): the
        # latest Checkpoint written by an in-node recovery progress record.
        # execute() bases its terminal transition on it so the checkpoint
        # sequence CAS never conflicts with in-node progress saves.
        self._recovery_state: GraphState | None = None
        nodes = _OnboardingNodes(self)
        self._definition = build_flowpilot_it_service_graph(
            OnboardingGraphState,
            nodes.as_graph_nodes(),
            checkpointer=self._checkpointer,
        )

    @property
    def definition(self) -> GraphDefinition:
        return self._definition

    @property
    def ledger(self) -> ContextBudgetLedger:
        return self._ledger_accounting

    async def execute(
        self,
        command: TaskCommand,
        *,
        execution_ref: str,
        lease: LeaseToken,
    ) -> GraphRunOutcome:
        self._validate_command(command)
        current = await self._load_or_initialize(command, lease)
        if current.status in {GraphStatus.COMPLETED, GraphStatus.FAILED}:
            return GraphRunOutcome(
                state=current,
                runtime_result=None,
                should_retry=False,
            )

        was_waiting_user = current.status is GraphStatus.WAITING_USER
        was_waiting_approval = current.status is GraphStatus.WAITING_APPROVAL
        if was_waiting_user and command.command_type is not CommandType.SUBMIT_MESSAGE:
            raise GraphError(
                GraphErrorCode.COMMAND_UNSUPPORTED,
                "onboarding clarification requires a submitted message command",
            )
        if (
            was_waiting_approval
            and command.command_type is not CommandType.DECIDE_APPROVAL
        ):
            raise GraphError(
                GraphErrorCode.COMMAND_UNSUPPORTED,
                "onboarding approval requires an approval decision command",
            )
        current = current.transition(
            GraphStatus.RUNNING,
            node=GraphNode.INTAKE,
            command_id=command.command_id,
            command_digest=command.command_digest,
            run_id=lease.run_id,
            run_generation=lease.run_generation,
            attempt_count=current.attempt_count + 1,
            pending_reason=None,
            failure_code=None,
        )
        current = await self._save(current, lease)
        # M5-2 recovery: in-node recovery progress records (read-branch
        # completion, sub-action plan/progress) base their Checkpoint CAS
        # on this freshly saved state and refresh this handle.
        self._recovery_state = current

        # Rebuild the cross-turn budget from the Checkpoint so interrupted
        # or restarted runs never re-charge rounds that already ran
        # (FP-CTX-004 / FP-FLOW-005).
        self._ledger_accounting.restore(
            round_count=current.conversation_round,
            input_tokens=current.cumulative_input_tokens,
            output_tokens=current.cumulative_output_tokens,
        )

        invocation = _Invocation(
            command=command,
            execution_ref=execution_ref,
            lease=lease,
        )
        token = _ACTIVE_INVOCATION.set(invocation)
        graph_config = {"configurable": {"thread_id": self._thread_id(command)}}
        try:
            graph_input: Mapping[str, Any] | Command[Any]
            if was_waiting_approval and await self._has_graph_checkpoint(graph_config):
                graph_input = Command(
                    resume={
                        "approval_id": str(command.payload["approval_id"]),
                        "action_digest": str(command.payload["action_digest"]),
                        "decision": (
                            "approved"
                            if command.payload["decision"] == "approve"
                            else "rejected"
                        ),
                        "approver_id": command.actor.id,
                    }
                )
            elif was_waiting_user and await self._has_graph_checkpoint(graph_config):
                graph_input = Command(resume={"confirmed": True})
            else:
                graph_input = self._recovery_input(command, current)
                if (
                    command.command_type is CommandType.DECIDE_APPROVAL
                    and bool(current.sub_action_plan)
                ):
                    # M5-2: the control-plane thread checkpoint was lost
                    # (process crash).  Replay the graph from its Checkpoint
                    # and feed the approval decision to the approval node so
                    # the full re-authorization validation still runs
                    # (binding / duties / manager / approval-active) instead
                    # of silently skipping the interrupt.  This covers both
                    # a crash parked at WAITING_APPROVAL and a crash inside
                    # run_agent (status RUNNING) after the approval.
                    graph_input = {
                        **graph_input,
                        "resume_decision": {
                            "approval_id": str(command.payload["approval_id"]),
                            "action_digest": str(command.payload["action_digest"]),
                            "decision": (
                                "approved"
                                if command.payload["decision"] == "approve"
                                else "rejected"
                            ),
                            "approver_id": command.actor.id,
                        },
                    }
                elif was_waiting_user:
                    # Same crash-recovery semantics for a clarification
                    # interrupt: the submitted message is the confirmation,
                    # the resolver re-reads the accumulated fields.
                    graph_input = {
                        **graph_input,
                        "resume_confirmed": True,
                    }
            result = await self._definition.graph.ainvoke(
                cast(Any, graph_input),
                config=cast(Any, graph_config),
            )
            self.last_safe_state = dict(result)
            # M5-2 recovery: in-node progress records advanced the
            # Checkpoint sequence; base the terminal transition on the
            # latest record so the save CAS never conflicts.
            if self._recovery_state is not None:
                current = self._recovery_state
            if result.get("__interrupt__"):
                waiting_route = self._pending_route(result)
                waiting = current.transition(
                    GraphStatus.WAITING_USER
                    if waiting_route == "clarification"
                    else GraphStatus.WAITING_APPROVAL,
                    node=GraphNode.INTERRUPT,
                    pending_reason=(
                        "onboarding_clarification:fields"
                        if waiting_route == "clarification"
                        else "onboarding_approval:permission.grant.v1"
                    ),
                    observation_ref=self._optional_text(result.get("observation_ref")),
                    # The ledger was charged synchronously before the pause,
                    # so its counters are the authoritative checkpoint state
                    # for the interrupted round (FP-CTX-004).
                    conversation_round=self._ledger_accounting.round_count,
                    cumulative_input_tokens=self._ledger_accounting.used_input_tokens,
                    cumulative_output_tokens=self._ledger_accounting.used_output_tokens,
                )
                waiting = await self._save(waiting, lease)
                return GraphRunOutcome(
                    state=waiting,
                    runtime_result=None,
                    should_retry=False,
                )

            status = result.get("status")
            if status is GraphStatus.COMPLETED.value:
                result_ref = self._required_text(result.get("result_ref"))
                completed = current.transition(
                    GraphStatus.COMPLETED,
                    node=GraphNode.FINALIZE,
                    context_id=self._optional_text(result.get("context_id")),
                    result_ref=result_ref,
                    observation_ref=self._optional_text(result.get("observation_ref")),
                    conversation_round=self._count(result.get("conversation_round")),
                    cumulative_input_tokens=self._count(
                        result.get("cumulative_input_tokens")
                    ),
                    cumulative_output_tokens=self._count(
                        result.get("cumulative_output_tokens")
                    ),
                    failure_code=None,
                )
                completed = await self._save(completed, lease)
                return GraphRunOutcome(
                    state=completed,
                    runtime_result=None,
                    should_retry=False,
                )
            if status is GraphStatus.FAILED.value:
                failed = current.transition(
                    GraphStatus.FAILED,
                    node=GraphNode.FINALIZE,
                    context_id=self._optional_text(result.get("context_id")),
                    result_ref=self._optional_text(result.get("result_ref")),
                    observation_ref=self._optional_text(result.get("observation_ref")),
                    failure_code=self._required_text(result.get("failure_code")),
                    conversation_round=self._count(result.get("conversation_round")),
                    cumulative_input_tokens=self._count(
                        result.get("cumulative_input_tokens")
                    ),
                    cumulative_output_tokens=self._count(
                        result.get("cumulative_output_tokens")
                    ),
                )
                failed = await self._save(failed, lease)
                return GraphRunOutcome(
                    state=failed,
                    runtime_result=None,
                    should_retry=False,
                )
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "onboarding graph ended without a deterministic terminal state",
            )
        except _OnboardingFailure as failure:
            should_retry = (
                failure.retryable
                and current.attempt_count < self._config.maximum_attempts
            )
            failed = current.transition(
                (GraphStatus.RETRY_PENDING if should_retry else GraphStatus.FAILED),
                node=(GraphNode.RUN_AGENT if should_retry else GraphNode.FINALIZE),
                failure_code=failure.code,
            )
            failed = await self._save(failed, lease)
            return GraphRunOutcome(
                state=failed,
                runtime_result=None,
                should_retry=should_retry,
            )
        finally:
            _ACTIVE_INVOCATION.reset(token)
            self._recovery_state = None

    def _recovery_input(
        self,
        command: TaskCommand,
        current: GraphState,
    ) -> dict[str, Any]:
        """Project Checkpoint recovery progress into the graph input.

        M5-2 (FP-FLOW-005 / AC-E2E-002 reliability face): after a Worker
        crash the control-plane thread checkpoint may be gone; the durable
        GraphState Checkpoint is the source of truth.  Completed parallel
        read branches, the reduced read facts, the sub-action plan and the
        per-sub-action execution progress are injected so the replayed graph
        resumes from the last completed node instead of re-running finished
        branches or verified sub-actions.  ``recovery_restored`` lets the
        ``prepare`` node keep injected progress instead of re-initializing.
        """
        recovery: dict[str, Any] = {}
        if current.completed_read_branches:
            recovery["reads_complete"] = True
            recovery["reads"] = {
                branch: {
                    "branch_id": branch,
                    "facts": {},
                    "evidence_refs": [],
                    "failure_code": None,
                }
                for branch in current.completed_read_branches
            }
            recovery["read_facts"] = dict(current.read_facts)
            recovery["read_failures"] = {}
        if current.sub_action_plan:
            recovery["sub_actions"] = list(current.sub_action_plan)
            permission_id = next(
                (
                    item["approval_id"]
                    for item in current.sub_action_plan
                    if item.get("approval_id")
                ),
                None,
            )
            if permission_id is not None:
                recovery["permission_approval_id"] = permission_id
        if current.sub_action_progress:
            recovery["write_results"] = {
                item["action_id"]: dict(item)
                for item in current.sub_action_progress
            }
        if current.recovery_fields:
            recovery["fields"] = dict(current.recovery_fields)
            recovery["input_complete"] = True
        if current.recovery_requester_id is not None:
            recovery["requester_id"] = current.recovery_requester_id
        if recovery:
            recovery["recovery_restored"] = True
        return {"task_ref": self._opaque_task_ref(command), **recovery}

    async def _record_recovery_progress(
        self,
        *,
        node: GraphNode,
        **updates: Any,
    ) -> None:
        """Persist one in-node recovery progress record (M5-2).

        Called from inside graph nodes after a parallel read-branch join,
        the sub-action plan and every completed sub-action.  The record is
        a RUNNING GraphState Checkpoint; its sequence participates in the
        same CAS/fencing as every other Checkpoint write, so a stale worker
        can never overwrite a newer generation's progress.
        """
        base = self._recovery_state
        if base is None:
            command = self._invocation().command
            base = await self._checkpoints.load(
                command.tenant_id, command.task_id
            )
        if base is None:
            return
        saved = await self._checkpoints.save(
            base.transition(GraphStatus.RUNNING, node=node, **updates),
            expected_sequence=base.checkpoint_sequence,
            lease=self._invocation().lease,
        )
        self._recovery_state = saved

    @staticmethod
    def _pending_route(result: Mapping[str, Any]) -> str:
        pending = result.get("__interrupt__")
        if isinstance(pending, (tuple, list)) and pending:
            # langgraph yields Interrupt objects; the card dict rides on
            # their ``value`` attribute.
            first = pending[0]
            value = getattr(first, "value", first)
            if isinstance(value, Mapping) and value.get("kind") == "approval":
                return "approval"
        return "clarification"

    def _build_context(
        self,
        observation: OnboardingObservation,
        *,
        task_state: Mapping[str, Any],
        context_kind: str,
    ) -> ContextEnvelope:
        command = self._invocation().command
        try:
            context = self._context_builder.build(
                ContextBuildRequest(
                    context_id=self._stable_id(
                        "ctx",
                        f"{command.task_id}:{command.command_id}:{context_kind}:"
                        f"{task_state.get('conversation_round', 0)}",
                    ),
                    task_id=command.task_id,
                    agent_id=self._config.agent_id,
                    purpose=command.security_context.purpose,
                    security_context=command.security_context,
                    task_state=dict(task_state),
                    task_state_ref=(
                        f"task://{command.task_id}/observation/"
                        f"{observation.source_digest.removeprefix('sha256:')[:16]}"
                    ),
                    system_policy_ref=self._config.system_policy_ref,
                    policy=self._config.context_policy,
                    excluded_fields=(
                        "original_message",
                        "request_body",
                        "internal_acl",
                        "credentials",
                        "tool_payload",
                    ),
                    redactions=("request_content", "knowledge_content"),
                )
            )
        except Exception as exc:
            code = getattr(getattr(exc, "code", None), "value", None)
            raise _OnboardingFailure(str(code or "RUNTIME_CONTEXT_INVALID")) from exc
        self.built_contexts.append(context)
        return context

    def _charge_clarification_round(
        self,
        observation: OnboardingObservation,
        *,
        missing_fields: Sequence[str],
        round_index: int,
    ) -> tuple[int, int]:
        """Charge one clarification round against the hard budget (FP-CTX-004)."""
        command = self._invocation().command
        context = self._build_context(
            observation,
            task_state={
                "status": GraphStatus.WAITING_USER.value,
                "intent": observation.intent,
                "observation_ref": observation.observation_ref,
                "missing_fields": list(missing_fields),
                "conversation_round": round_index,
            },
            context_kind="clarification",
        )
        input_tokens = sum(
            estimate_tokens(layer.to_mapping()) for layer in context.layers
        )
        output_tokens = 0
        layer_tokens = tuple(
            (layer.name.value, estimate_tokens(layer.to_mapping()))
            for layer in context.layers
        )
        try:
            self._ledger_accounting.charge(
                turn_index=round_index,
                request_id=self._stable_id(
                    "crq", f"{command.command_id}:clar:{round_index}"
                ),
                context_id=context.context_id,
                agent_id=self._config.agent_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                layer_tokens=layer_tokens,
            )
        except ContextError as exc:
            if exc.code is not ContextErrorCode.BUDGET_EXHAUSTED:
                raise
            raise _OnboardingFailure(
                "CLARIFICATION_BUDGET_EXHAUSTED"
                if self._ledger_accounting.round_count
                >= self._ledger_accounting.maximum_rounds
                else "CLARIFICATION_TOKEN_BUDGET_EXHAUSTED"
            ) from exc
        return input_tokens, output_tokens

    async def _read_branch(self, branch_id: str) -> BranchResult:
        """One isolated parallel read branch (FP-FLOW-003)."""
        command = self._invocation().command
        observation = await self._resolve()
        call = build_onboarding_read_call(
            config=self._config,
            command=command,
            observation=observation,
            branch_id=branch_id,
            run_id=self._invocation().lease.run_id,
        )
        started_at = self._clock().astimezone(UTC)
        try:
            result = await self._gateway.execute(call)
        except Exception:
            finished_at = self._clock().astimezone(UTC)
            self._record_branch_trace(
                branch_id,
                started_at=started_at,
                finished_at=finished_at,
            )
            return BranchResult(
                branch_id=branch_id,
                facts={},
                failure_code="RUNTIME_READ_GATEWAY_UNAVAILABLE",
            )
        finished_at = self._clock().astimezone(UTC)
        self._record_branch_trace(
            branch_id,
            started_at=started_at,
            finished_at=finished_at,
        )
        self._assert_read_result_binding(result, call)
        if result.status is not OnboardingResultStatus.VERIFIED or result.data is None:
            code = result.error_code or "RUNTIME_READ_FAILED"
            if result.status is OnboardingResultStatus.FAILED_RETRYABLE:
                code = result.error_code or "RUNTIME_READ_RETRYABLE"
            return BranchResult(
                branch_id=branch_id,
                facts={},
                failure_code=code,
            )
        classification = DataClassification(result.output_classification)
        ceiling = command.security_context.data_classification_ceiling
        if _CLASSIFICATION_RANK[classification] > _CLASSIFICATION_RANK[ceiling]:
            return BranchResult(
                branch_id=branch_id,
                facts={},
                failure_code="RUNTIME_READ_CLASSIFICATION_DENIED",
            )
        return BranchResult(
            branch_id=branch_id,
            # Branch facts are namespaced under the branch id so the flat
            # reducer merge cannot collide across branches (FP-FLOW-003).
            facts={branch_id: dict(result.data)},
            evidence_refs=(
                result.evidence_ref or f"evidence://onboarding/read/{branch_id}",
            ),
        )

    def _record_branch_trace(
        self,
        branch_id: str,
        *,
        started_at: datetime,
        finished_at: datetime,
    ) -> None:
        trace = {
            "branch_id": branch_id,
            "started_at": started_at.isoformat().replace("+00:00", "Z"),
            "finished_at": finished_at.isoformat().replace("+00:00", "Z"),
        }
        self._branch_traces[branch_id] = trace

    async def _resolve(self) -> OnboardingObservation:
        try:
            observation = await self._resolver.resolve(self._invocation().command)
        except Exception as exc:
            raise _OnboardingFailure("RUNTIME_OBSERVATION_UNAVAILABLE") from exc
        command = self._invocation().command
        if (
            observation.tenant_id != command.tenant_id
            or observation.task_id != command.task_id
        ):
            raise _OnboardingFailure("RUNTIME_OBSERVATION_BINDING_MISMATCH")
        return observation

    async def _execute_write(
        self,
        sub_action: Mapping[str, Any],
        *,
        reconcile_only: bool = False,
    ) -> dict[str, Any]:
        """Execute one approved sub-action with the FP-MCP-003/004/005 loop."""
        command = self._invocation().command
        call = build_onboarding_write_call(
            config=self._config,
            command=command,
            sub_action=sub_action,
            run_id=self._invocation().lease.run_id,
            reconcile=reconcile_only,
        )
        await self._ledger.record(
            OnboardingLedgerEntry(
                tenant_id=command.tenant_id,
                task_id=command.task_id,
                execution_id=call.request_id,
                action_digest=call.action_digest,
                idempotency_key=call.idempotency_key,
                tool=str(sub_action["tool"]),
                status=OnboardingLedgerStatus.PREPARED,
                started_at=self._clock().astimezone(UTC),
                finished_at=self._clock().astimezone(UTC),
            )
        )
        started_at = self._clock().astimezone(UTC)
        try:
            result = await self._gateway.execute(call)
        except Exception:
            finished_at = self._clock().astimezone(UTC)
            await self._record_ledger_failure(
                sub_action, call, "RUNTIME_WRITE_GATEWAY_UNAVAILABLE", started_at,
                finished_at,
            )
            return self._write_outcome(
                sub_action,
                status="failed_retryable",
                failure_code="WRITE_RETRYABLE:"
                f"{sub_action['tool']}:RUNTIME_WRITE_GATEWAY_UNAVAILABLE",
                started_at=started_at,
                finished_at=finished_at,
            )
        finished_at = self._clock().astimezone(UTC)
        if (
            result.request_id != call.request_id
            or result.policy_decision_id != call.policy_decision_id
            or result.operation is not ToolOperation.WRITE
        ):
            await self._record_ledger_failure(
                sub_action, call, "RUNTIME_WRITE_RESULT_BINDING_MISMATCH", started_at,
                finished_at,
            )
            return self._write_outcome(
                sub_action,
                status="failed_final",
                failure_code="WRITE_FAILED:"
                f"{sub_action['tool']}:RUNTIME_WRITE_RESULT_BINDING_MISMATCH",
                started_at=started_at,
                finished_at=finished_at,
            )
        if result.status is OnboardingResultStatus.VERIFIED:
            if result.verification_matched is not True:
                await self._record_ledger_failure(
                    sub_action, call, "RUNTIME_WRITE_READBACK_UNVERIFIED", started_at,
                    finished_at,
                )
                return self._write_outcome(
                    sub_action,
                    status="failed_final",
                    failure_code="WRITE_FAILED:"
                    f"{sub_action['tool']}:RUNTIME_WRITE_READBACK_UNVERIFIED",
                    started_at=started_at,
                    finished_at=finished_at,
                )
            await self._ledger.record(
                OnboardingLedgerEntry(
                    tenant_id=command.tenant_id,
                    task_id=command.task_id,
                    execution_id=call.request_id,
                    action_digest=call.action_digest,
                    idempotency_key=call.idempotency_key,
                    tool=str(sub_action["tool"]),
                    status=OnboardingLedgerStatus.VERIFIED,
                    started_at=started_at,
                    finished_at=finished_at,
                )
            )
            return self._write_outcome(
                sub_action,
                status="verified",
                failure_code=None,
                data=dict(result.data) if result.data else None,
                evidence_ref=result.evidence_ref,
                started_at=started_at,
                finished_at=finished_at,
            )
        if result.status is OnboardingResultStatus.UNKNOWN:
            # FP-MCP-005: never blind-retry an outcome-unknown write; read
            # back first and only accept the result if it already exists.
            reconciled = await self._execute_write(
                sub_action,
                reconcile_only=True,
            )
            if reconciled["status"] == "verified":
                return reconciled
            await self._record_ledger_failure(
                sub_action, call, "RUNTIME_WRITE_OUTCOME_UNKNOWN", started_at,
                finished_at,
            )
            return self._write_outcome(
                sub_action,
                status="failed_final",
                failure_code="WRITE_UNKNOWN:"
                f"{sub_action['tool']}:RUNTIME_WRITE_OUTCOME_UNKNOWN",
                started_at=started_at,
                finished_at=finished_at,
            )
        code = result.error_code or (
            "RUNTIME_WRITE_RETRYABLE"
            if result.status is OnboardingResultStatus.FAILED_RETRYABLE
            else "RUNTIME_WRITE_FAILED"
        )
        ledger_status = (
            OnboardingLedgerStatus.FAILED_RETRYABLE
            if result.status is OnboardingResultStatus.FAILED_RETRYABLE
            else OnboardingLedgerStatus.FAILED_FINAL
        )
        await self._record_ledger_failure(
            sub_action, call, code, started_at, finished_at, ledger_status=ledger_status
        )
        return self._write_outcome(
            sub_action,
            status=(
                "failed_retryable"
                if result.status is OnboardingResultStatus.FAILED_RETRYABLE
                else "failed_final"
            ),
            failure_code=(
                
                    "WRITE_RETRYABLE:"
                    if ledger_status
                    is OnboardingLedgerStatus.FAILED_RETRYABLE
                    else "WRITE_FAILED:"
                
            ) + f"{sub_action['tool']}:{code}",
            started_at=started_at,
            finished_at=finished_at,
        )

    async def _record_ledger_failure(
        self,
        sub_action: Mapping[str, Any],
        call: OnboardingGatewayCall,
        code: str,
        started_at: datetime,
        finished_at: datetime,
        *,
        ledger_status: OnboardingLedgerStatus = OnboardingLedgerStatus.FAILED_FINAL,
    ) -> None:
        await self._ledger.record(
            OnboardingLedgerEntry(
                tenant_id=call.action.tenant_id,
                task_id=call.action.task_id,
                execution_id=call.request_id,
                action_digest=call.action_digest,
                idempotency_key=call.idempotency_key,
                tool=str(sub_action["tool"]),
                status=ledger_status,
                started_at=started_at,
                finished_at=finished_at,
                error_code=code,
            )
        )

    @staticmethod
    def _write_outcome(
        sub_action: Mapping[str, Any],
        *,
        status: str,
        failure_code: str | None,
        started_at: datetime,
        finished_at: datetime,
        data: Mapping[str, Any] | None = None,
        evidence_ref: str | None = None,
    ) -> dict[str, Any]:
        return {
            "action_id": sub_action["action_id"],
            "tool": sub_action["tool"],
            "status": status,
            "failure_code": failure_code,
            "data": dict(data) if data else None,
            "evidence_ref": evidence_ref,
            "started_at": started_at.isoformat().replace("+00:00", "Z"),
            "finished_at": finished_at.isoformat().replace("+00:00", "Z"),
        }

    @staticmethod
    def _assert_read_result_binding(
        result: OnboardingToolResult,
        call: OnboardingGatewayCall,
    ) -> None:
        if (
            result.request_id != call.request_id
            or result.policy_decision_id != call.policy_decision_id
            or result.operation is not ToolOperation.READ
        ):
            raise _OnboardingFailure("RUNTIME_READ_RESULT_BINDING_MISMATCH")

    async def _save_summary(
        self,
        state: Mapping[str, Any],
        *,
        tickets: Sequence[str],
    ) -> str:
        command = self._invocation().command
        write_results = state.get("write_results", {})
        verified = [
            outcome
            for outcome in write_results.values()
            if outcome.get("status") == "verified"
        ]
        lines = ["## Onboarding provisioning summary"]
        if tickets:
            lines.append("\n### Tickets (created and read-back verified)")
            lines.extend(f"- {ticket}" for ticket in tickets)
        else:
            lines.append("\n### Tickets\n- none (no ticket was created and verified)")
        for outcome in verified:
            lines.append(
                f"\n- {outcome['tool']}: "
                f"{outcome.get('evidence_ref') or outcome.get('action_id')}"
            )
        content = "\n".join(lines)
        projection = {
            "tenant_id": command.tenant_id,
            "task_id": command.task_id,
            "media_type": "text/markdown",
            "content": content,
            "citations": [
                {
                    "source_ref": ticket,
                    "document_version": "1.0",
                    "section": "ticket",
                    "content_hash": canonical_sha256({"ticket": ticket}),
                }
                for ticket in tickets
            ],
        }
        draft = OnboardingArtifactDraft(
            tenant_id=command.tenant_id,
            task_id=command.task_id,
            idempotency_key=canonical_sha256(
                {
                    "tenant_id": command.tenant_id,
                    "task_id": command.task_id,
                    "summary": "onboarding",
                }
            ),
            media_type="text/markdown",
            content=content,
            result_digest=canonical_sha256(projection),
            citations=tuple(projection["citations"]),
        )
        receipt = await self._artifacts.save(draft)
        if receipt.result_ref is None:
            raise _OnboardingFailure("RUNTIME_RESULT_REFERENCE_MISSING")
        return receipt.result_ref

    async def _load_or_initialize(
        self,
        command: TaskCommand,
        lease: LeaseToken,
    ) -> GraphState:
        current = await self._checkpoints.load(command.tenant_id, command.task_id)
        if current is None:
            return GraphState(
                task_id=command.task_id,
                tenant_id=command.tenant_id,
                command_id=command.command_id,
                command_digest=command.command_digest,
                run_id=lease.run_id,
                run_generation=lease.run_generation,
                graph_version=self._config.graph_version,
                status=GraphStatus.QUEUED,
                node=GraphNode.START,
                security_context_ref=command.security_context.context_ref,
                security_context_hash=command.security_context.context_hash,
                purpose=command.security_context.purpose,
            )
        if current.graph_version != self._config.graph_version:
            raise GraphError(
                GraphErrorCode.VERSION_MIGRATION_REQUIRED,
                "onboarding checkpoint requires an explicit migration",
            )
        if (
            current.tenant_id != command.tenant_id
            or current.task_id != command.task_id
            or current.purpose != command.security_context.purpose
        ):
            raise GraphError(
                GraphErrorCode.SECURITY_BINDING_MISMATCH,
                "command does not match the onboarding checkpoint binding",
            )
        if (
            command.command_type is not CommandType.DECIDE_APPROVAL
            and (
                current.security_context_ref
                != command.security_context.context_ref
                or current.security_context_hash
                != command.security_context.context_hash
            )
        ):
            # An approval decision legitimately carries the approver's own
            # security context; the checkpoint keeps the requester's.
            raise GraphError(
                GraphErrorCode.SECURITY_BINDING_MISMATCH,
                "command does not match the onboarding checkpoint binding",
            )
        same_command = current.command_id == command.command_id
        if same_command and current.command_digest != command.command_digest:
            raise GraphError(
                GraphErrorCode.SECURITY_BINDING_MISMATCH,
                "replayed command does not match the onboarding checkpoint digest",
            )
        if current.status is GraphStatus.RUNNING and not same_command:
            raise GraphError(
                GraphErrorCode.COMMAND_MISMATCH,
                "an in-flight onboarding graph cannot switch commands",
            )
        if lease.run_generation < current.run_generation:
            raise GraphError(
                GraphErrorCode.LEASE_LOST,
                "worker lease generation is older than the onboarding checkpoint",
            )
        return replace(
            current,
            run_id=lease.run_id,
            run_generation=lease.run_generation,
        )

    async def _save(self, state: GraphState, lease: LeaseToken) -> GraphState:
        return await self._checkpoints.save(
            state,
            expected_sequence=state.checkpoint_sequence,
            lease=lease,
        )

    async def _has_graph_checkpoint(self, config: Mapping[str, Any]) -> bool:
        getter = getattr(self._checkpointer, "aget_tuple", None)
        if getter is None:
            return False
        return await getter(config) is not None

    @staticmethod
    def _validate_command(command: TaskCommand) -> None:
        if command.command_type not in {
            CommandType.CREATE,
            CommandType.SUBMIT_MESSAGE,
            CommandType.DECIDE_APPROVAL,
        }:
            raise GraphError(
                GraphErrorCode.COMMAND_UNSUPPORTED,
                "onboarding graph accepts create, submit-message and approval "
                "decision commands",
            )
        try:
            command.assert_digest()
            command.assert_security_binding()
        except DomainViolation as exc:
            raise GraphError(
                GraphErrorCode.SECURITY_BINDING_MISMATCH,
                "command failed deterministic onboarding security binding",
            ) from exc

    @staticmethod
    def _thread_id(command: TaskCommand) -> str:
        identity = f"{command.tenant_id}:{command.task_id}"
        return "onb-thread-" + hashlib.sha256(identity.encode()).hexdigest()[:12]

    @staticmethod
    def _opaque_task_ref(command: TaskCommand) -> str:
        suffix = hashlib.sha256(
            f"{command.tenant_id}:{command.task_id}".encode()
        ).hexdigest()[:20]
        return f"task://sha256/{suffix}"

    @staticmethod
    def _stable_id(prefix: str, value: str) -> str:
        return f"{prefix}_{hashlib.sha256(value.encode()).hexdigest()[:20]}"

    @staticmethod
    def _required_text(value: object) -> str:
        if not isinstance(value, str) or not value:
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "onboarding result is missing a required reference",
            )
        return value

    @staticmethod
    def _optional_text(value: object) -> str | None:
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _count(value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return 0
        return value

    @staticmethod
    def _invocation() -> _Invocation:
        invocation = _ACTIVE_INVOCATION.get()
        if invocation is None:
            raise GraphError(
                GraphErrorCode.STATE_INVALID,
                "onboarding node is outside an execution boundary",
            )
        return invocation


class _OnboardingNodes:
    def __init__(self, runtime: OnboardingCompositeGraph) -> None:
        self._runtime = runtime

    def as_graph_nodes(self) -> FlowPilotGraphNodes:
        return FlowPilotGraphNodes(
            prepare=self.prepare,
            build_context=self.build_context,
            route_request=self.route_request,
            route_after_request=self.route_after_request,
            clarification_interrupt=self.clarification_interrupt,
            knowledge_read=self.knowledge_read,
            service_read=self.service_read,
            permission_read=self.permission_read,
            join_reads=self.join_reads,
            handoff=self.handoff,
            approval_interrupt=self.approval_interrupt,
            run_agent=self.run_agent,
            route_result=self.route_result,
            route_after_result=self.route_after_result,
            retry=self.retry,
            compensate=self.compensate,
            finalize=self.finalize,
        )

    async def prepare(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        if state.get("recovery_restored") is True:
            # M5-2 recovery: keep the injected progress (completed read
            # branches, sub-action plan, per-sub-action execution progress)
            # and only re-assert the RUNNING status.  A fresh thread
            # checkpoint has no channel values for those keys; leaving them
            # untouched preserves the Checkpoint-restored progress.
            return self._advance(
                "prepare",
                {"status": GraphStatus.RUNNING.value},
            )
        return self._advance(
            "prepare",
            {
                "status": GraphStatus.RUNNING.value,
                "input_complete": False,
                "reads_complete": False,
                "writes_complete": False,
                "missing_fields": [],
                "reads": {},
                "read_facts": {},
                "read_failures": {},
                "sub_actions": [],
                "write_results": {},
                "ticket_refs": [],
                "conversation_round": 0,
                "cumulative_input_tokens": 0,
                "cumulative_output_tokens": 0,
            },
        )

    async def build_context(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        if state.get("recovery_restored") is True:
            # M5-2 recovery: intake fields and requester were restored from
            # the Checkpoint; never re-resolve the request (the resolver
            # may not serve approval-decision commands) and re-check the
            # field completeness against the restored fields.
            fields = dict(state.get("fields") or {})
            missing = self._missing_fields(fields)
            return self._advance(
                "build_context",
                {
                    "fields": fields,
                    "missing_fields": list(missing),
                    "input_complete": not missing,
                    "requester_id": str(state.get("requester_id") or ""),
                },
            )
        observation = await self._runtime._resolve()
        fields = dict(observation.fields)
        missing = self._missing_fields(fields)
        if missing:
            # Each clarification question is one model turn: charge it
            # against the hard cumulative budget before the interrupt asks
            # it (FP-CTX-004).  build_context runs exactly once per loop
            # pass, so rounds are never double-charged; exhaustion raises
            # and terminates the graph with a stable failure code.
            self._runtime._charge_clarification_round(
                observation,
                missing_fields=missing,
                round_index=self._runtime._ledger_accounting.round_count,
            )
        context = self._runtime._build_context(
            observation,
            task_state={
                "status": GraphStatus.RUNNING.value,
                "intent": observation.intent,
                "observation_ref": observation.observation_ref,
                "missing_fields": list(missing),
                "conversation_round": self._runtime._ledger_accounting.round_count,
            },
            context_kind="request",
        )
        requester_id = self._runtime._invocation().command.actor.id
        # M5-2 recovery: persist intake fields + original requester so a
        # crash-restart replay never re-resolves the request and the
        # approval separation-of-duties check keeps the ORIGINAL requester.
        await self._runtime._record_recovery_progress(
            node=GraphNode.BUILD_CONTEXT,
            recovery_fields=tuple(sorted(fields.items())),
            recovery_requester_id=requester_id,
        )
        return self._advance(
            "build_context",
            {
                "observation_ref": observation.observation_ref,
                # The requester is checkpointed at intake so approval-time
                # separation-of-duties checks compare against the original
                # requester, never the current (approver) command actor.
                "requester_id": requester_id,
                "fields": fields,
                "missing_fields": list(missing),
                "input_complete": not missing,
                "conversation_round": self._runtime._ledger_accounting.round_count,
                "cumulative_input_tokens": (
                    self._runtime._ledger_accounting.used_input_tokens
                ),
                "cumulative_output_tokens": (
                    self._runtime._ledger_accounting.used_output_tokens
                ),
                "context_id": context.context_id,
            },
        )

    def _missing_fields(self, fields: Mapping[str, str]) -> tuple[str, ...]:
        return tuple(
            field
            for field in self._runtime._config.required_fields
            if not isinstance(fields.get(field), str) or not fields.get(field)
        )

    async def route_request(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        if state.get("input_complete") is not True:
            return self._advance("route_request", {"route": "clarification"})
        if state.get("reads_complete") is not True:
            return self._advance("route_request", {"route": "parallel_reads"})
        failures = state.get("read_failures") or {}
        if failures:
            branch, code = sorted(failures.items())[0]
            return self._advance(
                "route_request",
                {
                    "route": "terminate",
                    "failure_code": f"READ_FAILED:{branch}:{code}",
                    "terminal_reason": "ONBOARDING_READ_FAILURE",
                },
            )
        if state.get("sub_actions") and state.get("approval_decision") is None:
            return self._advance("route_request", {"route": "approval"})
        if state.get("approval_decision") == "approved":
            return self._advance("route_request", {"route": "run_agent"})
        return self._advance(
            "route_request",
            {"route": "terminate", "failure_code": "RUNTIME_ROUTE_INVALID"},
        )

    @staticmethod
    def route_after_request(state: Mapping[str, Any]) -> str | Sequence[str]:
        route = state.get("route")
        if route == "parallel_reads":
            return ("knowledge_read", "service_read", "permission_read")
        if route in {"clarification", "approval", "run_agent", "terminate"}:
            return str(route)
        raise GraphError(GraphErrorCode.STATE_INVALID, "onboarding route is invalid")

    async def clarification_interrupt(
        self, state: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        observation = await self._runtime._resolve()
        missing = self._missing_fields(observation.fields)
        # The round was charged in build_context (exactly once per loop
        # pass); this node only pauses and re-checks after resume.
        card = {
            "schema": "flowpilot.onboarding-clarification.v1",
            "kind": "clarification",
            "observation_ref": observation.observation_ref,
            "required_fields": list(missing),
            # 0-based index of the question being asked.
            "conversation_round": max(
                0, self._runtime._ledger_accounting.round_count - 1
            ),
        }
        resume = state.get("resume_confirmed")
        if resume is not True:
            resume = interrupt(card)
        if not isinstance(resume, Mapping) or resume.get("confirmed") is not True:
            raise _OnboardingFailure("RUNTIME_CLARIFICATION_INVALID")
        refreshed = await self._runtime._resolve()
        missing = self._missing_fields(refreshed.fields)
        return self._advance(
            "clarification_interrupt",
            {
                "observation_ref": refreshed.observation_ref,
                "fields": dict(refreshed.fields),
                "missing_fields": list(missing),
                "input_complete": not missing,
                "conversation_round": self._runtime._ledger_accounting.round_count,
                "cumulative_input_tokens": (
                    self._runtime._ledger_accounting.used_input_tokens
                ),
                "cumulative_output_tokens": (
                    self._runtime._ledger_accounting.used_output_tokens
                ),
            },
        )

    async def knowledge_read(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        return await self._read_branch_state(
            state, "device_standard", "knowledge_read"
        )

    async def service_read(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        return await self._read_branch_state(state, "inventory", "service_read")

    async def permission_read(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        return await self._read_branch_state(
            state, "permission_template", "permission_read"
        )

    async def _read_branch_state(
        self,
        state: Mapping[str, Any],
        branch_id: str,
        node: str,
    ) -> Mapping[str, Any]:
        if state.get("input_complete") is not True:
            raise _OnboardingFailure("RUNTIME_CLARIFICATION_REQUIRED")
        branch = await self._runtime._read_branch(branch_id)
        entry: dict[str, Any] = {
            "branch_id": branch.branch_id,
            "facts": dict(branch.facts),
            "evidence_refs": list(branch.evidence_refs),
            "failure_code": branch.failure_code,
        }
        trace = self._runtime._branch_traces.get(branch_id)
        if trace is not None:
            entry.update(trace)
        reads = dict(state.get("reads") or {})
        reads[branch_id] = entry
        return self._advance(node, {"reads": reads}, record_current=False)

    async def join_reads(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        raw = state.get("reads") or {}
        if set(raw) != {
            "device_standard",
            "inventory",
            "permission_template",
        }:
            raise GraphError(
                GraphErrorCode.PARALLEL_REDUCER_CONFLICT,
                "onboarding read branches did not converge",
            )
        branches = tuple(
            BranchResult(
                branch_id=item["branch_id"],
                facts=dict(item.get("facts") or {}),
                evidence_refs=tuple(item.get("evidence_refs") or ()),
                failure_code=item.get("failure_code"),
            )
            for item in (raw[key] for key in sorted(raw))
        )
        reduced = reduce_parallel(branches)
        if not reduced.failures:
            # M5-2 recovery: persist the completed read-branch marks and
            # the reduced facts so a crash restart skips the three read
            # branches (the graph can re-plan sub-actions from the facts).
            await self._runtime._record_recovery_progress(
                node=GraphNode.SERVICE_READ,
                completed_read_branches=(
                    "device_standard",
                    "inventory",
                    "permission_template",
                ),
                read_facts=tuple(sorted(dict(reduced.facts).items())),
            )
        return self._advance(
            "join_reads",
            {
                "reads_complete": True,
                "read_facts": dict(reduced.facts),
                "read_failures": dict(reduced.failures),
            },
        )

    async def handoff(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        """M5-1 sub-action planner: two PlannedAction writes for this task."""
        failures = state.get("read_failures") or {}
        if failures:
            # A read branch failed: no plan can be grounded on partial
            # facts.  Record the localized failure and let route_request
            # terminate (never a fake COMPLETED).
            branch, code = sorted(failures.items())[0]
            return self._advance(
                "handoff",
                {
                    "failure_code": f"READ_FAILED:{branch}:{code}",
                    "terminal_reason": "ONBOARDING_READ_FAILURE",
                },
            )
        facts = state.get("read_facts") or {}
        fields = state.get("fields") or {}
        required = {"full_name", "department", "manager", "location", "start_date"}
        if not required <= set(fields):
            raise _OnboardingFailure("RUNTIME_ONBOARDING_FIELDS_INCOMPLETE")
        sub_actions = _plan_sub_actions(
            config=self._runtime._config,
            command=self._runtime._invocation().command,
            fields=fields,
            facts=facts,
            clock=self._runtime._clock,
        )
        # M5-2 recovery: persist the deterministic sub-action plan so a
        # crash restart re-routes to the approval interrupt instead of
        # re-planning (and never re-running the read branches).
        await self._runtime._record_recovery_progress(
            node=GraphNode.RUN_AGENT,
            sub_action_plan=tuple(sub_actions),
        )
        return self._advance(
            "handoff",
            {
                "sub_actions": sub_actions,
                "permission_approval_id": next(
                    item["approval_id"]
                    for item in sub_actions
                    if item.get("approval_id")
                ),
            },
        )

    async def approval_interrupt(
        self, state: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        sub_actions = state.get("sub_actions") or []
        permission = next(
            (item for item in sub_actions if item.get("approval_id")), None
        )
        if permission is None:
            raise _OnboardingFailure("RUNTIME_APPROVAL_PROPOSAL_MISSING")
        card = build_onboarding_approval_card(permission)
        # M5-2 recovery: when the control-plane thread checkpoint was lost
        # (process crash) execute() feeds the approval decision from the
        # DECIDE_APPROVAL command; every validation below still runs, so a
        # revoked / expired / tampered approval is rejected on recovery.
        decision = state.get("resume_decision")
        if decision is None:
            decision = interrupt(card)
        if not isinstance(decision, Mapping):
            raise _OnboardingFailure("RUNTIME_APPROVAL_DECISION_INVALID")
        if (
            decision.get("approval_id") != permission["approval_id"]
            or decision.get("action_digest") != permission["action_digest"]
        ):
            raise _OnboardingFailure("RUNTIME_APPROVAL_BINDING_MISMATCH")
        if decision.get("decision") != "approved":
            raise _OnboardingFailure("RUNTIME_APPROVAL_DECLINED")
        approver_id = str(decision.get("approver_id") or "")
        requester_id = str(state.get("requester_id") or "")
        if not approver_id or not requester_id or approver_id == requester_id:
            raise _OnboardingFailure("RUNTIME_APPROVAL_DUTIES_VIOLATION")
        manager = str(state.get("fields", {}).get("manager") or "")
        if approver_id != manager:
            raise _OnboardingFailure("RUNTIME_APPROVAL_NOT_MANAGER")
        await self._assert_approval_active(
            str(permission["approval_id"]),
            str(permission["action_digest"]),
        )
        return self._advance(
            "approval_interrupt",
            {
                "approval_decision": "approved",
                "permission_approval_id": permission["approval_id"],
            },
        )

    async def _assert_approval_active(
        self, approval_id: str, action_digest: str
    ) -> None:
        source = self._runtime._approvals
        if source is None:
            return
        try:
            approval = await source.resolve(approval_id)
        except Exception as exc:
            raise _OnboardingFailure("RUNTIME_APPROVAL_UNAVAILABLE") from exc
        if (
            approval.approval_id != approval_id
            or approval.action_digest != action_digest
            or approval.status is not ApprovalStatus.APPROVED
            or self._runtime._clock().astimezone(UTC) >= approval.expires_at
        ):
            raise _OnboardingFailure("RUNTIME_APPROVAL_INVALID")

    async def run_agent(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        sub_actions = state.get("sub_actions") or []
        if not sub_actions or state.get("approval_decision") != "approved":
            raise _OnboardingFailure("RUNTIME_APPROVAL_REQUIRED")
        write_results = dict(state.get("write_results") or {})
        ticket_refs = list(state.get("ticket_refs") or [])
        failure: str | None = state.get("write_failure")

        for sub_action in sub_actions:
            action_id = sub_action["action_id"]
            existing = write_results.get(action_id)
            if existing and existing.get("status") == "verified":
                # Already-succeeded sub-actions are never re-executed
                # (also across a crash restart: the progress Checkpoint
                # carries them, M5-2).
                continue
            if existing and existing.get("status") in (
                "failed_final",
                "failed_retryable",
            ):
                failure = str(existing.get("failure_code") or "WRITE_FAILED")
                break
            outcome = await self._runtime._execute_write(sub_action)
            write_results[action_id] = outcome
            # M5-2 recovery: persist per-sub-action progress before the
            # next action so a crash between sub-actions resumes from the
            # last verified action instead of replaying it.
            await self._runtime._record_recovery_progress(
                node=GraphNode.RUN_AGENT,
                sub_action_progress=tuple(write_results.values()),
            )
            if outcome["status"] != "verified":
                failure = str(outcome["failure_code"])
                break

        if failure is None:
            existing_ticket = write_results.get("ticket")
            if (
                existing_ticket is not None
                and existing_ticket.get("status") == "verified"
            ):
                # M5-2 recovery: the related ticket was already created and
                # verified before the crash; never re-execute it.
                ticket_outcome = existing_ticket
            else:
                ticket_outcome = await self._runtime._execute_write(
                    _plan_ticket_action(
                        config=self._runtime._config,
                        command=self._runtime._invocation().command,
                        state=state,
                        write_results=write_results,
                        clock=self._runtime._clock,
                    )
                )
                write_results["ticket"] = ticket_outcome
            ticket_id = None
            if ticket_outcome["status"] == "verified":
                data = ticket_outcome.get("data") or {}
                candidate = data.get("ticket_id")
                if isinstance(candidate, str) and candidate:
                    ticket_id = candidate
            if ticket_outcome["status"] != "verified" or ticket_id is None:
                failure = str(
                    ticket_outcome.get("failure_code") or "WRITE_FAILED"
                )
            else:
                ticket_ref = (
                    f"ticket://{self._runtime._invocation().command.tenant_id}/"
                    f"{ticket_id}"
                )
                if ticket_ref not in ticket_refs:
                    ticket_refs.append(ticket_ref)
            await self._runtime._record_recovery_progress(
                node=GraphNode.RUN_AGENT,
                sub_action_progress=tuple(write_results.values()),
            )

        update: dict[str, Any] = {
            "write_results": write_results,
            "ticket_refs": ticket_refs,
        }
        if failure is not None:
            update["write_failure"] = failure
            update["terminal_reason"] = "ONBOARDING_PARTIAL_FAILURE"
            update["runtime_outcome"] = "partial_failure"
            update["failure_code"] = failure
        else:
            update["writes_complete"] = True
            update["terminal_reason"] = "ONBOARDING_COMPOSITE_COMPLETED"
            update["runtime_outcome"] = "completed"
        result_ref = await self._runtime._save_summary(
            {**state, **update},
            tickets=ticket_refs,
        )
        update["result_ref"] = result_ref
        return self._advance("run_agent", update)

    async def route_result(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        if state.get("runtime_outcome") == "completed":
            if (
                state.get("writes_complete") is not True
                or not state.get("result_ref")
            ):
                raise _OnboardingFailure("RUNTIME_WRITE_RESULT_MISSING")
            return self._advance("route_result", {"route": "finalize"})
        if state.get("runtime_outcome") == "partial_failure":
            if not state.get("failure_code"):
                raise _OnboardingFailure("RUNTIME_WRITE_RESULT_MISSING")
            return self._advance("route_result", {"route": "finalize"})
        raise _OnboardingFailure("RUNTIME_WRITE_RESULT_MISSING")

    @staticmethod
    def route_after_result(state: Mapping[str, Any]) -> str | Sequence[str]:
        if state.get("route") == "finalize":
            return "finalize"
        raise GraphError(
            GraphErrorCode.STATE_INVALID, "onboarding result route is invalid"
        )

    async def retry(self, _state: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._advance("retry", {})

    async def compensate(self, _state: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._advance("compensate", {})

    async def finalize(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        failure_code = state.get("failure_code")
        if failure_code:
            return self._advance(
                "finalize",
                {
                    "status": GraphStatus.FAILED.value,
                    "failure_code": str(failure_code),
                },
            )
        return self._advance(
            "finalize",
            {
                "status": GraphStatus.COMPLETED.value,
                "failure_code": None,
            },
        )

    @staticmethod
    def _advance(
        node: str,
        update: Mapping[str, Any],
        *,
        record_current: bool = True,
    ) -> Mapping[str, Any]:
        result = {**update, "visited_nodes": [node]}
        if record_current:
            result["current_node"] = node
        return result


def _plan_sub_actions(
    *,
    config: OnboardingGraphConfig,
    command: TaskCommand,
    fields: Mapping[str, str],
    facts: Mapping[str, Any],
    clock: Callable[[], datetime],
) -> list[dict[str, Any]]:
    """M5-1 sub-action plan: device allocation + permission grant.

    Both actions belong to the same task but carry distinct idempotency
    keys (the tool name participates in the key), satisfying the
    AC-E2E-002 determinism assertion.
    """
    expires_at = min(
        command.issued_at + timedelta(minutes=30),
        command.security_context.expires_at,
    )
    employee = fields["full_name"]
    department = fields["department"]
    location = fields["location"]
    start_date = fields["start_date"]
    device_standard = facts.get("device_standard") or {}
    inventory = facts.get("inventory") or {}
    permission_template = facts.get("permission_template") or {}
    model = str(device_standard.get("model") or "UNKNOWN-MODEL")
    stock_id = str(inventory.get("stock_id") or "UNKNOWN-STOCK")
    template_id = str(permission_template.get("template_id") or "UNKNOWN-TEMPLATE")

    device_action = PlannedAction(
        action_id=_stable_id(
            "act",
            f"{command.tenant_id}:{command.task_id}:{DEVICE_ALLOCATE_TOOL}",
        ),
        tenant_id=command.tenant_id,
        task_id=command.task_id,
        requester_id=command.actor.id,
        agent=ActionAgent(id=config.agent_id, version=config.agent_version),
        tool=ActionTool(
            name=DEVICE_ALLOCATE_TOOL,
            schema_hash=DEVICE_ALLOCATE_SCHEMA_PIN,
            operation=ToolOperation.WRITE,
        ),
        arguments={
            "employee": employee,
            "department": department,
            "location": location,
            "start_date": start_date,
            "model": model,
            "stock_id": stock_id,
        },
        resource=ActionResource(type="device_assignment"),
        purpose=command.security_context.purpose,
        data_classification=DataClassification.INTERNAL,
        policy_version=config.policy_version,
        expires_at=expires_at,
    )
    permission_action = PlannedAction(
        action_id=_stable_id(
            "act",
            f"{command.tenant_id}:{command.task_id}:{PERMISSION_GRANT_TOOL}",
        ),
        tenant_id=command.tenant_id,
        task_id=command.task_id,
        requester_id=command.actor.id,
        agent=ActionAgent(id=config.agent_id, version=config.agent_version),
        tool=ActionTool(
            name=PERMISSION_GRANT_TOOL,
            schema_hash=PERMISSION_GRANT_SCHEMA_PIN,
            operation=ToolOperation.WRITE,
        ),
        arguments={
            "employee": employee,
            "department": department,
            "location": location,
            "template_id": template_id,
        },
        resource=ActionResource(type="permission_assignment"),
        purpose=command.security_context.purpose,
        data_classification=DataClassification.INTERNAL,
        policy_version=config.policy_version,
        expires_at=expires_at,
    )
    permission_digest = permission_action.digest()
    return [
        _sub_action_mapping(
            device_action,
            idempotency_key=canonical_sha256(
                {
                    "tenant_id": command.tenant_id,
                    "task_id": command.task_id,
                    "tool": DEVICE_ALLOCATE_TOOL,
                }
            ),
            approval_id=None,
        ),
        _sub_action_mapping(
            permission_action,
            idempotency_key=canonical_sha256(
                {
                    "tenant_id": command.tenant_id,
                    "task_id": command.task_id,
                    "tool": PERMISSION_GRANT_TOOL,
                }
            ),
            approval_id=_stable_id(
                "apr",
                f"{command.tenant_id}:{command.task_id}:{permission_digest}",
            ),
        ),
    ]


def _sub_action_mapping(
    action: PlannedAction,
    *,
    idempotency_key: str,
    approval_id: str | None,
) -> dict[str, Any]:
    return {
        "action_id": action.action_id,
        "approval_id": approval_id,
        "action_digest": action.digest(),
        "requester_id": action.requester_id,
        "policy_decision_id": _stable_id(
            "pd", f"{action.tenant_id}:{action.task_id}:{action.digest()}"
        ),
        "tool": action.tool.name,
        "tool_schema_hash": action.tool.schema_hash,
        "operation": action.tool.operation.value,
        "arguments": dict(action.arguments),
        "resource": action.resource.to_mapping(),
        "purpose": action.purpose,
        "data_classification": action.data_classification.value,
        "policy_version": action.policy_version,
        "idempotency_key": idempotency_key,
        "expires_at": action.expires_at.isoformat().replace("+00:00", "Z"),
    }


def _plan_ticket_action(
    *,
    config: OnboardingGraphConfig,
    command: TaskCommand,
    state: Mapping[str, Any],
    write_results: Mapping[str, Mapping[str, Any]],
    clock: Callable[[], datetime],
) -> dict[str, Any]:
    fields = state.get("fields") or {}
    ticket_id = _ticket_id(command.tenant_id, command.task_id)
    action = PlannedAction(
        action_id=_stable_id(
            "act",
            f"{command.tenant_id}:{command.task_id}:{TICKET_CREATE_TOOL}",
        ),
        tenant_id=command.tenant_id,
        task_id=command.task_id,
        requester_id=command.actor.id,
        agent=ActionAgent(id=config.agent_id, version=config.agent_version),
        tool=ActionTool(
            name=TICKET_CREATE_TOOL,
            schema_hash=TICKET_CREATE_SCHEMA_PIN,
            operation=ToolOperation.WRITE,
        ),
        arguments={
            "ticket_id": ticket_id,
            "title": (
                f"Onboarding provisioning - {fields.get('full_name', '')} "
                f"({fields.get('department', '')})"
            ),
            "requester": command.actor.id,
            "location": fields.get("location", ""),
            "start_date": fields.get("start_date", ""),
        },
        resource=ActionResource(type="ticket", id=ticket_id),
        purpose=command.security_context.purpose,
        data_classification=DataClassification.INTERNAL,
        policy_version=config.policy_version,
        expires_at=min(
            command.issued_at + timedelta(minutes=30),
            command.security_context.expires_at,
        ),
    )
    return _sub_action_mapping(
        action,
        idempotency_key=canonical_sha256(
            {
                "tenant_id": command.tenant_id,
                "task_id": command.task_id,
                "tool": TICKET_CREATE_TOOL,
            }
        ),
        approval_id=None,
    )


def _ticket_id(tenant_id: str, task_id: str) -> str:
    suffix = hashlib.sha256(f"{tenant_id}:{task_id}".encode()).hexdigest()[:10]
    return f"TCK-{suffix.upper()}"


def build_onboarding_approval_card(sub_action: Mapping[str, Any]) -> dict[str, Any]:
    """FP-APR-001 approval card contract for the permission sub-action."""
    return {
        "schema": "flowpilot.onboarding-approval.v1",
        "kind": "approval",
        "approval_id": sub_action["approval_id"],
        "action_id": sub_action["action_id"],
        "action_digest": sub_action["action_digest"],
        "tool": sub_action["tool"],
        "operation": sub_action["operation"],
        "impact": {
            "resource": sub_action["resource"],
            "purpose": sub_action["purpose"],
        },
        "arguments": sub_action["arguments"],
        "basis": {
            "policy_version": sub_action["policy_version"],
            "policy_decision_id": sub_action["policy_decision_id"],
        },
        "expires_at": sub_action["expires_at"],
    }


def build_onboarding_read_call(
    *,
    config: OnboardingGraphConfig,
    command: TaskCommand,
    observation: OnboardingObservation,
    branch_id: str,
    run_id: str | None = None,
) -> OnboardingGatewayCall:
    """Stable tenant-bound read call for one of the three parallel branches."""
    tool_names = {
        "device_standard": DEVICE_STANDARD_TOOL,
        "inventory": INVENTORY_TOOL,
        "permission_template": PERMISSION_TEMPLATE_TOOL,
    }
    schema_pins = {
        "device_standard": DEVICE_STANDARD_SCHEMA_PIN,
        "inventory": INVENTORY_SCHEMA_PIN,
        "permission_template": PERMISSION_TEMPLATE_SCHEMA_PIN,
    }
    if branch_id not in tool_names:
        raise _OnboardingFailure("RUNTIME_READ_BRANCH_UNKNOWN")
    if (
        observation.tenant_id != command.tenant_id
        or observation.task_id != command.task_id
    ):
        raise _OnboardingFailure("RUNTIME_OBSERVATION_BINDING_MISMATCH")
    department = observation.fields.get("department")
    location = observation.fields.get("location")
    for value in (department, location):
        if not isinstance(value, str) or _SAFE_FIELD.fullmatch(value) is None:
            raise _OnboardingFailure("RUNTIME_OBSERVATION_FIELD_INVALID")
    arguments = {
        "department": department,
        "location": location,
        "branch": branch_id,
    }
    action = PlannedAction(
        action_id=_stable_id(
            "act",
            f"{command.tenant_id}:{command.task_id}:{tool_names[branch_id]}",
        ),
        tenant_id=command.tenant_id,
        task_id=command.task_id,
        requester_id=command.actor.id,
        agent=ActionAgent(id=config.agent_id, version=config.agent_version),
        tool=ActionTool(
            name=tool_names[branch_id],
            schema_hash=schema_pins[branch_id],
            operation=ToolOperation.READ,
        ),
        arguments=arguments,
        resource=ActionResource(type="catalog", id=branch_id),
        purpose=command.security_context.purpose,
        data_classification=DataClassification.INTERNAL,
        policy_version=config.policy_version,
        expires_at=min(
            command.issued_at + timedelta(minutes=15),
            command.security_context.expires_at,
        ),
    )
    action_digest = action.digest()
    return OnboardingGatewayCall(
        request_id=_stable_id(
            "treq",
            f"{command.tenant_id}:{command.task_id}:{branch_id}:{observation.source_digest}",
        ),
        operation=ToolOperation.READ,
        action=action,
        action_digest=action_digest,
        policy_decision_id=_stable_id(
            "pd",
            f"{command.tenant_id}:{command.task_id}:{action_digest}",
        ),
        idempotency_key=canonical_sha256(
            {
                "tenant_id": command.tenant_id,
                "task_id": command.task_id,
                "tool": tool_names[branch_id],
                "branch": branch_id,
                "source_digest": observation.source_digest,
            }
        ),
        trace_id=hashlib.sha256(
            (command.correlation_id or command.command_id).encode()
        ).hexdigest(),
        requested_at=command.issued_at,
    )


def build_onboarding_write_call(
    *,
    config: OnboardingGraphConfig,
    command: TaskCommand,
    sub_action: Mapping[str, Any],
    run_id: str | None = None,
    reconcile: bool = False,
) -> OnboardingGatewayCall:
    """Rebuild the exact approved action digest and bind the write request."""
    action = PlannedAction(
        action_id=str(sub_action["action_id"]),
        tenant_id=command.tenant_id,
        task_id=command.task_id,
        requester_id=str(sub_action["requester_id"]),
        agent=ActionAgent(id=config.agent_id, version=config.agent_version),
        tool=ActionTool(
            name=str(sub_action["tool"]),
            schema_hash=str(sub_action["tool_schema_hash"]),
            operation=ToolOperation.WRITE,
        ),
        arguments=dict(sub_action["arguments"]),
        resource=ActionResource(
            type=str(sub_action["resource"]["type"]),
            id=sub_action["resource"].get("id"),
        ),
        purpose=str(sub_action["purpose"]),
        data_classification=DataClassification(
            str(sub_action["data_classification"])
        ),
        policy_version=str(sub_action["policy_version"]),
        expires_at=datetime.fromisoformat(
            str(sub_action["expires_at"]).replace("Z", "+00:00")
        ),
    )
    action_digest = action.digest()
    if action_digest != sub_action["action_digest"]:
        raise _OnboardingFailure("RUNTIME_APPROVAL_BINDING_MISMATCH")
    return OnboardingGatewayCall(
        request_id=_stable_id(
            "treq",
            f"{command.tenant_id}:{command.task_id}:{action_digest}:"
            f"{'reconcile' if reconcile else 'write'}",
        ),
        operation=ToolOperation.WRITE,
        action=action,
        action_digest=action_digest,
        policy_decision_id=str(sub_action["policy_decision_id"]),
        idempotency_key=str(sub_action["idempotency_key"]),
        approval_id=sub_action.get("approval_id"),
        reconcile=reconcile,
        trace_id=hashlib.sha256(
            (command.correlation_id or command.command_id).encode()
        ).hexdigest(),
        requested_at=command.issued_at,
    )


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}_{hashlib.sha256(value.encode()).hexdigest()[:20]}"


__all__ = [
    "DEVICE_ALLOCATE_SCHEMA_PIN",
    "DEVICE_ALLOCATE_TOOL",
    "DEVICE_STANDARD_SCHEMA_PIN",
    "DEVICE_STANDARD_TOOL",
    "INVENTORY_SCHEMA_PIN",
    "INVENTORY_TOOL",
    "ONBOARDING_AGENT_ID",
    "ONBOARDING_AGENT_PRINCIPAL",
    "ONBOARDING_AGENT_VERSION",
    "ONBOARDING_GRAPH_VERSION",
    "ONBOARDING_REQUIRED_FIELDS",
    "PERMISSION_GRANT_SCHEMA_PIN",
    "PERMISSION_GRANT_TOOL",
    "PERMISSION_TEMPLATE_SCHEMA_PIN",
    "PERMISSION_TEMPLATE_TOOL",
    "TICKET_CREATE_SCHEMA_PIN",
    "TICKET_CREATE_TOOL",
    "OnboardingArtifactDraft",
    "OnboardingArtifactPort",
    "OnboardingArtifactReceipt",
    "OnboardingApprovalSourcePort",
    "OnboardingCompositeGraph",
    "OnboardingGatewayCall",
    "OnboardingGatewayPort",
    "OnboardingGraphConfig",
    "OnboardingGraphState",
    "OnboardingLedgerEntry",
    "OnboardingLedgerPort",
    "OnboardingLedgerStatus",
    "OnboardingObservation",
    "OnboardingResolverPort",
    "OnboardingResultStatus",
    "OnboardingToolResult",
    "build_onboarding_approval_card",
    "build_onboarding_read_call",
    "build_onboarding_write_call",
    "plan_onboarding_sub_actions",
]


def plan_onboarding_sub_actions(
    *,
    config: OnboardingGraphConfig,
    command: TaskCommand,
    fields: Mapping[str, str],
    facts: Mapping[str, Any],
    clock: Callable[[], datetime] | None = None,
) -> list[dict[str, Any]]:
    """Public alias for the deterministic sub-action planner."""
    return _plan_sub_actions(
        config=config,
        command=command,
        fields=fields,
        facts=facts,
        clock=clock or (lambda: datetime.now(UTC)),
    )
