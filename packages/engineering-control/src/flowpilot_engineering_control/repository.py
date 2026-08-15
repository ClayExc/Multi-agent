"""Deterministic repository map construction."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flowpilot_engineering_control.errors import EngineeringControlError, ErrorCode
from flowpilot_engineering_control.git import GitClient
from flowpilot_engineering_control.owners import (
    OwnerResolver,
    OwnerRule,
    default_owner_rules,
)
from flowpilot_engineering_control.paths import is_excluded_path, normalize_repo_path
from flowpilot_engineering_control.serialization import (
    JsonValue,
    canonical_json_bytes,
    sha256_bytes,
)

SCHEMA_VERSION = "flowpilot.repository-map.v1"
GENERATOR_VERSION = "0.1.0"
OWNER_POLICY_VERSION = "flowpilot.repository-owners.v1"
_DEPENDENCY_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9_.-]*)")


@dataclass(frozen=True, slots=True)
class WorkspaceMember:
    path: str
    name: str
    dependencies: tuple[str, ...]

    def to_record(self) -> dict[str, JsonValue]:
        return {
            "dependencies": list(self.dependencies),
            "name": self.name,
            "path": self.path,
        }


@dataclass(frozen=True, slots=True)
class FileRecord:
    path: str
    sha256: str
    byte_count: int
    owner: str
    package: str | None
    kind: str
    public_signature: bool
    protected_tags: tuple[str, ...]

    def to_record(self) -> dict[str, JsonValue]:
        return {
            "byte_count": self.byte_count,
            "kind": self.kind,
            "owner": self.owner,
            "package": self.package,
            "path": self.path,
            "protected_tags": list(self.protected_tags),
            "public_signature_sha256": self.sha256 if self.public_signature else None,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class DependencyEdge:
    dependency: str
    dependent: str

    def to_record(self) -> dict[str, JsonValue]:
        return {"dependency": self.dependency, "dependent": self.dependent}


@dataclass(frozen=True, slots=True)
class TestMapping:
    package: str
    test_prefixes: tuple[str, ...]

    def to_record(self) -> dict[str, JsonValue]:
        return {"package": self.package, "test_prefixes": list(self.test_prefixes)}


@dataclass(frozen=True, slots=True)
class RepositoryMap:
    git_head: str
    files: tuple[FileRecord, ...]
    workspace_members: tuple[WorkspaceMember, ...]
    dependency_edges: tuple[DependencyEdge, ...]
    test_mappings: tuple[TestMapping, ...]
    owner_rules: tuple[OwnerRule, ...]
    tree_signatures: tuple[tuple[str, str], ...]

    def file_by_path(self) -> dict[str, FileRecord]:
        return {record.path: record for record in self.files}

    def member_by_path(self) -> dict[str, WorkspaceMember]:
        return {member.path: member for member in self.workspace_members}

    def member_by_name(self) -> dict[str, WorkspaceMember]:
        return {member.name: member for member in self.workspace_members}

    def payload(self) -> dict[str, JsonValue]:
        owner_rule_records: list[JsonValue] = [
            {
                "match_kind": rule.match_kind.value,
                "owner": rule.owner,
                "pattern": rule.pattern,
                "shared_writer": rule.shared_writer,
            }
            for rule in self.owner_rules
        ]
        total_bytes = sum(record.byte_count for record in self.files)
        return {
            "authorization": {
                "owner_policy_version": OWNER_POLICY_VERSION,
                "owner_rules": owner_rule_records,
            },
            "counts": {
                "dependency_edges": len(self.dependency_edges),
                "files": len(self.files),
                "public_signatures": sum(
                    1 for record in self.files if record.public_signature
                ),
                "source_bytes": total_bytes,
                "workspace_members": len(self.workspace_members),
            },
            "dependency_edges": [edge.to_record() for edge in self.dependency_edges],
            "generator": {
                "name": "flowpilot-engineering-control",
                "version": GENERATOR_VERSION,
            },
            "git_head": self.git_head,
            "path_entries": [record.to_record() for record in self.files],
            "schema_version": SCHEMA_VERSION,
            "test_mappings": [mapping.to_record() for mapping in self.test_mappings],
            "tree_signatures": dict(self.tree_signatures),
            "workspace_members": [
                member.to_record() for member in self.workspace_members
            ],
        }

    @property
    def digest(self) -> str:
        return sha256_bytes(canonical_json_bytes(self.payload()))

    def to_record(self) -> dict[str, JsonValue]:
        payload = self.payload()
        return {**payload, "map_sha256": self.digest}

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_record())


class RepositoryMapBuilder:
    """Build a clean-HEAD repository map without retaining file contents."""

    def __init__(
        self,
        root: Path,
        *,
        owner_rules: tuple[OwnerRule, ...] | None = None,
        git: GitClient | None = None,
    ) -> None:
        self._root = root.resolve()
        self._rules = owner_rules or default_owner_rules()
        self._owners = OwnerResolver(self._rules)
        self._git = git or GitClient(self._root)

    def build(self) -> RepositoryMap:
        self._git.require_clean()
        head = self._git.head()
        members = self._workspace_members()
        member_paths = tuple(member.path for member in members)
        files: list[FileRecord] = []
        casefold_paths: dict[str, str] = {}
        for path in self._git.tracked_files():
            if is_excluded_path(path):
                continue
            folded = path.casefold()
            existing = casefold_paths.get(folded)
            if existing is not None and existing != path:
                raise EngineeringControlError(
                    ErrorCode.INVALID_PATH,
                    metadata={"collision_count": 2},
                )
            casefold_paths[folded] = path
            assignment = self._owners.resolve(path)
            content = self._read_tracked_bytes(path)
            package = self._package_for_path(path, member_paths)
            tags = self._protected_tags(path)
            files.append(
                FileRecord(
                    path=path,
                    sha256=sha256_bytes(content),
                    byte_count=len(content),
                    owner=assignment.owner,
                    package=package,
                    kind=self._kind(path),
                    public_signature=self._is_public_signature(path, package),
                    protected_tags=tags,
                )
            )
        files.sort(key=lambda record: record.path.encode("utf-8"))
        edges = self._dependency_edges(members)
        mappings = self._test_mappings(members)
        signatures = self._tree_signatures(tuple(files))
        return RepositoryMap(
            git_head=head,
            files=tuple(files),
            workspace_members=members,
            dependency_edges=edges,
            test_mappings=mappings,
            owner_rules=self._rules,
            tree_signatures=signatures,
        )

    def _read_tracked_bytes(self, path: str) -> bytes:
        candidate = self._root.joinpath(*path.split("/"))
        try:
            if candidate.is_symlink():
                return os.readlink(candidate).encode("utf-8")
            return candidate.read_bytes()
        except OSError as exc:
            raise EngineeringControlError(
                ErrorCode.GIT_COMMAND_FAILED,
                metadata={"operation": "read-tracked-file"},
            ) from exc

    def _workspace_members(self) -> tuple[WorkspaceMember, ...]:
        root_data = self._read_toml(self._root / "pyproject.toml")
        try:
            member_values = root_data["tool"]["uv"]["workspace"]["members"]
            source_values = root_data["tool"]["uv"]["sources"]
        except (KeyError, TypeError) as exc:
            raise EngineeringControlError(ErrorCode.INVALID_WORKSPACE_METADATA) from exc
        if not isinstance(member_values, list) or not isinstance(source_values, dict):
            raise EngineeringControlError(ErrorCode.INVALID_WORKSPACE_METADATA)
        members: list[WorkspaceMember] = []
        seen_names: set[str] = set()
        for raw_member in member_values:
            if not isinstance(raw_member, str):
                raise EngineeringControlError(ErrorCode.INVALID_WORKSPACE_METADATA)
            path = normalize_repo_path(raw_member)
            metadata_path = self._root.joinpath(*path.split("/"), "pyproject.toml")
            if not metadata_path.is_file():
                raise EngineeringControlError(
                    ErrorCode.MISSING_WORKSPACE_MEMBER,
                    metadata={"path": path},
                )
            data = self._read_toml(metadata_path)
            try:
                raw_name = data["project"]["name"]
                raw_dependencies = data["project"].get("dependencies", [])
            except (KeyError, TypeError) as exc:
                raise EngineeringControlError(
                    ErrorCode.INVALID_WORKSPACE_METADATA,
                    metadata={"path": path},
                ) from exc
            if not isinstance(raw_name, str) or not isinstance(raw_dependencies, list):
                raise EngineeringControlError(ErrorCode.INVALID_WORKSPACE_METADATA)
            name = _normalize_project_name(raw_name)
            if name in seen_names:
                raise EngineeringControlError(
                    ErrorCode.INVALID_WORKSPACE_METADATA,
                    metadata={"duplicate_package_count": 1},
                )
            seen_names.add(name)
            source = source_values.get(raw_name) or source_values.get(name)
            if not isinstance(source, dict) or source.get("workspace") is not True:
                raise EngineeringControlError(
                    ErrorCode.INVALID_WORKSPACE_METADATA,
                    metadata={"path": path},
                )
            dependencies = tuple(
                sorted(
                    _dependency_project_name(item)
                    for item in raw_dependencies
                    if isinstance(item, str)
                )
            )
            members.append(
                WorkspaceMember(path=path, name=name, dependencies=dependencies)
            )
        return tuple(sorted(members, key=lambda item: item.path.encode("utf-8")))

    @staticmethod
    def _read_toml(path: Path) -> dict[str, Any]:
        try:
            with path.open("rb") as handle:
                data = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise EngineeringControlError(ErrorCode.INVALID_WORKSPACE_METADATA) from exc
        return data

    @staticmethod
    def _package_for_path(path: str, member_paths: tuple[str, ...]) -> str | None:
        matches = [
            member
            for member in member_paths
            if path == member or path.startswith(f"{member}/")
        ]
        if not matches:
            return None
        return max(matches, key=len)

    @staticmethod
    def _kind(path: str) -> str:
        if path.startswith("contracts/"):
            return "contract"
        if path.startswith("migrations/"):
            return "migration"
        if path == "uv.lock":
            return "lock"
        if path.startswith("tests/"):
            return "test"
        if path.endswith(".md") or path.startswith("docs/"):
            return "documentation"
        if path.endswith((".toml", ".yaml", ".yml", ".json")):
            return "configuration"
        return "source"

    @staticmethod
    def _is_public_signature(path: str, package: str | None) -> bool:
        if package is None or "/src/" not in path:
            return False
        name = path.rsplit("/", 1)[-1]
        return (
            name
            in {"__init__.py", "ports.py", "interfaces.py", "protocols.py", "py.typed"}
            or "/ports/" in path
            or name.endswith("_ports.py")
        )

    @staticmethod
    def _protected_tags(path: str) -> tuple[str, ...]:
        tags: list[str] = []
        if path.startswith("contracts/"):
            tags.append("contract")
        if path.startswith("migrations/"):
            tags.append("migration")
        if path == "uv.lock":
            tags.append("lock")
        if path.startswith(("infra/",)) or path == ".env.example":
            tags.append("environment")
        if path.startswith(
            (
                "apps/mcp-gateway/",
                "packages/policy/",
                "packages/security/",
                "tests/platform/",
            )
        ):
            tags.append("security")
        if path.startswith(
            ("apps/", "mcp-servers/", "packages/", "web/")
        ) and not path.startswith("packages/engineering-control/"):
            tags.append("product")
        return tuple(sorted(tags))

    @staticmethod
    def _dependency_edges(
        members: tuple[WorkspaceMember, ...],
    ) -> tuple[DependencyEdge, ...]:
        internal_names = {member.name for member in members}
        edges: list[DependencyEdge] = []
        for member in members:
            for dependency in member.dependencies:
                if dependency in internal_names:
                    edges.append(
                        DependencyEdge(dependency=dependency, dependent=member.name)
                    )
                elif dependency.startswith("flowpilot-"):
                    raise EngineeringControlError(
                        ErrorCode.MISSING_WORKSPACE_DEPENDENCY,
                        metadata={"package": member.name},
                    )
        return tuple(sorted(edges, key=lambda edge: (edge.dependency, edge.dependent)))

    @staticmethod
    def _test_mappings(
        members: tuple[WorkspaceMember, ...],
    ) -> tuple[TestMapping, ...]:
        mappings: list[TestMapping] = []
        for member in members:
            if member.path == "packages/engineering-control":
                prefixes = ("tests/core/engineering_control",)
            elif member.path in {
                "apps/api",
                "packages/application",
                "packages/domain",
            }:
                prefixes = ("tests/core",)
            elif member.path.startswith(
                (
                    "apps/worker",
                    "packages/agent-runtime",
                    "packages/context",
                    "packages/graph",
                    "packages/model-gateway",
                )
            ):
                prefixes = ("tests/runtime",)
            elif member.path.startswith(
                (
                    "apps/mcp-gateway",
                    "mcp-servers/",
                    "packages/policy",
                    "packages/security",
                    "packages/tool-contracts",
                )
            ):
                prefixes = ("tests/platform",)
            elif member.path == "packages/persistence":
                prefixes = ("tests/data",)
            else:
                prefixes = ("tests/integration",)
            mappings.append(TestMapping(package=member.name, test_prefixes=prefixes))
        return tuple(sorted(mappings, key=lambda item: item.package))

    @staticmethod
    def _tree_signatures(files: tuple[FileRecord, ...]) -> tuple[tuple[str, str], ...]:
        selectors: dict[str, tuple[str, ...]] = {
            "contract": ("contract",),
            "environment": ("environment",),
            "lock": ("lock",),
            "migration": ("migration",),
            "product": ("product",),
            "security": ("security",),
        }
        signatures: list[tuple[str, str]] = []
        for name, tags in sorted(selectors.items()):
            entries: list[JsonValue] = [
                {"path": record.path, "sha256": record.sha256}
                for record in files
                if any(tag in record.protected_tags for tag in tags)
            ]
            signatures.append((name, sha256_bytes(canonical_json_bytes(entries))))
        return tuple(signatures)


def _normalize_project_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _dependency_project_name(specifier: str) -> str:
    match = _DEPENDENCY_NAME.match(specifier)
    if match is None:
        raise EngineeringControlError(ErrorCode.INVALID_WORKSPACE_METADATA)
    return _normalize_project_name(match.group(1))
