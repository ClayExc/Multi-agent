from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/integration/verify_wp040.py"


def load_verifier() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "verify_wp040",
        SCRIPT,
    )
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def verifier() -> ModuleType:
    return load_verifier()


def test_candidate_is_exact_and_dependency_complete(verifier: ModuleType) -> None:
    manifest = verifier.build_manifest(ROOT)

    assert manifest["summary"]["verdict"] == "PASS"
    assert manifest["summary"]["failed_checks"] == []
    assert manifest["workspace"]["member_count"] == 9
    assert manifest["workspace"]["lock_package_count"] == 73
    assert manifest["migrations"]["head"] == "0002_checkpoint_sequence_cas"
    assert (
        manifest["integration"]["recommended_mainline_mode"]
        == "ATOMIC_FINAL_CANDIDATE"
    )
    assert (
        manifest["integration"]["safe_whole_input_sequential_order"]
        is None
    )


def test_manifest_and_report_are_deterministic(
    verifier: ModuleType,
    tmp_path: Path,
) -> None:
    manifest = verifier.build_manifest(ROOT)
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_paths = verifier.write_artifacts(manifest, first)
    second_paths = verifier.write_artifacts(manifest, second)

    assert first_paths[0].read_bytes() == second_paths[0].read_bytes()
    assert first_paths[1].read_bytes() == second_paths[1].read_bytes()
    assert first_paths[2:] == second_paths[2:]
    assert first_paths[2] == (
        "sha256:1e9140e267470a0b4404a34b07254569"
        "875c3d8c582517599cc328ba8b5dddb1"
    )
    assert first_paths[3] == (
        "sha256:533a2540a2d41264fe38bbc84c92ae5f"
        "a9bd5f3e1292b57598139e470c4e143c"
    )


def test_legal_s1_final_merge_passes(verifier: ModuleType) -> None:
    manifest = verifier.build_manifest(
        ROOT,
        phase=verifier.ValidationPhase.S1_FINAL,
        target_head=verifier.S1_FINAL_TEST_HEAD,
    )

    assert manifest["summary"]["verdict"] == "PASS"
    assert manifest["validation_phase"] == "S1_FINAL"
    assert manifest["branch"].startswith("codex/s1/")
    assert manifest["final"]["delta_scope_violations"] == []
    assert manifest["final"]["protected_path_mismatches"] == []
    assert all(manifest["final"]["input_head_ancestry"].values())


def test_s1_final_rejects_non_s1_product_path(verifier: ModuleType) -> None:
    changes = [
        ("M", "docs/team/CODEX_SESSIONS.md"),
        ("M", ".gitignore"),
        ("M", "packages/domain/src/flowpilot_domain/actions.py"),
    ]

    assert verifier.final_scope_violations(changes, ".idea/\n") == [
        "M:packages/domain/src/flowpilot_domain/actions.py"
    ]


def test_s1_final_branch_and_ignored_cleanup_fail_closed(
    verifier: ModuleType,
) -> None:
    assert verifier.is_s1_branch("master")
    assert verifier.is_s1_branch("codex/s1/wp-040-final-gate")
    assert not verifier.is_s1_branch(
        "codex/s7/wp-040-integration-verification"
    )
    assert verifier.final_scope_violations(
        [("M", ".idea/modules.xml")],
        ".idea/\n",
    ) == ["M:.idea/modules.xml"]


def test_candidate_rejects_s7_delta_outside_owner_scope(
    verifier: ModuleType,
) -> None:
    violations = verifier.path_scope_violations(
        (
            "scripts/integration/verify_wp040.py",
            "packages/application/src/flowpilot_application/ports.py",
        ),
        verifier.S7_ALLOWED_PREFIXES,
    )

    assert violations == [
        "packages/application/src/flowpilot_application/ports.py"
    ]


def test_wrong_merge_topology_fails_closed(verifier: ModuleType) -> None:
    reversed_construction = tuple(reversed(verifier.TEMPORARY_CONSTRUCTION))

    result = verifier.check_merge_topology(ROOT, reversed_construction)

    assert result.outcome == "FAIL"
    assert "parents=" in result.evidence


def test_cross_owner_path_is_rejected(verifier: ModuleType) -> None:
    assert verifier.is_allowed_path(
        "packages/graph/src/flowpilot_graph/ports.py",
        verifier.INPUTS["S2-RUNTIME"]["allowed"],
    )
    assert not verifier.is_allowed_path(
        "packages/persistence/src/flowpilot_persistence/ports.py",
        verifier.INPUTS["S2-RUNTIME"]["allowed"],
    )


def test_empty_increment_is_a_boundary_not_an_error(verifier: ModuleType) -> None:
    assert (
        verifier.changed_paths(
            ROOT,
            verifier.CANDIDATE_MERGE_HEAD,
            verifier.CANDIDATE_MERGE_HEAD,
        )
        == []
    )


def test_duplicate_input_head_is_rejected(verifier: ModuleType) -> None:
    duplicate = {
        "S2-RUNTIME": {"head": "a" * 40},
        "S5-CORE": {"head": "a" * 40},
    }

    assert not verifier.input_heads_are_unique(duplicate)


def test_dirty_worktree_status_is_rejected(verifier: ModuleType) -> None:
    assert verifier.status_is_clean("")
    assert not verifier.status_is_clean(" M uv.lock\n")


def test_missing_workspace_member_is_rejected(
    verifier: ModuleType,
    tmp_path: Path,
) -> None:
    member = tmp_path / "packages/domain"
    member.mkdir(parents=True)

    assert verifier.missing_workspace_members(
        tmp_path,
        ("packages/domain",),
    ) == ["packages/domain"]


def test_multiple_migration_heads_are_rejected(
    verifier: ModuleType,
    tmp_path: Path,
) -> None:
    (tmp_path / "0001_base.sql").write_text("BEGIN;\n", encoding="utf-8")
    (tmp_path / "0002_left.sql").write_text(
        "-- requires 0001_base\n",
        encoding="utf-8",
    )
    (tmp_path / "0002_right.sql").write_text(
        "-- requires 0001_base\n",
        encoding="utf-8",
    )

    assert verifier.discover_migration_heads(tmp_path) == [
        "0002_left",
        "0002_right",
    ]


def test_digest_changes_when_lock_bytes_drift(
    verifier: ModuleType,
    tmp_path: Path,
) -> None:
    source = ROOT / "uv.lock"
    drifted = tmp_path / "uv.lock"
    drifted.write_bytes(source.read_bytes() + b"\n# drift\n")

    assert verifier.sha256_file(drifted) != verifier.sha256_file(source)
