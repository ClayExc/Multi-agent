"""Independently verify the WP-093 engineering-control composition evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
INPUT_HEAD = "80eba3066bc7dfe3ed91985343881b89d280ac17"
CONTROL_BASE = "46b98605af898cf0631b4e6dd29b853d6c1d397a"
CONTRACT_DIGEST = (
    "sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2"
)
HANDOFF_SHA256 = "86f0ef5757bd3cea2a414cc9070c8a22330b523fc2094d59be8159c2f8c21f77"
UPSTREAM_PROOF_SHA256 = (
    "d512cffd08bf6d6bd3f94028e23694e2a08fcbf00e684c847c3a337f827a150c"
)


@dataclass(frozen=True, slots=True)
class VerificationResult:
    input_head: str
    contract_digest: str
    declared_cases: int
    passed_cases: int
    failed_cases: int
    skipped_cases: int
    unique_cases: int
    mutation_cases: int
    mutation_omissions: int
    initial_read_files: int
    repository_files: int
    initial_read_bytes: int
    repository_bytes: int
    ratio_basis_points: int
    cache_fail_closed_cases: int
    report_fail_closed_cases: int
    deterministic_outputs: int
    product_path_violations: int
    protected_tree_changes: int
    lock_workspace_complete: bool


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode()


def _cli(repository: Path, *args: str) -> bytes:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "flowpilot_engineering_control",
            "--repo",
            str(repository),
            *args,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr.decode("utf-8", errors="replace"))
    return result.stdout


def _verify_upstream_proof(
    proof: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    claimed = proof["proof_sha256"]
    payload = {key: value for key, value in proof.items() if key != "proof_sha256"}
    if hashlib.sha256(_canonical(payload)).hexdigest() != claimed:
        raise AssertionError("upstream Proof internal digest is invalid")
    cases = proof["cases"]
    if not isinstance(cases, list) or len(cases) != 28:
        raise AssertionError("upstream Proof denominator changed")
    typed_cases = [item for item in cases if isinstance(item, dict)]
    identifiers = [str(item.get("case_id")) for item in typed_cases]
    if len(typed_cases) != 28 or len(set(identifiers)) != 28:
        raise AssertionError("upstream Proof contains duplicate or invalid cases")
    if (
        proof["all_declared_cases"],
        proof["passed"],
        proof["failed"],
        proof["skipped"],
        proof["gate"],
    ) != (28, 28, 0, 0, "PASS"):
        raise AssertionError("upstream Proof summary is not 28/28 PASS")
    if any(item.get("status") != "PASSED" for item in typed_cases):
        raise AssertionError("upstream Proof contains a non-passing case")
    return payload, typed_cases


def _verify_mutations(cases: list[dict[str, Any]]) -> int:
    mutations = [item for item in cases if str(item["case_id"]).startswith("mutation/")]
    if len(mutations) != 12:
        raise AssertionError("Mutation Matrix denominator changed")
    for item in mutations:
        if item["case_id"] == "mutation/unknown-tracked-path":
            if item.get("observed_error") != "ENG_UNKNOWN_PATH":
                raise AssertionError("unknown path did not fail closed")
        elif not item.get("observed_tier"):
            raise AssertionError("mutation omitted its selected tier")
        if (
            item.get("observed_tier") != "FULL"
            and item["case_id"] != "mutation/unknown-tracked-path"
            and not item.get("observed_commands")
        ):
            raise AssertionError("mutation selected no commands")
    return len(mutations)


def _verify_protection() -> tuple[int, int, bool]:
    if _git("rev-parse", "HEAD") != INPUT_HEAD:
        raise AssertionError("verification must run at the exact input Head")
    protected = ("contracts", "migrations", "apps")
    changed_trees = sum(
        _git("rev-parse", f"{CONTROL_BASE}:{path}")
        != _git("rev-parse", f"{INPUT_HEAD}:{path}")
        for path in protected
    )
    changed_product = _git(
        "diff", "--name-only", f"{CONTROL_BASE}..{INPUT_HEAD}", "--", "apps", "packages"
    ).splitlines()
    violations = sum(
        not path.startswith("packages/engineering-control/") for path in changed_product
    )
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    workspace_complete = (
        '"packages/engineering-control"' in pyproject
        and "flowpilot-engineering-control = { workspace = true }" in pyproject
        and 'name = "flowpilot-engineering-control"' in lock
    )
    return violations, changed_trees, workspace_complete


def verify() -> VerificationResult:
    handoff = (
        ROOT / "tests/acceptance/engineering_control/evidence/WP-093-a1-HANDOFF.md"
    )
    proof_path = ROOT / "artifacts/acceptance/engineering-control/WP-093-a1-PROOF.json"
    if (
        _sha256(handoff) != HANDOFF_SHA256
        or _sha256(proof_path) != UPSTREAM_PROOF_SHA256
    ):
        raise AssertionError("upstream Handoff or Proof hash mismatch")
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    _, cases = _verify_upstream_proof(proof)
    mutation_count = _verify_mutations(cases)
    efficiency = next(
        item
        for item in cases
        if item["case_id"] == "efficiency/initial-read-under-20-percent"
    )
    if (
        efficiency["ratio_basis_points"] != 45
        or efficiency["ratio_basis_points"] >= 2_000
    ):
        raise AssertionError("initial-read efficiency claim is invalid")

    common = (
        "--base",
        INPUT_HEAD,
        "--target",
        INPUT_HEAD,
        "--owner",
        "S7-INTEGRATION",
        "--work-package",
        "WP-094",
        "--attempt",
        "WP-094-a1",
        "--risk",
        "R2",
        "--contract-digest",
        CONTRACT_DIGEST,
        "--write-scope",
        "packages/engineering-control/**",
        "--write-scope",
        "tests/core/**",
        "--write-scope",
        "tests/acceptance/**",
        "--write-scope",
        "artifacts/acceptance/**",
        "--write-scope",
        "pyproject.toml",
        "--write-scope",
        "uv.lock",
        "--write-scope",
        "Makefile",
        "--write-scope",
        ".gitignore",
    )
    with tempfile.TemporaryDirectory(prefix="flowpilot-wp094-") as temporary:
        repository = Path(temporary) / "repository"
        subprocess.run(
            ["git", "clone", "--shared", "--no-checkout", str(ROOT), str(repository)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "checkout", "--detach", INPUT_HEAD],
            cwd=repository,
            check=True,
            capture_output=True,
        )
        map_one, map_two = (
            _cli(repository, "map", "build"),
            _cli(repository, "map", "build"),
        )
        capsule_one = _cli(repository, "capsule", "build", *common)
        capsule_two = _cli(repository, "capsule", "build", *common)
        selection_one = _cli(
            repository,
            "tests",
            "select",
            *common,
            "--signal",
            "public_signature_change",
        )
        selection_two = _cli(
            repository,
            "tests",
            "select",
            *common,
            "--signal",
            "public_signature_change",
        )
    if (map_one, capsule_one, selection_one) != (map_two, capsule_two, selection_two):
        raise AssertionError("engineering-control outputs are not byte deterministic")
    selected = json.loads(selection_one)
    if not selected.get("commands"):
        raise AssertionError("representative selection omitted all commands")

    cache_cases = [item for item in cases if str(item["case_id"]).startswith("cache/")]
    report_cases = [
        item for item in cases if str(item["case_id"]).startswith("report/")
    ]
    violations, tree_changes, workspace_complete = _verify_protection()
    return VerificationResult(
        input_head=INPUT_HEAD,
        contract_digest=CONTRACT_DIGEST,
        declared_cases=28,
        passed_cases=28,
        failed_cases=0,
        skipped_cases=0,
        unique_cases=28,
        mutation_cases=mutation_count,
        mutation_omissions=0,
        initial_read_files=int(efficiency["initial_read_files"]),
        repository_files=int(efficiency["full_repository_files"]),
        initial_read_bytes=int(efficiency["initial_read_bytes"]),
        repository_bytes=int(efficiency["full_repository_bytes"]),
        ratio_basis_points=int(efficiency["ratio_basis_points"]),
        cache_fail_closed_cases=len(cache_cases),
        report_fail_closed_cases=len(report_cases),
        deterministic_outputs=3,
        product_path_violations=violations,
        protected_tree_changes=tree_changes,
        lock_workspace_complete=workspace_complete,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(_canonical(asdict(result)))
    print(
        "ENGINEERING_CONTROL_INTEGRATION_OK "
        f"cases={result.passed_cases}/{result.declared_cases} "
        f"ratio_basis_points={result.ratio_basis_points} "
        f"mutation_omissions={result.mutation_omissions} "
        f"product_violations={result.product_path_violations}"
    )


if __name__ == "__main__":
    main()
