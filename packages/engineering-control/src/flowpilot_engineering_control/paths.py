"""Cross-platform repository path policy."""

from __future__ import annotations

import re
import unicodedata

from flowpilot_engineering_control.errors import EngineeringControlError, ErrorCode

_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
_EXCLUDED_COMPONENTS = frozenset(
    {
        ".git",
        ".idea",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        ".vscode",
        "__pycache__",
        "build",
        "dist",
        "htmlcov",
        "node_modules",
        "site-packages",
    }
)
_COVERAGE_NAMES = frozenset({".coverage", "coverage.json", "coverage.xml"})


def normalize_repo_path(raw_path: str, *, allow_root: bool = False) -> str:
    """Return a normalized repository-relative POSIX path."""

    if not isinstance(raw_path, str) or "\x00" in raw_path:
        raise EngineeringControlError(ErrorCode.INVALID_PATH)
    normalized = unicodedata.normalize("NFC", raw_path).replace("\\", "/")
    if normalized.startswith("/") or _DRIVE_PREFIX.match(normalized):
        raise EngineeringControlError(ErrorCode.INVALID_PATH)
    parts: list[str] = []
    for part in normalized.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            raise EngineeringControlError(ErrorCode.INVALID_PATH)
        parts.append(part)
    result = "/".join(parts)
    if not result and not allow_root:
        raise EngineeringControlError(ErrorCode.INVALID_PATH)
    return result


def is_excluded_path(raw_path: str) -> bool:
    """Return whether a path is generated or local-only engineering noise."""

    path = normalize_repo_path(raw_path)
    parts = path.split("/")
    folded = [part.casefold() for part in parts]
    if any(part in _EXCLUDED_COMPONENTS for part in folded):
        return True
    if folded[0] == ".flowpilot-engineering":
        return True
    if folded[-1] in _COVERAGE_NAMES or folded[-1].startswith(".coverage."):
        return True
    if len(folded) >= 3 and folded[0] == "tests" and folded[2] == "evidence":
        return True
    return bool(
        len(folded) >= 2
        and folded[0] == "artifacts"
        and folded[1]
        in {
            "acceptance",
            "integration",
        }
    )


def path_is_within(path: str, prefix: str) -> bool:
    normalized_path = normalize_repo_path(path)
    normalized_prefix = normalize_repo_path(prefix)
    return normalized_path == normalized_prefix or normalized_path.startswith(
        f"{normalized_prefix}/"
    )
