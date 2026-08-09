from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path

import pytest
from flowpilot_application import ApplicationError, CommandIntakeService, ErrorCode
from flowpilot_application.testing import (
    FAKE_TASK_INITIALIZATION,
    FakeExecutionPort,
    FakeThreadIdFactory,
    FakeUnitOfWorkFactory,
)
from flowpilot_domain import DomainViolation, TaskCommand

DOMAIN_ROOT = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "domain"
    / "src"
    / "flowpilot_domain"
)
FORBIDDEN_ROOTS = {
    "fastapi",
    "langgraph",
    "sqlalchemy",
    "redis",
    "mcp",
    "openai",
    "anthropic",
}


def test_domain_has_no_framework_or_infrastructure_imports() -> None:
    violations: list[str] = []
    for source in DOMAIN_ROOT.glob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name.split(".", 1)[0] in FORBIDDEN_ROOTS:
                    violations.append(f"{source.name}:{node.lineno}:{name}")

    assert violations == []


@pytest.mark.parametrize(
    ("factory_overrides", "expected_code"),
    [
        ({"security_tenant_id": "tenant-b"}, ErrorCode.SECURITY_BINDING_MISMATCH),
        (
            {"security_purpose": "unrelated-purpose"},
            ErrorCode.SECURITY_BINDING_MISMATCH,
        ),
    ],
)
def test_command_security_binding_rejected_before_persistence(
    command_factory: Callable[..., TaskCommand],
    factory_overrides: dict[str, str],
    expected_code: ErrorCode,
) -> None:
    command = command_factory(**factory_overrides)
    unit_of_work = FakeUnitOfWorkFactory()
    execution = FakeExecutionPort()
    service = CommandIntakeService(
        unit_of_work=unit_of_work,
        execution=execution,
        task_initialization=FAKE_TASK_INITIALIZATION,
        thread_id_factory=FakeThreadIdFactory(),
    )

    with pytest.raises(ApplicationError) as captured:
        __import__("asyncio").run(service.accept(command))

    assert captured.value.code is expected_code
    assert unit_of_work.store.commands_by_id == {}
    assert execution.calls == []


def test_authority_fields_cannot_be_forged_in_command_payload(
    valid_create_mapping: dict[str, object],
) -> None:
    payload = valid_create_mapping["payload"]
    assert isinstance(payload, dict)
    payload["policy_decision_id"] = "pd_attacker00"

    with pytest.raises(DomainViolation):
        TaskCommand.from_mapping(valid_create_mapping)


def test_non_string_reference_cannot_cross_contract_boundary(
    valid_create_mapping: dict[str, object],
) -> None:
    payload = valid_create_mapping["payload"]
    assert isinstance(payload, dict)
    payload["initial_message_ref"] = 12345

    with pytest.raises(DomainViolation):
        TaskCommand.from_mapping(valid_create_mapping)


def test_tenant_scoped_deduplication_does_not_cross_tenants(
    command_factory: Callable[..., TaskCommand],
) -> None:
    unit_of_work = FakeUnitOfWorkFactory()
    execution = FakeExecutionPort()
    service = CommandIntakeService(
        unit_of_work=unit_of_work,
        execution=execution,
        task_initialization=FAKE_TASK_INITIALIZATION,
        thread_id_factory=FakeThreadIdFactory(),
    )
    tenant_a = command_factory()
    tenant_b = command_factory(
        tenant_id="tenant-b",
        task_id="task_abcdefgh",
        security_tenant_id="tenant-b",
    )

    __import__("asyncio").run(service.accept(tenant_a))
    __import__("asyncio").run(service.accept(tenant_b))

    assert len(unit_of_work.store.commands_by_id) == 2
    assert len(execution.calls) == 2
