from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPOSITION_SCRIPT = ROOT / "scripts/integration/verify_wp040.py"
RECOVERY_SCRIPT = ROOT / "scripts/integration/verify_durable_recovery.py"


def load_module(name: str, path: Path) -> ModuleType:
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def verifier() -> ModuleType:
    return load_module("verify_wp040_p2", COMPOSITION_SCRIPT)


@pytest.fixture(scope="module")
def recovery() -> ModuleType:
    return load_module("verify_durable_recovery_p2", RECOVERY_SCRIPT)


@pytest.fixture(scope="module")
def candidate_manifest(verifier: ModuleType) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        verifier.build_manifest(
            ROOT,
            phase=verifier.ValidationPhase.P2_DURABLE_CANDIDATE,
            target_head=verifier.P2_INPUT_HEAD,
        ),
    )


def test_p2_durable_candidate_is_exact_and_dependency_complete(
    candidate_manifest: dict[str, Any],
) -> None:
    assert candidate_manifest["summary"] == {
        "check_count": 33,
        "failed_check_count": 0,
        "failed_checks": [],
        "verdict": "PASS",
    }
    assert candidate_manifest["chain_id"] == "CHAIN-P2-DURABLE-RUNTIME-01"
    assert candidate_manifest["topology"]["commit_count"] == 5
    assert candidate_manifest["workspace"]["member_count"] == 14
    assert candidate_manifest["workspace"]["lock_package_count"] == 116


def test_p2_durable_topology_and_evidence_are_closed(
    candidate_manifest: dict[str, Any],
) -> None:
    assert all(
        not step["violations"]
        for step in candidate_manifest["topology"]["steps"].values()
    )
    evidence = candidate_manifest["evidence"]
    assert evidence["S6_HANDOFF"]["sha256"] == (
        "sha256:17759d0beca2644cfa5910bdf1d5327"
        "c924438a28eafc47434ea394b13ee1823"
    )
    assert evidence["S2_HANDOFF"]["sha256"] == (
        "sha256:5fb65bcb3f2c2e47ae081c70201e282d"
        "3d1d6e85b83b3800da076f4d1b6b24d1"
    )


def test_p2_durable_worker_uses_typed_ports_without_driver_bypass(
    candidate_manifest: dict[str, Any],
) -> None:
    assert candidate_manifest["boundaries"] == {
        "worker_source_count": 9,
        "driver_bypass_findings": [],
        "typed_durable_assembly": True,
        "explicit_control_checkpointer": True,
        "fenced_checkpoint_cas": True,
        "trusted_tenant_rebuild": True,
    }


def test_p2_durable_manifest_and_report_are_deterministic(
    verifier: ModuleType,
    candidate_manifest: dict[str, Any],
    tmp_path: Path,
) -> None:
    first = verifier.write_artifacts(candidate_manifest, tmp_path / "first")
    second = verifier.write_artifacts(candidate_manifest, tmp_path / "second")

    assert first[0].read_bytes() == second[0].read_bytes()
    assert first[1].read_bytes() == second[1].read_bytes()
    assert first[2:] == second[2:]


def test_p2_durable_wrong_linear_parent_fails_closed(
    verifier: ModuleType,
) -> None:
    wrong = {verifier.P2_DATA_IMPLEMENTATION_HEAD: verifier.P2_ACTIVATION_COMMIT}

    _record, checks = verifier.verify_p2_topology(ROOT, wrong)

    assert checks[0].check_id == "p2.git.linear_topology"
    assert checks[0].outcome == "FAIL"


def test_p2_durable_evidence_hash_drift_fails_closed(
    verifier: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drifted = dict(verifier.P2_EVIDENCE)
    revision, path, _expected = drifted["S2_HANDOFF"]
    drifted["S2_HANDOFF"] = (revision, path, "0" * 64)
    monkeypatch.setattr(verifier, "P2_EVIDENCE", drifted)

    _record, checks = verifier.verify_p2_evidence(ROOT)
    handoff = next(
        check for check in checks if check.check_id == "p2.evidence.s2_handoff"
    )

    assert handoff.outcome == "FAIL"


def test_p2_durable_candidate_rejects_non_s7_delta(
    verifier: ModuleType,
) -> None:
    violations = verifier.path_scope_violations(
        (
            "scripts/integration/verify_durable_recovery.py",
            "tests/integration/test_wp040_p2_durable.py",
            "apps/worker/src/flowpilot_worker/durable.py",
        ),
        verifier.S7_ALLOWED_PREFIXES,
    )

    assert violations == ["apps/worker/src/flowpilot_worker/durable.py"]


def test_p2_durable_final_requires_reviewed_s7_head(
    verifier: ModuleType,
) -> None:
    with pytest.raises(
        ValueError,
        match="--s7-head is required for P2_DURABLE_S1_FINAL",
    ):
        verifier.build_manifest(
            ROOT,
            phase=verifier.ValidationPhase.P2_DURABLE_S1_FINAL,
            target_head=verifier.P2_INPUT_HEAD,
        )


def test_p2_durable_final_scope_rejects_product_changes(
    verifier: ModuleType,
) -> None:
    changes = [
        ("M", "docs/review/WP-040-A7-S1-FINAL-REVIEW.md"),
        ("M", "scripts/integration/verify_wp040.py"),
        ("A", "tests/integration/evidence/WP-040-a7-HANDOFF.md"),
        ("M", "apps/worker/src/flowpilot_worker/durable.py"),
    ]

    assert verifier.final_scope_violations(changes, ".idea/\n") == [
        "M:apps/worker/src/flowpilot_worker/durable.py"
    ]


def valid_recovery_result(recovery: ModuleType) -> Any:
    return recovery.RecoveryResult(
        redis_loss_observed=True,
        first_rebuilt_signal_count=1,
        second_rebuilt_signal_count=1,
        terminal_rebuilt_signal_count=0,
        first_run_generation=1,
        recovered_run_generation=2,
        first_checkpoint_sequence=4,
        completed_checkpoint_sequence=8,
        old_worker_write_attempts=1,
        old_worker_successful_writes=0,
        stale_cas_successful_writes=0,
        terminal_node_reruns=0,
        terminal_checkpoint_writes=0,
        cross_tenant_successful_reads=0,
        redis_keys_after_terminal_rebuild=0,
        runtime_calls=2,
        control_checkpointers_observed=3,
    )


def test_p2_recovery_summary_accepts_all_zero_safety_counters(
    recovery: ModuleType,
) -> None:
    recovery.assert_recovery_result(valid_recovery_result(recovery))


@pytest.mark.parametrize(
    "field",
    (
        "old_worker_successful_writes",
        "stale_cas_successful_writes",
        "terminal_node_reruns",
        "terminal_checkpoint_writes",
        "cross_tenant_successful_reads",
        "redis_keys_after_terminal_rebuild",
    ),
)
def test_p2_recovery_summary_rejects_positive_safety_counters(
    recovery: ModuleType,
    field: str,
) -> None:
    result = replace(valid_recovery_result(recovery), **{field: 1})

    with pytest.raises(AssertionError, match="failed closed checks"):
        recovery.assert_recovery_result(result)
