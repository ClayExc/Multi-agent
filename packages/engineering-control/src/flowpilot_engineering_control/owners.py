"""Deterministic repository ownership resolution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from fnmatch import fnmatchcase

from flowpilot_engineering_control.errors import EngineeringControlError, ErrorCode
from flowpilot_engineering_control.paths import normalize_repo_path, path_is_within


class MatchKind(StrEnum):
    EXACT = "exact"
    PREFIX = "prefix"
    ROOT_GLOB = "root_glob"


@dataclass(frozen=True, slots=True)
class OwnerRule:
    pattern: str
    owner: str
    match_kind: MatchKind = MatchKind.PREFIX
    shared_writer: bool = False

    def matches(self, path: str) -> bool:
        if self.match_kind is MatchKind.EXACT:
            return path == normalize_repo_path(self.pattern)
        if self.match_kind is MatchKind.ROOT_GLOB:
            return "/" not in path and fnmatchcase(path, self.pattern)
        return path_is_within(path, self.pattern)


@dataclass(frozen=True, slots=True)
class OwnerAssignment:
    path: str
    owner: str
    shared_writer: bool
    rule: str


class OwnerResolver:
    def __init__(self, rules: tuple[OwnerRule, ...]) -> None:
        self._rules = rules

    @property
    def rules(self) -> tuple[OwnerRule, ...]:
        return self._rules

    def resolve(self, raw_path: str) -> OwnerAssignment:
        path = normalize_repo_path(raw_path)
        matches = [rule for rule in self._rules if rule.matches(path)]
        if not matches:
            raise EngineeringControlError(
                ErrorCode.UNKNOWN_PATH,
                metadata={"path": path},
            )
        if len(matches) != 1:
            raise EngineeringControlError(
                ErrorCode.OWNER_CONFLICT,
                metadata={"match_count": len(matches), "path": path},
            )
        rule = matches[0]
        return OwnerAssignment(
            path=path,
            owner=rule.owner,
            shared_writer=rule.shared_writer,
            rule=rule.pattern,
        )


def default_owner_rules() -> tuple[OwnerRule, ...]:
    """The non-overlapping ownership model registered by AGENTS.md."""

    prefix_owners = {
        ".github": "S1-ARCH",
        "apps/api": "S5-CORE",
        "apps/mcp-gateway": "S3-PLATFORM",
        "apps/worker": "S2-RUNTIME",
        "artifacts": "S4-QUALITY",
        "contracts": "S1-ARCH",
        "docs": "S1-ARCH",
        "domain-packs": "S5-CORE",
        "evals": "S4-QUALITY",
        "infra": "S6-DATA",
        "mcp-servers": "S3-PLATFORM",
        "migrations": "S6-DATA",
        "packages/agent-runtime": "S2-RUNTIME",
        "packages/application": "S5-CORE",
        "packages/context": "S2-RUNTIME",
        "packages/domain": "S5-CORE",
        "packages/engineering-control": "S5-CORE",
        "packages/evaluation": "S4-QUALITY",
        "packages/graph": "S2-RUNTIME",
        "packages/model-gateway": "S2-RUNTIME",
        "packages/observability": "S4-QUALITY",
        "packages/persistence": "S6-DATA",
        "packages/policy": "S3-PLATFORM",
        "packages/retrieval": "S4-QUALITY",
        "packages/security": "S3-PLATFORM",
        "packages/tool-contracts": "S3-PLATFORM",
        "scripts/acceptance": "S4-QUALITY",
        "scripts/engineering": "S5-CORE",
        "scripts/integration": "S7-INTEGRATION",
        "tests/acceptance": "S4-QUALITY",
        "tests/core": "S5-CORE",
        "tests/data": "S6-DATA",
        "tests/experience": "S4-QUALITY",
        "tests/integration": "S7-INTEGRATION",
        "tests/platform": "S3-PLATFORM",
        "tests/runtime": "S2-RUNTIME",
        "web": "S4-QUALITY",
    }
    exact_owners = {
        ".env.example": ("S6-DATA", True),
        ".gitattributes": ("S1-ARCH", True),
        ".gitignore": ("S5-CORE", True),
        "Makefile": ("S4-QUALITY", True),
        "langgraph.json": ("S2-RUNTIME", True),
        "pyproject.toml": ("S5-CORE", True),
        "scripts/quality.ps1": ("S4-QUALITY", False),
        "uv.lock": ("S5-CORE", True),
    }
    rules = [
        OwnerRule(pattern=path, owner=owner)
        for path, owner in sorted(prefix_owners.items())
    ]
    rules.extend(
        OwnerRule(
            pattern=path,
            owner=owner,
            match_kind=MatchKind.EXACT,
            shared_writer=shared,
        )
        for path, (owner, shared) in sorted(exact_owners.items())
    )
    rules.append(
        OwnerRule(pattern="*.md", owner="S1-ARCH", match_kind=MatchKind.ROOT_GLOB)
    )
    return tuple(rules)
