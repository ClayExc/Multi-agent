"""Deterministic sandbox adapter implementing AgentRuntimePort.

``SandboxAdapter`` is the offline reference implementation of the runtime
port: it validates request binding with the shared ``validation.py`` rules,
drives the model gateway through ``ModelGatewayPort`` (the only runtime
boundary), maps every gateway error onto the stable runtime error codes and
meters usage exactly from the provider wire response.  Provider online or
offline, every deterministic acceptance path stays green.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime

from flowpilot_model_gateway import (
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelGatewayPort,
    ModelRequest,
    ModelResult,
    ModelTask,
    ProviderToolProposal,
    WireToolOperation,
)

from .models import (
    AgentRunRequest,
    AgentRunResult,
    RunStatus,
    RuntimeErrorCode,
    RuntimeFailure,
    RuntimeUsage,
    ToolOperation,
    ToolProposal,
)
from .validation import (
    RequestConsistencyError,
    ToolScopeError,
    usage_exceeds_budget,
    validate_request,
    validate_tool_proposals,
)

# The v1 agent-run contract carries no model-task discriminator; the sandbox
# adapter fixes the runtime call shape to the summarize task so every request
# is deterministic at the wire level.
_SANDBOX_MODEL_TASK = ModelTask.SUMMARIZE


class SandboxAdapter:
    """AgentRuntimePort implementation backed by a ModelGatewayPort."""

    def __init__(
        self,
        gateway: ModelGatewayPort,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._gateway = gateway
        self._clock = clock or (lambda: datetime.now(UTC))
        self.calls: list[AgentRunRequest] = []

    async def run(self, request: AgentRunRequest) -> AgentRunResult:
        self.calls.append(request)
        call_number = len(self.calls)
        now = self._clock().astimezone(UTC)
        try:
            validate_request(request, now=now)
        except RequestConsistencyError:
            return self._failure(
                request,
                call_number,
                status=RunStatus.FAILED_FINAL,
                code=RuntimeErrorCode.REQUEST_INCONSISTENT,
                retryable=False,
                now=now,
            )
        model_request = ModelRequest(
            request_id=request.request_id,
            task_id=request.task_id,
            tenant_id=request.tenant_id,
            task=_SANDBOX_MODEL_TASK,
            payload={
                "agent_id": request.agent.id,
                "purpose": request.context.purpose,
            },
            data_classification=request.security_context.data_classification_ceiling,
            provider_allowlist=request.context.policy.provider_allowlist,
            maximum_input_tokens=request.budget.maximum_input_tokens,
            maximum_output_tokens=request.budget.maximum_output_tokens,
        )
        try:
            model_result = await self._gateway.complete(model_request)
        except ModelGatewayError as exc:
            return self._map_gateway_error(request, call_number, exc, now)
        usage = self._meter(model_result)
        if usage_exceeds_budget(request, usage):
            return self._failure(
                request,
                call_number,
                status=RunStatus.BUDGET_EXHAUSTED,
                code=RuntimeErrorCode.BUDGET_EXHAUSTED,
                retryable=False,
                now=now,
                usage=usage,
            )
        proposals = tuple(
            _runtime_proposal(proposal) for proposal in model_result.tool_proposals
        )
        try:
            validate_tool_proposals(request, proposals)
        except ToolScopeError:
            return self._failure(
                request,
                call_number,
                status=RunStatus.FAILED_FINAL,
                code=RuntimeErrorCode.TOOL_SCOPE_VIOLATION,
                retryable=False,
                now=now,
                usage=usage,
            )
        return AgentRunResult(
            result_id=self._result_id(request.request_id, call_number),
            request_id=request.request_id,
            status=RunStatus.COMPLETED,
            trace_id=request.trace_id,
            provider_name=model_result.provider,
            provider_model=model_result.model,
            structured_output=dict(model_result.output),
            public_reasoning_summary=(
                f"Sandbox provider {model_result.provider}/{model_result.model} "
                "completed deterministically."
            ),
            tool_proposals=proposals,
            provider_run_ref=(
                f"provider-run://{model_result.provider}/{model_result.result_id}"
            ),
            usage=usage,
            completed_at=now,
        )

    def _map_gateway_error(
        self,
        request: AgentRunRequest,
        call_number: int,
        exc: ModelGatewayError,
        now: datetime,
    ) -> AgentRunResult:
        if exc.code is ModelGatewayErrorCode.PROVIDER_UNAVAILABLE:
            # The one retryable runtime error; everything else is final.
            return self._failure(
                request,
                call_number,
                status=RunStatus.FAILED_RETRYABLE,
                code=RuntimeErrorCode.PROVIDER_UNAVAILABLE,
                retryable=True,
                now=now,
            )
        if exc.code is ModelGatewayErrorCode.BUDGET_EXHAUSTED:
            return self._failure(
                request,
                call_number,
                status=RunStatus.BUDGET_EXHAUSTED,
                code=RuntimeErrorCode.BUDGET_EXHAUSTED,
                retryable=False,
                now=now,
            )
        if exc.code is ModelGatewayErrorCode.INVALID_OUTPUT:
            return self._failure(
                request,
                call_number,
                status=RunStatus.FAILED_FINAL,
                code=RuntimeErrorCode.INVALID_OUTPUT,
                retryable=False,
                now=now,
            )
        # ROUTE_DENIED: the request's allowlist/classification matched no
        # approved route.  The request itself was consistent (validated
        # above), so this is a runtime routing configuration failure and maps
        # to the stable final internal code with a diagnostic detail ref.
        return self._failure(
            request,
            call_number,
            status=RunStatus.FAILED_FINAL,
            code=RuntimeErrorCode.INTERNAL,
            retryable=False,
            now=now,
            detail_ref="model_route_denied",
        )

    @staticmethod
    def _meter(model_result: ModelResult) -> RuntimeUsage:
        # Token dimensions are exact wire metering; turns/tool calls are the
        # single runtime call the adapter performs; cost is provider billing
        # and is deliberately not fabricated by the offline sandbox.
        return RuntimeUsage(
            input_tokens=model_result.input_tokens,
            output_tokens=model_result.output_tokens,
            total_tokens=model_result.input_tokens + model_result.output_tokens,
            tool_calls=0,
            turns=1,
            cost_microunits=0,
            elapsed_ms=1,
        )

    def _failure(
        self,
        request: AgentRunRequest,
        call_number: int,
        *,
        status: RunStatus,
        code: RuntimeErrorCode,
        retryable: bool,
        now: datetime,
        usage: RuntimeUsage | None = None,
        detail_ref: str | None = None,
    ) -> AgentRunResult:
        return AgentRunResult(
            result_id=self._result_id(request.request_id, call_number),
            request_id=request.request_id,
            status=status,
            trace_id=request.trace_id,
            provider_name=request.provider_selection.provider,
            provider_model=request.provider_selection.model,
            structured_output=None,
            public_reasoning_summary=None,
            usage=usage or RuntimeUsage(),
            error=RuntimeFailure(code=code, retryable=retryable, detail_ref=detail_ref),
            completed_at=now,
        )

    @staticmethod
    def _result_id(request_id: str, call_number: int) -> str:
        suffix = hashlib.sha256(
            f"{request_id}:{call_number}".encode()
        ).hexdigest()[:16]
        return f"arr_{suffix}"


def _runtime_proposal(proposal: ProviderToolProposal) -> ToolProposal:
    operation = (
        ToolOperation.READ
        if proposal.operation is WireToolOperation.READ
        else ToolOperation.PROPOSE_WRITE
    )
    return ToolProposal(
        proposal_id=proposal.proposal_id,
        tool=proposal.name,
        operation=operation,
        arguments=dict(proposal.arguments),
        resource=dict(proposal.resource),
        purpose=proposal.purpose,
        evidence_refs=proposal.evidence_refs,
    )
