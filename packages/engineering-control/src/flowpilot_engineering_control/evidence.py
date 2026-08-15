"""Integrity-bound, policy-aware local evidence cache."""

from __future__ import annotations

import json
import os
import platform
import re
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from flowpilot_engineering_control.errors import EngineeringControlError, ErrorCode
from flowpilot_engineering_control.git import GitClient
from flowpilot_engineering_control.paths import normalize_repo_path, path_is_within
from flowpilot_engineering_control.repository import RepositoryMap
from flowpilot_engineering_control.selection import CommandSpec
from flowpilot_engineering_control.serialization import (
    JsonValue,
    canonical_json_bytes,
    sha256_bytes,
)

SCHEMA_VERSION = "flowpilot.evidence-cache-record.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class EvidenceKind(StrEnum):
    LOCAL_TEST = "local_test"
    LOCAL_BUILD = "local_build"
    ONLINE_PROVIDER = "online_provider"
    SECRET_SCAN = "secret_scan"
    VULNERABILITY_QUERY = "vulnerability_query"
    REAL_MIGRATION = "real_migration"
    DESTRUCTIVE_RECOVERY = "destructive_recovery"
    SECURITY_REEXECUTE = "security_reexecute"


class CacheMissReason(StrEnum):
    NOT_FOUND = "not_found"
    POLICY_DENIED = "policy_denied"
    RECORD_INTEGRITY = "record_integrity_mismatch"
    EVIDENCE_INTEGRITY = "evidence_integrity_mismatch"
    COMMAND_DRIFT = "command_drift"
    PRODUCT_TREE_DRIFT = "product_tree_drift"
    CONTRACT_TREE_DRIFT = "contract_tree_drift"
    CONTRACT_DIGEST_DRIFT = "contract_digest_drift"
    MIGRATION_TREE_DRIFT = "migration_tree_drift"
    LOCK_DRIFT = "lock_drift"
    ENVIRONMENT_DRIFT = "environment_drift"
    TOOLCHAIN_DRIFT = "toolchain_drift"
    UNTRACEABLE_HEAD = "untraceable_head"


@dataclass(frozen=True, slots=True)
class EnvironmentFingerprint:
    os_name: str
    architecture: str
    python_implementation: str
    python_version: str

    @classmethod
    def current(cls) -> EnvironmentFingerprint:
        return cls(
            os_name=platform.system().lower(),
            architecture=platform.machine().lower(),
            python_implementation=platform.python_implementation().lower(),
            python_version=platform.python_version(),
        )

    @property
    def digest(self) -> str:
        return sha256_bytes(canonical_json_bytes(self.to_record()))

    def to_record(self) -> dict[str, JsonValue]:
        return {
            "architecture": self.architecture,
            "os_name": self.os_name,
            "python_implementation": self.python_implementation,
            "python_version": self.python_version,
        }


@dataclass(frozen=True, slots=True)
class CachePolicy:
    evidence_kind: EvidenceKind
    force_rerun: bool = False

    @property
    def reusable(self) -> bool:
        denied = {
            EvidenceKind.ONLINE_PROVIDER,
            EvidenceKind.SECRET_SCAN,
            EvidenceKind.VULNERABILITY_QUERY,
            EvidenceKind.REAL_MIGRATION,
            EvidenceKind.DESTRUCTIVE_RECOVERY,
            EvidenceKind.SECURITY_REEXECUTE,
        }
        return not self.force_rerun and self.evidence_kind not in denied


@dataclass(frozen=True, slots=True)
class EvidenceCacheKey:
    command_id: str
    key_sha256: str
    component_hashes: tuple[tuple[str, str], ...]

    def to_record(self) -> dict[str, JsonValue]:
        return {
            "command_id": self.command_id,
            "component_hashes": dict(self.component_hashes),
            "key_sha256": self.key_sha256,
        }


@dataclass(frozen=True, slots=True)
class CacheKeyInput:
    command: CommandSpec
    product_tree: str
    contract_tree: str
    contract_digest: str
    migration_tree: str
    lock_hash: str
    environment: EnvironmentFingerprint
    toolchain: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        hashes = (
            self.product_tree,
            self.contract_tree,
            self.migration_tree,
            self.lock_hash,
        )
        tool_names = [name for name, _ in self.toolchain]
        if (
            not all(_SHA256.fullmatch(value) for value in hashes)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", self.contract_digest)
            or not self.toolchain
            or len(set(tool_names)) != len(tool_names)
            or any(
                not name or not version or "\x00" in name or "\x00" in version
                for name, version in self.toolchain
            )
        ):
            raise EngineeringControlError(ErrorCode.EVIDENCE_INVALID)

    @classmethod
    def from_repository_map(
        cls,
        *,
        command: CommandSpec,
        repository_map: RepositoryMap,
        contract_digest: str,
        environment: EnvironmentFingerprint,
        toolchain: tuple[tuple[str, str], ...],
    ) -> CacheKeyInput:
        trees = dict(repository_map.tree_signatures)
        return cls(
            command=command,
            product_tree=trees["product"],
            contract_tree=trees["contract"],
            contract_digest=contract_digest,
            migration_tree=trees["migration"],
            lock_hash=trees["lock"],
            environment=environment,
            toolchain=tuple(sorted(toolchain)),
        )

    def build(self) -> EvidenceCacheKey:
        toolchain_digest = sha256_bytes(
            canonical_json_bytes(dict(sorted(self.toolchain)))
        )
        components = {
            "argv": self.command.argv_sha256,
            "contract_digest": sha256_bytes(self.contract_digest.encode("utf-8")),
            "contract_tree": self.contract_tree,
            "environment": self.environment.digest,
            "lock": self.lock_hash,
            "migration_tree": self.migration_tree,
            "product_tree": self.product_tree,
            "toolchain": toolchain_digest,
        }
        material = {
            "argv": list(self.command.argv),
            "command_id": self.command.command_id,
            "component_hashes": components,
        }
        return EvidenceCacheKey(
            command_id=self.command.command_id,
            key_sha256=sha256_bytes(canonical_json_bytes(material)),
            component_hashes=tuple(sorted(components.items())),
        )


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    cache_key: EvidenceCacheKey
    producer_head: str
    evidence_kind: EvidenceKind
    evidence_path: str
    evidence_sha256: str
    evidence_bytes: int

    def payload(self) -> dict[str, JsonValue]:
        return {
            "cache_key": self.cache_key.to_record(),
            "evidence_bytes": self.evidence_bytes,
            "evidence_kind": self.evidence_kind.value,
            "evidence_path": self.evidence_path,
            "evidence_sha256": self.evidence_sha256,
            "exit_code": 0,
            "producer_head": self.producer_head,
            "reusable": True,
            "schema_version": SCHEMA_VERSION,
        }

    @property
    def digest(self) -> str:
        return sha256_bytes(canonical_json_bytes(self.payload()))

    def to_record(self) -> dict[str, JsonValue]:
        return {**self.payload(), "record_sha256": self.digest}

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_record())


@dataclass(frozen=True, slots=True)
class CacheDecision:
    hit: bool
    reasons: tuple[CacheMissReason, ...]
    record_sha256: str | None = None

    def to_record(self) -> dict[str, JsonValue]:
        return {
            "hit": self.hit,
            "reasons": [reason.value for reason in self.reasons],
            "record_sha256": self.record_sha256,
        }


class EvidenceCache:
    def __init__(self, root: Path, *, git: GitClient | None = None) -> None:
        self._root = root.resolve()
        self._git = git or GitClient(self._root)

    def record(
        self,
        *,
        key: EvidenceCacheKey,
        producer_head: str,
        evidence_path: str,
        exit_code: int,
        policy: CachePolicy,
    ) -> str:
        if exit_code != 0:
            raise EngineeringControlError(ErrorCode.CACHE_FAILED_RESULT)
        if not policy.reusable:
            raise EngineeringControlError(
                ErrorCode.CACHE_POLICY_DENIED,
                metadata={"evidence_kind": policy.evidence_kind.value},
            )
        if not _COMMIT.fullmatch(producer_head):
            raise EngineeringControlError(ErrorCode.CACHE_UNTRACEABLE_HEAD)
        resolved_head = self._git.resolve_commit(producer_head)
        relative_evidence = normalize_repo_path(evidence_path)
        evidence = self._read_relative(relative_evidence)
        record = EvidenceRecord(
            cache_key=key,
            producer_head=resolved_head,
            evidence_kind=policy.evidence_kind,
            evidence_path=relative_evidence,
            evidence_sha256=sha256_bytes(evidence),
            evidence_bytes=len(evidence),
        )
        record_path = (
            f".flowpilot-engineering/cache/{key.command_id}-{key.key_sha256}.json"
        )
        destination = self._root.joinpath(*record_path.split("/"))
        self._atomic_create_or_match(destination, record.to_bytes())
        return record_path

    def check(
        self,
        *,
        record_path: str,
        expected_key: EvidenceCacheKey,
        current_head: str,
        policy: CachePolicy,
    ) -> CacheDecision:
        if not policy.reusable:
            return CacheDecision(False, (CacheMissReason.POLICY_DENIED,))
        try:
            normalized_record = normalize_repo_path(record_path)
            if not path_is_within(normalized_record, ".flowpilot-engineering/cache"):
                return CacheDecision(False, (CacheMissReason.RECORD_INTEGRITY,))
            raw_record = self._read_relative(normalized_record)
        except EngineeringControlError:
            return CacheDecision(False, (CacheMissReason.NOT_FOUND,))
        parsed = self._parse_record(raw_record)
        if parsed is None:
            return CacheDecision(False, (CacheMissReason.RECORD_INTEGRITY,))
        record, record_digest = parsed
        reasons = self._key_drift(record, expected_key)
        if (
            record.get("schema_version") != SCHEMA_VERSION
            or record.get("exit_code") != 0
            or record.get("reusable") is not True
        ):
            reasons.add(CacheMissReason.RECORD_INTEGRITY)
        if record.get("evidence_kind") != policy.evidence_kind.value:
            reasons.add(CacheMissReason.POLICY_DENIED)
        evidence_path = record.get("evidence_path")
        evidence_digest = record.get("evidence_sha256")
        evidence_bytes = record.get("evidence_bytes")
        if (
            not isinstance(evidence_path, str)
            or not isinstance(evidence_digest, str)
            or not isinstance(evidence_bytes, int)
        ):
            reasons.add(CacheMissReason.RECORD_INTEGRITY)
        else:
            try:
                evidence = self._read_relative(normalize_repo_path(evidence_path))
            except EngineeringControlError:
                reasons.add(CacheMissReason.EVIDENCE_INTEGRITY)
            else:
                if (
                    sha256_bytes(evidence) != evidence_digest
                    or len(evidence) != evidence_bytes
                ):
                    reasons.add(CacheMissReason.EVIDENCE_INTEGRITY)
        producer_head = record.get("producer_head")
        if not isinstance(producer_head, str) or not _COMMIT.fullmatch(producer_head):
            reasons.add(CacheMissReason.UNTRACEABLE_HEAD)
        else:
            try:
                self._git.require_ancestor(producer_head, current_head)
            except EngineeringControlError:
                reasons.add(CacheMissReason.UNTRACEABLE_HEAD)
        if reasons:
            return CacheDecision(
                False,
                tuple(sorted(reasons, key=lambda reason: reason.value)),
                record_digest,
            )
        return CacheDecision(True, (), record_digest)

    def _read_relative(self, relative_path: str) -> bytes:
        candidate = self._root.joinpath(*relative_path.split("/"))
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(self._root)
            return resolved.read_bytes()
        except (OSError, ValueError) as exc:
            raise EngineeringControlError(ErrorCode.EVIDENCE_INVALID) from exc

    @staticmethod
    def _parse_record(
        raw_record: bytes,
    ) -> tuple[dict[str, object], str] | None:
        try:
            decoded = json.loads(raw_record)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(decoded, dict):
            return None
        claimed_digest = decoded.get("record_sha256")
        if not isinstance(claimed_digest, str) or not _SHA256.fullmatch(claimed_digest):
            return None
        payload = {
            key: value for key, value in decoded.items() if key != "record_sha256"
        }
        if sha256_bytes(canonical_json_bytes(payload)) != claimed_digest:
            return None
        if canonical_json_bytes(decoded) != raw_record:
            return None
        return decoded, claimed_digest

    @staticmethod
    def _key_drift(
        record: dict[str, object],
        expected: EvidenceCacheKey,
    ) -> set[CacheMissReason]:
        cache_key = record.get("cache_key")
        if not isinstance(cache_key, dict):
            return {CacheMissReason.RECORD_INTEGRITY}
        stored_components = cache_key.get("component_hashes")
        stored_command = cache_key.get("command_id")
        stored_key_digest = cache_key.get("key_sha256")
        if not isinstance(stored_components, dict) or not isinstance(
            stored_command, str
        ):
            return {CacheMissReason.RECORD_INTEGRITY}
        expected_components = dict(expected.component_hashes)
        component_reasons = {
            "argv": CacheMissReason.COMMAND_DRIFT,
            "contract_digest": CacheMissReason.CONTRACT_DIGEST_DRIFT,
            "contract_tree": CacheMissReason.CONTRACT_TREE_DRIFT,
            "environment": CacheMissReason.ENVIRONMENT_DRIFT,
            "lock": CacheMissReason.LOCK_DRIFT,
            "migration_tree": CacheMissReason.MIGRATION_TREE_DRIFT,
            "product_tree": CacheMissReason.PRODUCT_TREE_DRIFT,
            "toolchain": CacheMissReason.TOOLCHAIN_DRIFT,
        }
        reasons: set[CacheMissReason] = set()
        if stored_command != expected.command_id:
            reasons.add(CacheMissReason.COMMAND_DRIFT)
        for component, reason in component_reasons.items():
            if stored_components.get(component) != expected_components.get(component):
                reasons.add(reason)
        if stored_key_digest != expected.key_sha256 and not reasons:
            reasons.add(CacheMissReason.RECORD_INTEGRITY)
        return reasons

    @staticmethod
    def _atomic_create_or_match(destination: Path, content: bytes) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.read_bytes() == content:
                return
            raise EngineeringControlError(ErrorCode.CACHE_KEY_CONFLICT)
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                delete=False,
            ) as handle:
                temporary_path = handle.name
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary_path, destination)
            except FileExistsError:
                if destination.read_bytes() != content:
                    raise EngineeringControlError(
                        ErrorCode.CACHE_KEY_CONFLICT
                    ) from None
            except OSError as exc:
                raise EngineeringControlError(ErrorCode.CACHE_KEY_CONFLICT) from exc
        finally:
            if temporary_path is not None:
                with suppress(FileNotFoundError):
                    os.unlink(temporary_path)
