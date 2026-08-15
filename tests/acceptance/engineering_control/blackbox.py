"""Public-CLI black-box harness for the WP-093 acceptance proof."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONTRACT_DIGEST = "sha256:" + "1" * 64
INPUT_HEAD = "fbee7919c4c8bd9d1318d65cc4ce8bb5361a5c9b"


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True, slots=True)
class CliResult:
    returncode: int
    stdout: bytes
    stderr: bytes

    def json_output(self) -> dict[str, Any]:
        raw = self.stdout if self.returncode == 0 else self.stderr
        decoded = json.loads(raw)
        if not isinstance(decoded, dict):
            raise AssertionError("CLI output is not an object")
        return decoded


class FixtureRepository:
    """Small deterministic multi-package repository observed only through the CLI."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._commit_index = 0

    @classmethod
    def create(cls, root: Path) -> FixtureRepository:
        repository = cls(root)
        root.mkdir(parents=True)
        repository.git("init", "-b", "main")
        repository.git("config", "user.email", "quality@example.invalid")
        repository.git("config", "user.name", "FlowPilot Quality")
        repository.write_text(
            "pyproject.toml",
            """[project]
name = "acceptance-workspace"
version = "0.1.0"

[tool.uv.workspace]
members = [
  "apps/worker",
  "packages/application",
  "packages/domain",
  "packages/persistence",
  "packages/security",
]

[tool.uv.sources]
flowpilot-worker = { workspace = true }
flowpilot-application = { workspace = true }
flowpilot-domain = { workspace = true }
flowpilot-persistence = { workspace = true }
flowpilot-security = { workspace = true }
""",
        )
        package_specs = {
            "apps/worker": ("flowpilot-worker", ["flowpilot-domain"]),
            "packages/application": (
                "flowpilot-application",
                ["flowpilot-domain"],
            ),
            "packages/domain": ("flowpilot-domain", []),
            "packages/persistence": (
                "flowpilot-persistence",
                ["flowpilot-domain"],
            ),
            "packages/security": ("flowpilot-security", ["flowpilot-domain"]),
        }
        for package_path, (name, dependencies) in package_specs.items():
            dependency_list = ", ".join(f'"{item}"' for item in dependencies)
            repository.write_text(
                f"{package_path}/pyproject.toml",
                "\n".join(
                    (
                        "[project]",
                        f'name = "{name}"',
                        'version = "0.1.0"',
                        f"dependencies = [{dependency_list}]",
                        "",
                    )
                ),
            )
        repository.write_text(
            "packages/domain/src/flowpilot_domain/__init__.py",
            "from .ports import DomainPort\n",
        )
        repository.write_text(
            "packages/domain/src/flowpilot_domain/ports.py",
            "class DomainPort:\n    pass\n",
        )
        repository.write_text(
            "packages/domain/src/flowpilot_domain/private.py",
            "VALUE = 'super-secret-canary-must-not-leak'\n",
        )
        repository.write_text(
            "packages/domain/src/flowpilot_domain/知识.py",
            "LABEL = '中文路径内容不得进入地图'\n",
        )
        for index in range(64):
            repository.write_text(
                f"packages/domain/src/flowpilot_domain/filler_{index:02}.py",
                f"VALUE_{index} = '" + ("x" * 1024) + "'\n",
            )
        repository.write_text(
            "packages/application/src/flowpilot_application/service.py",
            "def apply() -> str:\n    return 'ok'\n",
        )
        repository.write_text(
            "packages/security/src/flowpilot_security/policy.py",
            "POLICY = 'deny-by-default'\n",
        )
        repository.write_text(
            "packages/persistence/src/flowpilot_persistence/store.py",
            "STORE = 'postgres'\n",
        )
        repository.write_text(
            "apps/worker/src/flowpilot_worker/runtime.py",
            "RUNTIME = 'graph'\n",
        )
        repository.write_text(
            "tests/core/test_domain.py",
            "def test_domain() -> None:\n    assert True\n",
        )
        repository.write_text(
            "tests/runtime/test_worker.py",
            "def test_worker() -> None:\n    assert True\n",
        )
        repository.write_text(
            "tests/data/test_store.py",
            "def test_store() -> None:\n    assert True\n",
        )
        repository.write_text(
            "tests/platform/test_security.py",
            "def test_security() -> None:\n    assert True\n",
        )
        repository.write_text("contracts/jsonschema/example.json", "{}\n")
        repository.write_text("migrations/versions/0001.sql", "SELECT 1;\n")
        repository.write_text("docs/reviewer-note.md", "# Review\n")
        repository.write_text("AGENTS.md", "# Fixture authority\n")
        repository.write_text("uv.lock", "version = 1\n")
        repository.write_text(
            ".gitignore",
            ".flowpilot-engineering/\n",
        )
        repository.write_bytes(
            "artifacts/acceptance/generated-large.bin",
            b"generated-canary-must-not-leak" * 8192,
        )
        repository.write_bytes("coverage.xml", b"coverage-noise" * 8192)
        repository.commit("fixture baseline")
        return repository

    def write_text(self, relative: str, content: str) -> None:
        destination = self.root.joinpath(*relative.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8", newline="\n")

    def write_bytes(self, relative: str, content: bytes) -> None:
        destination = self.root.joinpath(*relative.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)

    def append(self, relative: str, marker: str) -> None:
        destination = self.root.joinpath(*relative.split("/"))
        current = destination.read_text(encoding="utf-8")
        destination.write_text(current + marker, encoding="utf-8", newline="\n")

    def git(self, *args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=self.root,
            check=True,
            shell=False,
            text=True,
            capture_output=True,
            env=self._git_environment(),
        )
        return completed.stdout.strip()

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-m", message)
        self._commit_index += 1
        return self.git("rev-parse", "HEAD")

    def head(self) -> str:
        return self.git("rev-parse", "HEAD")

    def _git_environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        second = self._commit_index + 1
        date = f"2000-01-01T00:00:{second:02d}+00:00"
        environment["GIT_AUTHOR_DATE"] = date
        environment["GIT_COMMITTER_DATE"] = date
        return environment


def run_cli(repository: FixtureRepository, *args: str) -> CliResult:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "flowpilot_engineering_control",
            "--repo",
            str(repository.root),
            *args,
        ],
        cwd=repository.root,
        check=False,
        shell=False,
        capture_output=True,
    )
    return CliResult(completed.returncode, completed.stdout, completed.stderr)


def _capsule_args(
    repository: FixtureRepository,
    *,
    base: str,
    owner: str,
    write_scope: str,
    signals: tuple[str, ...] = (),
    expansions: tuple[str, ...] = (),
) -> list[str]:
    values = [
        "--base",
        base,
        "--owner",
        owner,
        "--work-package",
        "WP-093",
        "--attempt",
        "WP-093-blackbox",
        "--risk",
        "R2",
        "--contract-digest",
        CONTRACT_DIGEST,
        "--write-scope",
        write_scope,
    ]
    for signal in signals:
        values.extend(("--signal", signal))
    for expansion in expansions:
        values.extend(("--expand", expansion))
    return values


@dataclass(frozen=True, slots=True)
class MutationCase:
    case_id: str
    changes: tuple[tuple[str, str], ...]
    owner: str
    write_scope: str
    expected_tier: str
    expected_prefixes: tuple[str, ...] = ()
    expected_commands: tuple[str, ...] = ()
    signals: tuple[str, ...] = ()


MUTATION_CASES = (
    MutationCase(
        "package-internal",
        (("packages/domain/src/flowpilot_domain/private.py", "# internal\n"),),
        "S5-CORE",
        "packages/domain/**",
        "TARGETED",
        ("tests/core", "tests/data", "tests/platform", "tests/runtime"),
    ),
    MutationCase(
        "cross-package",
        (
            ("packages/domain/src/flowpilot_domain/private.py", "# domain\n"),
            (
                "packages/application/src/flowpilot_application/service.py",
                "# application\n",
            ),
        ),
        "S5-CORE",
        "packages/**",
        "TARGETED",
        ("tests/core", "tests/data", "tests/platform", "tests/runtime"),
    ),
    MutationCase(
        "public-signature",
        (("packages/domain/src/flowpilot_domain/ports.py", "# public\n"),),
        "S5-CORE",
        "packages/domain/**",
        "SHARED",
        expected_commands=("pytest-shared",),
    ),
    MutationCase(
        "contract",
        (("contracts/jsonschema/example.json", " \n"),),
        "S1-ARCH",
        "contracts/**",
        "FULL",
        expected_commands=("test-full", "test-contract"),
    ),
    MutationCase(
        "migration",
        (("migrations/versions/0001.sql", "-- migration\n"),),
        "S6-DATA",
        "migrations/**",
        "RELEASE",
        expected_commands=(
            "test-full",
            "test-contract",
            "test-security",
            "acceptance",
            "migration-real",
        ),
    ),
    MutationCase(
        "lock",
        (("uv.lock", "# lock drift\n"),),
        "S5-CORE",
        "uv.lock",
        "FULL",
        expected_commands=("test-full", "test-contract"),
    ),
    MutationCase(
        "security",
        (("packages/security/src/flowpilot_security/policy.py", "# auth\n"),),
        "S3-PLATFORM",
        "packages/security/**",
        "RELEASE",
        expected_commands=(
            "test-full",
            "test-contract",
            "test-security",
            "acceptance",
        ),
    ),
    MutationCase(
        "unknown-signal",
        (("packages/domain/src/flowpilot_domain/private.py", "# known path\n"),),
        "S5-CORE",
        "packages/domain/**",
        "FULL",
        expected_commands=("test-full", "test-contract"),
        signals=("unknown_path",),
    ),
    MutationCase(
        "dependency-tool-failure",
        (("packages/domain/src/flowpilot_domain/private.py", "# tool failure\n"),),
        "S5-CORE",
        "packages/domain/**",
        "FULL",
        expected_commands=("test-full", "test-contract"),
        signals=("dependency_graph_incomplete",),
    ),
    MutationCase(
        "non-linear-tool-failure",
        (("packages/domain/src/flowpilot_domain/private.py", "# non-linear\n"),),
        "S5-CORE",
        "packages/domain/**",
        "RELEASE",
        expected_commands=(
            "test-full",
            "test-contract",
            "test-security",
            "acceptance",
        ),
        signals=("non_linear_base",),
    ),
)


def run_mutation_matrix(root: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for case in MUTATION_CASES:
        repository = FixtureRepository.create(root / case.case_id)
        base = repository.head()
        for path, marker in case.changes:
            repository.append(path, marker)
        repository.commit(case.case_id)
        result = run_cli(
            repository,
            "tests",
            "select",
            *_capsule_args(
                repository,
                base=base,
                owner=case.owner,
                write_scope=case.write_scope,
                signals=case.signals,
            ),
        )
        assert result.returncode == 0, result.stderr.decode("utf-8")
        plan = result.json_output()
        assert plan["tier"] == case.expected_tier
        prefixes = tuple(plan["selected_test_prefixes"])
        commands = tuple(item["command_id"] for item in plan["commands"])
        if case.expected_prefixes:
            assert prefixes == case.expected_prefixes
            selected_argv = tuple(item["argv"][-1] for item in plan["commands"])
            assert selected_argv == case.expected_prefixes
        if case.expected_commands:
            assert commands == case.expected_commands
        assert commands
        results.append(
            {
                "case_id": f"mutation/{case.case_id}",
                "observed_commands": list(commands),
                "observed_prefixes": list(prefixes),
                "observed_tier": plan["tier"],
                "status": "PASSED",
            }
        )

    repository = FixtureRepository.create(root / "unknown-tracked-path")
    repository.write_text("unknown-root.bin", "unknown\n")
    repository.commit("unknown path")
    unknown = run_cli(repository, "map", "build")
    assert unknown.returncode == 2
    assert unknown.json_output()["error"]["code"] == "ENG_UNKNOWN_PATH"
    results.append(
        {
            "case_id": "mutation/unknown-tracked-path",
            "observed_error": "ENG_UNKNOWN_PATH",
            "status": "PASSED",
        }
    )

    repository = FixtureRepository.create(root / "no-change-proof")
    head = repository.head()
    no_change = run_cli(
        repository,
        "tests",
        "select",
        *_capsule_args(
            repository,
            base=head,
            owner="S4-QUALITY",
            write_scope="tests/acceptance/**",
        ),
    )
    assert no_change.returncode == 0
    no_change_plan = no_change.json_output()
    assert no_change_plan["tier"] == "FULL"
    assert no_change_plan["fallback_required"] is True
    assert "no_change_proof" in no_change_plan["reasons"]
    results.append(
        {
            "case_id": "mutation/no-change-proof",
            "observed_tier": "FULL",
            "status": "PASSED",
        }
    )
    return results


def run_efficiency_and_path_case(root: Path) -> list[dict[str, Any]]:
    repository = FixtureRepository.create(root / "efficiency")
    base = repository.head()
    repository.append(
        "packages/domain/src/flowpilot_domain/private.py",
        "# efficient delta\n",
    )
    repository.commit("efficient delta")
    first_map = run_cli(repository, "map", "build")
    second_map = run_cli(repository, "map", "build")
    assert first_map.returncode == second_map.returncode == 0
    assert first_map.stdout == second_map.stdout
    assert first_map.stdout.startswith(b"{")
    assert first_map.stdout.endswith(b"\n")
    assert not first_map.stdout.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in first_map.stdout
    assert b"super-secret-canary-must-not-leak" not in first_map.stdout
    assert b"generated-canary-must-not-leak" not in first_map.stdout
    repository_map = first_map.json_output()
    paths = {entry["path"] for entry in repository_map["path_entries"]}
    assert "packages/domain/src/flowpilot_domain/知识.py" in paths
    assert "artifacts/acceptance/generated-large.bin" not in paths
    assert "coverage.xml" not in paths
    assert repository_map["counts"]["source_bytes"] == sum(
        entry["byte_count"] for entry in repository_map["path_entries"]
    )

    capsule_args = _capsule_args(
        repository,
        base=base,
        owner="S5-CORE",
        write_scope=r"packages\domain\**",
    )
    first_capsule = run_cli(repository, "capsule", "build", *capsule_args)
    second_capsule = run_cli(repository, "capsule", "build", *capsule_args)
    assert first_capsule.returncode == second_capsule.returncode == 0
    assert first_capsule.stdout == second_capsule.stdout
    capsule = first_capsule.json_output()
    counts = capsule["counts"]
    assert counts["initial_read_ratio_basis_points"] < 2_000
    assert counts["initial_read_files"] * 5 < counts["full_repository_files"]
    required = set(capsule["required_read_set"])
    assert {
        "tests/core/test_domain.py",
        "tests/data/test_store.py",
        "tests/platform/test_security.py",
        "tests/runtime/test_worker.py",
    }.issubset(required)
    return [
        {
            "case_id": "efficiency/deterministic-map-capsule",
            "map_bytes": len(first_map.stdout),
            "status": "PASSED",
        },
        {
            "case_id": "efficiency/initial-read-under-20-percent",
            "full_repository_bytes": counts["full_repository_bytes"],
            "full_repository_files": counts["full_repository_files"],
            "initial_read_bytes": counts["initial_read_bytes"],
            "initial_read_files": counts["initial_read_files"],
            "ratio_basis_points": counts["initial_read_ratio_basis_points"],
            "status": "PASSED",
        },
        {
            "case_id": "paths/windows-utf8-generated-coverage",
            "excluded_generated_count": 2,
            "status": "PASSED",
        },
    ]


def run_expansion_case(root: Path) -> list[dict[str, Any]]:
    repository = FixtureRepository.create(root / "manual-expansion")
    base = repository.head()
    repository.append(
        "packages/domain/src/flowpilot_domain/private.py",
        "# implementation\n",
    )
    repository.append("docs/reviewer-note.md", "Reviewer requested read.\n")
    repository.commit("manual expansion")
    expansion = "reviewer_request:S1-ARCH:docs/reviewer-note.md"
    capsule_result = run_cli(
        repository,
        "capsule",
        "build",
        *_capsule_args(
            repository,
            base=base,
            owner="S5-CORE",
            write_scope="packages/domain/**",
            expansions=(expansion,),
        ),
    )
    assert capsule_result.returncode == 0, capsule_result.stderr.decode("utf-8")
    capsule = capsule_result.json_output()
    assert capsule["counts"]["scope_expansions"] == 1
    assert "docs/reviewer-note.md" in capsule["allowed_initial_read_set"]
    plan_result = run_cli(
        repository,
        "tests",
        "select",
        *_capsule_args(
            repository,
            base=base,
            owner="S5-CORE",
            write_scope="packages/domain/**",
            expansions=(expansion,),
        ),
    )
    assert plan_result.returncode == 0
    assert plan_result.json_output()["tier"] == "TARGETED"
    return [
        {
            "case_id": "scope/manual-expansion-preserved",
            "scope_expansion_count": 1,
            "status": "PASSED",
        }
    ]


def _evidence_common(
    *, command_id: str, kind: str, toolchain: str = "python=3.12"
) -> list[str]:
    return [
        "--command-id",
        command_id,
        "--arg",
        "python",
        "--arg",
        "; | > $(literal-not-a-command)",
        "--contract-digest",
        CONTRACT_DIGEST,
        "--toolchain",
        toolchain,
        "--kind",
        kind,
    ]


def run_cache_cases(root: Path) -> list[dict[str, Any]]:
    repository = FixtureRepository.create(root / "cache")
    evidence_path = ".flowpilot-engineering/evidence/pass.txt"
    repository.write_text(evidence_path, "PASS\n")
    sentinel = repository.root / "literal-not-a-command"
    common = _evidence_common(command_id="blackbox-cache", kind="local_test")
    recorded = run_cli(
        repository,
        "evidence",
        "record",
        *common,
        "--evidence",
        evidence_path,
        "--exit-code",
        "0",
    )
    assert recorded.returncode == 0, recorded.stderr.decode("utf-8")
    assert b"literal-not-a-command" not in recorded.stdout
    assert not sentinel.exists()
    record_path = recorded.json_output()["record_path"]
    assert isinstance(record_path, str)
    record_file = repository.root.joinpath(*record_path.split("/"))
    original_record = record_file.read_bytes()
    exact = run_cli(
        repository,
        "evidence",
        "check",
        *common,
        "--record",
        record_path,
    )
    assert exact.returncode == 0
    assert exact.json_output()["hit"] is True

    repository.write_text(evidence_path, "TAMPERED\n")
    evidence_tamper = run_cli(
        repository,
        "evidence",
        "check",
        *common,
        "--record",
        record_path,
    )
    assert evidence_tamper.returncode == 0
    assert evidence_tamper.json_output()["hit"] is False
    assert "evidence_integrity_mismatch" in evidence_tamper.json_output()["reasons"]
    repository.write_text(evidence_path, "PASS\n")

    decoded = json.loads(original_record)
    decoded["cache_key"]["component_hashes"]["environment"] = "0" * 64
    payload = {key: value for key, value in decoded.items() if key != "record_sha256"}
    decoded["record_sha256"] = sha256_bytes(canonical_json(payload))
    record_file.write_bytes(canonical_json(decoded))
    environment_drift = run_cli(
        repository,
        "evidence",
        "check",
        *common,
        "--record",
        record_path,
    )
    assert environment_drift.returncode == 0
    assert environment_drift.json_output()["hit"] is False
    assert "environment_drift" in environment_drift.json_output()["reasons"]

    record_file.write_bytes(original_record + b" ")
    record_tamper = run_cli(
        repository,
        "evidence",
        "check",
        *common,
        "--record",
        record_path,
    )
    assert record_tamper.returncode == 0
    assert record_tamper.json_output()["reasons"] == [
        "record_integrity_mismatch"
    ]
    record_file.write_bytes(original_record)

    toolchain_drift = run_cli(
        repository,
        "evidence",
        "check",
        *_evidence_common(
            command_id="blackbox-cache",
            kind="local_test",
            toolchain="python=0.0",
        ),
        "--record",
        record_path,
    )
    assert toolchain_drift.returncode == 0
    assert "toolchain_drift" in toolchain_drift.json_output()["reasons"]

    failed = run_cli(
        repository,
        "evidence",
        "record",
        *_evidence_common(command_id="failed-result", kind="local_test"),
        "--evidence",
        evidence_path,
        "--exit-code",
        "1",
    )
    assert failed.returncode == 2
    assert failed.json_output()["error"]["code"] == "ENG_CACHE_FAILED_RESULT"

    denied_kinds = (
        "online_provider",
        "secret_scan",
        "vulnerability_query",
        "real_migration",
        "destructive_recovery",
        "security_reexecute",
    )
    for kind in denied_kinds:
        denied = run_cli(
            repository,
            "evidence",
            "record",
            *_evidence_common(command_id=f"denied-{kind}", kind=kind),
            "--evidence",
            evidence_path,
            "--exit-code",
            "0",
        )
        assert denied.returncode == 2
        assert denied.json_output()["error"]["code"] == "ENG_CACHE_POLICY_DENIED"

    repository.write_text(evidence_path, "COLLISION\n")
    collision = run_cli(
        repository,
        "evidence",
        "record",
        *common,
        "--evidence",
        evidence_path,
        "--exit-code",
        "0",
    )
    assert collision.returncode == 2
    assert collision.json_output()["error"]["code"] == "ENG_CACHE_KEY_CONFLICT"
    assert not sentinel.exists()
    return [
        {"case_id": "cache/exact-hit", "status": "PASSED"},
        {"case_id": "cache/argv-command-injection", "status": "PASSED"},
        {"case_id": "cache/evidence-tamper", "status": "PASSED"},
        {"case_id": "cache/record-tamper", "status": "PASSED"},
        {"case_id": "cache/environment-drift", "status": "PASSED"},
        {"case_id": "cache/toolchain-drift", "status": "PASSED"},
        {"case_id": "cache/failed-result-not-reused", "status": "PASSED"},
        {
            "case_id": "cache/policy-denied-kinds",
            "denied_kind_count": len(denied_kinds),
            "status": "PASSED",
        },
        {"case_id": "cache/same-key-pollution", "status": "PASSED"},
    ]


def run_report_cases(root: Path) -> list[dict[str, Any]]:
    repository = FixtureRepository.create(root / "report")
    base = repository.head()
    repository.append(
        "packages/domain/src/flowpilot_domain/private.py",
        "# report delta\n",
    )
    repository.commit("report delta")
    capsule_args = _capsule_args(
        repository,
        base=base,
        owner="S5-CORE",
        write_scope="packages/domain/**",
    )
    capsule_result = run_cli(repository, "capsule", "build", *capsule_args)
    assert capsule_result.returncode == 0
    estimated_bytes = capsule_result.json_output()["counts"]["initial_read_bytes"]
    observations = (
        "packages/domain/src/flowpilot_domain/private.py:" + "a" * 64 + ":3",
        "tests/core/test_domain.py:" + "b" * 64 + ":5",
    )
    args = [
        "attempt",
        "report",
        *capsule_args,
        "--actual-read",
        observations[0],
        "--actual-read",
        observations[1],
        "--selection-ms",
        "7",
    ]
    first = run_cli(repository, *args)
    second = run_cli(repository, *args)
    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    report = first.json_output()
    assert report["actual_read"]["record_available"] is True
    assert report["actual_read"]["file_count"] == 2
    assert report["actual_read"]["byte_count"] == 8
    assert report["estimated_usage"]["input_bytes"] == estimated_bytes
    assert report["estimated_usage"]["tokens"] == (estimated_bytes + 3) // 4
    assert report["selection_compute_ms"] == 7
    assert report["actual_read"]["byte_count"] != estimated_bytes
    assert "argv" not in report["commands"][0]

    no_actual = run_cli(
        repository,
        "attempt",
        "report",
        *capsule_args,
        "--selection-ms",
        "0",
    )
    assert no_actual.returncode == 0
    assert no_actual.json_output()["actual_read"] is None

    duplicate = run_cli(
        repository,
        "attempt",
        "report",
        *capsule_args,
        "--actual-read",
        observations[0],
        "--actual-read",
        observations[0],
        "--selection-ms",
        "1",
    )
    assert duplicate.returncode == 2
    assert duplicate.json_output()["error"]["code"] == "ENG_REPORT_INVALID"
    return [
        {
            "actual_bytes": 8,
            "case_id": "report/actual-vs-estimated-separated",
            "estimated_bytes": estimated_bytes,
            "status": "PASSED",
        },
        {"case_id": "report/missing-actual-is-null", "status": "PASSED"},
        {"case_id": "report/duplicate-actual-fails", "status": "PASSED"},
    ]


def build_proof(root: Path) -> dict[str, Any]:
    cases = [
        *run_mutation_matrix(root / "mutation"),
        *run_efficiency_and_path_case(root / "efficiency"),
        *run_expansion_case(root / "expansion"),
        *run_cache_cases(root / "cache"),
        *run_report_cases(root / "report"),
    ]
    assert len({item["case_id"] for item in cases}) == len(cases)
    assert all(item["status"] == "PASSED" for item in cases)
    payload: dict[str, Any] = {
        "all_declared_cases": len(cases),
        "attempt_id": "WP-093-a1",
        "cases": cases,
        "chain_id": "CHAIN-M9T-ENGINEERING-CONTROL-01",
        "contract_content_digest": (
            "sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2"
        ),
        "failed": 0,
        "feature_id": "FP-OPS-002",
        "gate": "PASS",
        "input_head": INPUT_HEAD,
        "passed": len(cases),
        "schema_version": "flowpilot.wp093-proof.v1",
        "skipped": 0,
        "step_id": "M9T-03-S4-ACCEPTANCE",
    }
    return {**payload, "proof_sha256": sha256_bytes(canonical_json(payload))}
