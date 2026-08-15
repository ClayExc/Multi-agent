"""Stable, redacted failures for the engineering control plane."""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class ErrorCode(StrEnum):
    """Machine-stable engineering-control failure codes."""

    INVALID_PATH = "ENG_INVALID_PATH"
    UNKNOWN_PATH = "ENG_UNKNOWN_PATH"
    OWNER_CONFLICT = "ENG_OWNER_CONFLICT"
    DIRTY_WORKTREE = "ENG_DIRTY_WORKTREE"
    GIT_COMMAND_FAILED = "ENG_GIT_COMMAND_FAILED"
    NON_LINEAR_BASE = "ENG_NON_LINEAR_BASE"
    MISSING_WORKSPACE_MEMBER = "ENG_MISSING_WORKSPACE_MEMBER"
    INVALID_WORKSPACE_METADATA = "ENG_INVALID_WORKSPACE_METADATA"
    MISSING_WORKSPACE_DEPENDENCY = "ENG_MISSING_WORKSPACE_DEPENDENCY"
    TARGET_NOT_HEAD = "ENG_TARGET_NOT_HEAD"
    SCOPE_VIOLATION = "ENG_SCOPE_VIOLATION"
    OUTPUT_POLICY_VIOLATION = "ENG_OUTPUT_POLICY_VIOLATION"


_MESSAGES: Final[dict[ErrorCode, str]] = {
    ErrorCode.INVALID_PATH: "repository path is invalid",
    ErrorCode.UNKNOWN_PATH: "repository path has no registered owner",
    ErrorCode.OWNER_CONFLICT: "repository path matches multiple owner rules",
    ErrorCode.DIRTY_WORKTREE: "repository worktree is not clean",
    ErrorCode.GIT_COMMAND_FAILED: "Git operation failed",
    ErrorCode.NON_LINEAR_BASE: "base commit is not an ancestor of target",
    ErrorCode.MISSING_WORKSPACE_MEMBER: "Workspace member is missing",
    ErrorCode.INVALID_WORKSPACE_METADATA: "Workspace metadata is invalid",
    ErrorCode.MISSING_WORKSPACE_DEPENDENCY: "Workspace dependency is unresolved",
    ErrorCode.TARGET_NOT_HEAD: "target must equal the clean worktree HEAD",
    ErrorCode.SCOPE_VIOLATION: "requested path is outside the authorized scope",
    ErrorCode.OUTPUT_POLICY_VIOLATION: "output would violate metadata-only policy",
}


class EngineeringControlError(RuntimeError):
    """A stable failure that never embeds source text or command output."""

    def __init__(
        self,
        code: ErrorCode,
        *,
        metadata: dict[str, str | int | bool] | None = None,
    ) -> None:
        self.code = code
        self.metadata = dict(sorted((metadata or {}).items()))
        super().__init__(_MESSAGES[code])

    @property
    def safe_message(self) -> str:
        return _MESSAGES[self.code]
