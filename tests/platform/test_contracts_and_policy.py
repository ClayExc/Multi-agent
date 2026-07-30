from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from factories import NOW, make_fixture
from flowpilot_domain import canonical_sha256
from flowpilot_policy import (
    PolicyDecision,
    PolicyDecisionKind,
    PolicyError,
    PolicyErrorCode,
)
from flowpilot_security import SecurityError, SecurityErrorCode, assert_safe_projection
from flowpilot_tool_contracts import (
    ToolContract,
    ToolContractError,
    ToolContractErrorCode,
    ToolRequest,
)


def test_tool_contract_hash_binds_input_and_output_schema() -> None:
    original = ToolContract.create(
        name="fixture.read.v1",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["query"],
            "properties": {"query": {"type": "string"}},
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["value"],
            "properties": {"value": {"type": "string"}},
        },
    )
    changed = ToolContract.create(
        name="fixture.read.v1",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["query"],
            "properties": {"query": {"type": "string", "maxLength": 32}},
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["value"],
            "properties": {"value": {"type": "string"}},
        },
    )

    assert original.schema_hash != changed.schema_hash


def test_tool_contract_requires_closed_object_schemas() -> None:
    with pytest.raises(ToolContractError) as captured:
        ToolContract.create(
            name="fixture.read.v1",
            input_schema={"type": "object"},
            output_schema={
                "type": "object",
                "additionalProperties": False,
            },
        )

    assert captured.value.code is ToolContractErrorCode.SCHEMA_INVALID


def test_tool_contract_rejects_unknown_schema_keywords() -> None:
    with pytest.raises(ToolContractError) as captured:
        ToolContract.create(
            name="fixture.read.v1",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {},
                "unevaluatedProperties": True,
            },
            output_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {},
            },
        )

    assert captured.value.code is ToolContractErrorCode.SCHEMA_INVALID


def test_tool_request_recomputes_action_digest() -> None:
    fixture = make_fixture()
    mapping = fixture.invocation.request.to_mapping()
    mapping["planned_action"]["arguments"]["status"] = "in_progress"

    with pytest.raises(ToolContractError) as captured:
        ToolRequest.from_mapping(mapping)

    assert captured.value.code is ToolContractErrorCode.ACTION_DIGEST_MISMATCH


def test_tool_request_rejects_contract_extension() -> None:
    fixture = make_fixture()
    mapping = fixture.invocation.request.to_mapping()
    mapping["model_authorized"] = True

    with pytest.raises(ToolContractError) as captured:
        ToolRequest.from_mapping(mapping)

    assert captured.value.code is ToolContractErrorCode.CONTRACT_INVALID


def test_policy_input_preimage_is_recomputed() -> None:
    fixture = make_fixture()
    record = fixture.policy_source.record
    tampered = dict(record.input_preimage)
    tampered["tenant_id"] = "tenant-forged"

    with pytest.raises(PolicyError) as captured:
        type(record).create(decision=record.decision, input_preimage=tampered)

    assert captured.value.code is PolicyErrorCode.INPUT_HASH_MISMATCH


def test_unknown_obligation_is_fail_closed() -> None:
    fixture = make_fixture()
    mapping = fixture.policy.to_mapping()
    mapping["obligations"] = [
        {"name": "model_may_override", "parameters": {}}
    ]

    with pytest.raises(PolicyError) as captured:
        PolicyDecision.from_mapping(mapping)

    assert captured.value.code is PolicyErrorCode.OBLIGATION_UNSUPPORTED


def test_duplicate_obligations_are_rejected() -> None:
    fixture = make_fixture()
    mapping = fixture.policy.to_mapping()
    mapping["obligations"] = [
        {"name": "audit_level", "parameters": {"level": "security"}},
        {"name": "audit_level", "parameters": {"level": "detailed"}},
    ]

    with pytest.raises(PolicyError) as captured:
        PolicyDecision.from_mapping(mapping)

    assert captured.value.code is PolicyErrorCode.OBLIGATION_CONFLICT


def test_policy_deny_overrides_execution() -> None:
    fixture = make_fixture(decision_kind=PolicyDecisionKind.DENY)

    with pytest.raises(PolicyError) as captured:
        fixture.gateway._deps.policy.enforce(
            decision=fixture.policy,
            context=fixture.invocation.request.security_context,
            agent=fixture.invocation.request.agent_principal,
            action=fixture.action,
            now=NOW,
            upstream_provider="fixture-mcp",
        )

    assert captured.value.code is PolicyErrorCode.DENIED


def test_future_policy_decision_is_not_active() -> None:
    fixture = make_fixture()
    future = replace(
        fixture.policy,
        evaluated_at=NOW + timedelta(seconds=1),
    )

    with pytest.raises(PolicyError) as captured:
        fixture.gateway._deps.policy.enforce(
            decision=future,
            context=fixture.invocation.request.security_context,
            agent=fixture.invocation.request.agent_principal,
            action=fixture.action,
            now=NOW,
            upstream_provider="fixture-mcp",
        )

    assert captured.value.code is PolicyErrorCode.EXPIRED


def test_safe_projection_rejects_secret_and_hidden_reasoning() -> None:
    for projection in (
        {"password": "not-allowed"},
        {"metadata": {"client_secret": "not-allowed"}},
        {"debug": {"chain_of_thought": "not-allowed"}},
        {"message": "Bearer abcdefghijklmnopqrstuvwxyz"},
    ):
        with pytest.raises(SecurityError) as captured:
            assert_safe_projection(projection)
        assert captured.value.code is SecurityErrorCode.UNSAFE_PROJECTION


def test_approval_expiry_is_not_independent_of_action_and_policy() -> None:
    fixture = make_fixture(decision_kind=PolicyDecisionKind.REQUIRE_APPROVAL)
    assert fixture.approval is not None
    fixture.approval_source.approval = replace(
        fixture.approval,
        expires_at=fixture.action.expires_at - timedelta(seconds=1),
    )

    assert (
        fixture.approval_source.approval.expires_at
        != fixture.policy.expires_at
    )
    assert (
        fixture.approval_source.approval.expires_at
        != fixture.action.expires_at
    )


def test_action_digest_is_rfc8785_canonical() -> None:
    left = canonical_sha256({"b": 2, "a": 1})
    right = canonical_sha256({"a": 1, "b": 2})

    assert left == right
