from __future__ import annotations

import pytest
from flowpilot_engineering_control.errors import EngineeringControlError, ErrorCode
from flowpilot_engineering_control.owners import (
    MatchKind,
    OwnerResolver,
    OwnerRule,
)
from flowpilot_engineering_control.paths import (
    is_excluded_path,
    normalize_repo_path,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (r"packages\domain\src\module.py", "packages/domain/src/module.py"),
        ("./packages//domain/src/module.py", "packages/domain/src/module.py"),
        ("dömain/é.py", "dömain/é.py"),
    ],
)
def test_normalize_repo_path_is_platform_independent(raw: str, expected: str) -> None:
    assert normalize_repo_path(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["../secret", "/absolute/path", r"C:\secret", "path/../../secret", "a\x00b"],
)
def test_normalize_repo_path_rejects_unsafe_paths(raw: str) -> None:
    with pytest.raises(EngineeringControlError) as captured:
        normalize_repo_path(raw)
    assert captured.value.code is ErrorCode.INVALID_PATH


def test_exclusions_use_path_segments_not_substrings() -> None:
    assert is_excluded_path(".git/config")
    assert is_excluded_path("tests/core/evidence/HANDOFF.md")
    assert is_excluded_path("packages/domain/.pytest_cache/value")
    assert not is_excluded_path("packages/domain/src/coverage_policy.py")


def test_owner_resolver_fails_on_unknown_and_conflict() -> None:
    resolver = OwnerResolver(
        (
            OwnerRule("packages", "S1-ARCH"),
            OwnerRule("packages/domain", "S5-CORE"),
        )
    )
    with pytest.raises(EngineeringControlError) as conflict:
        resolver.resolve("packages/domain/model.py")
    assert conflict.value.code is ErrorCode.OWNER_CONFLICT

    exact = OwnerResolver((OwnerRule("README.md", "S1-ARCH", MatchKind.EXACT),))
    with pytest.raises(EngineeringControlError) as unknown:
        exact.resolve("unowned.txt")
    assert unknown.value.code is ErrorCode.UNKNOWN_PATH
