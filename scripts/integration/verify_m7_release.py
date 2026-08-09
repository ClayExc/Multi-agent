"""Fail-closed verification for the M7 fixed-denominator acceptance bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

INPUT_HEAD = "b8a18af3afa5a84bf6b16fcaae259805599c7c42"
CONTRACT_DIGEST = (
    "sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2"
)
DECLARED = 156
PASSED = 24
FAILED = 132
ARTIFACT_HASH_COUNT = 39
EXECUTOR_ID = "flowpilot.m7.enterprise-knowledge"
EXECUTOR_VERSION = "1.0.0"


@dataclass(frozen=True)
class Check:
    check_id: str
    passed: bool
    detail: str


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def verify_bundle(bundle: Path) -> dict[str, Any]:
    manifest = _json(bundle / "manifest.json")
    aggregate = _json(bundle / "eval/aggregate.json")
    registry = _json(bundle / "eval/executor-registry.json")
    executions = _jsonl(bundle / "eval/execution-results.jsonl")
    failures = _json(bundle / "failures.json")["failures"]
    hashes: dict[str, str] = manifest["artifact_hashes"]

    supported_ids = [f"m6a.func.kq.{index:03d}" for index in range(1, PASSED + 1)]
    registered = registry["supported_cases"]
    registered_ids = [item["case_id"] for item in registered]
    registered_digests = [item["case_input_digest"] for item in registered]
    completed = [item for item in executions if item["state"] == "completed"]
    unimplemented = [item for item in executions if item["state"] == "not_executed"]

    artifact_mismatches = [
        path
        for path, expected in hashes.items()
        if not (bundle / path).is_file() or _sha256(bundle / path) != expected
    ]
    case_evidence = [
        _json(bundle / f"execution/cases/{case_id}.json") for case_id in supported_ids
    ]
    safety_fields = (
        "cross_tenant_success_count",
        "provider_session_exposure_count",
        "request_content_durable_exposure_count",
        "restart_replay_model_delta",
        "restart_replay_tool_delta",
    )

    checks = [
        Check(
            "manifest.identity",
            manifest["git_commit"] == INPUT_HEAD
            and manifest["contract_content_digest"] == CONTRACT_DIGEST
            and manifest["dirty_worktree"] is False,
            f"head={manifest['git_commit']}",
        ),
        Check(
            "denominator.fixed",
            aggregate["denominator_policy"] == "all_declared_cases"
            and aggregate["declared_case_count"] == DECLARED
            and aggregate["result_count"] == DECLARED
            and aggregate["passed"] == PASSED
            and aggregate["failed"] == FAILED
            and aggregate["failure_count"] == FAILED
            and aggregate["skipped"] == 0
            and aggregate["quarantined"] == 0,
            "results="
            f"{aggregate['result_count']} pass={aggregate['passed']} "
            f"fail={aggregate['failed']}",
        ),
        Check(
            "release.remains_blocked",
            manifest["gate_result"] == "fail"
            and aggregate["gate_result"] == "fail"
            and manifest["report_state"] == "complete",
            f"gate={manifest['gate_result']}",
        ),
        Check(
            "test_suites.pass",
            len(manifest["gate_checks"]) == 6
            and all(item["passed"] is True for item in manifest["gate_checks"]),
            "passed="
            f"{sum(item['passed'] is True for item in manifest['gate_checks'])}/6",
        ),
        Check(
            "executor.exact_cases",
            registry["executor_id"] == EXECUTOR_ID
            and registry["executor_version"] == EXECUTOR_VERSION
            and registry["match_policy"] == "exact_case_digest"
            and registry["supported_case_count"] == PASSED
            and registered_ids == supported_ids
            and len(set(registered_digests)) == PASSED,
            f"registered={len(registered_ids)}",
        ),
        Check(
            "execution.complete",
            len(executions) == DECLARED
            and len(completed) == PASSED
            and len(unimplemented) == FAILED
            and all(
                item["executor_id"] == EXECUTOR_ID
                and item["executor_version"] == EXECUTOR_VERSION
                and item["failure_code"] is None
                and item["judge_scores"] == {}
                for item in completed
            )
            and all(
                item["executor_id"] == "none"
                and item["failure_code"] == "EXECUTOR_NOT_REGISTERED"
                and item["evidence_refs"] == []
                and item["judge_scores"] == {}
                for item in unimplemented
            ),
            f"completed={len(completed)} unimplemented={len(unimplemented)}",
        ),
        Check(
            "failure_closure.explicit",
            len(failures) == FAILED
            and {item["case_id"] for item in failures}
            == {item["case_id"] for item in unimplemented}
            and all(
                any(
                    finding.startswith("EXECUTOR_NOT_REGISTERED:")
                    for finding in item["findings"]
                )
                for item in failures
            ),
            f"failures={len(failures)}",
        ),
        Check(
            "security.zero_and_replay_idle",
            len(case_evidence) == PASSED
            and all(
                evidence[field] == 0
                for evidence in case_evidence
                for field in safety_fields
            ),
            f"case_evidence={len(case_evidence)}",
        ),
        Check(
            "artifacts.hash_closure",
            len(hashes) == ARTIFACT_HASH_COUNT and not artifact_mismatches,
            f"hashes={len(hashes)} mismatches={artifact_mismatches}",
        ),
    ]
    return {
        "verdict": "PASS" if all(check.passed for check in checks) else "FAIL",
        "checks": [check.__dict__ for check in checks],
        "summary": {
            "declared": DECLARED,
            "passed": PASSED,
            "failed": FAILED,
            "skipped": 0,
            "quarantined": 0,
            "artifact_hashes": len(hashes),
            "manifest_gate": manifest["gate_result"],
            "release_claimed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = verify_bundle(args.bundle.resolve())
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8", newline="\n")
    print(payload, end="")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
