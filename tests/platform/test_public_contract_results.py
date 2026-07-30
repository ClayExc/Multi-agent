from __future__ import annotations

import json
from pathlib import Path

import pytest
from factories import WriteAdapter, make_fixture
from flowpilot_domain import ToolOperation
from flowpilot_policy import PolicyDecisionKind
from flowpilot_tool_contracts import ToolResultStatus
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "contracts" / "jsonschema"
SCHEMAS = {
    path.name: json.loads(path.read_text(encoding="utf-8"))
    for path in SCHEMA_DIR.glob("*.schema.json")
}
REGISTRY = Registry().with_resources(
    [
        (schema["$id"], Resource.from_contents(schema))
        for schema in SCHEMAS.values()
    ]
)


def assert_public_object(schema_name: str, value: dict[str, object]) -> None:
    validator = Draft202012Validator(
        SCHEMAS[schema_name],
        registry=REGISTRY,
        format_checker=FormatChecker(),
    )
    errors = sorted(validator.iter_errors(value), key=lambda item: list(item.path))
    assert errors == []


def test_gateway_input_adapters_validate_against_public_v1_schemas() -> None:
    fixture = make_fixture(
        decision_kind=PolicyDecisionKind.REQUIRE_APPROVAL
    )
    assert fixture.approval is not None

    for schema_name, value in (
        (
            "security-context-ref.v1.schema.json",
            fixture.invocation.request.security_context.to_mapping(),
        ),
        (
            "planned-action.v1.schema.json",
            fixture.action.to_mapping(),
        ),
        (
            "policy-decision.v1.schema.json",
            fixture.policy.to_mapping(),
        ),
        (
            "approval.v1.schema.json",
            fixture.approval.to_mapping(),
        ),
        (
            "tool-request.v1.schema.json",
            fixture.invocation.request.to_mapping(),
        ),
    ):
        assert_public_object(schema_name, value)


@pytest.mark.asyncio
async def test_gateway_results_validate_against_public_v1_schema() -> None:
    read = make_fixture(operation=ToolOperation.READ)
    read_result = await read.gateway.execute(read.invocation)

    verified = make_fixture()
    verified_result = await verified.gateway.execute(verified.invocation)

    unknown = make_fixture()
    assert isinstance(unknown.adapter, WriteAdapter)
    unknown.adapter.mode = "unknown_not_executed"
    unknown_result = await unknown.gateway.execute(unknown.invocation)

    retryable = make_fixture()
    assert isinstance(retryable.adapter, WriteAdapter)
    retryable.adapter.mode = "not_sent"
    retryable_result = await retryable.gateway.execute(retryable.invocation)

    assert read_result.result.status is ToolResultStatus.VERIFIED
    assert verified_result.result.status is ToolResultStatus.VERIFIED
    assert unknown_result.result.status is ToolResultStatus.UNKNOWN
    assert retryable_result.result.status is ToolResultStatus.FAILED_RETRYABLE
    for execution in (
        read_result,
        verified_result,
        unknown_result,
        retryable_result,
    ):
        assert_public_object(
            "tool-result.v1.schema.json",
            execution.result.to_mapping(),
        )
