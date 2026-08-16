"""Reproduce the M9 fixed-denominator composition from a committed S7 candidate."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from packages.evaluation.canonical import load_json_strict  # noqa: E402
from packages.evaluation.execution import ExecutionState  # noqa: E402
from packages.evaluation.reporting import CaseStatus  # noqa: E402
from packages.evaluation.validation import OfflineRepositoryValidator  # noqa: E402
from scripts.acceptance.run_acceptance import (
    build_product_executors,
    collect_cases,
    evaluate_case,
    executor_registration,
    verify_collection,
)  # noqa: E402

INPUT_HEAD = "f0b9c529e6408dd8faa53a734bb4e8dcb3844864"
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


def _validate_candidate() -> tuple[int, int]:
    candidate = _git("rev-parse", "HEAD")
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
        if _git("rev-parse", f"HEAD:{path}") != expected:
            changed += 1
    if changed:
        raise AssertionError("S7 candidate rewrote an M9 protected object")
    return len(violations), changed


def _validate_upstream() -> dict[str, Any]:
    handoff = ROOT / "tests/acceptance/m9/evidence/WP-108-a1-HANDOFF.md"
    proof_path = ROOT / "tests/acceptance/m9/evidence/WP-108-a1-PROOF.json"
    if (
        _sha256(handoff) != HANDOFF_SHA256
        or _sha256(proof_path) != UPSTREAM_PROOF_SHA256
    ):
        raise AssertionError("WP-108 Handoff or Proof hash mismatch")
    proof = load_json_strict(proof_path)
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
    cases = collect_cases()
    case_ids = [str(case["case_id"]) for case in cases]
    collection_errors = verify_collection(cases)
    if len(cases) != 156 or len(set(case_ids)) != 156 or collection_errors:
        raise AssertionError("official fixed denominator is not unique and complete")

    registry, executors = build_product_executors()
    registration = executor_registration(executors)
    supported = [
        int(item["supported_case_count"]) for item in registration["executors"]
    ]
    if (
        supported != [24, 6, 9]
        or registration["match_policy"] != "unique_exact_case_digest"
    ):
        raise AssertionError("product executor registry identity drifted")
    duplicate_matches = sum(
        sum(executor.supports(case) for executor in executors) > 1 for case in cases
    )
    if duplicate_matches:
        raise AssertionError("a fixed Case matches more than one executor")

    statuses: list[CaseStatus] = []
    execution_states: list[ExecutionState] = []
    dangerous_output_count = 0
    cross_tenant_success_count = 0
    judge_scores_used = 0
    with tempfile.TemporaryDirectory(prefix="flowpilot-wp109-") as temporary:
        evidence_root = Path(temporary)
        validator = OfflineRepositoryValidator(ROOT)
        for case in cases:
            result, execution, _findings, skip_reason = evaluate_case(
                validator,
                case,
                executors=registry,
                evidence_root=evidence_root,
                judge_calibrated=False,
            )
            if skip_reason is not None:
                raise AssertionError("official Case was unexpectedly skipped")
            statuses.append(result.status)
            execution_states.append(execution.state)
            judge_scores_used += len(execution.judge_scores)
            if execution.state is ExecutionState.COMPLETED and execution.evidence_refs:
                evidence = load_json_strict(evidence_root / execution.evidence_refs[0])
                dangerous_output_count += int(evidence.get("dangerous_output_count", 0))
                cross_tenant_success_count += int(
                    evidence.get("cross_tenant_success_count", 0)
                )

    completed = execution_states.count(ExecutionState.COMPLETED)
    explicit_failed = execution_states.count(ExecutionState.NOT_EXECUTED)
    skipped = statuses.count(CaseStatus.SKIPPED)
    quarantined = statuses.count(CaseStatus.QUARANTINED)
    if (completed, explicit_failed, skipped, quarantined) != (39, 117, 0, 0):
        raise AssertionError("official M9 execution denominator drifted")
    if (
        statuses.count(CaseStatus.PASSED) != 39
        or statuses.count(CaseStatus.FAILED) != 117
    ):
        raise AssertionError("official M9 result states drifted")
    if dangerous_output_count or cross_tenant_success_count or judge_scores_used:
        raise AssertionError("M9 safety observation is not fail closed")

    return CompositionResult(
        input_head=INPUT_HEAD,
        contract_digest=CONTRACT_DIGEST,
        declared_cases=156,
        unique_case_ids=len(set(case_ids)),
        collection_errors=len(collection_errors),
        completed=completed,
        explicit_failed=explicit_failed,
        skipped=skipped,
        quarantined=quarantined,
        m7_supported=supported[0],
        m8_supported=supported[1],
        m9_supported=supported[2],
        duplicate_matches=duplicate_matches,
        dangerous_output_count=dangerous_output_count,
        cross_tenant_success_count=cross_tenant_success_count,
        judge_scores_used=judge_scores_used,
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
