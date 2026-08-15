from __future__ import annotations

import os

import pytest
from flowpilot_engineering_control.capsule import (
    CapsuleBuilder,
    CapsuleRequest,
    ExpansionReason,
    ScopeExpansion,
)
from flowpilot_engineering_control.errors import EngineeringControlError, ErrorCode
from flowpilot_engineering_control.repository import RepositoryMapBuilder

from .conftest import ExampleRepository


def request(
    base: str, target: str, *, expansions: tuple[ScopeExpansion, ...] = ()
) -> CapsuleRequest:
    return CapsuleRequest(
        base=base,
        target=target,
        owner="S5-CORE",
        work_package="WP-091",
        attempt_id="WP-091-test",
        risk_class="R2",
        contract_digest="sha256:" + "a" * 64,
        write_scope=("packages/engineering-control/**",),
        expansions=expansions,
    )


def test_capsule_handles_rename_delete_and_is_small(
    example_repository: ExampleRepository,
) -> None:
    base = example_repository.git("rev-parse", "HEAD")
    source = example_repository.root / (
        "packages/engineering-control/src/flowpilot_engineering_control/filler_00.py"
    )
    renamed = source.with_name("renamed.py")
    os.replace(source, renamed)
    example_repository.remove(
        "packages/engineering-control/src/flowpilot_engineering_control/filler_01.py"
    )
    target = example_repository.commit("rename and delete")
    repository_map = RepositoryMapBuilder(example_repository.root).build()

    capsule = CapsuleBuilder(example_repository.root, repository_map).build(
        request(base, target)
    )
    assert {change.status for change in capsule.changes} == {"D", "R"}
    rename = next(change for change in capsule.changes if change.status == "R")
    assert rename.old_path is not None
    assert rename.path.endswith("renamed.py")
    assert capsule.counts["initial_read_files"] < (
        capsule.counts["full_repository_files"] * 20 // 100
    )
    assert capsule.counts["initial_read_ratio_basis_points"] < 2_000
    assert (
        capsule.to_bytes()
        == CapsuleBuilder(example_repository.root, repository_map)
        .build(request(base, target))
        .to_bytes()
    )


def test_capsule_records_public_signature_and_scope_expansion(
    example_repository: ExampleRepository,
) -> None:
    base = example_repository.git("rev-parse", "HEAD")
    example_repository.write(
        "packages/engineering-control/src/flowpilot_engineering_control/ports.py",
        "class PublicPort:\n    value: str\n",
    )
    target = example_repository.commit("change public port")
    repository_map = RepositoryMapBuilder(example_repository.root).build()
    expansion = ScopeExpansion(
        reason=ExpansionReason.PUBLIC_SIGNATURE_CHANGE,
        paths=("AGENTS.md",),
        authority="S5-CORE",
    )
    capsule = CapsuleBuilder(example_repository.root, repository_map).build(
        request(base, target, expansions=(expansion, expansion))
    )

    assert capsule.public_signature_changes[0][0].endswith("ports.py")
    assert capsule.allowed_initial_read_set.count("AGENTS.md") == 1
    assert len(capsule.expansions) == 1
    assert b"class PublicPort" not in capsule.to_bytes()


def test_capsule_rejects_non_ancestor_base(
    example_repository: ExampleRepository,
) -> None:
    common = example_repository.git("rev-parse", "HEAD")
    example_repository.git("checkout", "-b", "side")
    example_repository.write("AGENTS.md", "side\n")
    side = example_repository.commit("side")
    example_repository.git("checkout", "main")
    example_repository.write(
        "packages/engineering-control/src/flowpilot_engineering_control/private.py",
        "VALUE = 'main'\n",
    )
    target = example_repository.commit("main")
    assert common != side != target
    repository_map = RepositoryMapBuilder(example_repository.root).build()
    with pytest.raises(EngineeringControlError) as captured:
        CapsuleBuilder(example_repository.root, repository_map).build(
            request(side, target)
        )
    assert captured.value.code is ErrorCode.NON_LINEAR_BASE


def test_capsule_rejects_cross_owner_rename_without_expansion(
    example_repository: ExampleRepository,
) -> None:
    base = example_repository.git("rev-parse", "HEAD")
    source = example_repository.root / (
        "packages/engineering-control/src/flowpilot_engineering_control/private.py"
    )
    destination = example_repository.root / "packages/security/src/private.py"
    destination.parent.mkdir(parents=True)
    os.replace(source, destination)
    target = example_repository.commit("cross owner rename")
    repository_map = RepositoryMapBuilder(example_repository.root).build()

    with pytest.raises(EngineeringControlError) as captured:
        CapsuleBuilder(example_repository.root, repository_map).build(
            request(base, target)
        )
    assert captured.value.code is ErrorCode.SCOPE_VIOLATION


def test_capsule_rejects_dirty_worktree(
    example_repository: ExampleRepository,
) -> None:
    base = example_repository.git("rev-parse", "HEAD")
    repository_map = RepositoryMapBuilder(example_repository.root).build()
    example_repository.write("AGENTS.md", "dirty\n")
    with pytest.raises(EngineeringControlError) as captured:
        CapsuleBuilder(example_repository.root, repository_map).build(
            request(base, base)
        )
    assert captured.value.code is ErrorCode.DIRTY_WORKTREE
