from __future__ import annotations

from pathlib import Path

import pytest
from flowpilot_engineering_control.errors import EngineeringControlError, ErrorCode
from flowpilot_engineering_control.git import GitClient
from flowpilot_engineering_control.owners import OwnerRule, default_owner_rules
from flowpilot_engineering_control.repository import RepositoryMapBuilder

from .conftest import ExampleRepository


def test_repository_map_is_deterministic_and_metadata_only(
    example_repository: ExampleRepository,
) -> None:
    first = RepositoryMapBuilder(example_repository.root).build()
    second = RepositoryMapBuilder(example_repository.root).build()

    assert first.to_bytes() == second.to_bytes()
    assert first.digest == second.digest
    assert b"fixture-secret-that-must-not-leak" not in first.to_bytes()
    assert b"generated-secret" not in first.to_bytes()
    assert b"local-only-secret" not in first.to_bytes()
    assert all("evidence" not in record.path for record in first.files)
    assert all(".idea" not in record.path for record in first.files)
    assert dict(first.tree_signatures).keys() == {
        "contract",
        "environment",
        "lock",
        "migration",
        "product",
        "security",
    }


def test_repository_map_detects_owner_conflicts(
    example_repository: ExampleRepository,
) -> None:
    rules = (*default_owner_rules(), OwnerRule("packages", "S1-ARCH"))
    with pytest.raises(EngineeringControlError) as captured:
        RepositoryMapBuilder(example_repository.root, owner_rules=rules).build()
    assert captured.value.code is ErrorCode.OWNER_CONFLICT


def test_repository_map_rejects_unknown_path(
    example_repository: ExampleRepository,
) -> None:
    example_repository.write("unknown-tree/value.txt", "value\n")
    example_repository.commit("add unknown path")
    with pytest.raises(EngineeringControlError) as captured:
        RepositoryMapBuilder(example_repository.root).build()
    assert captured.value.code is ErrorCode.UNKNOWN_PATH


@pytest.mark.parametrize("untracked", [False, True])
def test_repository_map_rejects_dirty_worktree(
    example_repository: ExampleRepository,
    untracked: bool,
) -> None:
    path = "scratch.txt" if untracked else "AGENTS.md"
    example_repository.write(path, "dirty\n")
    with pytest.raises(EngineeringControlError) as captured:
        RepositoryMapBuilder(example_repository.root).build()
    assert captured.value.code is ErrorCode.DIRTY_WORKTREE
    assert captured.value.metadata["entry_count"] == 1


def test_repository_map_rejects_missing_workspace_member(
    example_repository: ExampleRepository,
) -> None:
    metadata = example_repository.root / "pyproject.toml"
    metadata.write_text(
        metadata.read_text(encoding="utf-8").replace(
            'members = ["packages/engineering-control"]',
            'members = ["packages/missing"]',
        ),
        encoding="utf-8",
    )
    example_repository.commit("break workspace")
    with pytest.raises(EngineeringControlError) as captured:
        RepositoryMapBuilder(example_repository.root).build()
    assert captured.value.code is ErrorCode.MISSING_WORKSPACE_MEMBER


def test_repository_map_rejects_casefold_collision(
    example_repository: ExampleRepository,
) -> None:
    class CaseCollisionGit(GitClient):
        def tracked_files(self) -> tuple[str, ...]:
            return (*super().tracked_files(), "agents.md")

    with pytest.raises(EngineeringControlError) as captured:
        RepositoryMapBuilder(
            example_repository.root,
            git=CaseCollisionGit(example_repository.root),
        ).build()
    assert captured.value.code is ErrorCode.INVALID_PATH
    assert captured.value.metadata["collision_count"] == 2


def test_repository_map_rejects_unresolved_internal_dependency(
    example_repository: ExampleRepository,
) -> None:
    package = example_repository.root / "packages/engineering-control/pyproject.toml"
    package.write_text(
        package.read_text(encoding="utf-8").replace(
            "dependencies = []", 'dependencies = ["flowpilot-missing"]'
        ),
        encoding="utf-8",
    )
    example_repository.commit("break dependency")
    with pytest.raises(EngineeringControlError) as captured:
        RepositoryMapBuilder(example_repository.root).build()
    assert captured.value.code is ErrorCode.MISSING_WORKSPACE_DEPENDENCY


def test_repository_map_has_no_absolute_paths(
    example_repository: ExampleRepository,
) -> None:
    output = RepositoryMapBuilder(example_repository.root).build().to_bytes()
    assert str(Path(example_repository.root)).encode() not in output
