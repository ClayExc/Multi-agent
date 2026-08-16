from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/integration/verify_engineering_control.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("wp094_verifier", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _proof() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(
            (
                ROOT / "artifacts/acceptance/engineering-control/WP-093-a1-PROOF.json"
            ).read_text(encoding="utf-8")
        ),
    )


def test_wp094_verifier_recomputes_exact_composition() -> None:
    result = _module().verify()

    assert result.declared_cases == result.passed_cases == result.unique_cases == 28
    assert result.failed_cases == result.skipped_cases == 0
    assert result.mutation_cases == 12
    assert result.mutation_omissions == 0
    assert (result.initial_read_files, result.repository_files) == (6, 88)
    assert (result.initial_read_bytes, result.repository_bytes) == (307, 67820)
    assert result.ratio_basis_points == 45
    assert result.product_path_violations == result.protected_tree_changes == 0
    assert result.lock_workspace_complete is True
    assert result.deterministic_outputs == 3


def test_wp094_verifier_rejects_denominator_drift() -> None:
    module = _module()
    proof = _proof()
    proof["all_declared_cases"] = 27
    payload = {key: value for key, value in proof.items() if key != "proof_sha256"}
    proof["proof_sha256"] = module.hashlib.sha256(
        module._canonical(payload)
    ).hexdigest()

    with pytest.raises(AssertionError, match="28/28"):
        module._verify_upstream_proof(proof)


def test_wp094_verifier_rejects_mutation_omission() -> None:
    module = _module()
    proof = _proof()
    case = next(
        item
        for item in proof["cases"]
        if item["case_id"] == "mutation/package-internal"
    )
    tampered = copy.deepcopy(case)
    tampered["observed_commands"] = []
    cases = [tampered if item is case else item for item in proof["cases"]]

    with pytest.raises(AssertionError, match="selected no commands"):
        module._verify_mutations(cases)


def test_wp094_verifier_accepts_committed_candidate_head() -> None:
    module = _module()

    module._validate_candidate_lineage(module.HISTORICAL_CANDIDATE_HEAD)


def test_wp094_verifier_rejects_non_ancestor(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_is_ancestor", lambda _base, _head: False)

    with pytest.raises(AssertionError, match="not an ancestor"):
        module._validate_candidate_lineage("candidate")


def test_wp094_verifier_rejects_unauthorized_successor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    monkeypatch.setattr(module, "_is_ancestor", lambda _base, _head: True)
    monkeypatch.setattr(module, "_candidate_paths", lambda _head: ("apps/api/main.py",))

    with pytest.raises(AssertionError, match="unauthorized S7 delta"):
        module._validate_candidate_lineage("candidate")


def test_wp094_verifier_rejects_input_tree_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    monkeypatch.setattr(module, "_git", lambda *_args: "drifted")

    with pytest.raises(AssertionError, match="input tree drifted"):
        module._validate_input_trees()
