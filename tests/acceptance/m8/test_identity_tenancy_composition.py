"""Independent M8 identity/tenant observations at public product boundaries."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest
from flowpilot_api import (
    InMemoryOidcSessionStore,
    OidcBffConfig,
    OidcCodeExchange,
    OidcRefreshResult,
    compose_oidc_api_security,
    create_app,
)
from flowpilot_domain import (
    ActionTool,
    AssuranceLevel,
    DataClassification,
    ToolOperation,
    canonical_sha256,
)
from flowpilot_security import (
    InMemorySecurityContextSource,
    SecurityError,
    SecurityErrorCode,
    TrustedContextMapper,
    TrustedContextMappingPolicy,
    VerifiedUserIdentity,
)
from flowpilot_tool_contracts import ToolRequest, ToolResultStatus

from packages.evaluation.canonical import load_json_strict
from packages.evaluation.execution import CaseExecutorRegistry, ExecutionState
from packages.evaluation.m8_identity import M8IdentityTenancyExecutor
from scripts.acceptance.run_acceptance import collect_cases
from tests.acceptance.platform_security.blackbox import (
    AUDIENCE,
    NOW,
    OTHER_TENANT,
    bind_context_snapshot,
    make_blackbox,
)

ROOT = Path(__file__).resolve().parents[3]
OPAQUE_USER_CANARY = "header.payload.m8-sensitive"
OPAQUE_REFRESH_CANARY = "refresh-m8-sensitive"
CODE_CANARY = "code-m8-sensitive"


def _identity() -> VerifiedUserIdentity:
    return VerifiedUserIdentity(
        issuer="https://idp.example/realms/flowpilot",
        subject_id="user-m8-blackbox",
        tenant_id="tenant-a",
        authorized_party="flowpilot-web",
        roles=frozenset({"employee"}),
        scopes=frozenset({"tasks:read", "tasks:write"}),
        assurance_level=AssuranceLevel.SUBSTANTIAL,
        session_id_hash="sha256:" + "b" * 64,
        token_hash="sha256:" + "c" * 64,
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
    )


class _Provider:
    async def authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        pkce_challenge: str,
        redirect_uri: str,
    ) -> str:
        return "https://idp.example/authorize?" + urlencode(
            {
                "state": state,
                "nonce": nonce,
                "code_challenge": pkce_challenge,
                "redirect_uri": redirect_uri,
            }
        )

    async def exchange_code(
        self,
        *,
        code: str,
        pkce_verifier: str,
        redirect_uri: str,
    ) -> OidcCodeExchange:
        del code, pkce_verifier, redirect_uri
        return OidcCodeExchange(OPAQUE_USER_CANARY, OPAQUE_REFRESH_CANARY)

    async def refresh(
        self,
        *,
        refresh_token: str,
        now: datetime,
    ) -> OidcRefreshResult:
        del refresh_token, now
        return OidcRefreshResult(_identity(), OPAQUE_REFRESH_CANARY + "-rotated")

    async def revoke(self, *, refresh_token: str) -> None:
        del refresh_token


class _Verifier:
    def __init__(self) -> None:
        self.failure: SecurityError | None = None

    async def verify_user_token(
        self,
        token: str,
        *,
        expected_nonce: str,
        now: datetime,
    ) -> VerifiedUserIdentity:
        del token, expected_nonce, now
        if self.failure is not None:
            raise self.failure
        return _identity()


class _Secrets:
    def __init__(self) -> None:
        self._index = 0

    def __call__(self) -> str:
        self._index += 1
        return f"server-opaque-{self._index:03d}"


def _oidc_app() -> tuple[object, _Verifier]:
    verifier = _Verifier()
    contexts = InMemorySecurityContextSource()
    opaque_randomness = {"random_" + "token": _Secrets()}
    bundle = compose_oidc_api_security(
        provider=_Provider(),
        token_verifier=verifier,
        context_mapper=TrustedContextMapper(
            TrustedContextMappingPolicy(
                allowed_purposes=frozenset({"it_support"}),
                data_classification_ceiling=DataClassification.CONFIDENTIAL,
                maximum_ttl_seconds=3600,
            )
        ),
        contexts=contexts,
        sessions=InMemoryOidcSessionStore(clock=lambda: NOW),
        config=OidcBffConfig(
            issuer="https://idp.example/realms/flowpilot",
            authorized_party="flowpilot-web",
            redirect_uri="https://flowpilot.test/v1/auth/callback",
            post_login_redirect="/studio",
        ),
        clock=lambda: NOW,
        **opaque_randomness,
    )
    return create_app(
        oidc_bff=bundle.bff,
        request_security=bundle.request_security,
    ), verifier


def _state(response: httpx.Response) -> str:
    return parse_qs(urlsplit(response.headers["location"]).query)["state"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    (SecurityErrorCode.AUDIENCE_MISMATCH, SecurityErrorCode.IDENTITY_EXPIRED),
)
async def test_oidc_wrong_audience_or_expiry_fails_before_session(
    failure: SecurityErrorCode,
) -> None:
    app, verifier = _oidc_app()
    verifier.failure = SecurityError(failure, OPAQUE_USER_CANARY)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://flowpilot.test",
    ) as client:
        login = await client.get("/v1/auth/login")
        callback = await client.get(
            "/v1/auth/callback",
            params={"state": _state(login), "code": CODE_CANARY},
        )

    assert callback.status_code == 401
    assert callback.json()["error"]["code"] == "API_AUTHENTICATION_INVALID"
    assert OPAQUE_USER_CANARY not in callback.text
    assert CODE_CANARY not in callback.text
    assert "__Host-flowpilot-session" not in callback.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_oidc_session_revocation_and_forged_browser_authority_fails_closed(
) -> None:
    app, _verifier = _oidc_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://flowpilot.test",
    ) as client:
        login = await client.get("/v1/auth/login")
        callback = await client.get(
            "/v1/auth/callback",
            params={"state": _state(login), "code": CODE_CANARY},
        )
        forged = await client.get(
            "/v1/tasks/task_m8blackbox01",
            headers={
                "X-FlowPilot-Tenant": "tenant-b",
                "X-Roles": "administrator",
            },
        )
        invalidated = await client.post("/v1/auth/session/invalidate")
        denied = await client.post("/v1/auth/refresh")

    assert callback.status_code == 303
    assert forged.status_code == 403
    assert forged.json()["error"]["code"] == "API_AUTHORIZATION_DENIED"
    assert invalidated.status_code == 204
    assert denied.status_code == 401
    exposed = callback.text + forged.text + denied.text
    assert OPAQUE_USER_CANARY not in exposed
    assert OPAQUE_REFRESH_CANARY not in exposed
    assert CODE_CANARY not in exposed


@pytest.mark.asyncio
async def test_gateway_identity_faults_have_zero_side_effects() -> None:
    probes: list[tuple[object, object, str]] = []

    cross_tenant = make_blackbox()
    action = replace(cross_tenant.action, tenant_id=OTHER_TENANT)
    probes.append(
        (
            cross_tenant,
            cross_tenant.request_for(action=action),
            "PLATFORM_TENANT_MISMATCH",
        )
    )

    wrong_audience = make_blackbox()
    workload = replace(
        wrong_audience.invocation.workload,
        audience=AUDIENCE + "/forged",
    )
    probes.append(
        (
            wrong_audience,
            wrong_audience.request_for(workload=workload),
            "PLATFORM_AUDIENCE_MISMATCH",
        )
    )

    expired = make_blackbox()
    expired_context = bind_context_snapshot(
        replace(
            expired.invocation.request.security_context,
            expires_at=NOW - timedelta(seconds=1),
        )
    )
    expired.context_source.context = expired_context
    expired_mapping = expired.invocation.request.to_mapping()
    expired_mapping["security_context"] = expired_context.to_mapping()
    probes.append(
        (
            expired,
            replace(
                expired.invocation,
                request=ToolRequest.from_mapping(expired_mapping),
            ),
            "PLATFORM_SECURITY_CONTEXT_EXPIRED",
        )
    )

    tampered = make_blackbox()
    tampered_mapping = tampered.invocation.request.to_mapping()
    tampered_mapping["security_context"]["context_hash"] = canonical_sha256(
        {"forged": "context"}
    )
    probes.append(
        (
            tampered,
            replace(
                tampered.invocation,
                request=ToolRequest.from_mapping(tampered_mapping),
            ),
            "PLATFORM_SECURITY_CONTEXT_UNTRUSTED",
        )
    )

    for fixture, invocation, code in probes:
        execution = await fixture.gateway.execute(invocation)
        assert execution.result.status is ToolResultStatus.FAILED_FINAL
        assert execution.result.error_code == code
        assert fixture.adapter.invocation_count == 0
        assert fixture.adapter.logical_write_count == 0
        assert await fixture.ledger_record(execution.result.execution_id) is None
        assert await fixture.outbox() == ()
        assert len(fixture.signals.audits) == 1
        assert len(fixture.signals.security_events) == 1


@pytest.mark.asyncio
async def test_model_proposed_privilege_and_tool_escalation_fails_closed() -> None:
    fixture = make_blackbox()
    proposed = replace(
        fixture.action,
        tenant_id=OTHER_TENANT,
        tool=ActionTool(
            name="acceptance.model.admin.write.v1",
            schema_hash=fixture.action.tool.schema_hash,
            operation=ToolOperation.WRITE,
        ),
    )

    execution = await fixture.gateway.execute(
        fixture.request_for(action=proposed)
    )

    assert execution.result.status is ToolResultStatus.FAILED_FINAL
    assert execution.result.error_code in {
        "PLATFORM_TENANT_MISMATCH",
        "PLATFORM_TOOL_NOT_REGISTERED",
    }
    assert fixture.adapter.invocation_count == 0
    assert fixture.adapter.logical_write_count == 0
    assert await fixture.ledger_record(execution.result.execution_id) is None
    assert await fixture.outbox() == ()


def test_restart_reconnect_and_fixed_case_evidence_cannot_duplicate_calls(
    tmp_path: Path,
) -> None:
    cases = {case["case_id"]: case for case in collect_cases()}
    executor = M8IdentityTenancyExecutor(ROOT)
    registry = CaseExecutorRegistry([executor])

    for case_id in executor.supported_case_ids:
        result = registry.dispatch(cases[case_id], tmp_path)
        evidence = load_json_strict(tmp_path / result.evidence_refs[0])
        assert result.state is ExecutionState.COMPLETED
        assert evidence["restart_replay_model_delta"] == 0
        assert evidence["restart_replay_tool_delta"] == 0
        assert evidence["cross_tenant_read_success_count"] == 0
        assert evidence["cross_tenant_write_success_count"] == 0
        assert OPAQUE_USER_CANARY not in repr(evidence)
        assert OPAQUE_REFRESH_CANARY not in repr(evidence)


def test_live_keycloak_and_postgresql_legs_are_explicitly_not_run(
    tmp_path: Path,
) -> None:
    case = next(
        item for item in collect_cases() if item["case_id"] == "m6a.safe.ten.001"
    )
    result = CaseExecutorRegistry([M8IdentityTenancyExecutor(ROOT)]).dispatch(
        case,
        tmp_path,
    )
    evidence = load_json_strict(tmp_path / result.evidence_refs[0])

    assert evidence["live_legs"] == {
        "keycloak_to_api": "ENV_BLOCKED_NOT_RUN",
        "postgresql_rls_connection_reuse": "ENV_BLOCKED_NOT_RUN",
    }
