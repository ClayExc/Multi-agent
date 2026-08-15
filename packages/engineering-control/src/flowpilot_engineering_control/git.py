"""Git adapter using argv-only subprocess calls."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from flowpilot_engineering_control.errors import EngineeringControlError, ErrorCode
from flowpilot_engineering_control.paths import normalize_repo_path


@dataclass(frozen=True, slots=True)
class GitChange:
    status: str
    path: str
    old_path: str | None = None


class GitClient:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def _run(
        self, argv: list[str], *, allowed_codes: frozenset[int] = frozenset({0})
    ) -> bytes:
        completed = subprocess.run(
            ["git", "-c", "core.quotePath=false", *argv],
            cwd=self._root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            shell=False,
        )
        if completed.returncode not in allowed_codes:
            raise EngineeringControlError(
                ErrorCode.GIT_COMMAND_FAILED,
                metadata={"operation": argv[0], "return_code": completed.returncode},
            )
        return completed.stdout

    def head(self) -> str:
        return self._run(["rev-parse", "HEAD"]).decode("ascii").strip()

    def resolve_commit(self, revision: str) -> str:
        return (
            self._run(
                ["rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}"]
            )
            .decode("ascii")
            .strip()
        )

    def require_clean(self) -> None:
        status = self._run(["status", "--porcelain=v1", "-z", "--untracked-files=all"])
        if status:
            entries = [entry for entry in status.split(b"\x00") if entry]
            raise EngineeringControlError(
                ErrorCode.DIRTY_WORKTREE,
                metadata={"entry_count": len(entries)},
            )

    def tracked_files(self) -> tuple[str, ...]:
        raw = self._run(["ls-files", "-z"])
        return tuple(
            sorted(
                normalize_repo_path(item.decode("utf-8", errors="strict"))
                for item in raw.split(b"\x00")
                if item
            )
        )

    def require_ancestor(self, base: str, target: str) -> None:
        base_commit = self.resolve_commit(base)
        target_commit = self.resolve_commit(target)
        completed = subprocess.run(
            [
                "git",
                "-c",
                "core.quotePath=false",
                "merge-base",
                "--is-ancestor",
                base_commit,
                target_commit,
            ],
            cwd=self._root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            shell=False,
        )
        if completed.returncode == 1:
            raise EngineeringControlError(
                ErrorCode.NON_LINEAR_BASE,
                metadata={"base": base_commit, "target": target_commit},
            )
        if completed.returncode != 0:
            raise EngineeringControlError(
                ErrorCode.GIT_COMMAND_FAILED,
                metadata={
                    "operation": "merge-base",
                    "return_code": completed.returncode,
                },
            )

    def changes(self, base: str, target: str) -> tuple[GitChange, ...]:
        self.require_ancestor(base, target)
        base_commit = self.resolve_commit(base)
        target_commit = self.resolve_commit(target)
        raw = self._run(
            [
                "diff",
                "--no-ext-diff",
                "--name-status",
                "-z",
                "--find-renames=50%",
                base_commit,
                target_commit,
                "--",
            ]
        )
        parts = [
            part.decode("utf-8", errors="strict") for part in raw.split(b"\x00") if part
        ]
        changes: list[GitChange] = []
        index = 0
        while index < len(parts):
            status = parts[index]
            index += 1
            if status.startswith(("R", "C")):
                if index + 1 >= len(parts):
                    raise EngineeringControlError(ErrorCode.GIT_COMMAND_FAILED)
                old_path = normalize_repo_path(parts[index])
                path = normalize_repo_path(parts[index + 1])
                index += 2
                changes.append(
                    GitChange(status=status[0], old_path=old_path, path=path)
                )
            else:
                if index >= len(parts):
                    raise EngineeringControlError(ErrorCode.GIT_COMMAND_FAILED)
                path = normalize_repo_path(parts[index])
                index += 1
                changes.append(GitChange(status=status[0], path=path))
        return tuple(
            sorted(
                changes, key=lambda item: (item.path, item.old_path or "", item.status)
            )
        )
