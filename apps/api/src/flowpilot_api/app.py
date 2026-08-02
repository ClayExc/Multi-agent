from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from flowpilot_application import (
    ApplicationError,
    ApprovalDecisionResult,
    ApprovalDecisionService,
    CommandAcceptance,
    CommandIntakeService,
    ErrorCode,
    TaskEventEnvelope,
    TaskEventSubscriptionService,
    TaskQueryService,
)
from flowpilot_domain import (
    CommandType,
    DomainErrorCode,
    DomainViolation,
    Task,
    TaskCommand,
)

from .errors import ApiError, ApiErrorCode
from .models import (
    ApprovalDecisionBody,
    CommandAcceptanceBody,
    ErrorBody,
    ErrorEnvelope,
    ExecutionReceiptBody,
    HealthBody,
    TaskBody,
    TaskCommandBody,
    TaskId,
)
from .security import RequestSecurityPort, TrustedRequestIdentity
from .stream import InMemoryEventStream

_CONFLICT_CODES = {
    ErrorCode.IDEMPOTENCY_CONFLICT,
    ErrorCode.COMMAND_ID_CONFLICT,
    ErrorCode.TASK_ALREADY_EXISTS,
    ErrorCode.TASK_VERSION_CONFLICT,
    ErrorCode.VERSION_SLOT_CONFLICT,
}
_BAD_REQUEST_CODES = {
    ErrorCode.CONTRACT_INVALID,
    ErrorCode.COMMAND_DIGEST_MISMATCH,
    ErrorCode.APPROVAL_BINDING_MISMATCH,
}
_UNAVAILABLE_CODES = {
    ErrorCode.EXECUTION_UNAVAILABLE,
    ErrorCode.REPOSITORY_UNAVAILABLE,
}
_COMMAND_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorEnvelope} for status in (400, 403, 409, 422, 500, 502, 503)
}
_TASK_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorEnvelope} for status in (403, 404, 422, 500, 502, 503)
}


def create_app(
    *,
    command_intake: CommandIntakeService | None = None,
    task_query: TaskQueryService | None = None,
    request_security: RequestSecurityPort | None = None,
    task_event_subscription: TaskEventSubscriptionService | None = None,
    event_stream: InMemoryEventStream | None = None,
    approval_decisions: ApprovalDecisionService | None = None,
) -> FastAPI:
    app = FastAPI(
        title="FlowPilot API",
        version="0.1.0",
        description="Versioned TaskCommand intake and read-only Task projection.",
    )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, _error: RequestValidationError
    ) -> JSONResponse:
        return _error_response(
            status_code=422,
            code=ErrorCode.CONTRACT_INVALID.value,
            message="request does not match the TaskCommand v1 contract",
        )

    @app.exception_handler(ApplicationError)
    async def handle_application_error(
        _request: Request, error: ApplicationError
    ) -> JSONResponse:
        return _error_response(
            status_code=_application_status(error.code),
            code=error.code.value,
            message=error.safe_message,
            retryable=error.retryable,
            detail_ref=error.detail_ref,
        )

    @app.exception_handler(ApiError)
    async def handle_api_error(_request: Request, error: ApiError) -> JSONResponse:
        return _error_response(
            status_code=error.status_code,
            code=error.code.value,
            message=error.safe_message,
            retryable=error.retryable,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(
        _request: Request, _error: Exception
    ) -> JSONResponse:
        return _error_response(
            status_code=500,
            code=ApiErrorCode.INTERNAL_ERROR.value,
            message="an unexpected API error occurred",
        )

    @app.get(
        "/health",
        response_model=HealthBody,
        tags=["health"],
        operation_id="getHealth",
    )
    async def health() -> HealthBody:
        return HealthBody(
            status="ok",
            service="flowpilot-api",
            version="0.1.0",
            configured=all(
                dependency is not None
                for dependency in (task_query, request_security)
            )
            and (command_intake is not None or approval_decisions is not None),
        )

    @app.post(
        "/v1/task-commands",
        response_model=CommandAcceptanceBody | ApprovalDecisionBody,
        responses=_COMMAND_ERROR_RESPONSES,
        status_code=202,
        tags=["commands"],
        operation_id="submitTaskCommandV1",
    )
    async def submit_task_command(
        body: TaskCommandBody, request: Request
    ) -> CommandAcceptanceBody | ApprovalDecisionBody:
        security = _require_dependency(
            request_security, "request security is not configured"
        )
        identity = await security.authenticate(request)
        command = _to_domain_command(body)
        _assert_request_binding(identity, command)
        _assert_command_integrity(command)
        await security.authorize_command(identity, command)
        if command.command_type is CommandType.DECIDE_APPROVAL:
            decisions = _require_dependency(
                approval_decisions, "approval decisions are not configured"
            )
            result = await decisions.decide(command)
            return _approval_decision_body(result)
        intake = _require_dependency(command_intake, "command intake is not configured")
        acceptance = await intake.accept(command)
        return _acceptance_body(acceptance)

    @app.get(
        "/v1/tasks/events",
        responses={
            403: {"model": ErrorEnvelope},
            422: {"model": ErrorEnvelope},
            500: {"model": ErrorEnvelope},
            503: {"model": ErrorEnvelope},
        },
        tags=["tasks"],
        operation_id="streamTaskEventsV1",
    )
    async def stream_task_events(request: Request) -> StreamingResponse:
        security = _require_dependency(
            request_security, "request security is not configured"
        )
        subscription = _require_dependency(
            task_event_subscription,
            "task event subscription is not configured",
        )
        stream = _require_dependency(
            event_stream, "task event stream is not configured"
        )
        identity = await security.authenticate(request)
        await security.authorize_event_stream(identity)
        tenant_id = identity.tenant_id
        await subscription.attach(tenant_id)
        queue = stream.subscribe(tenant_id)

        async def event_source() -> Any:
            try:
                while True:
                    try:
                        envelope = await asyncio.wait_for(queue.get(), timeout=15)
                    except TimeoutError:
                        yield ": ping\n\n"
                        continue
                    yield _sse_frame(envelope)
            finally:
                stream.unsubscribe(tenant_id, queue)
                await subscription.detach(tenant_id)

        return StreamingResponse(
            event_source(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.get(
        "/v1/tasks/{task_id}",
        response_model=TaskBody,
        response_model_exclude_unset=True,
        responses=_TASK_ERROR_RESPONSES,
        tags=["tasks"],
        operation_id="getTaskV1",
    )
    async def get_task(task_id: TaskId, request: Request) -> TaskBody:
        security = _require_dependency(
            request_security, "request security is not configured"
        )
        query = _require_dependency(task_query, "task query is not configured")
        identity = await security.authenticate(request)
        await security.authorize_task_read(identity, task_id)
        task = await query.get(identity.tenant_id, task_id)
        return _task_body(task)

    return app


def _to_domain_command(body: TaskCommandBody) -> TaskCommand:
    try:
        return TaskCommand.from_mapping(
            body.model_dump(mode="json", exclude_unset=True)
        )
    except DomainViolation as exc:
        raise ApplicationError(
            ErrorCode.CONTRACT_INVALID,
            "request does not match the TaskCommand v1 contract",
        ) from exc


def _assert_request_binding(
    identity: TrustedRequestIdentity, command: TaskCommand
) -> None:
    context = command.security_context
    if (
        identity.tenant_id != command.tenant_id
        or identity.subject_id != command.actor.id
        or identity.subject_type is not command.actor.type
        or identity.purpose != context.purpose
        or identity.security_context_id != context.context_id
        or identity.security_context_ref != context.context_ref
        or identity.security_context_hash != context.context_hash
    ):
        raise ApiError(
            ApiErrorCode.REQUEST_IDENTITY_MISMATCH,
            "request identity does not match the command security context",
            status_code=403,
        )


def _assert_command_integrity(command: TaskCommand) -> None:
    try:
        command.assert_digest()
        command.assert_security_binding()
    except DomainViolation as exc:
        code = {
            DomainErrorCode.DIGEST_MISMATCH: ErrorCode.COMMAND_DIGEST_MISMATCH,
            DomainErrorCode.SECURITY_BINDING_MISMATCH: (
                ErrorCode.SECURITY_BINDING_MISMATCH
            ),
        }.get(exc.code, ErrorCode.CONTRACT_INVALID)
        raise ApplicationError(code, exc.safe_message) from exc


def _acceptance_body(acceptance: CommandAcceptance) -> CommandAcceptanceBody:
    receipt = acceptance.execution_receipt
    return CommandAcceptanceBody(
        command_id=acceptance.command_id,
        tenant_id=acceptance.tenant_id,
        task_id=acceptance.task_id,
        accepted_at=acceptance.accepted_at,
        replayed=acceptance.replayed,
        execution_receipt=ExecutionReceiptBody(
            command_id=receipt.command_id,
            tenant_id=receipt.tenant_id,
            task_id=receipt.task_id,
            disposition=receipt.disposition.value,
            execution_ref=receipt.execution_ref,
        ),
    )


def _approval_decision_body(
    result: ApprovalDecisionResult,
) -> ApprovalDecisionBody:
    return ApprovalDecisionBody(
        approval_id=result.approval_id,
        tenant_id=result.tenant_id,
        task_id=result.task_id,
        status=result.status.value,
        action_digest=result.action_digest,
        decided_at=result.decided_at,
    )


def _task_body(task: Task) -> TaskBody:
    return TaskBody.model_validate_json(json.dumps(task.to_mapping()))


def _sse_frame(envelope: TaskEventEnvelope) -> str:
    data = json.dumps(
        envelope.to_mapping(),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"id: {envelope.event_id}\nevent: task.event\ndata: {data}\n\n"


def _require_dependency[T](dependency: T | None, message: str) -> T:
    if dependency is None:
        raise ApiError(
            ApiErrorCode.DEPENDENCY_UNAVAILABLE,
            message,
            status_code=503,
            retryable=True,
        )
    return dependency


def _application_status(code: ErrorCode) -> int:
    if code in _BAD_REQUEST_CODES:
        return 400
    if code in {
        ErrorCode.SECURITY_BINDING_MISMATCH,
        ErrorCode.APPROVAL_DUTIES_VIOLATION,
    }:
        return 403
    if code is ErrorCode.TASK_NOT_FOUND or code is ErrorCode.APPROVAL_NOT_FOUND:
        return 404
    if code in _CONFLICT_CODES or code in {
        ErrorCode.APPROVAL_CONFLICT,
        ErrorCode.APPROVAL_EXPIRED,
    }:
        return 409
    if code in _UNAVAILABLE_CODES:
        return 503
    if code in {
        ErrorCode.EXECUTION_PROTOCOL_ERROR,
        ErrorCode.REPOSITORY_PROTOCOL_ERROR,
    }:
        return 502
    return 500


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    retryable: bool = False,
    detail_ref: str | None = None,
) -> JSONResponse:
    payload = ErrorEnvelope(
        error=ErrorBody(
            code=code,
            message=message,
            retryable=retryable,
            detail_ref=detail_ref,
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
    )
