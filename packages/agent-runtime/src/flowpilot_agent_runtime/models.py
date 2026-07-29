from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from flowpilot_context import ContextEnvelope
from flowpilot_domain import SecurityContextRef


class AgentMode(StrEnum):
    STRUCTURED = "structured"
    BOUNDED_AGENT_LOOP = "bounded_agent_loop"


class ToolOperation(StrEnum):
    READ = "read"
    PROPOSE_WRITE = "propose_write"


class RunStatus(StrEnum):
    COMPLETED = "completed"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_FINAL = "failed_final"
    BUDGET_EXHAUSTED = "budget_exhausted"
    GUARDRAIL_BLOCKED = "guardrail_blocked"


class RuntimeErrorCode(StrEnum):
    PROVIDER_UNAVAILABLE = "RUNTIME_PROVIDER_UNAVAILABLE"
    REQUEST_INCONSISTENT = "RUNTIME_REQUEST_INCONSISTENT"
    INVALID_OUTPUT = "RUNTIME_INVALID_OUTPUT"
    BUDGET_EXHAUSTED = "RUNTIME_BUDGET_EXHAUSTED"
    GUARDRAIL_BLOCKED = "RUNTIME_GUARDRAIL_BLOCKED"
    TOOL_SCOPE_VIOLATION = "RUNTIME_TOOL_SCOPE_VIOLATION"
    DATA_POLICY_DENIED = "RUNTIME_DATA_POLICY_DENIED"
    INTERNAL = "RUNTIME_INTERNAL"


@dataclass(frozen=True, slots=True)
class OutputSchemaRef:
    id: str
    hash: str


@dataclass(frozen=True, slots=True)
class AllowedTool:
    name: str
    schema_hash: str
    operation: ToolOperation


@dataclass(frozen=True, slots=True)
class AgentProfile:
    id: str
    version: str
    prompt_version: str
    mode: AgentMode
    output_schema: OutputSchemaRef
    allowed_tools: tuple[AllowedTool, ...]
    maximum_handoffs: int

    def __post_init__(self) -> None:
        identities = [
            (item.name, item.schema_hash, item.operation) for item in self.allowed_tools
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("allowed tools must be unique")
        if not 0 <= self.maximum_handoffs <= 4:
            raise ValueError("maximum_handoffs is outside the v1 contract")


@dataclass(frozen=True, slots=True)
class ProviderSelection:
    provider: str
    model: str
    data_policy_id: str
    routing_reason_code: str


@dataclass(frozen=True, slots=True)
class RuntimeBudget:
    maximum_turns: int
    maximum_tool_calls: int
    maximum_input_tokens: int
    maximum_output_tokens: int
    maximum_total_tokens: int
    maximum_cost_microunits: int
    timeout_ms: int

    def __post_init__(self) -> None:
        if (
            self.maximum_turns < 1
            or self.maximum_tool_calls < 0
            or self.maximum_input_tokens < 1
            or self.maximum_output_tokens < 1
            or self.maximum_total_tokens < 2
            or self.maximum_cost_microunits < 0
            or not 1 <= self.timeout_ms <= 3_600_000
        ):
            raise ValueError("runtime budget is outside the v1 contract")


@dataclass(frozen=True, slots=True)
class AgentRunRequest:
    request_id: str
    task_id: str
    tenant_id: str
    trace_id: str
    run_id: str
    agent: AgentProfile
    context: ContextEnvelope
    security_context: SecurityContextRef
    provider_selection: ProviderSelection
    budget: RuntimeBudget
    session_ref: str | None
    issued_at: datetime


@dataclass(frozen=True, slots=True)
class ToolProposal:
    proposal_id: str
    tool: str
    operation: ToolOperation
    arguments: Mapping[str, Any]
    resource: Mapping[str, Any]
    purpose: str
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("tool proposal evidence references must be unique")


@dataclass(frozen=True, slots=True)
class HandoffProposal:
    target_agent_id: str
    reason_code: str
    context_id: str


@dataclass(frozen=True, slots=True)
class RuntimeUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    tool_calls: int = 0
    turns: int = 0
    cost_microunits: int = 0
    elapsed_ms: int = 0

    def __post_init__(self) -> None:
        if any(
            value < 0
            for value in (
                self.input_tokens,
                self.output_tokens,
                self.total_tokens,
                self.tool_calls,
                self.turns,
                self.cost_microunits,
                self.elapsed_ms,
            )
        ):
            raise ValueError("runtime usage cannot be negative")


@dataclass(frozen=True, slots=True)
class RuntimeFailure:
    code: RuntimeErrorCode
    retryable: bool
    detail_ref: str | None = None


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    result_id: str
    request_id: str
    status: RunStatus
    trace_id: str
    provider_name: str
    provider_model: str
    structured_output: Mapping[str, Any] | None
    public_reasoning_summary: str | None
    tool_proposals: tuple[ToolProposal, ...] = ()
    tool_call_refs: tuple[str, ...] = ()
    handoff_proposal: HandoffProposal | None = None
    session_ref: str | None = None
    provider_run_ref: str | None = None
    usage: RuntimeUsage = field(default_factory=RuntimeUsage)
    error: RuntimeFailure | None = None
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.status is RunStatus.COMPLETED:
            if self.structured_output is None or self.error is not None:
                raise ValueError(
                    "completed runtime results require output and no error"
                )
        elif self.structured_output is not None or self.error is None:
            raise ValueError("failed runtime results require an error and no output")
        if self.status is RunStatus.FAILED_RETRYABLE:
            if (
                self.error is None
                or not self.error.retryable
                or self.error.code is not RuntimeErrorCode.PROVIDER_UNAVAILABLE
            ):
                raise ValueError("retryable runtime result has an invalid error")
        elif self.error is not None and self.error.retryable:
            raise ValueError("only failed_retryable may be marked retryable")
        expected_error = {
            RunStatus.BUDGET_EXHAUSTED: RuntimeErrorCode.BUDGET_EXHAUSTED,
            RunStatus.GUARDRAIL_BLOCKED: RuntimeErrorCode.GUARDRAIL_BLOCKED,
        }.get(self.status)
        if (
            expected_error is not None
            and self.error is not None
            and self.error.code is not expected_error
        ):
            raise ValueError("runtime status and error code do not match")
        if len(self.tool_call_refs) != len(set(self.tool_call_refs)):
            raise ValueError("tool call references must be unique")
