"""Reproduce the M9 fixed-denominator composition from a committed S7 candidate."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]

INPUT_HEAD = "f0b9c529e6408dd8faa53a734bb4e8dcb3844864"
HISTORICAL_CANDIDATE_HEAD = "59f898ab8b24eb08ef5df7fc74eeeed39ea8b88b"
CONTRACT_DIGEST = (
    "sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2"
)
HANDOFF_SHA256 = "8ba0f2a26b8efb089040222482b1b5bf316fd2ca527597d626b1ac197fc7eba6"
UPSTREAM_PROOF_SHA256 = (
    "25caef1b05cfee84741fc6f93ceaa0e3e4ea534750c99b8f17647b37bee5f469"
)
AUTHORIZED_CANDIDATE_PATHS = frozenset(
    {
        "scripts/integration/verify_m9_composition.py",
        "tests/integration/m9/test_wp109_composition.py",
        "tests/integration/evidence/WP-109-a1-HANDOFF.md",
        "tests/integration/evidence/WP-109-a1-PROOF.json",
    }
)
EXPECTED_INPUT_OBJECTS = {
    "contracts": "8eab44bfe8436d7d5ba9f4be4854af8e207adb52",
    "migrations": "575fdc77c98ce110096396a3e5e453bb8fae1983",
    "uv.lock": "4f95ab10d47bf3f98c61472e7842313e927d850f",
    "infra/opa/bundle": "1dfdbfc226a0cc45c8aa1ae62b1a205e3582d53f",
    "apps": "92d7e0b69c1ebe0847c56b92c8bef9c81ceb941d",
    "packages": "60adfc8283f50057065937a259829d6915598508",
}
EXPECTED_EXECUTORS = (
    ("flowpilot.m7.enterprise-knowledge", "1.0.0", 24),
    ("flowpilot.m8.identity-tenancy", "1.0.0", 6),
    ("flowpilot.m9.governance-security", "1.0.0", 9),
)
_ORACLE_MARKER = "WP109_HISTORICAL_ORACLE="
_ORACLE_SOURCE = r"""
import dataclasses
import importlib.util
import json
import pathlib
import sys

root = pathlib.Path.cwd()
path = root / "scripts/integration/verify_m9_composition.py"
spec = importlib.util.spec_from_file_location("wp109_historical", path)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
module._validate_upstream = lambda: {}
module._validate_candidate = lambda: (0, 0)
cases = module.collect_cases()
collection_errors = module.verify_collection(cases)
registry, executors = module.build_product_executors()
statuses = []
execution_states = []
dangerous_output_count = 0
cross_tenant_success_count = 0
judge_scores_used = 0
with module.tempfile.TemporaryDirectory(prefix="flowpilot-wp109-oracle-") as temporary:
    evidence_root = pathlib.Path(temporary)
    validator = module.OfflineRepositoryValidator(root)
    for case in cases:
        result, execution, _findings, skip_reason = module.evaluate_case(
            validator,
            case,
            executors=registry,
            evidence_root=evidence_root,
            judge_calibrated=False,
        )
        if skip_reason is not None:
            raise AssertionError("historical Case was unexpectedly skipped")
        statuses.append(result.status)
        execution_states.append(execution.state)
        judge_scores_used += len(execution.judge_scores)
        if (
            execution.state is module.ExecutionState.COMPLETED
            and execution.evidence_refs
        ):
            evidence = module.load_json_strict(
                evidence_root / execution.evidence_refs[0]
            )
            dangerous_output_count += int(evidence.get("dangerous_output_count", 0))
            cross_tenant_success_count += int(
                evidence.get("cross_tenant_success_count", 0)
            )
payload = {
    "result": {
        "declared_cases": len(cases),
        "unique_case_ids": len({str(case["case_id"]) for case in cases}),
        "collection_errors": len(collection_errors),
        "completed": execution_states.count(module.ExecutionState.COMPLETED),
        "explicit_failed": execution_states.count(module.ExecutionState.NOT_EXECUTED),
        "skipped": statuses.count(module.CaseStatus.SKIPPED),
        "quarantined": statuses.count(module.CaseStatus.QUARANTINED),
        "passed": statuses.count(module.CaseStatus.PASSED),
        "failed": statuses.count(module.CaseStatus.FAILED),
        "duplicate_matches": sum(
            sum(executor.supports(case) for executor in executors) > 1
            for case in cases
        ),
        "dangerous_output_count": dangerous_output_count,
        "cross_tenant_success_count": cross_tenant_success_count,
        "judge_scores_used": judge_scores_used,
        "manifest_gate": "FAIL",
        "release_claimed": False,
        "frozen_claimed": False,
    },
    "registration": module.executor_registration(executors),
}
print("WP109_HISTORICAL_ORACLE=" + json.dumps(payload, sort_keys=True))
"""


@dataclass(frozen=True, slots=True)
class CompositionResult:
    input_head: str
    contract_digest: str
    declared_cases: int
    unique_case_ids: int
    collection_errors: int
    completed: int
    explicit_failed: int
    skipped: int
    quarantined: int
    m7_supported: int
    m8_supported: int
    m9_supported: int
    duplicate_matches: int
    dangerous_output_count: int
    cross_tenant_success_count: int
    judge_scores_used: int
    manifest_gate: str
    release_claimed: bool
    frozen_claimed: bool
    candidate_scope_violations: int
    protected_object_changes: int


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    return (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=ROOT,
            check=False,
            capture_output=True,
        ).returncode
        == 0
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _revision_bytes(revision: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{revision}:{path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout


def _load_revision_json(revision: str, path: str) -> dict[str, Any]:
    value = json.loads(_revision_bytes(revision, path))
    if not isinstance(value, dict):
        raise AssertionError("historical JSON root is not an object")
    return cast(dict[str, Any], value)


def _run_historical_oracle() -> dict[str, Any]:
    archive = subprocess.run(
        ["git", "archive", "--format=tar", HISTORICAL_CANDIDATE_HEAD],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    with tempfile.TemporaryDirectory(prefix="flowpilot-wp109-history-") as temporary:
        snapshot = Path(temporary)
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
            bundle.extractall(snapshot, filter="data")
        completed = subprocess.run(
            [sys.executable, "-c", _ORACLE_SOURCE],
            cwd=snapshot,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise AssertionError(
                "historical M9 oracle failed: "
                + completed.stderr.strip().splitlines()[-1]
            )
    line = next(
        (
            item
            for item in completed.stdout.splitlines()
            if item.startswith(_ORACLE_MARKER)
        ),
        None,
    )
    if line is None:
        raise AssertionError("historical M9 oracle returned no result")
    value = json.loads(line.removeprefix(_ORACLE_MARKER))
    if not isinstance(value, dict):
        raise AssertionError("historical M9 oracle result is invalid")
    return cast(dict[str, Any], value)


def _validate_historical_oracle(oracle: dict[str, Any]) -> dict[str, Any]:
    result = cast(dict[str, Any], oracle.get("result"))
    registration = cast(dict[str, Any], oracle.get("registration"))
    executors = registration.get("executors")
    if not isinstance(executors, list):
        raise AssertionError("historical executor registry is invalid")
    identities = tuple(
        (
            item.get("executor_id"),
            item.get("executor_version"),
            item.get("supported_case_count"),
        )
        for item in executors
        if isinstance(item, dict)
    )
    if (
        registration.get("schema") != "flowpilot.product-executor-registry.v1"
        or registration.get("match_policy") != "unique_exact_case_digest"
        or registration.get("executor_count") != 3
        or identities != EXPECTED_EXECUTORS
    ):
        raise AssertionError("product executor registry identity drifted")
    expected = {
        "declared_cases": 156,
        "unique_case_ids": 156,
        "collection_errors": 0,
        "completed": 39,
        "explicit_failed": 117,
        "skipped": 0,
        "quarantined": 0,
        "duplicate_matches": 0,
        "dangerous_output_count": 0,
        "cross_tenant_success_count": 0,
        "judge_scores_used": 0,
        "manifest_gate": "FAIL",
        "release_claimed": False,
        "frozen_claimed": False,
    }
    if any(result.get(key) != value for key, value in expected.items()):
        raise AssertionError("historical M9 execution oracle drifted")
    return result


def _validate_candidate(
    candidate: str = HISTORICAL_CANDIDATE_HEAD,
) -> tuple[int, int]:
    if not _is_ancestor(INPUT_HEAD, candidate):
        raise AssertionError("M9 input Head is not an ancestor of the candidate")
    paths = set(_git("diff", "--name-only", f"{INPUT_HEAD}..{candidate}").splitlines())
    violations = paths - AUTHORIZED_CANDIDATE_PATHS
    if violations:
        raise AssertionError("candidate contains an unauthorized WP-109 path")
    changed = 0
    for path, expected in EXPECTED_INPUT_OBJECTS.items():
        if _git("rev-parse", f"{INPUT_HEAD}:{path}") != expected:
            raise AssertionError("M9 protected input object drifted")
        if _git("rev-parse", f"{candidate}:{path}") != expected:
            changed += 1
    if changed:
        raise AssertionError("S7 candidate rewrote an M9 protected object")
    return len(violations), changed


def _validate_upstream() -> dict[str, Any]:
    handoff_path = "tests/acceptance/m9/evidence/WP-108-a1-HANDOFF.md"
    proof_path = "tests/acceptance/m9/evidence/WP-108-a1-PROOF.json"
    handoff = _revision_bytes(HISTORICAL_CANDIDATE_HEAD, handoff_path)
    proof_bytes = _revision_bytes(HISTORICAL_CANDIDATE_HEAD, proof_path)
    if (
        hashlib.sha256(handoff).hexdigest() != HANDOFF_SHA256
        or hashlib.sha256(proof_bytes).hexdigest() != UPSTREAM_PROOF_SHA256
    ):
        raise AssertionError("WP-108 Handoff or Proof hash mismatch")
    proof = _load_revision_json(HISTORICAL_CANDIDATE_HEAD, proof_path)
    counts = proof["fixed_denominator"]
    if (
        counts["declared_cases"],
        counts["completed"],
        counts["explicit_failed"],
        counts["skipped"],
        counts["quarantined"],
        counts["gate"],
    ) != (156, 39, 117, 0, 0, "fail"):
        raise AssertionError("WP-108 fixed denominator claim drifted")
    if proof["release_claimed"] is not False:
        raise AssertionError("WP-108 made an unauthorized release claim")
    return cast(dict[str, Any], proof)


def verify() -> CompositionResult:
    _validate_upstream()
    scope_violations, protected_changes = _validate_candidate()
    historical = _validate_historical_oracle(_run_historical_oracle())

    return CompositionResult(
        input_head=INPUT_HEAD,
        contract_digest=CONTRACT_DIGEST,
        declared_cases=156,
        unique_case_ids=int(historical["unique_case_ids"]),
        collection_errors=int(historical["collection_errors"]),
        completed=int(historical["completed"]),
        explicit_failed=int(historical["explicit_failed"]),
        skipped=int(historical["skipped"]),
        quarantined=int(historical["quarantined"]),
        m7_supported=EXPECTED_EXECUTORS[0][2],
        m8_supported=EXPECTED_EXECUTORS[1][2],
        m9_supported=EXPECTED_EXECUTORS[2][2],
        duplicate_matches=int(historical["duplicate_matches"]),
        dangerous_output_count=int(historical["dangerous_output_count"]),
        cross_tenant_success_count=int(historical["cross_tenant_success_count"]),
        judge_scores_used=int(historical["judge_scores_used"]),
        manifest_gate="FAIL",
        release_claimed=False,
        frozen_claimed=False,
        candidate_scope_violations=scope_violations,
        protected_object_changes=protected_changes,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(asdict(result), sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(
        "M9_COMPOSITION_OK "
        f"completed={result.completed} explicit_failed={result.explicit_failed} "
        f"skipped={result.skipped} quarantined={result.quarantined} "
        f"manifest_gate={result.manifest_gate}"
    )


if __name__ == "__main__":
    main()
