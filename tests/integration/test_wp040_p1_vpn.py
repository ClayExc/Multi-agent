from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/integration/verify_wp040.py"


def load_verifier() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "verify_wp040_p1",
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


@pytest.fixture(scope="module")
def candidate_manifest(verifier: ModuleType) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        verifier.build_manifest(
            ROOT,
            phase=verifier.ValidationPhase.P1_VPN_CANDIDATE,
            target_head=verifier.P1_INPUT_HEAD,
        ),
    )


def test_p1_vpn_candidate_is_exact_and_dependency_complete(
    verifier: ModuleType,
    candidate_manifest: dict[str, Any],
) -> None:
    manifest = candidate_manifest

    assert manifest["summary"] == {
        "check_count": 46,
        "failed_check_count": 0,
        "failed_checks": [],
        "verdict": "PASS",
    }
    assert manifest["chain_id"] == "CHAIN-P1-VPN-READONLY-01"
    assert manifest["topology"]["commit_count"] == 10
    assert manifest["workspace"]["member_count"] == 14
    assert manifest["workspace"]["lock_package_count"] == 116
    assert manifest["workspace"]["expected_wheel_count"] == 14
    assert manifest["dataset"]["case_count"] == 20
    assert manifest["security"] == {
        "high_confidence_secret_findings": [],
        "cross_tenant_successful_retrievals": 0,
        "knowledge_bypass_findings": [],
    }


def test_p1_vpn_manifest_and_report_are_deterministic(
    verifier: ModuleType,
    candidate_manifest: dict[str, Any],
    tmp_path: Path,
) -> None:
    manifest = candidate_manifest
    first = verifier.write_artifacts(manifest, tmp_path / "first")
    second = verifier.write_artifacts(manifest, tmp_path / "second")

    assert first[0].read_bytes() == second[0].read_bytes()
    assert first[1].read_bytes() == second[1].read_bytes()
    assert first[2:] == second[2:]
    assert first[2] == (
        "sha256:f1ae490993f7514c41911e514b438710"
        "17319375feecd9c6ecfe8df5e1f490b6"
    )
    assert first[3] == (
        "sha256:855cf594728f3e14f372a3e192034b1"
        "e16cf03a6a4ef000f671d1c379b888fda"
    )


def test_p1_vpn_topology_and_evidence_are_closed(
    verifier: ModuleType,
    candidate_manifest: dict[str, Any],
) -> None:
    manifest = candidate_manifest

    assert all(
        not step["violations"]
        for step in manifest["topology"]["steps"].values()
    )
    assert manifest["evidence"]["S5_HANDOFF"]["sha256"] == (
        "sha256:413e59aa5177827185a294f2af795fc7"
        "f86a02aa19496eab1884433f9fa66c44"
    )
    assert manifest["evidence"]["S3_HANDOFF"]["sha256"] == (
        "sha256:d130501fdf0f5a032a174fa3171406d69"
        "20f930d2792ee48ca61922d6ba1ec1f"
    )
    assert manifest["evidence"]["S2_HANDOFF"]["sha256"] == (
        "sha256:27fa68887d6a68d3566f23f8323b776b"
        "a966a3054cdd45b91d9833538615cb67"
    )
    assert manifest["evidence"]["S4_HANDOFF"]["sha256"] == (
        "sha256:b785b6607cc93a595a78e92dc28d924d"
        "52b704f666a41f34933e0f2d7103cf98"
    )
    assert manifest["evidence"]["S4_PROOF"]["sha256"] == (
        "sha256:44b48979e439c1bbdca970459cdad7ced"
        "3478d4f895aadcdca3484a23fc8a7aa"
    )


def test_p1_vpn_recomputes_schema_and_case_hashes(
    verifier: ModuleType,
    candidate_manifest: dict[str, Any],
) -> None:
    manifest = candidate_manifest

    assert manifest["boundaries"]["knowledge_schema_pin"] == {
        "declared": verifier.P1_KNOWLEDGE_SCHEMA_PIN,
        "recomputed": verifier.P1_KNOWLEDGE_SCHEMA_PIN,
    }
    assert manifest["dataset"]["dataset_card_sha256"] == (
        "sha256:" + verifier.P1_DATASET_CARD_SHA256
    )
    assert manifest["dataset"]["case_file_sha256"] == (
        "sha256:" + verifier.P1_CASE_FILE_SHA256
    )
    assert manifest["dataset"]["case_ids"] == [
        f"vpn-p1-{index:03d}" for index in range(1, 21)
    ]


def test_p1_vpn_wrong_linear_parent_fails_closed(
    verifier: ModuleType,
) -> None:
    wrong = {
        verifier.P1_CORE_IMPLEMENTATION_HEAD: verifier.P1_ACTIVATION_COMMIT,
        verifier.P1_CORE_HEAD: verifier.P1_ACTIVATION_COMMIT,
    }

    _record, checks = verifier.verify_p1_topology(ROOT, wrong)

    assert checks[0].check_id == "p1.git.linear_topology"
    assert checks[0].outcome == "FAIL"
    assert "expected=" in checks[0].evidence


def test_p1_vpn_dataset_rejects_count_hash_and_boundary_drift(
    verifier: ModuleType,
) -> None:
    root = ROOT / "evals/datasets/functional/vpn-readonly-p1"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    cases = json.loads((root / "vpn-cases.json").read_text(encoding="utf-8"))
    card = (root / "dataset-card.yaml").read_text(encoding="utf-8")
    drifted_manifest = copy.deepcopy(manifest)
    drifted_cases = copy.deepcopy(cases)
    drifted_manifest["case_count"] = 19
    drifted_cases["cases"][0]["case_id"] = "vpn-p1-999"

    violations = verifier.p1_dataset_violations(
        drifted_manifest,
        drifted_cases,
        card.replace("release_eligible: false", "release_eligible: true"),
    )

    assert violations == [
        "cases.ids",
        "dataset_card.boundaries",
        "manifest.case_count",
    ]


def test_p1_vpn_schema_drift_fails_closed(
    verifier: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        verifier,
        "P1_KNOWLEDGE_SCHEMA_PIN",
        "sha256:" + "0" * 64,
    )

    _record, checks = verifier.verify_p1_static_boundaries(ROOT)
    schema_check = next(
        check for check in checks if check.check_id == "p1.knowledge.schema_hash"
    )

    assert schema_check.outcome == "FAIL"


def test_p1_vpn_evidence_hash_drift_fails_closed(
    verifier: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset, _checks = verifier.verify_p1_dataset(ROOT)
    drifted = dict(verifier.P1_EVIDENCE)
    revision, path, _expected = drifted["S4_HANDOFF"]
    drifted["S4_HANDOFF"] = (revision, path, "0" * 64)
    monkeypatch.setattr(verifier, "P1_EVIDENCE", drifted)

    _record, checks = verifier.verify_p1_evidence(ROOT, dataset)
    handoff_check = next(
        check for check in checks if check.check_id == "p1.evidence.s4_handoff"
    )

    assert handoff_check.outcome == "FAIL"


def test_p1_vpn_candidate_rejects_non_s7_delta(
    verifier: ModuleType,
) -> None:
    violations = verifier.path_scope_violations(
        (
            "scripts/integration/verify_wp040.py",
            "tests/integration/test_wp040_p1_vpn.py",
            "apps/worker/src/flowpilot_worker/vpn.py",
        ),
        verifier.S7_ALLOWED_PREFIXES,
    )

    assert violations == ["apps/worker/src/flowpilot_worker/vpn.py"]


def test_p1_vpn_final_requires_reviewed_s7_head(
    verifier: ModuleType,
) -> None:
    with pytest.raises(
        ValueError,
        match="--s7-head is required for P1_VPN_S1_FINAL",
    ):
        verifier.build_manifest(
            ROOT,
            phase=verifier.ValidationPhase.P1_VPN_S1_FINAL,
            target_head=verifier.P1_INPUT_HEAD,
        )


def test_p1_vpn_final_scope_keeps_product_protected(
    verifier: ModuleType,
) -> None:
    allowed = [
        ("M", "docs/review/WP-040-A6-S1-FINAL-REVIEW.md"),
        ("M", "scripts/integration/verify_wp040.py"),
        ("A", "tests/integration/evidence/WP-040-a6-HANDOFF.md"),
        ("M", ".gitignore"),
    ]
    forbidden = allowed + [
        ("M", "apps/worker/src/flowpilot_worker/vpn.py"),
        ("M", "tests/acceptance/vpn/blackbox.py"),
        ("A", "scripts/release/skip-vpn-gate.py"),
    ]

    assert verifier.final_scope_violations(allowed, ".idea/\n") == []
    assert verifier.final_scope_violations(forbidden, ".idea/\n") == [
        "A:scripts/release/skip-vpn-gate.py",
        "M:apps/worker/src/flowpilot_worker/vpn.py",
        "M:tests/acceptance/vpn/blackbox.py",
    ]


def test_p1_vpn_proof_closes_security_and_recovery(
    candidate_manifest: dict[str, Any],
) -> None:
    manifest = candidate_manifest
    proof = manifest["evidence"]["S4_PROOF_SEMANTICS"]

    assert proof == {
        "declared_case_count": 20,
        "passed": 20,
        "failed": 0,
        "candidate_only": True,
        "release_eligible": False,
        "cross_tenant_successful_retrievals": 0,
        "recovery_single_logical_call": True,
    }
