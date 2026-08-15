"""Delta Context Capsule construction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from fnmatch import fnmatchcase
from pathlib import Path

from flowpilot_engineering_control.errors import EngineeringControlError, ErrorCode
from flowpilot_engineering_control.git import GitChange, GitClient
from flowpilot_engineering_control.owners import OwnerResolver
from flowpilot_engineering_control.paths import (
    is_excluded_path,
    normalize_repo_path,
    path_is_within,
)
from flowpilot_engineering_control.repository import FileRecord, RepositoryMap
from flowpilot_engineering_control.serialization import (
    JsonValue,
    canonical_json_bytes,
    sha256_bytes,
)

SCHEMA_VERSION = "flowpilot.context-capsule.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ExpansionReason(StrEnum):
    UNRESOLVED_DEPENDENCY = "unresolved_dependency"
    PUBLIC_SIGNATURE_CHANGE = "public_signature_change"
    TEST_FAILURE = "test_failure"
    SECURITY_BOUNDARY_CHANGE = "security_boundary_change"
    REVIEWER_REQUEST = "reviewer_request"


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    reference_id: str
    path: str
    sha256: str

    def __post_init__(self) -> None:
        normalized = normalize_repo_path(self.path)
        if normalized != self.path or not _SHA256.fullmatch(self.sha256):
            raise EngineeringControlError(ErrorCode.INVALID_PATH)

    def to_record(self) -> dict[str, JsonValue]:
        return {
            "id": self.reference_id,
            "path": self.path,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class ScopeExpansion:
    reason: ExpansionReason
    paths: tuple[str, ...]
    authority: str

    def to_record(self) -> dict[str, JsonValue]:
        return {
            "authority": self.authority,
            "paths": list(self.paths),
            "reason_code": self.reason.value,
        }


@dataclass(frozen=True, slots=True)
class CapsuleRequest:
    base: str
    target: str
    owner: str
    work_package: str
    attempt_id: str
    risk_class: str
    contract_digest: str
    write_scope: tuple[str, ...]
    required_refs: tuple[EvidenceReference, ...] = ()
    known_fact_refs: tuple[EvidenceReference, ...] = ()
    do_not_recheck_refs: tuple[EvidenceReference, ...] = ()
    expansions: tuple[ScopeExpansion, ...] = ()


@dataclass(frozen=True, slots=True)
class ChangeRecord:
    status: str
    path: str
    owner: str
    package: str | None
    sha256: str | None
    old_path: str | None = None
    old_owner: str | None = None
    old_package: str | None = None

    def to_record(self) -> dict[str, JsonValue]:
        return {
            "old_owner": self.old_owner,
            "old_package": self.old_package,
            "old_path": self.old_path,
            "owner": self.owner,
            "package": self.package,
            "path": self.path,
            "sha256": self.sha256,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class ContextCapsule:
    authority: dict[str, JsonValue]
    base: str
    target: str
    map_sha256: str
    changes: tuple[ChangeRecord, ...]
    affected_packages: tuple[str, ...]
    direct_dependencies: tuple[str, ...]
    direct_dependents: tuple[str, ...]
    public_signature_changes: tuple[tuple[str, str | None], ...]
    required_read_set: tuple[str, ...]
    allowed_initial_read_set: tuple[str, ...]
    protected_change_tags: tuple[str, ...]
    known_fact_refs: tuple[EvidenceReference, ...]
    do_not_recheck_refs: tuple[EvidenceReference, ...]
    expansions: tuple[ScopeExpansion, ...]
    counts: dict[str, int]

    def payload(self) -> dict[str, JsonValue]:
        return {
            "affected_packages": list(self.affected_packages),
            "allowed_initial_read_set": list(self.allowed_initial_read_set),
            "authority": self.authority,
            "base": self.base,
            "changes": [change.to_record() for change in self.changes],
            "counts": self.counts,
            "direct_dependencies": list(self.direct_dependencies),
            "direct_dependents": list(self.direct_dependents),
            "do_not_recheck_refs": [
                reference.to_record() for reference in self.do_not_recheck_refs
            ],
            "known_fact_refs": [
                reference.to_record() for reference in self.known_fact_refs
            ],
            "map_sha256": self.map_sha256,
            "protected_change_tags": list(self.protected_change_tags),
            "public_signature_changes": [
                {"path": path, "sha256": digest}
                for path, digest in self.public_signature_changes
            ],
            "required_read_set": list(self.required_read_set),
            "schema_version": SCHEMA_VERSION,
            "scope_expansions": [
                expansion.to_record() for expansion in self.expansions
            ],
            "target": self.target,
        }

    @property
    def digest(self) -> str:
        return sha256_bytes(canonical_json_bytes(self.payload()))

    def to_record(self) -> dict[str, JsonValue]:
        return {**self.payload(), "capsule_sha256": self.digest}

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_record())


class CapsuleBuilder:
    def __init__(
        self,
        root: Path,
        repository_map: RepositoryMap,
        *,
        git: GitClient | None = None,
    ) -> None:
        self._root = root.resolve()
        self._map = repository_map
        self._git = git or GitClient(self._root)
        self._owners = OwnerResolver(repository_map.owner_rules)

    def build(self, request: CapsuleRequest) -> ContextCapsule:
        self._git.require_clean()
        head = self._git.head()
        target = self._git.resolve_commit(request.target)
        if target != head or target != self._map.git_head:
            raise EngineeringControlError(
                ErrorCode.TARGET_NOT_HEAD,
                metadata={"target": target},
            )
        base = self._git.resolve_commit(request.base)
        raw_changes = tuple(
            change
            for change in self._git.changes(base, target)
            if not self._change_is_excluded(change)
        )
        file_index = self._map.file_by_path()
        member_paths = tuple(member.path for member in self._map.workspace_members)
        changes = tuple(
            self._change_record(change, file_index, member_paths)
            for change in raw_changes
        )
        self._validate_change_scope(changes, request)
        affected_packages = tuple(
            sorted(
                {
                    package
                    for change in changes
                    for package in (change.package, change.old_package)
                    if package is not None
                }
            )
        )
        dependencies, dependents = self._direct_relations(affected_packages)
        required = self._required_read_set(
            changes=changes,
            affected_packages=affected_packages,
            dependencies=dependencies,
            dependents=dependents,
            required_refs=request.required_refs,
        )
        expansions = self._normalize_expansions(request.expansions, file_index)
        allowed = tuple(
            sorted(
                set(required).union(
                    path for expansion in expansions for path in expansion.paths
                )
            )
        )
        protected_tags = tuple(
            sorted(
                {
                    tag
                    for change in changes
                    for tag in self._tags_for_change(change, file_index)
                }
            )
        )
        public_changes = tuple(
            sorted(
                (
                    change.path,
                    change.sha256,
                )
                for change in changes
                if self._is_public_change(change, file_index)
            )
        )
        total_bytes = sum(record.byte_count for record in self._map.files)
        selected_bytes = sum(file_index[path].byte_count for path in allowed)
        ratio_basis_points = (
            (selected_bytes * 10_000) // total_bytes if total_bytes else 0
        )
        authority: dict[str, JsonValue] = {
            "attempt_id": request.attempt_id,
            "contract_digest": request.contract_digest,
            "owner": request.owner,
            "risk_class": request.risk_class,
            "work_package": request.work_package,
            "write_scope": sorted(
                normalize_repo_path(path) for path in request.write_scope
            ),
        }
        return ContextCapsule(
            authority=authority,
            base=base,
            target=target,
            map_sha256=self._map.digest,
            changes=changes,
            affected_packages=affected_packages,
            direct_dependencies=dependencies,
            direct_dependents=dependents,
            public_signature_changes=public_changes,
            required_read_set=required,
            allowed_initial_read_set=allowed,
            protected_change_tags=protected_tags,
            known_fact_refs=tuple(
                sorted(request.known_fact_refs, key=lambda ref: ref.path)
            ),
            do_not_recheck_refs=tuple(
                sorted(request.do_not_recheck_refs, key=lambda ref: ref.path)
            ),
            expansions=expansions,
            counts={
                "changed_paths": len(changes),
                "full_repository_bytes": total_bytes,
                "full_repository_files": len(self._map.files),
                "initial_read_bytes": selected_bytes,
                "initial_read_files": len(allowed),
                "initial_read_ratio_basis_points": ratio_basis_points,
                "scope_expansions": len(expansions),
            },
        )

    @staticmethod
    def _change_is_excluded(change: GitChange) -> bool:
        paths = [change.path]
        if change.old_path is not None:
            paths.append(change.old_path)
        return all(is_excluded_path(path) for path in paths)

    def _change_record(
        self,
        change: GitChange,
        file_index: dict[str, FileRecord],
        member_paths: tuple[str, ...],
    ) -> ChangeRecord:
        assignment = self._owners.resolve(change.path)
        current = file_index.get(change.path)
        if change.status != "D" and current is None:
            raise EngineeringControlError(
                ErrorCode.UNKNOWN_PATH,
                metadata={"path": change.path},
            )
        old_owner: str | None = None
        old_package: str | None = None
        if change.old_path is not None:
            old_owner = self._owners.resolve(change.old_path).owner
            old_package = self._package_for_path(change.old_path, member_paths)
        package = (
            current.package
            if current is not None
            else self._package_for_path(change.path, member_paths)
        )
        return ChangeRecord(
            status=change.status,
            path=change.path,
            owner=assignment.owner,
            package=package,
            sha256=current.sha256 if current is not None else None,
            old_path=change.old_path,
            old_owner=old_owner,
            old_package=old_package,
        )

    @staticmethod
    def _package_for_path(path: str, member_paths: tuple[str, ...]) -> str | None:
        matches = [
            member
            for member in member_paths
            if path == member or path.startswith(f"{member}/")
        ]
        return max(matches, key=len) if matches else None

    @staticmethod
    def _validate_change_scope(
        changes: tuple[ChangeRecord, ...],
        request: CapsuleRequest,
    ) -> None:
        scopes = tuple(normalize_repo_path(scope) for scope in request.write_scope)
        expansion_paths = {
            normalize_repo_path(path)
            for expansion in request.expansions
            for path in expansion.paths
        }
        for change in changes:
            paths = [(change.path, change.owner)]
            if change.old_path is not None and change.old_owner is not None:
                paths.append((change.old_path, change.old_owner))
            for path, owner in paths:
                in_scope = any(
                    fnmatchcase(path, scope)
                    or (
                        not any(marker in scope for marker in "*?[")
                        and path_is_within(path, scope)
                    )
                    for scope in scopes
                )
                if owner == request.owner and in_scope:
                    continue
                if path in expansion_paths:
                    continue
                raise EngineeringControlError(
                    ErrorCode.SCOPE_VIOLATION,
                    metadata={"path": path},
                )

    def _direct_relations(
        self,
        affected_paths: tuple[str, ...],
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        members_by_path = self._map.member_by_path()
        names = {members_by_path[path].name for path in affected_paths}
        dependencies = {
            edge.dependency
            for edge in self._map.dependency_edges
            if edge.dependent in names
        }
        dependents = {
            edge.dependent
            for edge in self._map.dependency_edges
            if edge.dependency in names
        }
        return tuple(sorted(dependencies)), tuple(sorted(dependents))

    def _required_read_set(
        self,
        *,
        changes: tuple[ChangeRecord, ...],
        affected_packages: tuple[str, ...],
        dependencies: tuple[str, ...],
        dependents: tuple[str, ...],
        required_refs: tuple[EvidenceReference, ...],
    ) -> tuple[str, ...]:
        file_index = self._map.file_by_path()
        members_by_name = self._map.member_by_name()
        required: set[str] = {
            change.path
            for change in changes
            if change.status != "D" and change.path in file_index
        }
        for package_path in affected_packages:
            metadata = f"{package_path}/pyproject.toml"
            if metadata in file_index:
                required.add(metadata)
        dependency_paths = {
            members_by_name[name].path
            for name in dependencies
            if name in members_by_name
        }
        for record in self._map.files:
            if record.package in dependency_paths and record.public_signature:
                required.add(record.path)
        mapping_by_name = {
            mapping.package: mapping for mapping in self._map.test_mappings
        }
        for dependent in dependents:
            mapping = mapping_by_name.get(dependent)
            if mapping is None:
                raise EngineeringControlError(
                    ErrorCode.MISSING_WORKSPACE_DEPENDENCY,
                    metadata={"package": dependent},
                )
            for record in self._map.files:
                if record.kind == "test" and any(
                    path_is_within(record.path, prefix)
                    for prefix in mapping.test_prefixes
                ):
                    required.add(record.path)
        for reference in required_refs:
            referenced_record = file_index.get(reference.path)
            if (
                referenced_record is None
                or referenced_record.sha256 != reference.sha256
            ):
                raise EngineeringControlError(
                    ErrorCode.SCOPE_VIOLATION,
                    metadata={"path": reference.path},
                )
            required.add(reference.path)
        if not required:
            # A no-op Base/Target still needs the authorization metadata source.
            for fallback in ("AGENTS.md", "pyproject.toml"):
                if fallback in file_index:
                    required.add(fallback)
                    break
        return tuple(sorted(required))

    def _normalize_expansions(
        self,
        expansions: tuple[ScopeExpansion, ...],
        file_index: dict[str, FileRecord],
    ) -> tuple[ScopeExpansion, ...]:
        normalized: list[ScopeExpansion] = []
        seen: set[tuple[str, str, tuple[str, ...]]] = set()
        for expansion in expansions:
            paths = tuple(
                sorted({normalize_repo_path(path) for path in expansion.paths})
            )
            if not paths or any(path not in file_index for path in paths):
                raise EngineeringControlError(ErrorCode.SCOPE_VIOLATION)
            for path in paths:
                self._owners.resolve(path)
            key = (expansion.reason.value, expansion.authority, paths)
            if key in seen:
                continue
            seen.add(key)
            normalized.append(
                ScopeExpansion(
                    reason=expansion.reason,
                    paths=paths,
                    authority=expansion.authority,
                )
            )
        return tuple(
            sorted(
                normalized,
                key=lambda item: (item.reason.value, item.authority, item.paths),
            )
        )

    @staticmethod
    def _tags_for_change(
        change: ChangeRecord,
        file_index: dict[str, FileRecord],
    ) -> tuple[str, ...]:
        record = file_index.get(change.path)
        return record.protected_tags if record is not None else ()

    @staticmethod
    def _is_public_change(
        change: ChangeRecord,
        file_index: dict[str, FileRecord],
    ) -> bool:
        record = file_index.get(change.path)
        if record is not None and record.public_signature:
            return True
        names = [change.path]
        if change.old_path is not None:
            names.append(change.old_path)
        return any(
            path.rsplit("/", 1)[-1]
            in {"__init__.py", "ports.py", "interfaces.py", "protocols.py", "py.typed"}
            or "/ports/" in path
            or path.endswith("_ports.py")
            for path in names
        )
