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
    assert manifest["branch"] == verifier.CANDIDATE_BRANCH
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
        ("M", "tests/acceptance/test_release_gate.py"),
    ]

    assert verifier.final_scope_violations(changes, ".idea/\n") == [
        "M:packages/domain/src/flowpilot_domain/actions.py",
        "M:tests/acceptance/test_release_gate.py",
    ]


def test_s1_final_allows_reviewed_s7_control_paths(
    verifier: ModuleType,
) -> None:
    changes = [
        ("M", "scripts/integration/verify_wp040.py"),
        ("M", "tests/integration/test_wp040_composition.py"),
        ("A", "tests/integration/evidence/WP-040-a3-HANDOFF.md"),
    ]

    assert verifier.final_scope_violations(changes, ".idea/\n") == []


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


def test_candidate_checkout_identity_remains_explicit(
    verifier: ModuleType,
) -> None:
    assert verifier.is_candidate_branch(verifier.CANDIDATE_BRANCH)
    assert not verifier.is_candidate_branch("master")
    assert not verifier.is_candidate_branch("codex/s1/wp-040-final-gate")


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


def test_m1_platform_candidate_is_exact_and_dependency_complete(
    verifier: ModuleType,
) -> None:
    manifest = verifier.build_manifest(
        ROOT,
        phase=verifier.ValidationPhase.M1_PLATFORM_CANDIDATE,
        target_head=verifier.M1_INPUT_HEAD,
    )

    assert manifest["summary"] == {
        "check_count": 34,
        "failed_check_count": 0,
        "failed_checks": [],
        "verdict": "PASS",
    }
    assert manifest["chain_id"] == "CHAIN-M1-PLATFORM-01"
    assert manifest["workspace"]["member_count"] == 14
    assert manifest["workspace"]["lock_package_count"] == 78
    assert manifest["workspace"]["expected_wheel_count"] == 14
    assert manifest["workspace"]["internal_dependency_violations"] == []
    assert manifest["commands"]["make_acceptance_implemented"] is False
    assert manifest["security"]["high_confidence_secret_findings"] == []


def test_m1_platform_manifest_and_report_are_deterministic(
    verifier: ModuleType,
    tmp_path: Path,
) -> None:
    manifest = verifier.build_manifest(
        ROOT,
        phase=verifier.ValidationPhase.M1_PLATFORM_CANDIDATE,
        target_head=verifier.M1_INPUT_HEAD,
    )
    first = verifier.write_artifacts(manifest, tmp_path / "first")
    second = verifier.write_artifacts(manifest, tmp_path / "second")

    assert first[0].read_bytes() == second[0].read_bytes()
    assert first[1].read_bytes() == second[1].read_bytes()
    assert first[2:] == second[2:]
    assert first[2] == (
        "sha256:df72d6e13efb06bc34bedd96b14dcca6"
        "534a20752543b649c7a53e1d880c9633"
    )
    assert first[3] == (
        "sha256:7021c14b0102abac385179a2cd7d34501"
        "1297639bf8f3f004ea6ff211b35d75a"
    )


def test_m1_platform_topology_and_evidence_are_closed(
    verifier: ModuleType,
) -> None:
    manifest = verifier.build_manifest(
        ROOT,
        phase=verifier.ValidationPhase.M1_PLATFORM_CANDIDATE,
        target_head=verifier.M1_INPUT_HEAD,
    )

    assert manifest["topology"]["commit_count"] == 5
    assert all(
        not step["violations"]
        for step in manifest["topology"]["steps"].values()
    )
    assert manifest["evidence"]["S3_HANDOFF"]["sha256"] == (
        "sha256:3a9fae37edecce2bf2251ae0d5b35f3d"
        "d9e79d69567cb7628aed99bcc6e0e888"
    )
    assert manifest["evidence"]["S5_HANDOFF"]["sha256"] == (
        "sha256:e2bdf0c50f7a07a6ad345491abc70d7e"
        "11e994ac696b2e4a8ace8d931489d6fc"
    )
    assert manifest["evidence"]["S4_HANDOFF"]["sha256"] == (
        "sha256:42a2e3dc20751598174e5c85f959ead00"
        "d3cf2146a82851704ced5f3e5d3a48a"
    )
    assert manifest["evidence"]["S4_PROOF"]["sha256"] == (
        "sha256:bb118a6f48ef288e081d1d3c08b7f9bc"
        "acb7d9edeb9e8d83af6e4f91150e0f67"
    )


def test_m1_candidate_rejects_s7_delta_outside_owner_scope(
    verifier: ModuleType,
) -> None:
    violations = verifier.path_scope_violations(
        (
            "scripts/integration/verify_wp040.py",
            "tests/integration/test_wp040_composition.py",
            "packages/security/src/flowpilot_security/verifier.py",
        ),
        verifier.S7_ALLOWED_PREFIXES,
    )

    assert violations == [
        "packages/security/src/flowpilot_security/verifier.py"
    ]


def test_m1_final_requires_reviewed_s7_head(
    verifier: ModuleType,
) -> None:
    with pytest.raises(ValueError, match="--s7-head is required"):
        verifier.build_manifest(
            ROOT,
            phase=verifier.ValidationPhase.M1_PLATFORM_S1_FINAL,
            target_head=verifier.M1_INPUT_HEAD,
        )


def test_m1_final_scope_rejects_non_s1_non_s7_paths(
    verifier: ModuleType,
) -> None:
    changes = [
        ("M", "docs/review/WP-040-M1-S1-REVIEW.md"),
        ("M", "scripts/integration/verify_wp040.py"),
        ("M", "tests/integration/evidence/WP-040-a4-HANDOFF.md"),
        ("M", "tests/acceptance/platform_security/blackbox.py"),
        ("M", "packages/security/src/flowpilot_security/verifier.py"),
    ]

    assert verifier.final_scope_violations(changes, ".idea/\n") == [
        "M:packages/security/src/flowpilot_security/verifier.py",
        "M:tests/acceptance/platform_security/blackbox.py",
    ]


def test_m1_secret_scan_is_high_confidence_and_fails_closed(
    verifier: ModuleType,
) -> None:
    samples = (
        "-----BEGIN PRIVATE KEY-----",
        "AKIAABCDEFGHIJKLMNOP",
        "sk-abcdefghijklmnopqrstuvwxyz",
        "ghp_abcdefghijklmnopqrstuvwxyz",
    )

    for sample in samples:
        assert any(
            pattern.search(sample)
            for pattern in verifier.HIGH_CONFIDENCE_SECRET_PATTERNS
        )
    assert not any(
        pattern.search("secret-like-placeholder")
        for pattern in verifier.HIGH_CONFIDENCE_SECRET_PATTERNS
    )


def test_m1_scope_rules_do_not_allow_exact_path_prefixes(
    verifier: ModuleType,
) -> None:
    violations = verifier.path_scope_violations_by_rule(
        ("uv.lock", "uv.lock.backup"),
        exact=("uv.lock",),
    )

    assert violations == ["uv.lock.backup"]


def test_m2_studio_candidate_is_exact_and_dependency_complete(
    verifier: ModuleType,
) -> None:
    manifest = verifier.build_manifest(
        ROOT,
        phase=verifier.ValidationPhase.M2_STUDIO_CANDIDATE,
        target_head=verifier.M2_INPUT_HEAD,
    )

    assert manifest["summary"] == {
        "check_count": 40,
        "failed_check_count": 0,
        "failed_checks": [],
        "verdict": "PASS",
    }
    assert manifest["chain_id"] == "CHAIN-M2-STUDIO-01"
    assert manifest["topology"]["commit_count"] == 6
    assert manifest["workspace"]["member_count"] == 14
    assert manifest["workspace"]["lock_package_count"] == 116
    assert manifest["workspace"]["expected_wheel_count"] == 14
    assert manifest["workspace"]["agent_server_versions"] == {
        "langgraph-api": "0.11.2",
        "langgraph-cli": "0.4.31",
        "langgraph-runtime-inmem": "0.31.2",
        "langgraph-sdk": "0.4.2",
    }
    assert manifest["security"]["high_confidence_secret_findings"] == []


def test_m2_studio_manifest_and_report_are_deterministic(
    verifier: ModuleType,
    tmp_path: Path,
) -> None:
    manifest = verifier.build_manifest(
        ROOT,
        phase=verifier.ValidationPhase.M2_STUDIO_CANDIDATE,
        target_head=verifier.M2_INPUT_HEAD,
    )
    first = verifier.write_artifacts(manifest, tmp_path / "first")
    second = verifier.write_artifacts(manifest, tmp_path / "second")

    assert first[0].read_bytes() == second[0].read_bytes()
    assert first[1].read_bytes() == second[1].read_bytes()
    assert first[2:] == second[2:]
    assert first[2] == (
        "sha256:732b971522f5bb4b4840814952efcdcea"
        "e3ffd1bea8a1996e75edfb642e3dc84"
    )
    assert first[3] == (
        "sha256:69d01b16ae97165d1c9122c9f7bc3bf"
        "755fa31b2d1522710f71d05b1e60d17b0"
    )


def test_m2_studio_topology_and_evidence_are_closed(
    verifier: ModuleType,
) -> None:
    manifest = verifier.build_manifest(
        ROOT,
        phase=verifier.ValidationPhase.M2_STUDIO_CANDIDATE,
        target_head=verifier.M2_INPUT_HEAD,
    )

    assert all(
        not step["violations"]
        for step in manifest["topology"]["steps"].values()
    )
    assert manifest["studio"]["runtime_topology"] == {
        "graph_id": "flowpilot_it_service",
        "factory_id": "flowpilot.graph.factory.v1",
        "topology_digest": (
            "sha256:f915742bd4c091b44364ab3073b485901338bd8c270d146"
            "3344b9eb52a31d8c2"
        ),
        "node_count": 14,
        "edge_count": 20,
    }
    assert manifest["studio"]["quality_topology"] == {
        "graph_id": "flowpilot_it_service",
        "node_count": 16,
        "edge_count": 22,
    }
    assert manifest["evidence"]["S5_HANDOFF"]["sha256"] == (
        "sha256:98e1e1e4442dfe7bdce2f309a9e516e"
        "a223173d126680257451c17203c49e799"
    )
    assert manifest["evidence"]["S2_HANDOFF"]["sha256"] == (
        "sha256:e9542a5c95592679f2e4fac29fefcd36"
        "b97531c59b22fe99c876a6298c730ce3"
    )
    assert manifest["evidence"]["S4_HANDOFF"]["sha256"] == (
        "sha256:d5ab849a707d91468c2dd5876ae69271"
        "b518d0c26865fba2251d60dc176fa712"
    )
    assert manifest["evidence"]["S4_PROOF"]["sha256"] == (
        "sha256:027346eaf7b4ec620804c7c08b39ce8b"
        "5cfbc4616e18339cd0e9928f3b329dcd"
    )
    assert all(
        value == 0
        for value in manifest["evidence"]["S4_PROOF_SEMANTICS"][
            "cleanup"
        ].values()
    )


def test_m2_studio_wrong_linear_parent_fails_closed(
    verifier: ModuleType,
) -> None:
    wrong = {
        verifier.M2_WORKSPACE_IMPLEMENTATION_HEAD: (
            verifier.M2_ACTIVATION_COMMIT
        ),
        verifier.M2_WORKSPACE_HEAD: verifier.M2_ACTIVATION_COMMIT,
    }

    _record, checks = verifier.verify_m2_topology(ROOT, wrong)

    assert checks[0].check_id == "m2.git.linear_topology"
    assert checks[0].outcome == "FAIL"
    assert "expected=" in checks[0].evidence


def test_m2_studio_candidate_rejects_non_s7_delta(
    verifier: ModuleType,
) -> None:
    violations = verifier.path_scope_violations(
        (
            "scripts/integration/verify_wp040.py",
            "apps/worker/src/flowpilot_worker/studio.py",
        ),
        verifier.S7_ALLOWED_PREFIXES,
    )

    assert violations == ["apps/worker/src/flowpilot_worker/studio.py"]


def test_m2_studio_final_requires_reviewed_s7_head(
    verifier: ModuleType,
) -> None:
    with pytest.raises(
        ValueError,
        match="--s7-head is required for M2_STUDIO_S1_FINAL",
    ):
        verifier.build_manifest(
            ROOT,
            phase=verifier.ValidationPhase.M2_STUDIO_S1_FINAL,
            target_head=verifier.M2_INPUT_HEAD,
        )


def test_m2_studio_final_scope_keeps_product_protected(
    verifier: ModuleType,
) -> None:
    allowed = [
        ("M", "docs/review/WP-040-A5-S1-FINAL-REVIEW.md"),
        ("M", "scripts/integration/verify_wp040.py"),
        ("A", "tests/integration/evidence/WP-040-a5-HANDOFF.md"),
        ("M", ".gitignore"),
    ]
    forbidden = allowed + [
        ("M", "apps/worker/src/flowpilot_worker/studio.py"),
        ("A", "web/studio-shortcut.ts"),
    ]

    assert verifier.final_scope_violations(allowed, ".idea/\n") == []
    assert verifier.final_scope_violations(forbidden, ".idea/\n") == [
        "A:web/studio-shortcut.ts",
        "M:apps/worker/src/flowpilot_worker/studio.py",
    ]


def test_m2_studio_static_profile_is_fail_closed(
    verifier: ModuleType,
) -> None:
    studio, checks = verifier.verify_m2_studio_static(
        ROOT,
        verifier.M2_INPUT_HEAD,
    )

    assert all(check.outcome == "PASS" for check in checks)
    assert studio["config"]["env"]["FLOWPILOT_STUDIO_PROFILE"] == (
        "studio-safe"
    )
    assert studio["config"]["env"]["FLOWPILOT_EXTERNAL_NETWORK"] == (
        "disabled"
    )
    assert "--tunnel" not in "\n".join(studio["make_surface"])
