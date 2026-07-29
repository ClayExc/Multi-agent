"""Reproduce WP-040 candidate or S1 final static composition evidence.

The verifier is deliberately read-only with respect to Git and product sources.
It emits deterministic artifacts below ``artifacts/integration/runs`` when an
output directory is supplied. Runtime, wheel, database, and Compose results are
recorded separately in the S7 handoff. The default phase preserves WP-040-a1
candidate output; ``S1_FINAL`` adds final-branch and invariant checks.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
import tomllib
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

BASE_COMMIT = "55125ae3992311eab03cc888ea9c908486b4b727"
CONTROL_HEAD = "6a16320a16fc76f2a5ffdedfc0ab893c87a636fa"
COMMON_MERGE_BASE = "93597a5023320d48875b292dc08106f03227a3fb"
CANDIDATE_MERGE_HEAD = "56c90b1355213357415778bda43fc3acf96aa8ed"
S7_CANDIDATE_HEAD = "4314766c0cfb57c3332a5fc0b0c27395e93cf879"
S1_FINAL_TEST_HEAD = "9b166f8cbc6a85fc036458c5d88caf1ec10feacf"
CONTRACT_DIGEST = (
    "sha256:0a82e7f58c4223362721c95a50e9a820"
    "d714e550e72eebc7a90ab01e283100fc"
)
CONTRACT_TREE = "3b67857c6aacce574080089ce1d8b763dd766a77"
LOCK_DIGEST = (
    "sha256:eb0f7ef676b42d81bd60d47de02b2021"
    "97cc6d300ae8d4715814c3ebf3da70f8"
)

INPUTS: dict[str, dict[str, Any]] = {
    "S2-RUNTIME": {
        "base": "34bec05003cb59b3e16f1a16ae166b1f77465c46",
        "head": "c3da3118eac5ee7d57c6b333c2aac3a0f119d799",
        "commit_count": 3,
        "handoff": "tests/runtime/evidence/WP-010-a2-HANDOFF.md",
        "handoff_sha256": (
            "d27b4fae55b8006a5337184ff0754fd6"
            "f037e86a2b8577b1cf991a6c1618bb83"
        ),
        "allowed": (
            "apps/worker/",
            "packages/graph/",
            "packages/agent-runtime/",
            "packages/model-gateway/",
            "packages/context/",
            "tests/runtime/",
        ),
    },
    "S5-CORE": {
        "base": "0be20f5b56d330f4da494ce4c3d46b183b09ae8b",
        "head": "315822de1c8a50f5ede304836686ce5e63f9ad1d",
        "commit_count": 1,
        "handoff": "tests/core/evidence/WP-011-a3-HANDOFF.md",
        "handoff_sha256": (
            "8db60024d62b63c03b8f9fdc7abdce3"
            "8a6eb3b861e27411805b2ed38c5afe5fe"
        ),
        "allowed": ("uv.lock", "tests/core/"),
    },
    "S6-DATA": {
        "base": "3e0101999061a44a3a5b2fd455ec792e3f73954e",
        "head": "e41f0266e6e588417332043b68a3309b2d40bcf7",
        "commit_count": 2,
        "handoff": "tests/data/evidence/WP-021-a2/HANDOFF.md",
        "handoff_sha256": (
            "da2f44abc2c9f34f8549df905898949b"
            "c6de59ac419232a2f2654efa19ccd479"
        ),
        "allowed": (
            "packages/persistence/",
            "migrations/",
            "tests/data/",
        ),
    },
}

TEMPORARY_CONSTRUCTION: tuple[tuple[str, str], ...] = (
    ("S5-CORE", "8f162841cec085221320c638d2ec7f1c04308cff"),
    ("S6-DATA", "9e8f427e5b02f9e48252ef706ebc9b82f31f1aa3"),
    ("S2-RUNTIME", CANDIDATE_MERGE_HEAD),
)

WORKSPACE_PACKAGES: dict[str, str] = {
    "apps/api": "flowpilot-api",
    "apps/worker": "flowpilot-worker",
    "packages/agent-runtime": "flowpilot-agent-runtime",
    "packages/application": "flowpilot-application",
    "packages/context": "flowpilot-context",
    "packages/domain": "flowpilot-domain",
    "packages/graph": "flowpilot-graph",
    "packages/model-gateway": "flowpilot-model-gateway",
    "packages/persistence": "flowpilot-persistence",
}

MIGRATION_HASHES = {
    "migrations/0001_persistence_baseline.down.sql": (
        "c7efb33a30dae969d2dba39a06b92186"
        "3390794ec618188bf9ea0969a42c56df"
    ),
    "migrations/0001_persistence_baseline.sql": (
        "0a6c20e172f59c5c70cdd9370c996672"
        "a79841771575541c3c8bc372f38808cd"
    ),
    "migrations/0002_checkpoint_sequence_cas.down.sql": (
        "beb71df8b0f82fdc11f9b59a3f323f9"
        "d43857356b76d136742f43fc67ff1f22c"
    ),
    "migrations/0002_checkpoint_sequence_cas.sql": (
        "e5ca8fca2de8e913caedd488821356e4"
        "41b2adc5ae72a20d015fe4df5b403112"
    ),
}

CONTRACT_CONTENT_FIELDS = (
    "$schema",
    "contract_set_id",
    "version",
    "digest_profile",
    "owner",
    "published_on",
    "supersedes",
    "required_reviewers",
    "freeze_requirements",
    "schemas",
    "artifacts",
    "release_dependencies",
)

S7_ALLOWED_PREFIXES = (
    "scripts/integration/",
    "tests/integration/",
    "artifacts/integration/",
)

S1_EXACT_PATHS = {
    "AGENTS.md",
    "README.md",
    "STRUCTURE.md",
    "WORKFLOW.md",
}

S1_ALLOWED_PREFIXES = (
    "contracts/",
    "docs/architecture/",
    "docs/acceptance/",
    "docs/decisions/",
    "docs/roadmap/",
    "docs/review/",
    "docs/team/",
)

S1_ALLOWED_SHARED_PATHS = {".gitignore"}

FINAL_PROTECTED_PATHS = (
    ".env.example",
    "Makefile",
    "apps",
    "domain-packs",
    "infra",
    "migrations",
    "packages",
    "pyproject.toml",
    "tests/core",
    "tests/data",
    "tests/runtime",
    "uv.lock",
)


class ValidationPhase(StrEnum):
    S7_CANDIDATE = "S7_CANDIDATE"
    S1_FINAL = "S1_FINAL"


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    outcome: str
    evidence: str


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def run_git(repo: Path, *args: str, check: bool = True) -> str:
    completed = subprocess.run(
        ("git", "-C", str(repo), *args),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return completed.stdout.strip()


def load_json(path: Path) -> Any:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_keys,
    )


def rfc8785_canonical_bytes(value: Any) -> bytes:
    """Canonicalize FlowPilot's integer-only I-JSON contract profile."""

    def encode(item: Any) -> str:
        if item is None:
            return "null"
        if item is True:
            return "true"
        if item is False:
            return "false"
        if isinstance(item, int):
            if not -(2**53 - 1) <= item <= 2**53 - 1:
                raise ValueError("integer exceeds the I-JSON safe range")
            return str(item)
        if isinstance(item, float):
            raise ValueError("FlowPilot contract digests reject floats")
        if isinstance(item, str):
            return json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        if isinstance(item, list):
            return "[" + ",".join(encode(child) for child in item) + "]"
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ValueError("RFC 8785 object keys must be strings")
            keys = sorted(
                item,
                key=lambda key: key.encode("utf-16-be", errors="strict"),
            )
            encoded = (f"{encode(key)}:{encode(item[key])}" for key in keys)
            return "{" + ",".join(encoded) + "}"
        raise ValueError(f"unsupported RFC 8785 value: {type(item)!r}")

    return encode(value).encode("utf-8", errors="strict")


def contract_content_digest(manifest: dict[str, Any]) -> str:
    projection = {field: manifest[field] for field in CONTRACT_CONTENT_FIELDS}
    digest = sha256_bytes(rfc8785_canonical_bytes(projection))
    return f"sha256:{digest}"


def is_allowed_path(path: str, allowed: Iterable[str]) -> bool:
    normalized = path.replace("\\", "/")
    return any(
        normalized == item or normalized.startswith(item)
        for item in allowed
    )


def changed_paths(repo: Path, base: str, head: str) -> list[str]:
    output = run_git(repo, "diff", "--name-only", base, head)
    return sorted(line for line in output.splitlines() if line)


def changed_path_statuses(
    repo: Path,
    base: str,
    head: str,
) -> list[tuple[str, str]]:
    output = run_git(repo, "diff", "--name-status", base, head)
    changes: list[tuple[str, str]] = []
    for line in output.splitlines():
        if not line:
            continue
        fields = line.split("\t")
        status = fields[0]
        paths = fields[1:]
        if status.startswith(("R", "C")):
            changes.extend((status, path) for path in paths)
        elif len(paths) == 1:
            changes.append((status, paths[0]))
        else:
            raise ValueError(f"unexpected git name-status line: {line}")
    return changes


def commit_is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    return (
        subprocess.run(
            (
                "git",
                "-C",
                str(repo),
                "merge-base",
                "--is-ancestor",
                ancestor,
                descendant,
            ),
            check=False,
            capture_output=True,
        ).returncode
        == 0
    )


def resolve_commit(repo: Path, revision: str) -> str:
    return run_git(repo, "rev-parse", f"{revision}^{{commit}}")


def branches_containing(repo: Path, revision: str) -> list[str]:
    output = run_git(
        repo,
        "for-each-ref",
        "--format=%(refname:short)",
        "--contains",
        revision,
        "refs/heads",
    )
    return sorted(line for line in output.splitlines() if line)


def is_s1_branch(branch: str) -> bool:
    return branch == "master" or branch.startswith("codex/s1/")


def select_target_branch(repo: Path, target_head: str) -> str:
    current_head = run_git(repo, "rev-parse", "HEAD")
    current_branch = run_git(repo, "branch", "--show-current")
    if current_head == target_head and current_branch:
        return current_branch
    branches = branches_containing(repo, target_head)
    allowed = [branch for branch in branches if is_s1_branch(branch)]
    if allowed:
        return allowed[0]
    return branches[0] if branches else "(detached)"


def path_scope_violations(
    paths: Iterable[str],
    allowed: Iterable[str],
) -> list[str]:
    return sorted(path for path in paths if not is_allowed_path(path, allowed))


def is_s1_owned_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized in S1_EXACT_PATHS or any(
        normalized.startswith(prefix) for prefix in S1_ALLOWED_PREFIXES
    )


def final_scope_violations(
    changes: Iterable[tuple[str, str]],
    final_gitignore: str,
) -> list[str]:
    ignores_idea = any(
        line.strip().rstrip("/") == ".idea"
        for line in final_gitignore.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    violations: list[str] = []
    for status, path in changes:
        normalized = path.replace("\\", "/")
        if (
            is_s1_owned_path(normalized)
            or normalized in S1_ALLOWED_SHARED_PATHS
        ):
            continue
        if status == "D" and normalized.startswith(".idea/") and ignores_idea:
            continue
        violations.append(f"{status}:{normalized}")
    return sorted(violations)


def revision_object_id(repo: Path, revision: str, path: str) -> str:
    completed = subprocess.run(
        ("git", "-C", str(repo), "rev-parse", f"{revision}:{path}"),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        return "missing"
    return completed.stdout.strip()


def compare_revision_paths(
    repo: Path,
    base: str,
    target: str,
    paths: Iterable[str],
) -> tuple[dict[str, dict[str, str]], list[str]]:
    identities: dict[str, dict[str, str]] = {}
    mismatches: list[str] = []
    for path in paths:
        base_object = revision_object_id(repo, base, path)
        target_object = revision_object_id(repo, target, path)
        identities[path] = {
            "s7_candidate": base_object,
            "final": target_object,
        }
        if base_object != target_object:
            mismatches.append(path)
    return identities, mismatches


def git_object_exists(repo: Path, revision_path: str) -> bool:
    return (
        subprocess.run(
            ("git", "-C", str(repo), "cat-file", "-e", revision_path),
            check=False,
            capture_output=True,
        ).returncode
        == 0
    )


def status_is_clean(porcelain_output: str) -> bool:
    return not porcelain_output.strip()


def input_heads_are_unique(inputs: dict[str, dict[str, Any]]) -> bool:
    heads = [str(specification["head"]) for specification in inputs.values()]
    return len(heads) == len(set(heads))


def missing_workspace_members(
    repo: Path,
    members: Iterable[str],
) -> list[str]:
    return sorted(
        member
        for member in members
        if not (repo / member / "pyproject.toml").is_file()
    )


def discover_migration_heads(migrations_dir: Path) -> list[str]:
    upgrades = sorted(
        path
        for path in migrations_dir.glob("[0-9][0-9][0-9][0-9]_*.sql")
        if not path.name.endswith(".down.sql")
    )
    migration_ids = {path.stem for path in upgrades}
    predecessors: set[str] = set()
    for path in upgrades:
        source = path.read_text(encoding="utf-8")
        predecessors.update(
            re.findall(r"\brequires ([0-9]{4}_[A-Za-z0-9_]+)\b", source)
        )
    return sorted(migration_ids - predecessors)


def imported_modules(source_root: Path) -> set[str]:
    modules: set[str] = set()
    for path in sorted(source_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                modules.add(node.module)
    return modules


def make_check(check_id: str, outcome: bool, evidence: str) -> CheckResult:
    return CheckResult(
        check_id=check_id,
        outcome="PASS" if outcome else "FAIL",
        evidence=evidence,
    )


def check_merge_topology(
    repo: Path,
    construction: Sequence[tuple[str, str]] = TEMPORARY_CONSTRUCTION,
) -> CheckResult:
    previous = BASE_COMMIT
    failures: list[str] = []
    for role, merge_commit in construction:
        parents = run_git(
            repo,
            "show",
            "-s",
            "--format=%P",
            merge_commit,
        ).split()
        expected = [previous, str(INPUTS[role]["head"])]
        if parents != expected:
            failures.append(
                f"{merge_commit[:12]} parents={','.join(parents)} "
                f"expected={','.join(expected)}"
            )
        previous = merge_commit
    evidence = (
        "temporary construction is S5->S6->S2; "
        "it is a final-tree fixture, not a mainline integration order"
    )
    if failures:
        evidence = "; ".join(failures)
    return make_check("git.temporary_merge_topology", not failures, evidence)


def verify_input(
    repo: Path,
    role: str,
    specification: dict[str, Any],
) -> tuple[dict[str, Any], list[CheckResult]]:
    checks: list[CheckResult] = []
    base = str(specification["base"])
    head = str(specification["head"])
    merge_base = run_git(repo, "merge-base", BASE_COMMIT, head)
    count = int(run_git(repo, "rev-list", "--count", f"{base}..{head}"))
    paths = changed_paths(repo, base, head)
    violations = [
        path
        for path in paths
        if not is_allowed_path(path, specification["allowed"])
    ]
    handoff = repo / str(specification["handoff"])
    handoff_hash = sha256_file(handoff) if handoff.is_file() else "missing"
    contract_tree = run_git(repo, "rev-parse", f"{head}:contracts")

    checks.extend(
        (
            make_check(
                f"input.{role}.merge_base",
                merge_base == COMMON_MERGE_BASE,
                f"merge_base={merge_base}",
            ),
            make_check(
                f"input.{role}.commit_range",
                count == specification["commit_count"],
                f"{base}..{head} commits={count}",
            ),
            make_check(
                f"input.{role}.path_scope",
                not violations,
                (
                    f"changed={len(paths)} violations="
                    f"{','.join(violations) if violations else 'none'}"
                ),
            ),
            make_check(
                f"input.{role}.handoff_hash",
                handoff_hash == specification["handoff_sha256"],
                f"sha256:{handoff_hash}",
            ),
            make_check(
                f"input.{role}.contract_tree",
                contract_tree == CONTRACT_TREE,
                f"tree={contract_tree}",
            ),
        )
    )
    record = {
        "base": base,
        "head": head,
        "merge_base_with_control_base": merge_base,
        "commit_count": count,
        "changed_path_count": len(paths),
        "changed_paths": paths,
        "path_scope_violations": violations,
        "handoff": specification["handoff"],
        "handoff_sha256": f"sha256:{handoff_hash}",
        "contract_tree": contract_tree,
    }
    return record, checks


def verify_workspace(repo: Path) -> tuple[dict[str, Any], list[CheckResult]]:
    checks: list[CheckResult] = []
    pyproject = tomllib.loads(
        (repo / "pyproject.toml").read_text(encoding="utf-8")
    )
    lock_path = repo / "uv.lock"
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))

    actual_members = pyproject["tool"]["uv"]["workspace"]["members"]
    actual_sources = pyproject["tool"]["uv"]["sources"]
    expected_members = list(WORKSPACE_PACKAGES)
    expected_packages = set(WORKSPACE_PACKAGES.values())
    expected_lock_members = expected_packages | {"flowpilot-workspace"}
    lock_members = set(lock["manifest"]["members"])
    lock_packages = [item["name"] for item in lock["package"]]
    lock_hash = sha256_file(lock_path)

    project_names: dict[str, str] = {}
    missing_members = missing_workspace_members(repo, WORKSPACE_PACKAGES)
    for member, expected_name in WORKSPACE_PACKAGES.items():
        member_path = repo / member / "pyproject.toml"
        if not member_path.is_file():
            continue
        member_toml = tomllib.loads(member_path.read_text(encoding="utf-8"))
        project_names[member] = member_toml["project"]["name"]
        if project_names[member] != expected_name:
            missing_members.append(
                f"{member}:name={project_names[member]}"
            )

    source_mismatches = [
        package
        for package in sorted(expected_packages)
        if actual_sources.get(package) != {"workspace": True}
    ]
    checks.extend(
        (
            make_check(
                "workspace.members",
                actual_members == expected_members and not missing_members,
                (
                    f"members={len(actual_members)} "
                    f"missing_or_mismatched={missing_members or 'none'}"
                ),
            ),
            make_check(
                "workspace.sources",
                not source_mismatches
                and set(actual_sources) == expected_packages,
                f"workspace_sources={len(actual_sources)}",
            ),
            make_check(
                "workspace.lock_members",
                lock_members == expected_lock_members,
                f"members={','.join(sorted(lock_members))}",
            ),
            make_check(
                "workspace.lock_package_count",
                len(lock_packages) == 73
                and len(lock_packages) == len(set(lock_packages)),
                f"packages={len(lock_packages)} unique={len(set(lock_packages))}",
            ),
            make_check(
                "workspace.lock_digest",
                f"sha256:{lock_hash}" == LOCK_DIGEST,
                f"sha256:{lock_hash}",
            ),
        )
    )
    record = {
        "member_count": len(actual_members),
        "members": actual_members,
        "project_names": project_names,
        "source_count": len(actual_sources),
        "lock_member_count": len(lock_members),
        "lock_package_count": len(lock_packages),
        "lock_sha256": f"sha256:{lock_hash}",
    }
    return record, checks


def verify_code_dependencies(repo: Path) -> tuple[dict[str, Any], list[CheckResult]]:
    checks: list[CheckResult] = []
    worker_toml = tomllib.loads(
        (repo / "apps/worker/pyproject.toml").read_text(encoding="utf-8")
    )
    worker_dependencies = set(worker_toml["project"]["dependencies"])
    worker_sources = worker_toml["tool"]["uv"]["sources"]
    required_worker_dependencies = {
        "flowpilot-application",
        "flowpilot-domain",
        "flowpilot-graph",
        "flowpilot-persistence",
    }

    persistence_toml = tomllib.loads(
        (repo / "packages/persistence/pyproject.toml").read_text(
            encoding="utf-8"
        )
    )
    persistence_dependencies = set(persistence_toml["project"]["dependencies"])
    persistence_imports = imported_modules(
        repo / "packages/persistence/src"
    )
    forbidden_reverse_imports = sorted(
        module
        for module in persistence_imports
        if module == "flowpilot_graph"
        or module.startswith("flowpilot_graph.")
        or module == "flowpilot_worker"
        or module.startswith("flowpilot_worker.")
    )

    ports_source = (
        repo
        / "packages/application/src/flowpilot_application/ports.py"
    ).read_text(encoding="utf-8")
    actions_source = (
        repo / "packages/domain/src/flowpilot_domain/actions.py"
    ).read_text(encoding="utf-8")
    postgres_source = (
        repo / "packages/persistence/src/flowpilot_persistence/postgres.py"
    ).read_text(encoding="utf-8")

    checks.extend(
        (
            make_check(
                "dependencies.s2_worker_ports",
                required_worker_dependencies <= worker_dependencies
                and all(
                    worker_sources.get(package) == {"workspace": True}
                    for package in required_worker_dependencies
                ),
                "worker consumes S5 application/domain and S6 persistence",
            ),
            make_check(
                "dependencies.s6_application_port",
                {
                    "flowpilot-application",
                    "flowpilot-domain",
                }
                <= persistence_dependencies,
                "persistence consumes S5 application/domain",
            ),
            make_check(
                "dependencies.no_persistence_reverse_edge",
                not forbidden_reverse_imports,
                (
                    "forbidden imports="
                    f"{forbidden_reverse_imports or 'none'}"
                ),
            ),
            make_check(
                "ports.task_query_full_task",
                "class TaskQueryPort(Protocol):" in ports_source
                and "-> Task | None:" in ports_source
                and "Task.from_mapping" in postgres_source,
                "TaskQueryPort returns Task and PostgreSQL restores Task.from_mapping",
            ),
            make_check(
                "domain.planned_action_digest",
                "def digest(self) -> str:" in actions_source
                and "return canonical_sha256(self.to_mapping())"
                in actions_source,
                "PlannedAction.digest uses the full authoritative mapping",
            ),
        )
    )
    record = {
        "worker_dependencies": sorted(worker_dependencies),
        "persistence_dependencies": sorted(persistence_dependencies),
        "forbidden_persistence_imports": forbidden_reverse_imports,
        "task_query_port": "Task | None",
        "planned_action_digest": "canonical_sha256(self.to_mapping())",
    }
    return record, checks


def verify_migrations(repo: Path) -> tuple[dict[str, Any], list[CheckResult]]:
    actual_hashes = {
        path: sha256_file(repo / path)
        for path in sorted(MIGRATION_HASHES)
    }
    mismatches = [
        path
        for path, expected in MIGRATION_HASHES.items()
        if actual_hashes[path] != expected
    ]
    upgrade_source = (
        repo / "migrations/0002_checkpoint_sequence_cas.sql"
    ).read_text(encoding="utf-8")
    linear = (
        "requires 0001_persistence_baseline" in upgrade_source
        and "0002_checkpoint_sequence_cas" in upgrade_source
        and CONTRACT_DIGEST in upgrade_source
        and "checkpoint_sequence bigint" in upgrade_source
    )
    heads = discover_migration_heads(repo / "migrations")
    checks = [
        make_check(
            "migrations.file_hashes",
            not mismatches,
            f"files={len(actual_hashes)} mismatches={mismatches or 'none'}",
        ),
        make_check(
            "migrations.linear_head",
            linear and heads == ["0002_checkpoint_sequence_cas"],
            (
                "0001_persistence_baseline -> "
                f"{','.join(heads) if heads else 'none'}"
            ),
        ),
    ]
    record = {
        "head": "0002_checkpoint_sequence_cas",
        "discovered_heads": heads,
        "predecessor": "0001_persistence_baseline",
        "file_sha256": {
            path: f"sha256:{digest}"
            for path, digest in actual_hashes.items()
        },
        "compose_auto_applies_head": False,
    }
    return record, checks


def verify_atomic_integration(
    repo: Path,
    full_input_paths: dict[str, set[str]],
) -> tuple[dict[str, Any], list[CheckResult]]:
    s2_worker = tomllib.loads(
        run_git(
            repo,
            "show",
            f"{INPUTS['S2-RUNTIME']['head']}:apps/worker/pyproject.toml",
        )
    )
    s5_root = tomllib.loads(
        run_git(
            repo,
            "show",
            f"{INPUTS['S5-CORE']['head']}:pyproject.toml",
        )
    )

    s2_needs_persistence = (
        "flowpilot-persistence"
        in s2_worker["project"]["dependencies"]
    )
    s5_expands_all_members = (
        s5_root["tool"]["uv"]["workspace"]["members"]
        == list(WORKSPACE_PACKAGES)
    )
    s5_missing_members = [
        member
        for member in WORKSPACE_PACKAGES
        if not git_object_exists(
            repo,
            f"{INPUTS['S5-CORE']['head']}:{member}/pyproject.toml",
        )
    ]
    s2_missing_persistence = not git_object_exists(
        repo,
        f"{INPUTS['S2-RUNTIME']['head']}:"
        "packages/persistence/pyproject.toml",
    )
    non_s5_root_writers = {
        role: sorted(
            {"pyproject.toml", "uv.lock"} & full_input_paths[role]
        )
        for role in ("S2-RUNTIME", "S6-DATA")
    }
    input_roles = sorted(full_input_paths)
    overlaps: dict[str, list[str]] = {}
    for index, left in enumerate(input_roles):
        for right in input_roles[index + 1 :]:
            intersection = sorted(
                full_input_paths[left] & full_input_paths[right]
            )
            overlaps[f"{left}|{right}"] = intersection

    facts_hold = (
        s2_needs_persistence
        and s5_expands_all_members
        and bool(s5_missing_members)
        and s2_missing_persistence
        and not any(non_s5_root_writers.values())
        and not any(overlaps.values())
    )
    checks = [
        make_check(
            "integration.atomicity_required",
            facts_hold,
            (
                "no whole-input sequential order keeps every newly introduced "
                "package and the root workspace simultaneously runnable"
            ),
        ),
        make_check(
            "integration.input_path_disjointness",
            not any(overlaps.values()),
            f"pairwise_overlaps={overlaps}",
        ),
    ]
    record = {
        "recommended_mainline_mode": "ATOMIC_FINAL_CANDIDATE",
        "safe_whole_input_sequential_order": None,
        "remediation_dependency_order": [
            "S6-DATA",
            "S2-RUNTIME",
            "S5-CORE",
        ],
        "logical_dependency_edges": [
            "S5-CORE Application/Domain -> S6-DATA Persistence",
            "S6-DATA Persistence -> S2-RUNTIME Worker adapter",
            "S2/S6 package closure -> S5-CORE final uv.lock",
        ],
        "reason": (
            "The S5 head bundles its ports with a nine-member workspace and "
            "final lock, but does not contain the S2/S6 member trees. S2 "
            "requires S6 persistence, while S2/S6 do not update the root "
            "workspace or lock. Only the complete candidate closes both sides."
        ),
        "temporary_construction_order": [
            role for role, _commit in TEMPORARY_CONSTRUCTION
        ],
        "temporary_construction_is_mainline_order": False,
        "pairwise_full_delta_overlaps": overlaps,
        "s5_head_missing_workspace_members": s5_missing_members,
        "s2_head_missing_persistence_member": s2_missing_persistence,
        "non_s5_root_workspace_writers": non_s5_root_writers,
    }
    return record, checks


def build_manifest(
    repo: Path,
    phase: ValidationPhase | str = ValidationPhase.S7_CANDIDATE,
    target_head: str | None = None,
) -> dict[str, Any]:
    repo = repo.resolve()
    validation_phase = ValidationPhase(phase)
    checks: list[CheckResult] = []
    checkout_head = run_git(repo, "rev-parse", "HEAD")
    final_record: dict[str, Any] | None = None

    if validation_phase is ValidationPhase.S7_CANDIDATE:
        verified_head = S7_CANDIDATE_HEAD
        branch = run_git(repo, "branch", "--show-current")
        checks.append(
            make_check(
                "git.branch",
                branch == "codex/s7/wp-040-integration-verification",
                f"branch={branch}",
            )
        )
    else:
        verified_head = resolve_commit(
            repo,
            target_head if target_head is not None else checkout_head,
        )
        branch = select_target_branch(repo, verified_head)
        checks.append(
            make_check(
                "git.branch",
                is_s1_branch(branch),
                f"phase=S1_FINAL branch={branch}",
            )
        )

    checks.append(
        make_check(
            "git.unique_input_heads",
            input_heads_are_unique(INPUTS),
            f"heads={len(INPUTS)} unique={len(INPUTS)}",
        )
    )

    s7_delta = changed_paths(
        repo,
        CANDIDATE_MERGE_HEAD,
        S7_CANDIDATE_HEAD,
    )
    s7_scope_violations = path_scope_violations(
        s7_delta,
        S7_ALLOWED_PREFIXES,
    )

    if validation_phase is ValidationPhase.S7_CANDIDATE:
        checks.extend(
            (
                make_check(
                    "git.candidate_ancestor",
                    commit_is_ancestor(
                        repo,
                        CANDIDATE_MERGE_HEAD,
                        S7_CANDIDATE_HEAD,
                    ),
                    f"candidate={CANDIDATE_MERGE_HEAD}",
                ),
                make_check(
                    "git.s7_delta_scope",
                    not s7_scope_violations,
                    (
                        "post-candidate committed paths are S7-owned; "
                        f"violations={s7_scope_violations or 'none'}"
                    ),
                ),
                check_merge_topology(repo),
            )
        )
    else:
        final_changes = changed_path_statuses(
            repo,
            S7_CANDIDATE_HEAD,
            verified_head,
        )
        final_gitignore = run_git(
            repo,
            "show",
            f"{verified_head}:.gitignore",
        )
        final_violations = final_scope_violations(
            final_changes,
            final_gitignore,
        )
        protected_identities, protected_mismatches = compare_revision_paths(
            repo,
            S7_CANDIDATE_HEAD,
            verified_head,
            FINAL_PROTECTED_PATHS,
        )
        s7_contract_tree = revision_object_id(
            repo,
            S7_CANDIDATE_HEAD,
            "contracts",
        )
        final_contract_tree = revision_object_id(
            repo,
            verified_head,
            "contracts",
        )
        s7_lock_blob = revision_object_id(
            repo,
            S7_CANDIDATE_HEAD,
            "uv.lock",
        )
        final_lock_blob = revision_object_id(
            repo,
            verified_head,
            "uv.lock",
        )
        s7_migration_tree = revision_object_id(
            repo,
            S7_CANDIDATE_HEAD,
            "migrations",
        )
        final_migration_tree = revision_object_id(
            repo,
            verified_head,
            "migrations",
        )
        input_ancestry = {
            role: commit_is_ancestor(
                repo,
                str(specification["head"]),
                verified_head,
            )
            for role, specification in INPUTS.items()
        }
        idea_cleanup = sorted(
            path
            for status, path in final_changes
            if status == "D" and path.replace("\\", "/").startswith(".idea/")
        )
        checks.extend(
            (
                make_check(
                    "git.s7_head_ancestor",
                    commit_is_ancestor(
                        repo,
                        S7_CANDIDATE_HEAD,
                        verified_head,
                    ),
                    (
                        f"s7_head={S7_CANDIDATE_HEAD} "
                        f"final_head={verified_head}"
                    ),
                ),
                make_check(
                    "git.s1_final_delta_scope",
                    not final_violations,
                    (
                        "final delta is S1-owned or explicitly allowed; "
                        f"violations={final_violations or 'none'}"
                    ),
                ),
                make_check(
                    "git.s7_delta_scope",
                    not s7_scope_violations,
                    (
                        "candidate-to-S7 delta is S7-owned; "
                        f"violations={s7_scope_violations or 'none'}"
                    ),
                ),
                make_check(
                    "git.final_product_tree",
                    not protected_mismatches,
                    (
                        "protected product paths unchanged; "
                        f"mismatches={protected_mismatches or 'none'}"
                    ),
                ),
                make_check(
                    "contract.final_tree",
                    s7_contract_tree == final_contract_tree == CONTRACT_TREE,
                    (
                        f"s7={s7_contract_tree} "
                        f"final={final_contract_tree}"
                    ),
                ),
                make_check(
                    "git.final_input_heads",
                    all(input_ancestry.values()),
                    f"ancestry={input_ancestry}",
                ),
                make_check(
                    "workspace.final_lock_blob",
                    s7_lock_blob == final_lock_blob,
                    f"s7={s7_lock_blob} final={final_lock_blob}",
                ),
                make_check(
                    "migrations.final_tree",
                    s7_migration_tree == final_migration_tree,
                    (
                        f"s7={s7_migration_tree} "
                        f"final={final_migration_tree}"
                    ),
                ),
                check_merge_topology(repo),
            )
        )
        final_record = {
            "target_head": verified_head,
            "s7_candidate_head": S7_CANDIDATE_HEAD,
            "delta": [
                {"status": status, "path": path}
                for status, path in final_changes
            ],
            "delta_scope_violations": final_violations,
            "ignored_metadata_deletions": idea_cleanup,
            "input_head_ancestry": input_ancestry,
            "protected_path_identities": protected_identities,
            "protected_path_mismatches": protected_mismatches,
            "contract_tree": {
                "s7_candidate": s7_contract_tree,
                "final": final_contract_tree,
            },
            "lock_blob": {
                "s7_candidate": s7_lock_blob,
                "final": final_lock_blob,
            },
            "migration_tree": {
                "s7_candidate": s7_migration_tree,
                "final": final_migration_tree,
            },
        }

    inputs: dict[str, Any] = {}
    full_input_paths: dict[str, set[str]] = {}
    for role, specification in INPUTS.items():
        record, input_checks = verify_input(repo, role, specification)
        inputs[role] = record
        checks.extend(input_checks)
        full_input_paths[role] = set(
            changed_paths(repo, COMMON_MERGE_BASE, specification["head"])
        )

    contract_manifest = load_json(repo / "contracts/contract-set.v1.json")
    recomputed_contract_digest = contract_content_digest(contract_manifest)
    base_contract_tree = run_git(
        repo,
        "rev-parse",
        f"{BASE_COMMIT}:contracts",
    )
    checks.extend(
        (
            make_check(
                "contract.content_digest",
                recomputed_contract_digest == CONTRACT_DIGEST
                and contract_manifest["content_digest"] == CONTRACT_DIGEST,
                f"recomputed={recomputed_contract_digest}",
            ),
            make_check(
                "contract.base_tree",
                base_contract_tree == CONTRACT_TREE,
                f"tree={base_contract_tree}",
            ),
        )
    )

    workspace, workspace_checks = verify_workspace(repo)
    dependencies, dependency_checks = verify_code_dependencies(repo)
    migrations, migration_checks = verify_migrations(repo)
    integration, integration_checks = verify_atomic_integration(
        repo,
        full_input_paths,
    )
    checks.extend(workspace_checks)
    checks.extend(dependency_checks)
    checks.extend(migration_checks)
    checks.extend(integration_checks)

    failed = [item.check_id for item in checks if item.outcome != "PASS"]
    manifest: dict[str, Any] = {
        "schema": "flowpilot.integration-composition-manifest.v1",
        "work_package": "WP-040",
        "attempt_id": "WP-040-a1",
        "chain_id": "CHAIN-WP040-A0-REMEDIATION-01",
        "execution_mode": "ORDERED",
        "risk_class": "R2",
        "base_commit": BASE_COMMIT,
        "control_head_at_authorization": CONTROL_HEAD,
        "candidate_merge_head": CANDIDATE_MERGE_HEAD,
        "branch": branch,
        "contract": {
            "declared_content_digest": contract_manifest["content_digest"],
            "recomputed_content_digest": recomputed_contract_digest,
            "digest_profile": contract_manifest["digest_profile"],
            "contract_tree": base_contract_tree,
        },
        "inputs": inputs,
        "workspace": workspace,
        "dependencies": dependencies,
        "migrations": migrations,
        "integration": integration,
        "checks": [asdict(item) for item in checks],
        "summary": {
            "check_count": len(checks),
            "failed_check_count": len(failed),
            "failed_checks": failed,
            "verdict": "PASS" if not failed else "FAIL",
        },
    }
    if validation_phase is ValidationPhase.S1_FINAL:
        manifest.update(
            {
                "attempt_id": "WP-040-a2",
                "risk_class": "R1",
                "base_commit": S7_CANDIDATE_HEAD,
                "validation_phase": validation_phase.value,
                "final": final_record,
            }
        )
    return manifest


def canonical_manifest_bytes(manifest: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def render_report(manifest: dict[str, Any]) -> str:
    summary = manifest["summary"]
    final_phase = (
        manifest.get("validation_phase") == ValidationPhase.S1_FINAL.value
    )
    title = (
        "# WP-040-a2 S1 Final Evidence Reproduction Report"
        if final_phase
        else "# WP-040-a1 Evidence Reproduction Report"
    )
    lines = [title, ""]
    if final_phase:
        lines.extend(
            (
                f"- Validation phase: `{manifest['validation_phase']}`",
                f"- Final target head: `{manifest['final']['target_head']}`",
            )
        )
    lines.extend(
        (
        f"- Verdict: `{summary['verdict']}`",
        f"- Static checks: `{summary['check_count']}`",
        f"- Failed checks: `{summary['failed_check_count']}`",
        f"- Candidate merge head: `{manifest['candidate_merge_head']}`",
        (
            "- Contract digest: "
            f"`{manifest['contract']['recomputed_content_digest']}`"
        ),
        (
            "- Lock digest: "
            f"`{manifest['workspace']['lock_sha256']}`"
        ),
        (
            "- Migration head: "
            f"`{manifest['migrations']['head']}`"
        ),
        (
            "- Recommended mainline mode: "
            f"`{manifest['integration']['recommended_mainline_mode']}`"
        ),
        "",
        "## Static checks",
        "",
        "| Check | Outcome | Evidence |",
        "|---|---|---|",
        )
    )
    for check in manifest["checks"]:
        evidence = check["evidence"].replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| `{check['check_id']}` | {check['outcome']} | {evidence} |"
        )
    lines.extend(
        (
            "",
            "## Evidence boundary",
            "",
            (
                "This deterministic report covers Git identity, input scope, "
                "handoff hashes, ContractSet digest, package closure, code "
                "dependency direction, and migration identity."
            ),
            (
                "Runtime tests, wheel installation, vulnerability scan, real "
                "Compose, PostgreSQL, and Redis recovery are command evidence "
                "and remain recorded in the S7 handoff."
            ),
            "",
        )
    )
    return "\n".join(lines)


def write_artifacts(
    manifest: dict[str, Any],
    output_dir: Path,
) -> tuple[Path, Path, str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "composition-manifest.json"
    report_path = output_dir / "evidence-report.md"
    manifest_bytes = canonical_manifest_bytes(manifest)
    report_bytes = render_report(manifest).encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)
    report_path.write_bytes(report_bytes)
    return (
        manifest_path,
        report_path,
        f"sha256:{sha256_bytes(manifest_bytes)}",
        f"sha256:{sha256_bytes(report_bytes)}",
    )


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify the WP-040 candidate or S1 final integration",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="write deterministic manifest and report to this directory",
    )
    parser.add_argument(
        "--phase",
        choices=[phase.value for phase in ValidationPhase],
        default=ValidationPhase.S7_CANDIDATE.value,
        help="validation phase; defaults to the backward-compatible candidate",
    )
    parser.add_argument(
        "--target-head",
        help="S1 final revision; defaults to the selected repository HEAD",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    manifest = build_manifest(
        args.repo,
        phase=args.phase,
        target_head=args.target_head,
    )
    prefix = (
        "WP040_S1_FINAL"
        if args.phase == ValidationPhase.S1_FINAL.value
        else "WP040_COMPOSITION"
    )
    print(
        f"{prefix}_{manifest['summary']['verdict']} "
        f"checks={manifest['summary']['check_count']} "
        f"failed={manifest['summary']['failed_check_count']}"
    )
    if args.output_dir is not None:
        manifest_path, report_path, manifest_hash, report_hash = (
            write_artifacts(manifest, args.output_dir)
        )
        print(f"MANIFEST={manifest_path} {manifest_hash}")
        print(f"REPORT={report_path} {report_hash}")
    return 0 if manifest["summary"]["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
