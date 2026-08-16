from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/integration/verify_m10_composition.py"
PROOF = ROOT / "artifacts/integration/WP-120-a1-PROOF.json"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("wp120_verifier", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_wp120_recomputes_repository_and_current_registry() -> None:
    module = _module()
    checks = [*module.verify_repository(), module.verify_current_registry()]

    assert checks
    assert all(check.passed for check in checks)


def test_wp120_proof_keeps_fixed_denominator_and_release_blocked() -> None:
    proof = json.loads(PROOF.read_text(encoding="utf-8"))

    assert proof["summary"] == {
        "artifact_hashes": 55,
        "completed": 40,
        "declared": 156,
        "explicit_failed": 116,
        "failed_checks": [],
        "frozen_claimed": False,
        "manifest_gate": "fail",
        "quarantined": 0,
        "release_claimed": False,
        "skipped": 0,
        "verdict": "PASS",
    }


def test_wp120_hash_check_detects_tamper(tmp_path: Path) -> None:
    module = _module()
    artifact = tmp_path / "artifact.json"
    artifact.write_text("{}\n", encoding="utf-8")
    original = module._sha256(artifact)
    artifact.write_text('{"drift":true}\n', encoding="utf-8")

    assert module._sha256(artifact) != original
