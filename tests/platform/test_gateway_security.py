from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from factories import (
    AUDIENCE,
    NOW,
    OTHER_TENANT,
    make_fixture,
)
from flowpilot_domain import (
    ActionTool,
    ApprovalStatus,
    DataClassification,
    ToolOperation,
    canonical_sha256,
)
from flowpilot_mcp_gateway import DEBUG_PROJECTION_KEYS, GatewayReason
from flowpilot_policy import PolicyDecisionKind
from flowpilot_tool_contracts import ToolRequest, ToolResultStatus


async def ledger_record(fixture, execution_id: str):
    async with fixture.data_uow() as uow:
        return await uow.ledger.get(
            fixture.invocation.request.security_context.tenant_id,
            execution_id,
        )


async def outbox_items(fixture):
    async with fixture.data_uow() as uow:
        return await uow.outbox.unpublished(
            fixture.invocation.request.security_context.tenant_id,
            now=NOW + timedelta(days=1),
            limit=100,
        )


@pytest.mark.asyncio
async def test_read_tool_is_tenant_filtered_and_observable() -> None:
    fixture = make_fixture(operation=ToolOperation.READ)

    execution = await fixture.gateway.execute(fixture.invocation)

    assert execution.result.status is ToolResultStatus.VERIFIED
    assert execution.result.data is not None
    assert execution.result.data["returned_count"] == 1
    records = execution.result.data["records"]
    assert isinstance(records, tuple)
    assert records[0]["record_id"] == "kb-alpha-1"
    assert fixture.adapter.invocation_count == 1
    assert await ledger_record(fixture, execution.result.execution_id) is None
    assert len(fixture.signals.audits) == 1
    assert fixture.signals.security == []
    assert set(execution.debug_projection) == DEBUG_PROJECTION_KEYS
    assert [event.sequence for event in execution.lifecycle] == list(
        range(1, len(execution.lifecycle) + 1)
    )
    assert {"identity", "registry", "policy", "approval", "upstream", "audit"} <= {
        event.stage.value for event in execution.lifecycle
    }


@pytest.mark.asyncio
async def test_trace_sampling_does_not_sample_audit() -> None:
    fixture = make_fixture(operation=ToolOperation.READ)
    fixture.signals.trace_sampled = True

    execution = await fixture.gateway.execute(fixture.invocation)

    assert execution.result.status is ToolResultStatus.VERIFIED
    assert fixture.signals.traces == []
    assert len(fixture.signals.audits) == 1


@pytest.mark.asyncio
async def test_limit_records_and_mask_obligations_are_enforced() -> None:
    fixture = make_fixture(
        operation=ToolOperation.READ,
        obligations=[
            {"name": "limit_records", "parameters": {"maximum": 1}},
            {
                "name": "mask_fields",
                "parameters": {"fields": ["returned_count"]},
            },
            {"name": "audit_level", "parameters": {"level": "security"}},
            {
                "name": "credential_ttl_seconds",
                "parameters": {"seconds": 60},
            },
        ],
    )

    execution = await fixture.gateway.execute(fixture.invocation)

    assert execution.result.status is ToolResultStatus.VERIFIED
    assert execution.result.data is not None
    assert execution.result.data["returned_count"] == "[REDACTED]"
    assert execution.result.redaction_summary is not None
    assert execution.result.redaction_summary["masked_fields"] == (
        "returned_count",
    )


@pytest.mark.asyncio
async def test_cross_tenant_forgery_has_no_ledger_outbox_or_upstream_call() -> None:
    fixture = make_fixture()
    forged_action = replace(fixture.action, tenant_id=OTHER_TENANT)
    invocation = fixture.replace_invocation(action=forged_action)

    execution = await fixture.gateway.execute(invocation)

    assert execution.result.status is ToolResultStatus.FAILED_FINAL
    assert execution.result.error_code == "PLATFORM_TENANT_MISMATCH"
    assert fixture.adapter.invocation_count == 0
    assert await ledger_record(fixture, execution.result.execution_id) is None
    assert await outbox_items(fixture) == ()
    assert len(fixture.signals.audits) == 1
    assert len(fixture.signals.security) == 1
    audit = fixture.signals.audits[0]
    security = fixture.signals.security[0]
    assert audit.security_event_id == security.event_id
    assert security.audit_event_id == audit.event_id


@pytest.mark.asyncio
async def test_forged_context_tenant_cannot_stamp_security_event_tenant() -> None:
    fixture = make_fixture()
    forged_context = replace(
        fixture.invocation.request.security_context,
        tenant_id=OTHER_TENANT,
    )
    forged_action = replace(fixture.action, tenant_id=OTHER_TENANT)
    request_mapping = fixture.invocation.request.to_mapping()
    request_mapping["security_context"] = forged_context.to_mapping()
    request_mapping["planned_action"] = forged_action.to_mapping()
    request_mapping["action_digest"] = forged_action.digest()
    request = ToolRequest.from_mapping(request_mapping)
    invocation = replace(fixture.invocation, request=request)

    execution = await fixture.gateway.execute(invocation)

    assert execution.result.error_code == "PLATFORM_SECURITY_CONTEXT_UNTRUSTED"
    assert fixture.adapter.invocation_count == 0
    assert fixture.signals.audits[0].tenant_id == "tenant-alpha"
    assert fixture.signals.security[0].tenant_id == "tenant-alpha"
    assert fixture.signals.security[0].context is fixture.context_source.context


@pytest.mark.asyncio
async def test_wrong_workload_audience_is_rejected_before_ledger() -> None:
    fixture = make_fixture()
    workload = replace(
        fixture.invocation.workload,
        audience=AUDIENCE + "/forged",
    )

    execution = await fixture.gateway.execute(
        fixture.replace_invocation(workload=workload)
    )

    assert execution.result.error_code == "PLATFORM_AUDIENCE_MISMATCH"
    assert fixture.adapter.invocation_count == 0
    assert await ledger_record(fixture, execution.result.execution_id) is None
    assert await outbox_items(fixture) == ()


@pytest.mark.asyncio
async def test_context_classification_ceiling_is_enforced() -> None:
    fixture = make_fixture()
    changed_action = replace(
        fixture.action,
        data_classification=DataClassification.RESTRICTED,
    )

    execution = await fixture.gateway.execute(
        fixture.replace_invocation(action=changed_action)
    )

    assert execution.result.error_code == "PLATFORM_SECURITY_CONTEXT_UNTRUSTED"
    assert fixture.adapter.invocation_count == 0
    assert await ledger_record(fixture, execution.result.execution_id) is None


@pytest.mark.asyncio
async def test_expired_context_is_rejected_before_policy_or_ledger() -> None:
    fixture = make_fixture()
    expired = replace(
        fixture.invocation.request.security_context,
        expires_at=NOW - timedelta(seconds=1),
    )
    fixture.context_source.context = expired
    request_mapping = fixture.invocation.request.to_mapping()
    request_mapping["security_context"] = expired.to_mapping()
    request = ToolRequest.from_mapping(request_mapping)
    invocation = replace(fixture.invocation, request=request)

    execution = await fixture.gateway.execute(invocation)

    assert execution.result.error_code == "PLATFORM_SECURITY_CONTEXT_EXPIRED"
    assert fixture.adapter.invocation_count == 0
    assert await ledger_record(fixture, execution.result.execution_id) is None


@pytest.mark.asyncio
async def test_schema_hash_change_is_rejected_by_registry() -> None:
    fixture = make_fixture()
    changed_tool = ActionTool(
        name=fixture.action.tool.name,
        schema_hash=canonical_sha256({"changed_schema": True}),
        operation=fixture.action.tool.operation,
    )
    changed_action = replace(fixture.action, tool=changed_tool)

    execution = await fixture.gateway.execute(
        fixture.replace_invocation(action=changed_action)
    )

    assert (
        execution.result.error_code
        == GatewayReason.TOOL_SCHEMA_MISMATCH.value
    )
    assert fixture.adapter.invocation_count == 0
    assert await ledger_record(fixture, execution.result.execution_id) is None


@pytest.mark.asyncio
async def test_capability_ttl_is_clamped_to_authorization_expiry() -> None:
    fixture = make_fixture()
    short_action = replace(
        fixture.action,
        expires_at=NOW + timedelta(seconds=45),
    )
    fixture.replace_policy_for_action(short_action)
    invocation = fixture.replace_invocation(action=short_action)

    execution = await fixture.gateway.execute(invocation)

    assert execution.result.status is ToolResultStatus.VERIFIED
    assert fixture.credentials.last_ttl_seconds is not None
    assert 1 <= fixture.credentials.last_ttl_seconds <= 45


@pytest.mark.asyncio
async def test_policy_unavailable_is_fail_closed_before_ledger() -> None:
    fixture = make_fixture()
    fixture.policy_source.available = False

    execution = await fixture.gateway.execute(fixture.invocation)

    assert execution.result.error_code == "PLATFORM_POLICY_UNAVAILABLE"
    assert fixture.adapter.invocation_count == 0
    assert await ledger_record(fixture, execution.result.execution_id) is None
    assert await outbox_items(fixture) == ()


@pytest.mark.asyncio
async def test_policy_deny_is_fail_closed() -> None:
    fixture = make_fixture(decision_kind=PolicyDecisionKind.DENY)

    execution = await fixture.gateway.execute(fixture.invocation)

    assert execution.result.error_code == "PLATFORM_POLICY_DENIED"
    assert fixture.adapter.invocation_count == 0
    assert await ledger_record(fixture, execution.result.execution_id) is None


@pytest.mark.asyncio
async def test_parameter_change_invalidates_existing_approval() -> None:
    fixture = make_fixture(
        decision_kind=PolicyDecisionKind.REQUIRE_APPROVAL
    )
    changed_action = replace(
        fixture.action,
        arguments={"ticket_id": "TCK-100", "status": "in_progress"},
    )
    fixture.replace_policy_for_action(changed_action)
    invocation = fixture.replace_invocation(action=changed_action)

    execution = await fixture.gateway.execute(invocation)

    assert execution.result.error_code == "PLATFORM_APPROVAL_INVALID"
    assert fixture.adapter.invocation_count == 0
    assert await ledger_record(fixture, execution.result.execution_id) is None
    assert (
        fixture.signals.audits[0].policy_decision_id
        == fixture.policy.decision_id
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    ["tool_schema_hash", "policy_version", "expires_at", "requester_id"],
)
async def test_approval_binding_tamper_is_rejected(change: str) -> None:
    fixture = make_fixture(
        decision_kind=PolicyDecisionKind.REQUIRE_APPROVAL
    )
    assert fixture.approval is not None
    if change == "tool_schema_hash":
        changed = replace(
            fixture.approval,
            tool_schema_hash=canonical_sha256({"forged": "schema"}),
        )
    elif change == "policy_version":
        changed = replace(fixture.approval, policy_version="forged-policy")
    elif change == "expires_at":
        changed = replace(
            fixture.approval,
            expires_at=fixture.action.expires_at - timedelta(seconds=1),
        )
    else:
        changed = replace(fixture.approval, requester_id="user-forged")
    fixture.approval_source.approval = changed

    execution = await fixture.gateway.execute(fixture.invocation)

    assert execution.result.error_code == "PLATFORM_APPROVAL_INVALID"
    assert fixture.adapter.invocation_count == 0
    assert await ledger_record(fixture, execution.result.execution_id) is None


@pytest.mark.asyncio
async def test_revoked_approval_and_forged_role_are_rejected() -> None:
    fixture = make_fixture(
        decision_kind=PolicyDecisionKind.REQUIRE_APPROVAL
    )
    assert fixture.approval is not None
    fixture.approval_source.approval = replace(
        fixture.approval,
        status=ApprovalStatus.REVOKED,
    )

    revoked = await fixture.gateway.execute(fixture.invocation)

    assert revoked.result.error_code == "PLATFORM_APPROVAL_REQUIRED"
    assert fixture.adapter.invocation_count == 0

    fixture = make_fixture(
        decision_kind=PolicyDecisionKind.REQUIRE_APPROVAL
    )
    fixture.approvers.authorized = False
    forged = await fixture.gateway.execute(fixture.invocation)
    assert forged.result.error_code == "PLATFORM_SEPARATION_OF_DUTIES"
    assert fixture.adapter.invocation_count == 0


@pytest.mark.asyncio
async def test_malicious_read_output_is_rejected_and_not_projected() -> None:
    fixture = make_fixture(operation=ToolOperation.READ)

    class MaliciousAdapter:
        invocation_count = 0

        async def invoke(self, **kwargs):
            del kwargs
            self.invocation_count += 1
            from flowpilot_mcp_gateway import ToolInvocationResult

            return ToolInvocationResult(
                data={
                    "records": [],
                    "returned_count": 0,
                    "password": "secret-value",
                }
            )

        async def readback(self, **kwargs):
            raise AssertionError(kwargs)

        async def reconcile(self, **kwargs):
            raise AssertionError(kwargs)

    malicious = MaliciousAdapter()
    definition = next(iter(fixture.gateway._deps.registry._by_name.values()))
    registry = type(fixture.gateway._deps.registry)(
        (replace(definition, adapter=malicious),)
    )
    fixture.gateway = type(fixture.gateway)(
        replace(fixture.gateway._deps, registry=registry)
    )

    execution = await fixture.gateway.execute(fixture.invocation)

    assert execution.result.status is ToolResultStatus.FAILED_FINAL
    assert execution.result.error_code == "PLATFORM_TOOL_OUTPUT_INVALID"
    assert execution.result.data is None
    assert malicious.invocation_count == 1
    assert len(fixture.signals.security) == 1


@pytest.mark.asyncio
async def test_read_mcp_unavailable_has_stable_operational_failure() -> None:
    fixture = make_fixture(operation=ToolOperation.READ)

    class UnavailableAdapter:
        invocation_count = 0

        async def invoke(self, **kwargs):
            del kwargs
            self.invocation_count += 1
            raise RuntimeError("provider-specific failure")

        async def readback(self, **kwargs):
            raise AssertionError(kwargs)

        async def reconcile(self, **kwargs):
            raise AssertionError(kwargs)

    unavailable = UnavailableAdapter()
    definition = next(iter(fixture.gateway._deps.registry._by_name.values()))
    registry = type(fixture.gateway._deps.registry)(
        (replace(definition, adapter=unavailable),)
    )
    fixture.gateway = type(fixture.gateway)(
        replace(fixture.gateway._deps, registry=registry)
    )

    execution = await fixture.gateway.execute(fixture.invocation)

    assert (
        execution.result.error_code
        == GatewayReason.UPSTREAM_UNAVAILABLE.value
    )
    assert unavailable.invocation_count == 1
    assert len(fixture.signals.audits) == 1
    assert fixture.signals.security == []
