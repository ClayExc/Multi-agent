from __future__ import annotations

from dataclasses import replace

import pytest
from flowpilot_engineering_control.capsule import CapsuleBuilder, CapsuleRequest
from flowpilot_engineering_control.errors import EngineeringControlError, ErrorCode
from flowpilot_engineering_control.repository import RepositoryMap, RepositoryMapBuilder
from flowpilot_engineering_control.selection import (
    CommandSpec,
    SelectionRequest,
    SelectionSignal,
)
from flowpilot_engineering_control.selection import (
    TestSelector as EngineeringTestSelector,
)
from flowpilot_engineering_control.selection import (
    TestTier as EngineeringTestTier,
)

from .conftest import ExampleRepository


def _capsule(
    repository: ExampleRepository,
    base: str,
    target: str,
) -> tuple[RepositoryMap, object]:
    repository_map = RepositoryMapBuilder(repository.root).build()
    capsule = CapsuleBuilder(repository.root, repository_map).build(
        CapsuleRequest(
            base=base,
            target=target,
            owner="S5-CORE",
            work_package="WP-092",
            attempt_id="WP-092-test",
            risk_class="R2",
            contract_digest="sha256:" + "a" * 64,
            write_scope=("packages/engineering-control/**",),
        )
    )
    return repository_map, capsule


def test_package_change_selects_targeted_tests(
    example_repository: ExampleRepository,
) -> None:
    base = example_repository.git("rev-parse", "HEAD")
    example_repository.write(
        "packages/engineering-control/src/flowpilot_engineering_control/private.py",
        "VALUE = 'changed'\n",
    )
    target = example_repository.commit("package change")
    repository_map, capsule = _capsule(example_repository, base, target)

    plan = EngineeringTestSelector(repository_map).select(
        SelectionRequest(capsule=capsule)
    )
    assert plan.tier is EngineeringTestTier.TARGETED
    assert plan.selection_complete
    assert plan.selected_test_prefixes == ("tests/core/engineering_control",)
    assert plan.commands[0].argv == (
        "uv",
        "run",
        "--all-packages",
        "--all-groups",
        "--locked",
        "python",
        "-B",
        "-m",
        "pytest",
        "-q",
        "tests/core/engineering_control",
    )


def test_public_signature_change_upgrades_shared(
    example_repository: ExampleRepository,
) -> None:
    base = example_repository.git("rev-parse", "HEAD")
    example_repository.write(
        "packages/engineering-control/src/flowpilot_engineering_control/ports.py",
        "class PublicPort:\n    value: str\n",
    )
    target = example_repository.commit("public change")
    repository_map, capsule = _capsule(example_repository, base, target)

    plan = EngineeringTestSelector(repository_map).select(
        SelectionRequest(capsule=capsule)
    )
    assert plan.tier is EngineeringTestTier.SHARED
    assert plan.commands[0].command_id == "pytest-shared"
    assert plan.commands[0].argv == (
        "uv",
        "run",
        "--all-packages",
        "--all-groups",
        "--locked",
        "python",
        "-B",
        "-m",
        "pytest",
        "-q",
        "tests/core",
        "tests/runtime",
        "tests/data",
        "tests/platform",
    )


def test_pytest_runner_change_invalidates_legacy_plan_hash(
    example_repository: ExampleRepository,
) -> None:
    base = example_repository.git("rev-parse", "HEAD")
    example_repository.write(
        "packages/engineering-control/src/flowpilot_engineering_control/ports.py",
        "class PublicPort:\n    value: str\n",
    )
    target = example_repository.commit("public runner change")
    repository_map, capsule = _capsule(example_repository, base, target)
    plan = EngineeringTestSelector(repository_map).select(
        SelectionRequest(capsule=capsule)
    )
    legacy = replace(
        plan,
        commands=(
            CommandSpec(
                "pytest-shared",
                (
                    "uv",
                    "run",
                    "--locked",
                    "pytest",
                    "-q",
                    "tests/core",
                    "tests/runtime",
                    "tests/data",
                    "tests/platform",
                ),
            ),
        ),
    )

    assert plan.digest != legacy.digest
    assert plan.commands[0].argv_sha256 != legacy.commands[0].argv_sha256


def test_package_change_selects_transitive_dependent_tests(
    example_repository: ExampleRepository,
) -> None:
    root_metadata = example_repository.root / "pyproject.toml"
    root_metadata.write_text(
        root_metadata.read_text(encoding="utf-8")
        .replace(
            'members = ["packages/engineering-control"]',
            'members = ["packages/engineering-control", "packages/domain", '
            '"packages/persistence"]',
        )
        .replace(
            "flowpilot-engineering-control = { workspace = true }",
            "flowpilot-engineering-control = { workspace = true }\n"
            "flowpilot-domain = { workspace = true }\n"
            "flowpilot-persistence = { workspace = true }",
        ),
        encoding="utf-8",
    )
    example_repository.write(
        "packages/domain/pyproject.toml",
        """[project]
name = "flowpilot-domain"
version = "0.1.0"
dependencies = ["flowpilot-engineering-control"]
""",
    )
    example_repository.write(
        "packages/domain/src/flowpilot_domain/__init__.py",
        "VALUE = 1\n",
    )
    example_repository.write(
        "packages/persistence/pyproject.toml",
        """[project]
name = "flowpilot-persistence"
version = "0.1.0"
dependencies = ["flowpilot-domain"]
""",
    )
    example_repository.write(
        "packages/persistence/src/flowpilot_persistence/__init__.py",
        "VALUE = 1\n",
    )
    example_repository.write(
        "tests/data/test_transitive_consumer.py",
        "def test_consumer():\n    assert True\n",
    )
    example_repository.commit("add dependency chain")
    base = example_repository.git("rev-parse", "HEAD")
    example_repository.write(
        "packages/engineering-control/src/flowpilot_engineering_control/private.py",
        "VALUE = 'changed'\n",
    )
    target = example_repository.commit("change dependency root")
    repository_map, capsule = _capsule(example_repository, base, target)

    plan = EngineeringTestSelector(repository_map).select(
        SelectionRequest(capsule=capsule)
    )
    assert plan.tier is EngineeringTestTier.TARGETED
    assert "tests/core" in plan.selected_test_prefixes
    assert "tests/data" in plan.selected_test_prefixes


@pytest.mark.parametrize(
    ("tag", "tier"),
    [
        ("contract", EngineeringTestTier.FULL),
        ("lock", EngineeringTestTier.FULL),
        ("migration", EngineeringTestTier.RELEASE),
        ("security", EngineeringTestTier.RELEASE),
    ],
)
def test_protected_changes_upgrade_without_empty_plan(
    example_repository: ExampleRepository,
    tag: str,
    tier: EngineeringTestTier,
) -> None:
    base = example_repository.git("rev-parse", "HEAD")
    example_repository.write(
        "packages/engineering-control/src/flowpilot_engineering_control/private.py",
        "VALUE = 'changed'\n",
    )
    target = example_repository.commit("protected simulation")
    repository_map, capsule = _capsule(example_repository, base, target)
    protected_capsule = replace(capsule, protected_change_tags=(tag,))

    plan = EngineeringTestSelector(repository_map).select(
        SelectionRequest(capsule=protected_capsule)
    )
    assert plan.tier is tier
    assert plan.commands
    assert plan.fallback_required
    command_ids = {command.command_id for command in plan.commands}
    if tag == "migration":
        assert "migration-real" in command_ids
        migration = next(
            command
            for command in plan.commands
            if command.command_id == "migration-real"
        )
        assert migration.argv == (
            "uv",
            "run",
            "--all-packages",
            "--all-groups",
            "--locked",
            "python",
            "-B",
            "-m",
            "pytest",
            "-q",
            "tests/data/integration",
        )
    else:
        assert "migration-real" not in command_ids


@pytest.mark.parametrize(
    ("signal", "tier"),
    [
        (SelectionSignal.UNKNOWN_PATH, EngineeringTestTier.FULL),
        (SelectionSignal.NON_LINEAR_BASE, EngineeringTestTier.RELEASE),
        (SelectionSignal.DEPENDENCY_GRAPH_INCOMPLETE, EngineeringTestTier.FULL),
    ],
)
def test_control_failure_returns_nonempty_fail_closed_fallback(
    example_repository: ExampleRepository,
    signal: SelectionSignal,
    tier: EngineeringTestTier,
) -> None:
    repository_map = RepositoryMapBuilder(example_repository.root).build()
    plan = EngineeringTestSelector(repository_map).select(
        SelectionRequest(capsule=None, fallback_signals=(signal,))
    )
    assert plan.tier is tier
    assert not plan.selection_complete
    assert plan.commands


def test_selector_rejects_missing_capsule_without_reason(
    example_repository: ExampleRepository,
) -> None:
    repository_map = RepositoryMapBuilder(example_repository.root).build()
    with pytest.raises(EngineeringControlError) as captured:
        EngineeringTestSelector(repository_map).select(SelectionRequest(capsule=None))
    assert captured.value.code is ErrorCode.SELECTION_INCOMPLETE


def test_command_argv_preserves_shell_metacharacters_as_literals() -> None:
    command = CommandSpec(
        "injection-regression",
        ("python", "-c", "; | > $(not-executed)"),
    )
    assert command.to_record()["argv"] == [
        "python",
        "-c",
        "; | > $(not-executed)",
    ]
    with pytest.raises(EngineeringControlError) as captured:
        CommandSpec("invalid", ("python", "bad\x00arg"))
    assert captured.value.code is ErrorCode.ARGV_INVALID


def test_test_plan_is_byte_deterministic(
    example_repository: ExampleRepository,
) -> None:
    repository_map = RepositoryMapBuilder(example_repository.root).build()
    request = SelectionRequest(
        capsule=None,
        fallback_signals=(SelectionSignal.UNKNOWN_PATH,),
    )
    assert (
        EngineeringTestSelector(repository_map).select(request).to_bytes()
        == EngineeringTestSelector(repository_map).select(request).to_bytes()
    )
