from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/integration/verify_m9_composition.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("wp109_verifier", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_wp109_recomputes_unique_official_registry() -> None:
    result = _module().verify()

    assert result.declared_cases == result.unique_case_ids == 156
    assert result.completed == 39
    assert result.explicit_failed == 117
    assert result.skipped == result.quarantined == 0
    assert (result.m7_supported, result.m8_supported, result.m9_supported) == (
        24,
        6,
        9,
    )
    assert result.duplicate_matches == 0
    assert result.dangerous_output_count == result.cross_tenant_success_count == 0
    assert result.judge_scores_used == 0
    assert result.manifest_gate == "FAIL"
    assert result.release_claimed is result.frozen_claimed is False
    assert result.candidate_scope_violations == result.protected_object_changes == 0


def test_wp109_rejects_non_ancestor_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    monkeypatch.setattr(module, "_is_ancestor", lambda _base, _head: False)

    with pytest.raises(AssertionError, match="not an ancestor"):
        module._validate_candidate()


def test_wp109_rejects_unauthorized_candidate_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    monkeypatch.setattr(module, "_is_ancestor", lambda _base, _head: True)

    def fake_git(*args: str) -> str:
        if args[:2] == ("rev-parse", "HEAD"):
            return "candidate"
        if args[:2] == ("diff", "--name-only"):
            return "packages/security/unauthorized.py"
        return cast(
            str,
            module.EXPECTED_INPUT_OBJECTS[args[-1].split(":", 1)[1]],
        )

    monkeypatch.setattr(module, "_git", fake_git)
    with pytest.raises(AssertionError, match="unauthorized WP-109 path"):
        module._validate_candidate()


def test_wp109_rejects_protected_input_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    monkeypatch.setattr(module, "_is_ancestor", lambda _base, _head: True)

    def fake_git(*args: str) -> str:
        if args[:2] == ("rev-parse", "HEAD"):
            return "candidate"
        if args[:2] == ("diff", "--name-only"):
            return ""
        return "drifted"

    monkeypatch.setattr(module, "_git", fake_git)
    with pytest.raises(AssertionError, match="protected input object drifted"):
        module._validate_candidate()
