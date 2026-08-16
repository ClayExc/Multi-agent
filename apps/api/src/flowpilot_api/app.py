from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, replace
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from flowpilot_application import (
    ApplicationError,
    ApprovalDecisionResult,
    ApprovalDecisionService,
    AuditEventView,
    CommandAcceptance,
    CommandIntakeService,
    ErrorCode,
    EventQuery,
    GovernancePageRequest,
    GovernanceQueryContext,
    GovernanceQueryService,
    GovernanceTimeWindow,
    KnowledgeDiagnostic,
    KnowledgeDocumentProjection,
    KnowledgeImportRequest,
    KnowledgeLifecycleRequest,
    KnowledgeOperation,
    KnowledgeOperationReceipt,
    KnowledgeReadRequest,
    KnowledgeRebuildRequest,
    KnowledgeRequestContext,
    KnowledgeUpdateRequest,
    PolicyDecisionQuery,
    PolicyDecisionView,
    SecurityEventView,
    TaskEventEnvelope,
    TaskEventErrorCode,
    TaskEventSubscriptionService,
    TaskEventValidationError,
    TaskQueryService,
)
from flowpilot_domain import (
    ApprovalStatus,
    CommandType,
    DomainErrorCode,
    DomainViolation,
    KnowledgeAccessControl,
    KnowledgeContent,
    KnowledgeSource,
    KnowledgeSourceType,
    Task,
    TaskCommand,
)
from flowpilot_domain import (
    DataClassification as DomainDataClassification,
)
from flowpilot_security import TrustedSecurityContext

from .errors import ApiError, ApiErrorCode
from .knowledge import (
    KnowledgeAccessControlFactory,
    KnowledgeAccessKind,
    KnowledgeAccessPolicy,
    KnowledgeApiServiceFactory,
    KnowledgeApiServices,
)
from .models import (
    ApprovalDecisionBody,
    AuthSessionBody,
    CommandAcceptanceBody,
    DocumentId,
    ErrorBody,
    ErrorEnvelope,
    ExecutionReceiptBody,
    GovernanceAuditEventBody,
    GovernanceAuditEventPageBody,
    GovernanceCorrelationBody,
    GovernancePolicyDecisionBody,
    GovernancePolicyDecisionPageBody,
    GovernanceSecurityEventBody,
    GovernanceSecurityEventPageBody,
    HealthBody,
    KnowledgeDiagnosticBody,
    KnowledgeDocumentBody,
    KnowledgeImportBody,
    KnowledgeLifecycleBody,
    KnowledgeOperationReceiptBody,
    KnowledgeRebuildBody,
    KnowledgeUpdateBody,
    PolicyVersionBody,
    PolicyVersionPageBody,
    TaskBody,
    TaskCommandBody,
    TaskId,
)
from .oidc import OidcBffConfig, OidcBffService, OidcSessionStart
from .security import (
    GovernanceAccessPolicy,
    RequestSecurityPort,
    TrustedRequestIdentity,
)
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
    ErrorCode.GOVERNANCE_CURSOR_INVALID,
}
_UNAVAILABLE_CODES = {
    ErrorCode.EXECUTION_UNAVAILABLE,
    ErrorCode.REPOSITORY_UNAVAILABLE,
    ErrorCode.GOVERNANCE_REPOSITORY_UNAVAILABLE,
}
_COMMAND_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorEnvelope}
    for status in (400, 401, 403, 409, 422, 500, 502, 503)
}
_TASK_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorEnvelope} for status in (401, 403, 404, 422, 500, 502, 503)
}
_AUTH_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorEnvelope} for status in (401, 403, 409, 503)
}
_GOVERNANCE_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorEnvelope} for status in (400, 401, 403, 404, 500, 502, 503)
}
_KNOWLEDGE_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorEnvelope}
    for status in (400, 401, 403, 404, 409, 422, 500, 502, 503)
}
_INTEGER = re.compile(r"^[1-9][0-9]{0,2}$")
_TASK_FILTER = re.compile(r"^task_[A-Za-z0-9_-]{8,128}$")
_CORRELATION_FILTER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def create_app(
    *,
    command_intake: CommandIntakeService | None = None,
    task_query: TaskQueryService | None = None,
    request_security: RequestSecurityPort | None = None,
    task_event_subscription: TaskEventSubscriptionService | None = None,
    event_stream: InMemoryEventStream | None = None,
    approval_decisions: ApprovalDecisionService | None = None,
    oidc_bff: OidcBffService | None = None,
    governance_queries: GovernanceQueryService | None = None,
    governance_access: GovernanceAccessPolicy | None = None,
    knowledge_services: KnowledgeApiServiceFactory | None = None,
    knowledge_access: KnowledgeAccessPolicy | None = None,
    knowledge_access_control: KnowledgeAccessControlFactory | None = None,
) -> FastAPI:
    knowledge_dependencies = (
        knowledge_services,
        knowledge_access,
        knowledge_access_control,
    )
    if any(item is not None for item in knowledge_dependencies) and not all(
        item is not None for item in knowledge_dependencies
    ):
        raise ValueError(
            "knowledge services, access, and ACL factory must be configured together"
        )
    app = FastAPI(
        title="FlowPilot API",
        version="0.1.0",
        description="Versioned TaskCommand intake and read-only Task projection.",
    )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, _error: RequestValidationError
    ) -> JSONResponse:
        is_knowledge = request.url.path.startswith("/v1/knowledge/")
        return _error_response(
            status_code=422,
            code=(
                ErrorCode.KNOWLEDGE_CONTRACT_INVALID.value
                if is_knowledge
                else ErrorCode.CONTRACT_INVALID.value
            ),
            message=(
                "request does not match the Knowledge API contract"
                if is_knowledge
                else "request does not match the TaskCommand v1 contract"
            ),
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
                dependency is not None for dependency in (task_query, request_security)
            )
            and (command_intake is not None or approval_decisions is not None),
        )

    @app.get(
        "/v1/auth/login",
        responses={
            302: {"description": "Redirect to the trusted OIDC provider"},
            **_AUTH_ERROR_RESPONSES,
        },
        tags=["auth"],
        operation_id="startOidcLoginV1",
    )
    async def start_oidc_login() -> Response:
        bff = _require_dependency(oidc_bff, "OIDC BFF is not configured")
        start = await bff.begin_login()
        response = RedirectResponse(start.authorization_url, status_code=302)
        _set_cookie(
            response,
            name=bff.config.transaction_cookie_name,
            value=start.transaction_cookie,
            max_age=start.max_age_seconds,
            config=bff.config,
        )
        return response

    @app.get(
        "/v1/auth/callback",
        responses={
            303: {"description": "OIDC login completed"},
            **_AUTH_ERROR_RESPONSES,
        },
        tags=["auth"],
        operation_id="completeOidcLoginV1",
    )
    async def complete_oidc_login(
        request: Request,
        state: str | None = None,
        code: str | None = None,
    ) -> Response:
        bff = _require_dependency(oidc_bff, "OIDC BFF is not configured")
        try:
            session = await bff.complete_callback(
                transaction_cookie=request.cookies.get(
                    bff.config.transaction_cookie_name
                ),
                state=state,
                code=code,
            )
        except ApiError as error:
            error_response = _api_error_response(error)
            _clear_cookie(
                error_response,
                name=bff.config.transaction_cookie_name,
                config=bff.config,
            )
            return error_response
        success_response = RedirectResponse(
            bff.config.post_login_redirect,
            status_code=303,
        )
        _clear_cookie(
            success_response,
            name=bff.config.transaction_cookie_name,
            config=bff.config,
        )
        _set_session_cookie(success_response, bff.config, session)
        return success_response

    @app.post(
        "/v1/auth/refresh",
        response_model=AuthSessionBody,
        responses=_AUTH_ERROR_RESPONSES,
        tags=["auth"],
        operation_id="refreshOidcSessionV1",
    )
    async def refresh_oidc_session(request: Request) -> Response:
        bff = _require_dependency(oidc_bff, "OIDC BFF is not configured")
        try:
            session = await bff.refresh(
                request.cookies.get(bff.config.session_cookie_name)
            )
        except ApiError as error:
            response = _api_error_response(error)
            _clear_cookie(
                response,
                name=bff.config.session_cookie_name,
                config=bff.config,
            )
            return response
        response = JSONResponse(
            AuthSessionBody(
                status="active",
                expires_at=session.expires_at,
            ).model_dump(mode="json")
        )
        _set_session_cookie(response, bff.config, session)
        return response

    @app.post(
        "/v1/auth/logout",
        status_code=204,
        responses=_AUTH_ERROR_RESPONSES,
        tags=["auth"],
        operation_id="logoutOidcSessionV1",
    )
    async def logout_oidc_session(request: Request) -> Response:
        bff = _require_dependency(oidc_bff, "OIDC BFF is not configured")
        await bff.logout(request.cookies.get(bff.config.session_cookie_name))
        response = Response(status_code=204)
        _clear_cookie(
            response,
            name=bff.config.session_cookie_name,
            config=bff.config,
        )
        return response

    @app.post(
        "/v1/auth/session/invalidate",
        status_code=204,
        responses=_AUTH_ERROR_RESPONSES,
        tags=["auth"],
        operation_id="invalidateOidcSessionV1",
    )
    async def invalidate_oidc_session(request: Request) -> Response:
        bff = _require_dependency(oidc_bff, "OIDC BFF is not configured")
        await bff.invalidate(request.cookies.get(bff.config.session_cookie_name))
        response = Response(status_code=204)
        _clear_cookie(
            response,
            name=bff.config.session_cookie_name,
            config=bff.config,
        )
        return response

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
            401: {"model": ErrorEnvelope},
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
        identity = await security.authenticate(request)
        await security.authorize_event_stream(identity)
        subscription = _require_dependency(
            task_event_subscription,
            "task event subscription is not configured",
        )
        stream = _require_dependency(
            event_stream, "task event stream is not configured"
        )
        tenant_id = identity.tenant_id
        await subscription.attach(tenant_id)
        queue = stream.subscribe(tenant_id)

        async def event_source() -> Any:
            try:
                while True:
                    try:
                        envelope = await asyncio.wait_for(queue.get(), timeout=15)
                    except TimeoutError:
                        try:
                            await security.authorize_event_stream(identity)
                        except ApiError:
                            return
                        yield ": ping\n\n"
                        continue
                    try:
                        await security.authorize_event_stream(identity)
                    except ApiError:
                        return
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
        identity = await security.authenticate(request)
        await security.authorize_task_read(identity, task_id)
        query = _require_dependency(task_query, "task query is not configured")
        task = await query.get(identity.tenant_id, task_id)
        return _task_body(task)

    async def knowledge_context(
        request: Request,
        kind: KnowledgeAccessKind,
    ) -> tuple[
        KnowledgeApiServices,
        KnowledgeRequestContext,
        TrustedSecurityContext,
    ]:
        security = _require_dependency(
            request_security, "request security is not configured"
        )
        access = _require_dependency(
            knowledge_access, "knowledge access policy is not configured"
        )
        factory = _require_dependency(
            knowledge_services, "knowledge services are not configured"
        )
        identity = await security.authenticate(request)
        trusted = await security.authorize_knowledge_access(identity, access, kind)
        services = factory.create(trusted)
        return (
            services,
            KnowledgeRequestContext(
                tenant_id=trusted.context.tenant_id,
                purpose=trusted.context.purpose,
                security_context=trusted.context,
            ),
            trusted,
        )

    @app.post(
        "/v1/knowledge/documents",
        response_model=KnowledgeOperationReceiptBody,
        status_code=201,
        responses=_KNOWLEDGE_ERROR_RESPONSES,
        tags=["knowledge"],
        operation_id="importKnowledgeDocumentV1",
    )
    async def import_knowledge_document(
        body: KnowledgeImportBody,
        request: Request,
        idempotency_key: Annotated[
            str,
            Header(alias="Idempotency-Key", pattern=r"^sha256:[a-f0-9]{64}$"),
        ],
    ) -> KnowledgeOperationReceiptBody:
        services, context, trusted = await knowledge_context(
            request, KnowledgeAccessKind.MANAGE
        )
        acl_factory = _require_dependency(
            knowledge_access_control,
            "knowledge ACL factory is not configured",
        )
        command = _knowledge_import_request(
            body,
            context=context,
            access_control=acl_factory.create(trusted),
            idempotency_key=idempotency_key,
        )
        return _knowledge_receipt_body(await services.commands.import_document(command))

    @app.put(
        "/v1/knowledge/documents/{document_id}",
        response_model=KnowledgeOperationReceiptBody,
        responses=_KNOWLEDGE_ERROR_RESPONSES,
        tags=["knowledge"],
        operation_id="updateKnowledgeDocumentV1",
    )
    async def update_knowledge_document(
        document_id: DocumentId,
        body: KnowledgeUpdateBody,
        request: Request,
        idempotency_key: Annotated[
            str,
            Header(alias="Idempotency-Key", pattern=r"^sha256:[a-f0-9]{64}$"),
        ],
    ) -> KnowledgeOperationReceiptBody:
        services, context, trusted = await knowledge_context(
            request, KnowledgeAccessKind.MANAGE
        )
        acl_factory = _require_dependency(
            knowledge_access_control,
            "knowledge ACL factory is not configured",
        )
        command = _knowledge_update_request(
            body,
            document_id=document_id,
            context=context,
            access_control=acl_factory.create(trusted),
            idempotency_key=idempotency_key,
        )
        return _knowledge_receipt_body(await services.commands.update_document(command))

    @app.post(
        "/v1/knowledge/documents/{document_id}/retire",
        response_model=KnowledgeOperationReceiptBody,
        responses=_KNOWLEDGE_ERROR_RESPONSES,
        tags=["knowledge"],
        operation_id="retireKnowledgeDocumentV1",
    )
    async def retire_knowledge_document(
        document_id: DocumentId,
        body: KnowledgeLifecycleBody,
        request: Request,
        idempotency_key: Annotated[
            str,
            Header(alias="Idempotency-Key", pattern=r"^sha256:[a-f0-9]{64}$"),
        ],
    ) -> KnowledgeOperationReceiptBody:
        services, context, _trusted = await knowledge_context(
            request, KnowledgeAccessKind.MANAGE
        )
        command = _knowledge_lifecycle_request(
            body,
            document_id=document_id,
            context=context,
            idempotency_key=idempotency_key,
            operation=KnowledgeOperation.RETIRE,
        )
        return _knowledge_receipt_body(await services.commands.retire_document(command))

    @app.delete(
        "/v1/knowledge/documents/{document_id}",
        response_model=KnowledgeOperationReceiptBody,
        responses=_KNOWLEDGE_ERROR_RESPONSES,
        tags=["knowledge"],
        operation_id="deleteKnowledgeDocumentV1",
    )
    async def delete_knowledge_document(
        document_id: DocumentId,
        body: KnowledgeLifecycleBody,
        request: Request,
        idempotency_key: Annotated[
            str,
            Header(alias="Idempotency-Key", pattern=r"^sha256:[a-f0-9]{64}$"),
        ],
    ) -> KnowledgeOperationReceiptBody:
        services, context, _trusted = await knowledge_context(
            request, KnowledgeAccessKind.MANAGE
        )
        command = _knowledge_lifecycle_request(
            body,
            document_id=document_id,
            context=context,
            idempotency_key=idempotency_key,
            operation=KnowledgeOperation.DELETE,
        )
        return _knowledge_receipt_body(await services.commands.delete_document(command))

    @app.post(
        "/v1/knowledge/documents/{document_id}/rebuild",
        response_model=KnowledgeOperationReceiptBody,
        responses=_KNOWLEDGE_ERROR_RESPONSES,
        tags=["knowledge"],
        operation_id="rebuildKnowledgeIndexV1",
    )
    async def rebuild_knowledge_index(
        document_id: DocumentId,
        body: KnowledgeRebuildBody,
        request: Request,
        idempotency_key: Annotated[
            str,
            Header(alias="Idempotency-Key", pattern=r"^sha256:[a-f0-9]{64}$"),
        ],
    ) -> KnowledgeOperationReceiptBody:
        services, context, _trusted = await knowledge_context(
            request, KnowledgeAccessKind.MANAGE
        )
        command = _knowledge_rebuild_request(
            body,
            document_id=document_id,
            context=context,
            idempotency_key=idempotency_key,
        )
        return _knowledge_receipt_body(
            await services.commands.rebuild_document(command)
        )

    @app.get(
        "/v1/knowledge/documents/{document_id}",
        response_model=KnowledgeDocumentBody,
        responses=_KNOWLEDGE_ERROR_RESPONSES,
        tags=["knowledge"],
        operation_id="getKnowledgeDocumentV1",
    )
    async def get_knowledge_document(
        document_id: DocumentId,
        request: Request,
        response: Response,
        document_version: Annotated[int | None, Query(ge=0, le=2**53 - 1)] = None,
    ) -> KnowledgeDocumentBody:
        services, context, _trusted = await knowledge_context(
            request, KnowledgeAccessKind.READ
        )
        projection = await services.queries.get_document(
            KnowledgeReadRequest(
                context=context,
                document_id=document_id,
                document_version=document_version,
            )
        )
        _set_knowledge_headers(response)
        return _knowledge_document_body(projection)

    @app.get(
        "/v1/knowledge/documents/{document_id}/diagnostic",
        response_model=KnowledgeDiagnosticBody,
        responses=_KNOWLEDGE_ERROR_RESPONSES,
        tags=["knowledge"],
        operation_id="diagnoseKnowledgeDocumentV1",
    )
    async def diagnose_knowledge_document(
        document_id: DocumentId,
        request: Request,
        response: Response,
        document_version: Annotated[int | None, Query(ge=0, le=2**53 - 1)] = None,
    ) -> KnowledgeDiagnosticBody:
        services, context, _trusted = await knowledge_context(
            request, KnowledgeAccessKind.DIAGNOSTIC
        )
        diagnostic = await services.queries.diagnose(
            KnowledgeReadRequest(
                context=context,
                document_id=document_id,
                document_version=document_version,
            )
        )
        _set_knowledge_headers(response)
        return _knowledge_diagnostic_body(diagnostic)

    async def governance_context(
        request: Request,
    ) -> tuple[GovernanceQueryService, GovernanceQueryContext]:
        security = _require_dependency(
            request_security, "request security is not configured"
        )
        access = _require_dependency(
            governance_access, "governance access policy is not configured"
        )
        service = _require_dependency(
            governance_queries, "governance query service is not configured"
        )
        identity = await security.authenticate(request)
        await security.authorize_governance_read(identity, access)
        return service, GovernanceQueryContext(
            tenant_id=identity.tenant_id,
            subject_id=identity.subject_id,
            purpose=identity.purpose,
            security_context_ref=identity.security_context_ref,
            security_context_hash=identity.security_context_hash,
        )

    @app.get(
        "/v1/governance/policy-versions",
        response_model=PolicyVersionPageBody,
        responses=_GOVERNANCE_ERROR_RESPONSES,
        tags=["governance"],
        operation_id="listGovernancePolicyVersionsV1",
    )
    async def list_governance_policy_versions(
        request: Request,
        response: Response,
    ) -> PolicyVersionPageBody:
        service, context = await governance_context(request)
        values = _governance_query_values(request, {"limit", "cursor"})
        page_request = _governance_page_request(values)
        page = await service.list_policy_versions(context, page_request)
        _set_governance_headers(response)
        return PolicyVersionPageBody(
            items=[PolicyVersionBody(**asdict(item)) for item in page.items],
            next_cursor=page.next_cursor,
        )

    @app.get(
        "/v1/governance/policy-decisions",
        response_model=GovernancePolicyDecisionPageBody,
        responses=_GOVERNANCE_ERROR_RESPONSES,
        tags=["governance"],
        operation_id="listGovernancePolicyDecisionsV1",
    )
    async def list_governance_policy_decisions(
        request: Request,
        response: Response,
    ) -> GovernancePolicyDecisionPageBody:
        service, context = await governance_context(request)
        values = _governance_query_values(request, {"limit", "cursor", "task_id"})
        task_id = values.get("task_id")
        if task_id is not None and _TASK_FILTER.fullmatch(task_id) is None:
            raise _governance_query_error()
        try:
            query = PolicyDecisionQuery(
                page=_governance_page_request(values),
                task_id=task_id,
            )
        except (TypeError, ValueError):
            raise _governance_query_error() from None
        page = await service.list_policy_decisions(context, query)
        _set_governance_headers(response)
        return GovernancePolicyDecisionPageBody(
            items=[_governance_policy_decision_body(item) for item in page.items],
            next_cursor=page.next_cursor,
        )

    @app.get(
        "/v1/governance/audit-events",
        response_model=GovernanceAuditEventPageBody,
        responses=_GOVERNANCE_ERROR_RESPONSES,
        tags=["governance"],
        operation_id="listGovernanceAuditEventsV1",
    )
    async def list_governance_audit_events(
        request: Request,
        response: Response,
    ) -> GovernanceAuditEventPageBody:
        service, context = await governance_context(request)
        query = _governance_event_query(request)
        page = await service.list_audit_events(context, query)
        _set_governance_headers(response)
        return GovernanceAuditEventPageBody(
            items=[_governance_audit_body(item) for item in page.items],
            next_cursor=page.next_cursor,
        )

    @app.get(
        "/v1/governance/security-events",
        response_model=GovernanceSecurityEventPageBody,
        responses=_GOVERNANCE_ERROR_RESPONSES,
        tags=["governance"],
        operation_id="listGovernanceSecurityEventsV1",
    )
    async def list_governance_security_events(
        request: Request,
        response: Response,
    ) -> GovernanceSecurityEventPageBody:
        service, context = await governance_context(request)
        query = _governance_event_query(request)
        page = await service.list_security_events(context, query)
        _set_governance_headers(response)
        return GovernanceSecurityEventPageBody(
            items=[_governance_security_body(item) for item in page.items],
            next_cursor=page.next_cursor,
        )

    @app.get(
        "/v1/governance/correlations/{correlation_id}",
        response_model=GovernanceCorrelationBody,
        responses=_GOVERNANCE_ERROR_RESPONSES,
        tags=["governance"],
        operation_id="getGovernanceCorrelationV1",
    )
    async def get_governance_correlation(
        correlation_id: str,
        request: Request,
        response: Response,
    ) -> GovernanceCorrelationBody:
        service, context = await governance_context(request)
        _governance_query_values(request, set())
        if _CORRELATION_FILTER.fullmatch(correlation_id) is None:
            raise _governance_query_error()
        chain = await service.get_correlation_chain(context, correlation_id)
        _set_governance_headers(response)
        return GovernanceCorrelationBody(
            correlation_id=chain.correlation_id,
            policy_decisions=[
                _governance_policy_decision_body(item)
                for item in chain.policy_decisions
            ],
            audit_events=[_governance_audit_body(item) for item in chain.audit_events],
            security_events=[
                _governance_security_body(item) for item in chain.security_events
            ],
        )

    return app


_EMPTY_SHA256 = "sha256:" + "0" * 64
_KNOWLEDGE_RECEIPT_OPERATIONS: dict[
    KnowledgeOperation,
    Literal["import", "update", "retire", "delete", "rebuild"],
] = {
    KnowledgeOperation.IMPORT: "import",
    KnowledgeOperation.UPDATE: "update",
    KnowledgeOperation.RETIRE: "retire",
    KnowledgeOperation.DELETE: "delete",
    KnowledgeOperation.REBUILD: "rebuild",
}


def _knowledge_import_request(
    body: KnowledgeImportBody,
    *,
    context: KnowledgeRequestContext,
    access_control: KnowledgeAccessControl,
    idempotency_key: str,
) -> KnowledgeImportRequest:
    source, content, classification = _knowledge_version_input(body)
    try:
        command = KnowledgeImportRequest(
            context=context,
            document_id=body.document_id,
            source=source,
            access_control=access_control,
            data_classification=classification,
            effective_at=body.effective_at,
            expires_at=body.expires_at,
            content=content,
            idempotency_key=idempotency_key,
            request_digest=_EMPTY_SHA256,
        )
        return replace(command, request_digest=command.recompute_digest())
    except (DomainViolation, TypeError, ValueError) as exc:
        raise _knowledge_contract_error() from exc


def _knowledge_update_request(
    body: KnowledgeUpdateBody,
    *,
    document_id: str,
    context: KnowledgeRequestContext,
    access_control: KnowledgeAccessControl,
    idempotency_key: str,
) -> KnowledgeUpdateRequest:
    source, content, classification = _knowledge_version_input(body)
    try:
        command = KnowledgeUpdateRequest(
            context=context,
            document_id=document_id,
            expected_revision=body.expected_revision,
            source=source,
            access_control=access_control,
            data_classification=classification,
            effective_at=body.effective_at,
            expires_at=body.expires_at,
            content=content,
            idempotency_key=idempotency_key,
            request_digest=_EMPTY_SHA256,
        )
        return replace(command, request_digest=command.recompute_digest())
    except (DomainViolation, TypeError, ValueError) as exc:
        raise _knowledge_contract_error() from exc


def _knowledge_version_input(
    body: KnowledgeImportBody | KnowledgeUpdateBody,
) -> tuple[KnowledgeSource, KnowledgeContent, DomainDataClassification]:
    try:
        return (
            KnowledgeSource.build(
                source_type=KnowledgeSourceType(body.source_type),
                source_ref=body.source_ref,
                source_version=body.source_version,
            ),
            KnowledgeContent.from_text(body.content),
            DomainDataClassification(body.data_classification),
        )
    except (DomainViolation, TypeError, ValueError) as exc:
        raise _knowledge_contract_error() from exc


def _knowledge_lifecycle_request(
    body: KnowledgeLifecycleBody,
    *,
    document_id: str,
    context: KnowledgeRequestContext,
    idempotency_key: str,
    operation: KnowledgeOperation,
) -> KnowledgeLifecycleRequest:
    try:
        command = KnowledgeLifecycleRequest(
            context=context,
            document_id=document_id,
            expected_revision=body.expected_revision,
            idempotency_key=idempotency_key,
            request_digest=_EMPTY_SHA256,
        )
        return replace(
            command,
            request_digest=command.recompute_digest(operation),
        )
    except (DomainViolation, TypeError, ValueError) as exc:
        raise _knowledge_contract_error() from exc


def _knowledge_rebuild_request(
    body: KnowledgeRebuildBody,
    *,
    document_id: str,
    context: KnowledgeRequestContext,
    idempotency_key: str,
) -> KnowledgeRebuildRequest:
    try:
        command = KnowledgeRebuildRequest(
            context=context,
            document_id=document_id,
            expected_revision=body.expected_revision,
            document_version=body.document_version,
            idempotency_key=idempotency_key,
            request_digest=_EMPTY_SHA256,
        )
        return replace(command, request_digest=command.recompute_digest())
    except (DomainViolation, TypeError, ValueError) as exc:
        raise _knowledge_contract_error() from exc


def _knowledge_receipt_body(
    receipt: KnowledgeOperationReceipt,
) -> KnowledgeOperationReceiptBody:
    return KnowledgeOperationReceiptBody(
        document_id=receipt.document_id,
        operation=_KNOWLEDGE_RECEIPT_OPERATIONS[receipt.operation],
        revision=receipt.revision,
        document_version=receipt.document_version,
        disposition=receipt.disposition.value,
        event_id=receipt.event_id,
        index_job_id=receipt.index_job_id,
    )


def _knowledge_document_body(
    projection: KnowledgeDocumentProjection,
) -> KnowledgeDocumentBody:
    document = projection.document
    version = projection.version
    source = version.source.safe_mapping()
    return KnowledgeDocumentBody(
        document_id=document.document_id,
        revision=document.revision,
        current_version=document.current_version,
        lifecycle=document.lifecycle.value,
        document_version=version.version,
        source_type=version.source.source_type.value,
        source_version=source["source_version"],
        source_digest=version.source.source_digest,
        acl_digest=version.access_control.digest(),
        data_classification=version.data_classification.value,
        effective_at=version.effective_at,
        expires_at=version.expires_at,
        content_hash=version.content_hash,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def _knowledge_diagnostic_body(
    diagnostic: KnowledgeDiagnostic,
) -> KnowledgeDiagnosticBody:
    return KnowledgeDiagnosticBody(
        document_id=diagnostic.document_id,
        document_version=diagnostic.document_version,
        document_revision=diagnostic.document_revision,
        content_hash=diagnostic.content_hash,
        index_state=diagnostic.index_state.value,
        last_job_id=diagnostic.last_job_id,
        indexed_at=diagnostic.indexed_at,
        failure_code=diagnostic.failure_code,
    )


def _knowledge_contract_error() -> ApplicationError:
    return ApplicationError(
        ErrorCode.KNOWLEDGE_CONTRACT_INVALID,
        "request does not match the Knowledge API contract",
    )


def _set_knowledge_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Vary"] = "Cookie"


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


def _governance_query_values(
    request: Request,
    allowed: set[str],
) -> dict[str, str]:
    values: dict[str, str] = {}
    for key, value in request.query_params.multi_items():
        if key not in allowed or key in values or not value or len(value) > 512:
            raise _governance_query_error()
        values[key] = value
    return values


def _governance_page_request(values: dict[str, str]) -> GovernancePageRequest:
    raw_limit = values.get("limit")
    if raw_limit is None:
        limit = 50
    elif _INTEGER.fullmatch(raw_limit) is None:
        raise _governance_query_error()
    else:
        limit = int(raw_limit)
    try:
        return GovernancePageRequest(limit=limit, cursor=values.get("cursor"))
    except ApplicationError:
        raise
    except (TypeError, ValueError):
        raise _governance_query_error() from None


def _governance_event_query(request: Request) -> EventQuery:
    values = _governance_query_values(
        request,
        {
            "limit",
            "cursor",
            "task_id",
            "correlation_id",
            "occurred_after",
            "occurred_before",
        },
    )
    task_id = values.get("task_id")
    correlation_id = values.get("correlation_id")
    if task_id is not None and _TASK_FILTER.fullmatch(task_id) is None:
        raise _governance_query_error()
    if (
        correlation_id is not None
        and _CORRELATION_FILTER.fullmatch(correlation_id) is None
    ):
        raise _governance_query_error()
    try:
        return EventQuery(
            page=_governance_page_request(values),
            window=GovernanceTimeWindow(
                occurred_after=_governance_datetime(values.get("occurred_after")),
                occurred_before=_governance_datetime(values.get("occurred_before")),
            ),
            task_id=task_id,
            correlation_id=correlation_id,
        )
    except (TypeError, ValueError):
        raise _governance_query_error() from None


def _governance_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise _governance_query_error() from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _governance_query_error()
    return parsed.astimezone(UTC)


def _governance_query_error() -> ApiError:
    return ApiError(
        ApiErrorCode.GOVERNANCE_QUERY_INVALID,
        "governance query is invalid",
        status_code=400,
    )


def _set_governance_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Vary"] = "Cookie"


def _governance_policy_decision_body(
    item: PolicyDecisionView,
) -> GovernancePolicyDecisionBody:
    values = asdict(item)
    values.pop("tenant_id")
    return GovernancePolicyDecisionBody(**values)


def _governance_audit_body(item: AuditEventView) -> GovernanceAuditEventBody:
    values = asdict(item)
    values.pop("tenant_id")
    return GovernanceAuditEventBody(**values)


def _governance_security_body(
    item: SecurityEventView,
) -> GovernanceSecurityEventBody:
    values = asdict(item)
    values.pop("tenant_id")
    return GovernanceSecurityEventBody(**values)


def _assert_request_binding(
    identity: TrustedRequestIdentity, command: TaskCommand
) -> None:
    context = command.security_context
    context_mismatch = (
        identity.security_context is not None
        and identity.security_context.to_mapping() != context.to_mapping()
    )
    if (
        context_mismatch
        or identity.tenant_id != command.tenant_id
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


def _set_session_cookie(
    response: Response,
    config: OidcBffConfig,
    session: OidcSessionStart,
) -> None:
    _set_cookie(
        response,
        name=config.session_cookie_name,
        value=session.session_cookie,
        max_age=session.max_age_seconds,
        config=config,
    )


def _set_cookie(
    response: Response,
    *,
    name: str,
    value: str,
    max_age: int,
    config: OidcBffConfig,
) -> None:
    response.set_cookie(
        key=name,
        value=value,
        max_age=max_age,
        path="/",
        secure=config.cookie_secure,
        httponly=True,
        samesite=config.cookie_same_site,
    )


def _clear_cookie(
    response: Response,
    *,
    name: str,
    config: OidcBffConfig,
) -> None:
    response.delete_cookie(
        key=name,
        path="/",
        secure=config.cookie_secure,
        httponly=True,
        samesite=config.cookie_same_site,
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
        status=_approval_status_value(result.status),
        action_digest=result.action_digest,
        decided_at=result.decided_at,
    )


def _approval_status_value(
    status: ApprovalStatus,
) -> Literal["approved", "rejected", "revoked"]:
    """Narrow a decided domain status to the public response literal."""
    if status is ApprovalStatus.APPROVED:
        return "approved"
    if status is ApprovalStatus.REJECTED:
        return "rejected"
    if status is ApprovalStatus.REVOKED:
        return "revoked"
    raise ValueError("approval decision result has not reached a decision status")


def _task_body(task: Task) -> TaskBody:
    return TaskBody.model_validate_json(json.dumps(task.to_mapping()))


def _sse_frame(envelope: TaskEventEnvelope) -> str:
    if not isinstance(envelope, TaskEventEnvelope):
        raise TaskEventValidationError(
            TaskEventErrorCode.INVALID_SHAPE,
            path="sse.event",
        )
    envelope.assert_valid()
    try:
        data = json.dumps(
            envelope.to_mapping(),
            ensure_ascii=False,
            separators=(",", ":"),
        )
    except TaskEventValidationError:
        raise
    except (TypeError, ValueError):
        raise TaskEventValidationError(
            TaskEventErrorCode.INVALID_SHAPE,
            path="sse.frame",
        ) from None
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
    if code in _BAD_REQUEST_CODES or code in {
        ErrorCode.KNOWLEDGE_CONTRACT_INVALID,
        ErrorCode.KNOWLEDGE_CONTENT_UNSAFE,
    }:
        return 400
    if code in {
        ErrorCode.SECURITY_BINDING_MISMATCH,
        ErrorCode.APPROVAL_DUTIES_VIOLATION,
        ErrorCode.KNOWLEDGE_AUTHORIZATION_DENIED,
        ErrorCode.KNOWLEDGE_TENANT_MISMATCH,
        ErrorCode.KNOWLEDGE_PURPOSE_DENIED,
        ErrorCode.KNOWLEDGE_CLASSIFICATION_DENIED,
    }:
        return 403
    if code in {
        ErrorCode.TASK_NOT_FOUND,
        ErrorCode.APPROVAL_NOT_FOUND,
        ErrorCode.GOVERNANCE_NOT_FOUND,
        ErrorCode.KNOWLEDGE_NOT_FOUND,
        ErrorCode.KNOWLEDGE_REFERENCE_UNAVAILABLE,
    }:
        return 404
    if code in _CONFLICT_CODES or code in {
        ErrorCode.APPROVAL_CONFLICT,
        ErrorCode.APPROVAL_EXPIRED,
        ErrorCode.KNOWLEDGE_IDEMPOTENCY_CONFLICT,
        ErrorCode.KNOWLEDGE_ALREADY_EXISTS,
        ErrorCode.KNOWLEDGE_VERSION_CONFLICT,
        ErrorCode.KNOWLEDGE_LIFECYCLE_CONFLICT,
        ErrorCode.KNOWLEDGE_REFERENCE_MISMATCH,
    }:
        return 409
    if code in _UNAVAILABLE_CODES or code in {
        ErrorCode.KNOWLEDGE_AUTHORIZATION_UNAVAILABLE,
        ErrorCode.KNOWLEDGE_REPOSITORY_UNAVAILABLE,
        ErrorCode.KNOWLEDGE_CONTENT_PROJECTION_UNAVAILABLE,
    }:
        return 503
    if code in {
        ErrorCode.EXECUTION_PROTOCOL_ERROR,
        ErrorCode.REPOSITORY_PROTOCOL_ERROR,
        ErrorCode.TASK_INITIALIZATION_PROTOCOL_ERROR,
        ErrorCode.GOVERNANCE_REPOSITORY_PROTOCOL_ERROR,
        ErrorCode.GOVERNANCE_UNSAFE_PROJECTION,
        ErrorCode.KNOWLEDGE_AUTHORIZATION_PROTOCOL_ERROR,
        ErrorCode.KNOWLEDGE_REPOSITORY_PROTOCOL_ERROR,
        ErrorCode.KNOWLEDGE_CONTENT_PROJECTION_PROTOCOL_ERROR,
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


def _api_error_response(error: ApiError) -> JSONResponse:
    return _error_response(
        status_code=error.status_code,
        code=error.code.value,
        message=error.safe_message,
        retryable=error.retryable,
    )
