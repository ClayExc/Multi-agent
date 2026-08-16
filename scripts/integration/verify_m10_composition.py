"""Fail-closed WP-120 verification of the M10 acceptance composition."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
INPUT_HEAD = "ba725376af0bc8e8b7d118f3b965f35dd542682c"
RUNNER_HEAD = "df2283049d717e62cf16ff6361de5d04ac2e4203"
CONTRACT_DIGEST = (
    "sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2"
)
HANDOFF_SHA256 = "94ecb7832505cb09fd07eb53940d9248af6995e7897adc26d3392eb041033967"
PROOF_SHA256 = "dbd785bd2f493674e9a2a03d38977fd2aa74c67b0adf5aa638264d96fabe1df8"
EXPECTED_EXECUTORS = (
    ("flowpilot.m7.enterprise-knowledge", "1.0.0", 24),
    ("flowpilot.m8.identity-tenancy", "1.0.0", 6),
    ("flowpilot.m9.governance-security", "1.0.0", 9),
    ("flowpilot.m10.knowledge-security", "1.0.0", 1),
)
AUTHORIZED_FINAL_PATHS = frozenset(
    {
        "tests/acceptance/m10/evidence/WP-119-a1-HANDOFF.md",
        "tests/acceptance/m10/evidence/WP-119-a1-PROOF.json",
    }
)
PROTECTED_PATHS = (
    "contracts",
    "migrations",
    "uv.lock",
    "pyproject.toml",
    "infra/compose/compose.yaml",
    "packages/persistence",
    "packages/evaluation",
    "mcp-servers/knowledge",
    "apps/api",
    "apps/worker",
    "web",
)


@dataclass(frozen=True, slots=True)
class Check:
    check_id: str
    passed: bool
    detail: str


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def _sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"JSON root is not an object: {path.name}")
    return cast(dict[str, Any], value)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        cast(dict[str, Any], json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def _revision_sha256(revision: str, path: str) -> str:
    payload = subprocess.run(
        ["git", "show", f"{revision}:{path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def verify_repository() -> list[Check]:
    changed = set(
        _git("diff", "--name-only", f"{RUNNER_HEAD}..{INPUT_HEAD}").splitlines()
    )
    protected_drift = [
        path
        for path in PROTECTED_PATHS
        if _git("rev-parse", f"{RUNNER_HEAD}:{path}")
        != _git("rev-parse", f"{INPUT_HEAD}:{path}")
    ]
    contract = _json(ROOT / "contracts/contract-set.v1.json")
    migrations = sorted((ROOT / "migrations").glob("*.sql"))
    up_names = [path.stem for path in migrations if not path.name.endswith(".down.sql")]
    handoff_path = "tests/acceptance/m10/evidence/WP-119-a1-HANDOFF.md"
    proof_path = "tests/acceptance/m10/evidence/WP-119-a1-PROOF.json"
    return [
        Check(
            "repository.final_delta",
            changed == AUTHORIZED_FINAL_PATHS,
            f"paths={sorted(changed)}",
        ),
        Check(
            "repository.protected_objects",
            not protected_drift,
            f"drift={protected_drift}",
        ),
        Check(
            "contract.digest",
            contract.get("content_digest") == CONTRACT_DIGEST,
            f"digest={contract.get('content_digest')}",
        ),
        Check(
            "migrations.linear_0001_0007",
            len(up_names) == 7
            and up_names[0].startswith("0001_")
            and up_names[-1] == "0007_pgvector_knowledge_index"
            and [name[:4] for name in up_names]
            == [f"{number:04d}" for number in range(1, 8)],
            f"chain={up_names}",
        ),
        Check(
            "upstream.handoff_proof",
            _revision_sha256(INPUT_HEAD, handoff_path)
            == f"sha256:{HANDOFF_SHA256}"
            and _revision_sha256(INPUT_HEAD, proof_path)
            == f"sha256:{PROOF_SHA256}",
            "pinned input revision bytes",
        ),
    ]


def verify_current_registry() -> Check:
    from scripts.acceptance.run_acceptance import (
        build_product_executors,
        collect_cases,
        executor_registration,
        verify_collection,
    )

    cases = collect_cases()
    _registry, executors = build_product_executors()
    registration = executor_registration(executors)
    identities = tuple(
        (
            item["executor_id"],
            item["executor_version"],
            item["supported_case_count"],
        )
        for item in registration["executors"]
    )
    match_counts = [
        sum(executor.supports(case) for executor in executors) for case in cases
    ]
    passed = (
        len(cases) == len({str(case["case_id"]) for case in cases}) == 156
        and not verify_collection(cases)
        and identities == EXPECTED_EXECUTORS
        and registration["match_policy"] == "unique_exact_case_digest"
        and sum(count == 1 for count in match_counts) == 40
        and sum(count == 0 for count in match_counts) == 116
        and max(match_counts) == 1
    )
    return Check(
        "registry.current_recomputation",
        passed,
        f"cases={len(cases)} matched={sum(count == 1 for count in match_counts)}",
    )


def verify_bundle(bundle: Path) -> dict[str, Any]:
    manifest = _json(bundle / "manifest.json")
    aggregate = _json(bundle / "eval/aggregate.json")
    registry = _json(bundle / "eval/executor-registry.json")
    executions = _jsonl(bundle / "eval/execution-results.jsonl")
    failures = _json(bundle / "failures.json")["failures"]
    proof = _json(ROOT / "tests/acceptance/m10/evidence/WP-119-a1-PROOF.json")
    hashes = cast(dict[str, str], manifest["artifact_hashes"])
    mismatches = [
        path
        for path, expected in hashes.items()
        if not (bundle / path).is_file() or _sha256(bundle / path) != expected
    ]
    registrations = cast(list[dict[str, Any]], registry["executors"])
    identities = tuple(
        (
            item["executor_id"],
            item["executor_version"],
            item["supported_case_count"],
        )
        for item in registrations
    )
    completed = [item for item in executions if item["state"] == "completed"]
    not_executed = [item for item in executions if item["state"] == "not_executed"]
    registered_cases = [
        case
        for registration in registrations
        for case in registration["supported_cases"]
    ]
    registered_ids = [case["case_id"] for case in registered_cases]
    checks = verify_repository() + [
        verify_current_registry(),
        Check(
            "bundle.identity",
            manifest["git_commit"] == RUNNER_HEAD
            and manifest["contract_content_digest"] == CONTRACT_DIGEST
            and manifest["dirty_worktree"] is False,
            f"head={manifest['git_commit']}",
        ),
        Check(
            "denominator.fixed",
            aggregate["declared_case_count"] == 156
            and aggregate["result_count"] == 156
            and aggregate["passed"] == 40
            and aggregate["failed"] == 116
            and aggregate["skipped"] == 0
            and aggregate["quarantined"] == 0,
            f"pass={aggregate['passed']} fail={aggregate['failed']}",
        ),
        Check(
            "registry.four_unique",
            registry["match_policy"] == "unique_exact_case_digest"
            and registry["executor_count"] == 4
            and registry["supported_case_count"] == 40
            and identities == EXPECTED_EXECUTORS
            and len(registered_ids) == len(set(registered_ids)) == 40,
            f"identities={identities} unique={len(set(registered_ids))}",
        ),
        Check(
            "execution.closed",
            len(executions) == 156
            and len(completed) == 40
            and len(not_executed) == 116
            and len(failures) == 116
            and all(item["failure_code"] is None for item in completed)
            and all(
                item["failure_code"] == "EXECUTOR_NOT_REGISTERED"
                and item["executor_id"] == "none"
                for item in not_executed
            ),
            f"completed={len(completed)} not_executed={len(not_executed)}",
        ),
        Check(
            "artifacts.hash_closure",
            len(hashes) == 55 and not mismatches,
            f"hashes={len(hashes)} mismatches={mismatches}",
        ),
        Check(
            "engineering.six_gates",
            len(manifest["gate_checks"]) == 6
            and all(item["passed"] is True for item in manifest["gate_checks"]),
            "passed="
            f"{sum(item['passed'] is True for item in manifest['gate_checks'])}/6",
        ),
        Check(
            "manifest.release_blocked",
            manifest["gate_result"] == "fail"
            and aggregate["gate_result"] == "fail"
            and proof["release_claimed"] is False
            and proof["frozen_claimed"] is False,
            f"gate={manifest['gate_result']}",
        ),
        Check(
            "m10.safety_observation",
            all(
                proof["m10_observation"][field] == 0
                for field in (
                    "cross_tenant_success_count",
                    "expired_candidate_read_count",
                    "low_relevance_returned_count",
                    "dangerous_output_count",
                    "judge_scores_used",
                )
            )
            and proof["m10_observation"]["malicious_document_rejected"] is True
            and proof["m10_observation"]["citation_drift_rejected"] is True,
            "zero security counters and deterministic rejection",
        ),
    ]
    failed = [check.check_id for check in checks if not check.passed]
    return {
        "schema": "flowpilot.wp120-composition-proof.v1",
        "input_head": INPUT_HEAD,
        "runner_head": RUNNER_HEAD,
        "contract_content_digest": CONTRACT_DIGEST,
        "checks": [asdict(check) for check in checks],
        "summary": {
            "verdict": "PASS" if not failed else "FAIL",
            "failed_checks": failed,
            "declared": 156,
            "completed": 40,
            "explicit_failed": 116,
            "skipped": 0,
            "quarantined": 0,
            "artifact_hashes": len(hashes),
            "manifest_gate": "fail",
            "release_claimed": False,
            "frozen_claimed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = verify_bundle(args.bundle.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(report["summary"], sort_keys=True))
    return 0 if report["summary"]["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
