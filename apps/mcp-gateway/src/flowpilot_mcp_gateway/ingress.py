from __future__ import annotations

from flowpilot_security import (
    SecurityError,
    SecurityErrorCode,
    WorkloadTokenVerifierPort,
)

from .gateway import McpGateway
from .models import GatewayExecution, GatewayIngressRequest, GatewayInvocation
from .ports import Clock


class GatewayIngress:
    """The only MCP Gateway boundary intended for network transport mounting.

    The bearer credential is a transient method argument. It is verified before
    an internal ``GatewayInvocation`` exists and is never retained on an object.
    ``McpGateway`` remains the process-internal authenticated service core.
    """

    def __init__(
        self,
        *,
        core: McpGateway,
        workload_tokens: WorkloadTokenVerifierPort,
        clock: Clock,
    ) -> None:
        self._core = core
        self._workload_tokens = workload_tokens
        self._clock = clock

    async def execute(
        self,
        request: GatewayIngressRequest,
        *,
        workload_bearer: str,
    ) -> GatewayExecution:
        invocation = await self._authenticate(request, workload_bearer)
        return await self._core.execute(invocation)

    async def reconcile(
        self,
        request: GatewayIngressRequest,
        *,
        workload_bearer: str,
    ) -> GatewayExecution:
        invocation = await self._authenticate(request, workload_bearer)
        return await self._core.reconcile(invocation)

    async def _authenticate(
        self,
        request: GatewayIngressRequest,
        workload_bearer: str,
    ) -> GatewayInvocation:
        if not isinstance(workload_bearer, str) or not workload_bearer:
            raise SecurityError(
                SecurityErrorCode.IDENTITY_TOKEN_INVALID,
                "OIDC workload token is missing",
            )
        workload = await self._workload_tokens.verify_workload_token(
            workload_bearer,
            now=self._clock(),
        )
        return GatewayInvocation(
            request=request.request,
            workload=workload,
            thread_id=request.thread_id,
            run_id=request.run_id,
            correlation_id=request.correlation_id,
        )
