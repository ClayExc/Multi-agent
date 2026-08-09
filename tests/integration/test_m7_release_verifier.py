from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.integration.verify_m7_release import (
    CONTRACT_DIGEST,
    INPUT_HEAD,
    verify_bundle,
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _build_bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "bundle"
    supported = [f"m6a.func.kq.{index:03d}" for index in range(1, 25)]
    unsupported = [f"unsupported.{index:03d}" for index in range(1, 133)]
    gate_checks = [
        {"check_id": f"test-suite:{name}", "passed": True}
        for name in ("unit", "contract", "integration", "e2e", "recovery", "security")
    ]
    aggregate = {
        "denominator_policy": "all_declared_cases",
        "declared_case_count": 156,
        "result_count": 156,
        "passed": 24,
        "failed": 132,
        "failure_count": 132,
        "skipped": 0,
        "quarantined": 0,
        "gate_result": "fail",
    }
    registry = {
        "executor_id": "flowpilot.m7.enterprise-knowledge",
        "executor_version": "1.0.0",
        "match_policy": "exact_case_digest",
        "supported_case_count": 24,
        "supported_cases": [
            {"case_id": case_id, "case_input_digest": f"sha256:{index:064x}"}
            for index, case_id in enumerate(supported, start=1)
        ],
    }
    executions: list[dict[str, object]] = []
    executions.extend(
        {
            "case_id": case_id,
            "state": "completed",
            "executor_id": "flowpilot.m7.enterprise-knowledge",
            "executor_version": "1.0.0",
            "failure_code": None,
            "judge_scores": {},
        }
        for case_id in supported
    )
    executions.extend(
        {
            "case_id": case_id,
            "state": "not_executed",
            "executor_id": "none",
            "failure_code": "EXECUTOR_NOT_REGISTERED",
            "evidence_refs": [],
            "judge_scores": {},
        }
        for case_id in unsupported
    )
    failures = {
        "failures": [
            {
                "case_id": case_id,
                "findings": ["EXECUTOR_NOT_REGISTERED: synthetic unsupported case"],
            }
            for case_id in unsupported
        ]
    }
    _write_json(bundle / "eval/aggregate.json", aggregate)
    _write_json(bundle / "eval/executor-registry.json", registry)
    (bundle / "eval/execution-results.jsonl").write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in executions),
        encoding="utf-8",
        newline="\n",
    )
    _write_json(bundle / "failures.json", failures)
    for case_id in supported:
        _write_json(
            bundle / f"execution/cases/{case_id}.json",
            {
                "cross_tenant_success_count": 0,
                "provider_session_exposure_count": 0,
                "request_content_durable_exposure_count": 0,
                "restart_replay_model_delta": 0,
                "restart_replay_tool_delta": 0,
            },
        )
    for path in (
        "REPORT.md",
        "environment.json",
        "eval/case-results.jsonl",
        "eval/verdicts.json",
        "test-results-summary.json",
        "test-results/unit.xml",
        "test-results/contract.xml",
        "test-results/integration.xml",
        "test-results/e2e.xml",
        "test-results/recovery.xml",
        "test-results/security.xml",
    ):
        target = bundle / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("synthetic\n", encoding="utf-8", newline="\n")
    artifacts = [path for path in bundle.rglob("*") if path.is_file()]
    hashes = {
        path.relative_to(
            bundle
        ).as_posix(): f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
        for path in artifacts
    }
    assert len(hashes) == 39
    _write_json(
        bundle / "manifest.json",
        {
            "artifact_hashes": hashes,
            "contract_content_digest": CONTRACT_DIGEST,
            "dirty_worktree": False,
            "gate_checks": gate_checks,
            "gate_result": "fail",
            "git_commit": INPUT_HEAD,
            "report_state": "complete",
        },
    )
    return bundle


def test_m7_release_bundle_reproduces_expected_blocked_gate(tmp_path: Path) -> None:
    report = verify_bundle(_build_bundle(tmp_path))

    assert report["verdict"] == "PASS"
    assert report["summary"] == {
        "declared": 156,
        "passed": 24,
        "failed": 132,
        "skipped": 0,
        "quarantined": 0,
        "artifact_hashes": 39,
        "manifest_gate": "fail",
        "release_claimed": False,
    }


def test_denominator_shrink_fails_closed(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path)
    aggregate_path = bundle / "eval/aggregate.json"
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    aggregate["declared_case_count"] = 24
    _write_json(aggregate_path, aggregate)

    report = verify_bundle(bundle)

    failed = {item["check_id"] for item in report["checks"] if not item["passed"]}
    assert {"denominator.fixed", "artifacts.hash_closure"} <= failed


def test_release_gate_cannot_be_promoted(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path)
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["gate_result"] = "pass"
    _write_json(manifest_path, manifest)

    report = verify_bundle(bundle)

    assert "release.remains_blocked" in {
        item["check_id"] for item in report["checks"] if not item["passed"]
    }


def test_artifact_hash_drift_fails_closed(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path)
    evidence = bundle / "execution/cases/m6a.func.kq.001.json"
    evidence.write_bytes(evidence.read_bytes() + b"\n")

    report = verify_bundle(bundle)

    assert "artifacts.hash_closure" in {
        item["check_id"] for item in report["checks"] if not item["passed"]
    }


def test_positive_security_counter_fails_closed(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path)
    evidence_path = bundle / "execution/cases/m6a.func.kq.001.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["cross_tenant_success_count"] = 1
    _write_json(evidence_path, evidence)

    report = verify_bundle(bundle)

    failed = {item["check_id"] for item in report["checks"] if not item["passed"]}
    assert {"security.zero_and_replay_idle", "artifacts.hash_closure"} <= failed
