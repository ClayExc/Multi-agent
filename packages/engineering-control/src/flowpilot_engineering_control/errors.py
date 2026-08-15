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
    SELECTION_INCOMPLETE = "ENG_SELECTION_INCOMPLETE"
    TEST_PLAN_EMPTY = "ENG_TEST_PLAN_EMPTY"
    ARGV_INVALID = "ENG_ARGV_INVALID"
    CACHE_FAILED_RESULT = "ENG_CACHE_FAILED_RESULT"
    CACHE_POLICY_DENIED = "ENG_CACHE_POLICY_DENIED"
    CACHE_INTEGRITY_MISMATCH = "ENG_CACHE_INTEGRITY_MISMATCH"
    CACHE_KEY_CONFLICT = "ENG_CACHE_KEY_CONFLICT"
    CACHE_UNTRACEABLE_HEAD = "ENG_CACHE_UNTRACEABLE_HEAD"
    EVIDENCE_INVALID = "ENG_EVIDENCE_INVALID"
    REPORT_INVALID = "ENG_REPORT_INVALID"


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
    ErrorCode.SELECTION_INCOMPLETE: "test selection completeness cannot be proven",
    ErrorCode.TEST_PLAN_EMPTY: "test plan cannot be empty",
    ErrorCode.ARGV_INVALID: "command argv is invalid",
    ErrorCode.CACHE_FAILED_RESULT: "failed command result is not cacheable",
    ErrorCode.CACHE_POLICY_DENIED: "evidence reuse policy denies caching",
    ErrorCode.CACHE_INTEGRITY_MISMATCH: "evidence cache integrity check failed",
    ErrorCode.CACHE_KEY_CONFLICT: "cache key already has different evidence",
    ErrorCode.CACHE_UNTRACEABLE_HEAD: "evidence producer Head is not traceable",
    ErrorCode.EVIDENCE_INVALID: "evidence metadata is invalid",
    ErrorCode.REPORT_INVALID: "attempt report metadata is invalid",
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
