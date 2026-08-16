from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Any, Self

import httpx
import pytest
from fastapi import FastAPI
from flowpilot_api import (
    BrowserSessionBinding,
    GovernanceAccessPolicy,
    OidcRequestSecurity,
    create_app,
)
from flowpilot_application import (
    ApplicationError,
    AuditEventView,
    CorrelationChainView,
    ErrorCode,
    EventQuery,
    GovernancePage,
    GovernancePageRequest,
    GovernanceQueryContext,
    GovernanceQueryService,
    PolicyDecisionQuery,
    PolicyDecisionView,
    PolicyVersionView,
    SecurityEventView,
)
from flowpilot_domain import (
    ActorType,
    AssuranceLevel,
    AuthenticationMethod,
    AuthenticationRef,
    DataClassification,
    SecurityContextRef,
)
from flowpilot_security import (
    SecurityError,
    SecurityVerifier,
    TrustedSecurityContext,
    trusted_context_snapshot_hash,
)

NOW = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)
TENANT = "tenant-a"
OTHER_TENANT = "tenant-b"
COOKIE = "opaque-browser-session"
CURSOR = "gcur_" + "A" * 24
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64


def _policy_version() -> PolicyVersionView:
    return PolicyVersionView(
        version="policy-v9",
        bundle_digest=DIGEST_A,
        active=True,
        parent_version="policy-v8",
        published_at=NOW - timedelta(days=1),
    )


def _decision(*, tenant_id: str = TENANT) -> PolicyDecisionView:
    return PolicyDecisionView(
        tenant_id=tenant_id,
        decision_id="pd_decision01",
        task_id="task_task0001",
        decision="deny",
        policy_version="policy-v9",
        reason_codes=("TENANT_POLICY",),
        obligation_names=("audit_level",),
        action_digest=DIGEST_B,
        evaluated_at=NOW - timedelta(minutes=2),
        expires_at=NOW + timedelta(minutes=3),
    )


def _audit(*, tenant_id: str = TENANT) -> AuditEventView:
    return AuditEventView(
        tenant_id=tenant_id,
        event_id="evt_event0001",
        event_type="policy.decision.recorded.v1",
        occurred_at=NOW - timedelta(minutes=1),
        trace_id="trace-000000000001",
        thread_id="thread_thread01",
        task_id="task_task0001",
        run_id="run_run00001",
        correlation_id="correlation-001",
        causation_id="command-001",
        action="ticket.update.v1",
        decision="deny",
        reason_codes=("TENANT_POLICY",),
        result="blocked",
        data_classification="confidential",
        stream_id="audit-stream-tenant-a",
        sequence=7,
        event_hash=DIGEST_C,
        previous_hash=DIGEST_B,
        policy_decision_id="pd_decision01",
        policy_version="policy-v9",
        action_digest=DIGEST_B,
        security_event_id="sevt_event0001",
    )


def _security_event(*, tenant_id: str = TENANT) -> SecurityEventView:
    return SecurityEventView(
        tenant_id=tenant_id,
        event_id="sevt_event0001",
        event_type="security.authorization.denied.v1",
        occurred_at=NOW,
        trace_id="trace-000000000001",
        thread_id="thread_thread01",
        task_id="task_task0001",
        run_id="run_run00001",
        correlation_id="correlation-001",
        causation_id="evt_event0001",
        control_component="policy",
        control_rule_id="tenant-policy",
        control_rule_version="v9",
        reason_codes=("TENANT_POLICY",),
        severity="medium",
        category="authorization",
        control_outcome="blocked",
        impact="attempted",
        disposition="contained",
        data_classification="confidential",
        policy_decision_id="pd_decision01",
        audit_event_id="evt_event0001",
        event_hash=DIGEST_A,
    )


class FakeGovernancePort:
    def __init__(self) -> None:
        self.policy_versions = GovernancePage((_policy_version(),), CURSOR)
        self.policy_decisions = GovernancePage((_decision(),), CURSOR)
        self.audit_events = GovernancePage((_audit(),), CURSOR)
        self.security_events = GovernancePage((_security_event(),), CURSOR)
        self.correlation: CorrelationChainView | None = CorrelationChainView(
            tenant_id=TENANT,
            correlation_id="correlation-001",
            policy_decisions=(_decision(),),
            audit_events=(_audit(),),
            security_events=(_security_event(),),
        )
        self.calls: list[tuple[str, object]] = []
        self.failure: Exception | None = None

    def _fail(self) -> None:
        if self.failure is not None:
            raise self.failure

    async def list_policy_versions(
        self, page: GovernancePageRequest
    ) -> GovernancePage[PolicyVersionView]:
        self._fail()
        self.calls.append(("policy_versions", page))
        return self.policy_versions

    async def list_policy_decisions(
        self, query: PolicyDecisionQuery
    ) -> GovernancePage[PolicyDecisionView]:
        self._fail()
        self.calls.append(("policy_decisions", query))
        return self.policy_decisions

    async def list_audit_events(
        self, query: EventQuery
    ) -> GovernancePage[AuditEventView]:
        self._fail()
        self.calls.append(("audit_events", query))
        return self.audit_events

    async def list_security_events(
        self, query: EventQuery
    ) -> GovernancePage[SecurityEventView]:
        self._fail()
        self.calls.append(("security_events", query))
        return self.security_events

    async def get_correlation_chain(
        self, correlation_id: str
    ) -> CorrelationChainView | None:
        self._fail()
        self.calls.append(("correlation", correlation_id))
        return self.correlation


class FakeGovernanceUnitOfWork:
    def __init__(self, port: FakeGovernancePort) -> None:
        self.governance = port

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        return None


class FakeGovernanceUnitOfWorkFactory:
    def __init__(self, port: FakeGovernancePort) -> None:
        self.port = port
        self.contexts: list[GovernanceQueryContext] = []

    def __call__(self, context: GovernanceQueryContext) -> FakeGovernanceUnitOfWork:
        self.contexts.append(context)
        return FakeGovernanceUnitOfWork(self.port)


class FakeSessionSource:
    def __init__(self, binding: BrowserSessionBinding) -> None:
        self.binding = binding

    async def resolve_binding(self, session_id: str) -> BrowserSessionBinding | None:
        return self.binding if session_id == COOKIE else None


class FakeContextSource:
    def __init__(self, trusted: TrustedSecurityContext) -> None:
        self.trusted = trusted
        self.failure: SecurityError | None = None

    async def resolve(self, _context_ref: str) -> TrustedSecurityContext:
        if self.failure is not None:
            raise self.failure
        return self.trusted


def _trusted_context(
    *,
    roles: frozenset[str] = frozenset({"governance-reader"}),
    purpose: str = "security_review",
    active: bool = True,
    expires_at: datetime = NOW + timedelta(hours=1),
) -> TrustedSecurityContext:
    authentication = AuthenticationRef(
        method=AuthenticationMethod.OIDC,
        assurance_level=AssuranceLevel.SUBSTANTIAL,
        session_id_hash=DIGEST_A,
    )
    context_id = "secctx_context01"
    context_ref = "security-context/context01"
    issuer = "https://idp.example/realms/flowpilot"
    authorized_party = "flowpilot-web"
    token_hash = DIGEST_B
    context_hash = trusted_context_snapshot_hash(
        context_id=context_id,
        context_ref=context_ref,
        tenant_id=TENANT,
        subject_id="user-auditor",
        subject_type=ActorType.USER,
        issuer=issuer,
        authorized_party=authorized_party,
        roles=roles,
        scopes=frozenset({"governance:read"}),
        authentication=authentication,
        purpose=purpose,
        data_classification_ceiling=DataClassification.RESTRICTED,
        issued_at=NOW - timedelta(minutes=5),
        expires_at=expires_at,
        source_token_hash=token_hash,
    )
    context = SecurityContextRef(
        context_id=context_id,
        context_ref=context_ref,
        context_hash=context_hash,
        tenant_id=TENANT,
        subject_id="user-auditor",
        subject_type=ActorType.USER,
        purpose=purpose,
        authentication=authentication,
        data_classification_ceiling=DataClassification.RESTRICTED,
        issued_at=NOW - timedelta(minutes=5),
        expires_at=expires_at,
    )
    return TrustedSecurityContext(
        context=context,
        active=active,
        roles=roles,
        scopes=frozenset({"governance:read"}),
        issuer=issuer,
        authorized_party=authorized_party,
        identity_token_hash=token_hash,
    )


def _harness(
    *,
    trusted: TrustedSecurityContext | None = None,
) -> tuple[
    FastAPI, FakeGovernancePort, FakeGovernanceUnitOfWorkFactory, FakeContextSource
]:
    current = trusted or _trusted_context()
    contexts = FakeContextSource(current)
    binding = BrowserSessionBinding(
        session_id_hash=DIGEST_C,
        security_context=current.context,
        active=True,
        expires_at=NOW + timedelta(hours=1),
    )
    request_security = OidcRequestSecurity(
        sessions=FakeSessionSource(binding),
        contexts=contexts,
        verifier=SecurityVerifier(),
        cookie_name="flowpilot_session",
        clock=lambda: NOW,
    )
    port = FakeGovernancePort()
    factory = FakeGovernanceUnitOfWorkFactory(port)
    app = create_app(
        request_security=request_security,
        governance_queries=GovernanceQueryService(factory),
        governance_access=GovernanceAccessPolicy(
            allowed_roles=frozenset({"governance-reader"}),
            allowed_purposes=frozenset({"security_review"}),
        ),
    )
    return app, port, factory, contexts


def _request(
    app: FastAPI,
    path: str,
    *,
    cookie: bool = True,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://flowpilot.test",
        ) as client:
            if cookie:
                client.cookies.set("flowpilot_session", COOKIE)
            return await client.get(path, headers=headers)

    return asyncio.run(send())


def _run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


def test_application_pages_bind_trusted_context_and_validate_safe_projection() -> None:
    port = FakeGovernancePort()
    factory = FakeGovernanceUnitOfWorkFactory(port)
    service = GovernanceQueryService(factory)
    context = GovernanceQueryContext(
        tenant_id=TENANT,
        subject_id="user-auditor",
        purpose="security_review",
        security_context_ref="security-context/context01",
        security_context_hash=DIGEST_A,
    )

    page = _run(
        service.list_policy_decisions(
            context,
            PolicyDecisionQuery(GovernancePageRequest(limit=2), "task_task0001"),
        )
    )

    assert page.items == (_decision(),)
    assert factory.contexts == [context]


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda port: setattr(
                port,
                "policy_decisions",
                GovernancePage((_decision(tenant_id=OTHER_TENANT),)),
            ),
            ErrorCode.GOVERNANCE_REPOSITORY_PROTOCOL_ERROR,
        ),
        (
            lambda port: setattr(
                port, "policy_decisions", GovernancePage((_decision(), _decision()))
            ),
            ErrorCode.GOVERNANCE_REPOSITORY_PROTOCOL_ERROR,
        ),
        (
            lambda port: setattr(
                port, "policy_decisions", GovernancePage((_decision(),), "forged")
            ),
            ErrorCode.GOVERNANCE_REPOSITORY_PROTOCOL_ERROR,
        ),
        (
            lambda port: setattr(
                port,
                "policy_decisions",
                GovernancePage(
                    (replace(_decision(), reason_codes=("sk-admin-" + "A" * 32,)),)
                ),
            ),
            ErrorCode.GOVERNANCE_UNSAFE_PROJECTION,
        ),
    ],
)
def test_application_rejects_cross_tenant_duplicate_bad_cursor_and_secret_projection(
    mutate: Callable[[FakeGovernancePort], None],
    expected: ErrorCode,
) -> None:
    port = FakeGovernancePort()
    mutate(port)
    service = GovernanceQueryService(FakeGovernanceUnitOfWorkFactory(port))
    context = GovernanceQueryContext(
        TENANT,
        "user-auditor",
        "security_review",
        "security-context/context01",
        DIGEST_A,
    )

    with pytest.raises(ApplicationError) as caught:
        _run(
            service.list_policy_decisions(
                context,
                PolicyDecisionQuery(GovernancePageRequest(limit=2)),
            )
        )

    assert caught.value.code is expected


def test_application_maps_backend_failure_and_missing_correlation() -> None:
    port = FakeGovernancePort()
    service = GovernanceQueryService(FakeGovernanceUnitOfWorkFactory(port))
    context = GovernanceQueryContext(
        TENANT,
        "user-auditor",
        "security_review",
        "security-context/context01",
        DIGEST_A,
    )
    port.failure = RuntimeError("database DSN and credential must stay private")
    with pytest.raises(ApplicationError) as unavailable:
        _run(service.list_policy_versions(context, GovernancePageRequest()))
    assert unavailable.value.code is ErrorCode.GOVERNANCE_REPOSITORY_UNAVAILABLE
    assert "credential" not in unavailable.value.safe_message

    port.failure = None
    port.correlation = None
    with pytest.raises(ApplicationError) as missing:
        _run(service.get_correlation_chain(context, "correlation-001"))
    assert missing.value.code is ErrorCode.GOVERNANCE_NOT_FOUND


def test_all_governance_routes_return_closed_safe_projections() -> None:
    app, port, factory, _contexts = _harness()

    paths = (
        "/v1/governance/policy-versions?limit=2",
        "/v1/governance/policy-decisions?task_id=task_task0001",
        "/v1/governance/audit-events?correlation_id=correlation-001",
        "/v1/governance/security-events?occurred_after=2026-08-16T08:00:00Z",
        "/v1/governance/correlations/correlation-001",
    )
    responses = [_request(app, path) for path in paths]

    assert [response.status_code for response in responses] == [200] * 5
    assert all(
        response.headers["cache-control"] == "no-store" for response in responses
    )
    assert all(response.headers["vary"] == "Cookie" for response in responses)
    serialized = "".join(response.text for response in responses)
    for forbidden in (
        "tenant_id",
        "subject_id",
        "input_preimage",
        "prompt",
        "tool_arguments",
        "arguments_redacted",
        "evidence_refs",
        "credential",
        "hidden_reasoning",
    ):
        assert forbidden not in serialized
    assert len(port.calls) == 5
    assert all(context.tenant_id == TENANT for context in factory.contexts)


@pytest.mark.parametrize(
    "path",
    [
        "/v1/governance/policy-versions?limit=0",
        "/v1/governance/policy-versions?cursor=forged",
        "/v1/governance/policy-versions?limit=2&limit=3",
        "/v1/governance/policy-decisions?tenant_id=tenant-b",
        "/v1/governance/audit-events?prompt=ignore",
        "/v1/governance/audit-events?occurred_after=2026-08-16T10:00:00Z&occurred_before=2026-08-16T09:00:00Z",
        "/v1/governance/correlations/correlation-001?role=administrator",
    ],
)
def test_invalid_forged_or_sensitive_query_is_rejected_before_repository(
    path: str,
) -> None:
    app, port, _factory, _contexts = _harness()

    response = _request(app, path)

    assert response.status_code == 400
    expected_code = (
        "CORE_GOVERNANCE_CURSOR_INVALID"
        if "cursor=forged" in path
        else "API_GOVERNANCE_QUERY_INVALID"
    )
    assert response.json()["error"]["code"] == expected_code
    assert port.calls == []


@pytest.mark.parametrize(
    ("cookie", "headers", "status", "code"),
    [
        (False, None, 401, "API_AUTHENTICATION_REQUIRED"),
        (
            True,
            {"Authorization": "Bearer browser-token"},
            401,
            "API_AUTHENTICATION_INVALID",
        ),
        (True, {"X-Tenant-Id": "tenant-b"}, 403, "API_AUTHORIZATION_DENIED"),
        (True, {"X-Role": "governance-reader"}, 403, "API_AUTHORIZATION_DENIED"),
        (True, {"X-Purpose": "security_review"}, 403, "API_AUTHORIZATION_DENIED"),
    ],
)
def test_governance_api_is_cookie_only_and_rejects_identity_overrides(
    cookie: bool,
    headers: dict[str, str] | None,
    status: int,
    code: str,
) -> None:
    app, port, _factory, _contexts = _harness()

    response = _request(
        app,
        "/v1/governance/policy-versions",
        cookie=cookie,
        headers=headers,
    )

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert port.calls == []
    assert "browser-token" not in response.text


@pytest.mark.parametrize(
    ("trusted", "status"),
    [
        (_trusted_context(roles=frozenset({"requester"})), 403),
        (_trusted_context(purpose="it_support"), 403),
        (_trusted_context(active=False), 401),
        (_trusted_context(expires_at=NOW), 401),
    ],
)
def test_governance_api_revalidates_role_purpose_and_context_each_request(
    trusted: TrustedSecurityContext,
    status: int,
) -> None:
    app, port, _factory, _contexts = _harness(trusted=trusted)

    response = _request(app, "/v1/governance/security-events")

    assert response.status_code == status
    assert port.calls == []


def test_repository_errors_are_stable_and_do_not_leak_backend_details() -> None:
    app, port, _factory, _contexts = _harness()
    port.failure = RuntimeError("postgres://admin:secret@tenant-b.internal")

    response = _request(app, "/v1/governance/audit-events")

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "CORE_GOVERNANCE_REPOSITORY_UNAVAILABLE",
        "message": "governance repository is unavailable",
        "retryable": True,
        "detail_ref": None,
    }
    assert "postgres" not in response.text
    assert "tenant-b" not in response.text


def test_cross_tenant_projection_and_repository_cursor_rejection_are_stable() -> None:
    app, port, _factory, _contexts = _harness()
    port.policy_decisions = GovernancePage((_decision(tenant_id=OTHER_TENANT),))

    cross_tenant = _request(app, "/v1/governance/policy-decisions")

    assert cross_tenant.status_code == 502
    assert cross_tenant.json()["error"]["code"] == (
        "CORE_GOVERNANCE_REPOSITORY_PROTOCOL_ERROR"
    )
    assert OTHER_TENANT not in cross_tenant.text

    port.failure = ApplicationError(
        ErrorCode.GOVERNANCE_CURSOR_INVALID,
        "governance cursor is invalid",
    )
    cursor = _request(
        app,
        f"/v1/governance/policy-decisions?cursor={CURSOR}",
    )

    assert cursor.status_code == 400
    assert cursor.json()["error"]["code"] == "CORE_GOVERNANCE_CURSOR_INVALID"


def test_missing_governance_composition_fails_closed() -> None:
    response = _request(create_app(), "/v1/governance/policy-versions", cookie=False)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "API_DEPENDENCY_UNAVAILABLE"
