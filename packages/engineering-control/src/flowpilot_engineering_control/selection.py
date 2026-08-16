"""Fail-closed deterministic test selection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum, StrEnum

from flowpilot_engineering_control.capsule import ContextCapsule
from flowpilot_engineering_control.errors import EngineeringControlError, ErrorCode
from flowpilot_engineering_control.repository import RepositoryMap
from flowpilot_engineering_control.serialization import (
    JsonValue,
    canonical_json_bytes,
    sha256_bytes,
)

SCHEMA_VERSION = "flowpilot.test-plan.v1"
_COMMAND_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_PYTEST_ARGV_PREFIX = (
    "uv",
    "run",
    "--all-packages",
    "--all-groups",
    "--locked",
    "python",
    "-B",
    "-m",
    "pytest",
    "-q",
)


class TestTier(IntEnum):
    TARGETED = 1
    SHARED = 2
    FULL = 3
    RELEASE = 4

    @property
    def label(self) -> str:
        return self.name


class SelectionSignal(StrEnum):
    PACKAGE_CHANGE = "package_change"
    PUBLIC_SIGNATURE_CHANGE = "public_signature_change"
    CONTRACT_CHANGE = "contract_change"
    MIGRATION_CHANGE = "migration_change"
    LOCK_CHANGE = "lock_change"
    SECURITY_CHANGE = "security_change"
    UNKNOWN_PATH = "unknown_path"
    NON_LINEAR_BASE = "non_linear_base"
    DEPENDENCY_GRAPH_INCOMPLETE = "dependency_graph_incomplete"
    NO_TEST_MAPPING = "no_test_mapping"
    NO_CHANGE_PROOF = "no_change_proof"


@dataclass(frozen=True, slots=True)
class CommandSpec:
    command_id: str
    argv: tuple[str, ...]

    def __post_init__(self) -> None:
        if not _COMMAND_ID.fullmatch(self.command_id):
            raise EngineeringControlError(ErrorCode.ARGV_INVALID)
        if not self.argv or not self.argv[0].strip():
            raise EngineeringControlError(ErrorCode.ARGV_INVALID)
        if any(not isinstance(arg, str) or "\x00" in arg for arg in self.argv):
            raise EngineeringControlError(ErrorCode.ARGV_INVALID)

    @property
    def argv_sha256(self) -> str:
        return sha256_bytes(canonical_json_bytes(list(self.argv)))

    def to_record(self) -> dict[str, JsonValue]:
        return {
            "argv": list(self.argv),
            "argv_sha256": self.argv_sha256,
            "command_id": self.command_id,
        }


@dataclass(frozen=True, slots=True)
class SelectionRequest:
    capsule: ContextCapsule | None
    fallback_signals: tuple[SelectionSignal, ...] = ()


@dataclass(frozen=True, slots=True)
class TestPlan:
    tier: TestTier
    commands: tuple[CommandSpec, ...]
    reasons: tuple[SelectionSignal, ...]
    selected_test_prefixes: tuple[str, ...]
    selection_complete: bool
    fallback_required: bool
    tree_signatures: tuple[tuple[str, str], ...]

    def payload(self) -> dict[str, JsonValue]:
        return {
            "commands": [command.to_record() for command in self.commands],
            "fallback_required": self.fallback_required,
            "reasons": [reason.value for reason in self.reasons],
            "schema_version": SCHEMA_VERSION,
            "selected_test_prefixes": list(self.selected_test_prefixes),
            "selection_complete": self.selection_complete,
            "tier": self.tier.label,
            "tree_signatures": dict(self.tree_signatures),
        }

    @property
    def digest(self) -> str:
        return sha256_bytes(canonical_json_bytes(self.payload()))

    def to_record(self) -> dict[str, JsonValue]:
        return {**self.payload(), "plan_sha256": self.digest}

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_record())


class TestSelector:
    def __init__(self, repository_map: RepositoryMap) -> None:
        self._map = repository_map

    def select(self, request: SelectionRequest) -> TestPlan:
        reasons = set(request.fallback_signals)
        capsule = request.capsule
        tier = TestTier.TARGETED
        selection_complete = True
        selected_prefixes: set[str] = set()

        if capsule is None:
            if not reasons:
                raise EngineeringControlError(ErrorCode.SELECTION_INCOMPLETE)
            tier = self._fallback_tier(reasons)
            selection_complete = False
        else:
            reasons.update(self._capsule_signals(capsule))
            if not capsule.changes:
                reasons.add(SelectionSignal.NO_CHANGE_PROOF)
                tier = TestTier.FULL
                selection_complete = False
            else:
                tier = self._fallback_tier(reasons)
                if tier <= TestTier.SHARED:
                    selected_prefixes, mapped = self._targeted_prefixes(capsule)
                    if not mapped or not selected_prefixes:
                        reasons.add(SelectionSignal.NO_TEST_MAPPING)
                        tier = TestTier.FULL
                        selection_complete = False

        commands = self._commands(tier, selected_prefixes, reasons)
        if not commands:
            raise EngineeringControlError(ErrorCode.TEST_PLAN_EMPTY)
        return TestPlan(
            tier=tier,
            commands=commands,
            reasons=tuple(sorted(reasons, key=lambda reason: reason.value)),
            selected_test_prefixes=tuple(sorted(selected_prefixes)),
            selection_complete=selection_complete,
            fallback_required=not selection_complete or tier >= TestTier.FULL,
            tree_signatures=self._map.tree_signatures,
        )

    @staticmethod
    def _capsule_signals(capsule: ContextCapsule) -> set[SelectionSignal]:
        signals: set[SelectionSignal] = set()
        if capsule.affected_packages:
            signals.add(SelectionSignal.PACKAGE_CHANGE)
        if capsule.public_signature_changes:
            signals.add(SelectionSignal.PUBLIC_SIGNATURE_CHANGE)
        tags = set(capsule.protected_change_tags)
        for tag, signal in {
            "contract": SelectionSignal.CONTRACT_CHANGE,
            "lock": SelectionSignal.LOCK_CHANGE,
            "migration": SelectionSignal.MIGRATION_CHANGE,
            "security": SelectionSignal.SECURITY_CHANGE,
        }.items():
            if tag in tags:
                signals.add(signal)
        return signals

    @staticmethod
    def _fallback_tier(reasons: set[SelectionSignal]) -> TestTier:
        release = {
            SelectionSignal.MIGRATION_CHANGE,
            SelectionSignal.SECURITY_CHANGE,
            SelectionSignal.NON_LINEAR_BASE,
        }
        full = {
            SelectionSignal.CONTRACT_CHANGE,
            SelectionSignal.LOCK_CHANGE,
            SelectionSignal.UNKNOWN_PATH,
            SelectionSignal.DEPENDENCY_GRAPH_INCOMPLETE,
            SelectionSignal.NO_TEST_MAPPING,
            SelectionSignal.NO_CHANGE_PROOF,
        }
        if reasons.intersection(release):
            return TestTier.RELEASE
        if reasons.intersection(full):
            return TestTier.FULL
        if SelectionSignal.PUBLIC_SIGNATURE_CHANGE in reasons:
            return TestTier.SHARED
        return TestTier.TARGETED

    def _targeted_prefixes(
        self,
        capsule: ContextCapsule,
    ) -> tuple[set[str], bool]:
        members_by_path = self._map.member_by_path()
        mapping_by_name = {
            mapping.package: mapping for mapping in self._map.test_mappings
        }
        package_names = {
            members_by_path[path].name
            for path in capsule.affected_packages
            if path in members_by_path
        }
        package_names.update(capsule.direct_dependents)
        pending = list(package_names)
        while pending:
            dependency = pending.pop()
            for edge in self._map.dependency_edges:
                if (
                    edge.dependency == dependency
                    and edge.dependent not in package_names
                ):
                    package_names.add(edge.dependent)
                    pending.append(edge.dependent)
        prefixes: set[str] = set()
        mapped = True
        for package_name in package_names:
            mapping = mapping_by_name.get(package_name)
            if mapping is None:
                mapped = False
                continue
            prefixes.update(mapping.test_prefixes)
        return prefixes, mapped

    @staticmethod
    def _commands(
        tier: TestTier,
        selected_prefixes: set[str],
        reasons: set[SelectionSignal],
    ) -> tuple[CommandSpec, ...]:
        if tier is TestTier.TARGETED:
            return tuple(
                CommandSpec(
                    command_id=f"pytest-targeted-{index}",
                    argv=(*_PYTEST_ARGV_PREFIX, prefix),
                )
                for index, prefix in enumerate(sorted(selected_prefixes), start=1)
            )
        if tier is TestTier.SHARED:
            return (
                CommandSpec(
                    command_id="pytest-shared",
                    argv=(
                        *_PYTEST_ARGV_PREFIX,
                        "tests/core",
                        "tests/runtime",
                        "tests/data",
                        "tests/platform",
                    ),
                ),
            )
        base = (
            CommandSpec(command_id="test-full", argv=("make", "test")),
            CommandSpec(
                command_id="test-contract",
                argv=("make", "test-contract"),
            ),
        )
        if tier is TestTier.FULL:
            return base
        release_commands: tuple[CommandSpec, ...] = (
            *base,
            CommandSpec(
                command_id="test-security",
                argv=("make", "test-security"),
            ),
            CommandSpec(command_id="acceptance", argv=("make", "acceptance")),
        )
        if SelectionSignal.MIGRATION_CHANGE in reasons:
            return (
                *release_commands,
                CommandSpec(
                    command_id="migration-real",
                    argv=(
                        *_PYTEST_ARGV_PREFIX,
                        "tests/data/integration",
                    ),
                ),
            )
        return release_commands
