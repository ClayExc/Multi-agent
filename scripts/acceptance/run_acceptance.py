"""make acceptance 编排器：一条命令生成机器 Manifest 与人类报告。

流程：
1. 收集 156 候选（A 69 + B 52 + C 35 = 120 功能 + 36 安全），按类型
   （suite × category）枚举校验配额；任一类型缺失/超量 -> 报错退出并留痕
   （collection-errors.json）。
2. 逐候选做确定性静态判定（OfflineRepositoryValidator，0 findings
   -> PASS；否则 FAIL 且保留失败证据；显式 skip 标记 -> SKIPPED），
   结构化判定清单 eval/verdicts.json 落盘（156 候选每项一条记录）。
3. 跑六类测试（unit/contract/integration/e2e/recovery/security）生成
   junit XML 到 test-results/；六类中任一无可用目标目录 -> 报错退出并留痕。
4. 收集 environment.json 与测试结果快照。
5. 组装 acceptance bundle（manifest.json + REPORT.md + eval/），
   manifest.artifact_hashes 与全部产物一一对应。
6. 退出码 = gate_result（0=通过）。

用法：python scripts/acceptance/run_acceptance.py
      [--output artifacts/acceptance/<run_id>]
"""
from __future__ import annotations

import argparse
import datetime
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.evaluation.canonical import (  # noqa: E402
    load_json_strict,
    sha256_file,
    stable_json_bytes,
)
from packages.evaluation.incremental_a import load_cases as load_a  # noqa: E402
from packages.evaluation.incremental_b import load_cases as load_b  # noqa: E402
from packages.evaluation.incremental_c import load_cases as load_c  # noqa: E402
from packages.evaluation.reporting import (  # noqa: E402
    AssertionOutcome,
    CaseResult,
    CaseStatus,
    generate_acceptance_bundle,
)
from packages.evaluation.validation import (  # noqa: E402
    FIXED_SUITE_QUOTAS,
    OfflineRepositoryValidator,
)

# 六类测试：名称 -> 候选目标目录（运行时只跑实际存在的目录；
# 某一类全部目录缺失视为“类型缺失”，报错退出并留痕）。
TEST_SUITES = {
    "unit": "tests/core tests/runtime/unit tests/experience",
    "contract": (
        "tests/runtime/contract tests/core/contract tests/platform/contract"
    ),
    "integration": (
        "tests/integration tests/runtime/integration tests/platform/integration"
    ),
    "e2e": "tests/runtime/e2e tests/acceptance",
    "recovery": (
        "tests/runtime/recovery tests/data/integration tests/platform/recovery"
    ),
    "security": (
        "tests/platform/security tests/data/security tests/acceptance/security"
    ),
}

GATE_DOMAINS = {"functional", "safety", "authorization", "data_integrity"}

DATASET_BY_PREFIX = {
    "m6a": "m6-incremental-a",
    "m6b": "m6-incremental-b",
    "m6c": "m6-incremental-c",
}

SKIP_TAG_PREFIX = "skip:"


class CollectionError(RuntimeError):
    """六类测试中某一类没有可用目标目录。"""


def collect_cases() -> list[dict[str, Any]]:
    """收集全部候选（A 69 + B 52 + C 35 = 156），按 case_id 去重并排序。"""
    seen: dict[str, dict[str, Any]] = {}
    for loader in (load_a, load_b, load_c):
        for case in loader(ROOT):
            seen[case["case_id"]] = case
    return sorted(seen.values(), key=lambda item: item["case_id"])


def verify_collection(cases: list[dict[str, Any]]) -> list[str]:
    """按类型枚举校验收集完整性：suite × category 配额必须与
    Evaluation Registry 的 FIXED_SUITE_QUOTAS 完全一致（120 功能 + 36 安全）。
    任一类型缺失/超量返回错误清单，由调用方报错退出并留痕。"""
    errors: list[str] = []
    actual: dict[str, dict[str, int]] = {}
    for case in cases:
        suite = case.get("suite", "")
        category = case.get("category", "")
        actual.setdefault(suite, {}).setdefault(category, 0)
        actual[suite][category] += 1
    for suite, quotas in FIXED_SUITE_QUOTAS.items():
        expected_total = sum(quotas.values())
        if suite not in actual:
            errors.append(
                f"类型缺失: suite={suite}（期望 {expected_total} 候选，实际 0）")
            continue
        for category, quota in quotas.items():
            got = actual[suite].get(category, 0)
            if got != quota:
                errors.append(
                    f"类型缺失/超量: {suite}/{category} 期望 {quota}，实际 {got}"
                )
        for category, got in actual[suite].items():
            if category not in quotas:
                errors.append(f"未知类型: {suite}/{category} 实际 {got}")
    for suite in actual:
        if suite not in FIXED_SUITE_QUOTAS:
            errors.append(
                f"未知 suite: {suite}（实际 {sum(actual[suite].values())} 候选）")
    return sorted(errors)


def _skip_reason(case: dict[str, Any]) -> str | None:
    """确定性跳过规则：tag `skip:<reason>` 或 tag `status:skipped`。"""
    for tag in case.get("tags", []):
        if isinstance(tag, str):
            if tag.startswith(SKIP_TAG_PREFIX):
                reason = tag[len(SKIP_TAG_PREFIX):].strip()
                return reason or "declared skip"
            if tag == "status:skipped":
                return "declared skip"
    return None


def evaluate_case(
    validator: OfflineRepositoryValidator, case: dict[str, Any]
) -> tuple[CaseResult, list[str], str | None]:
    """单候选确定性判定：结构/绑定/引用 0 findings -> PASS；
    显式 skip 标记 -> SKIPPED；否则 FAIL 并保留失败证据。"""
    skip_reason = _skip_reason(case)
    assertions = tuple(
        AssertionOutcome(
            assertion_id=item["assertion_id"],
            gate_domain=_gate_domain(item["assertion_id"]),
            passed=False,
        )
        for item in case.get("deterministic_assertions", [])
    )
    if skip_reason is not None:
        result = CaseResult(
            case_id=case["case_id"],
            suite=case["suite"],
            category=case["category"],
            status=CaseStatus.SKIPPED,
            assertions=assertions,
            judge_scores={},
        )
        return result, [], skip_reason

    findings = validator.validate_evaluation_cases([case])
    failed = [f.message for f in findings]
    evidence_path = _evidence_path_of(case)
    if not evidence_path.is_file():
        failed.append(f"evidence file missing: {evidence_path}")
    passed_assertions = tuple(
        AssertionOutcome(
            assertion_id=item["assertion_id"],
            gate_domain=_gate_domain(item["assertion_id"]),
            passed=not failed,
        )
        for item in case.get("deterministic_assertions", [])
    )
    status = CaseStatus.FAILED if failed else CaseStatus.PASSED
    result = CaseResult(
        case_id=case["case_id"],
        suite=case["suite"],
        category=case["category"],
        status=status,
        assertions=passed_assertions,
        judge_scores={},
    )
    return result, failed, None


def _gate_domain(assertion_id: str) -> str:
    for domain in GATE_DOMAINS:
        if domain in assertion_id:
            return domain
    return "functional"


def _dataset_of(case_id: str) -> str:
    prefix = case_id.split(".", 1)[0]
    return DATASET_BY_PREFIX.get(prefix, "m6-incremental-c")


def _evidence_path_of(case: dict[str, Any]) -> Path:
    case_id = case["case_id"]
    return (
        ROOT
        / "evals"
        / "datasets"
        / _dataset_of(case_id)
        / "cases"
        / case["suite"]
        / f"{case_id}.json"
    )


def run_tests(output_dir: Path) -> list[dict[str, Any]]:
    """跑六类测试生成 junit XML，返回每类的 {name, rc, xml, targets, passed}。

    只运行实际存在的目标目录；某一类全部目录缺失时抛 CollectionError。
    子进程清空 PYTHONPATH，避免宿主 venv 污染测试导入。
    """
    results: list[dict[str, Any]] = []
    test_results = output_dir / "test-results"
    test_results.mkdir(parents=True, exist_ok=True)
    clean_env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    for name, targets in TEST_SUITES.items():
        existing = [
            target for target in targets.split() if (ROOT / target).is_dir()
        ]
        if not existing:
            raise CollectionError(
                f"六类测试缺失: {name} 无任何可用目标目录（配置: {targets}）"
            )
        xml = test_results / f"{name}.xml"
        proc = subprocess.run(
            [
                sys.executable, "-B", "-m", "pytest",
                "-q", "--junitxml", str(xml),
                *existing,
            ],
            cwd=ROOT,
            env=clean_env,
            capture_output=True,
            text=True,
            timeout=1800,
        )
        passed = proc.returncode == 0
        results.append({
            "name": name,
            "rc": proc.returncode,
            "targets": existing,
            "xml": f"test-results/{name}.xml",
            "passed": passed,
            "tail": (proc.stdout + proc.stderr).strip()[-300:],
        })
        if not passed:
            print(f"  [{name}] rc={proc.returncode} FAILED", file=sys.stderr)
    return results


def collect_environment() -> dict[str, Any]:
    """环境快照（确定性信息，不含密钥）。"""
    git_commit = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain"],
        capture_output=True, text=True).stdout.strip())
    return {
        "git_commit": git_commit,
        "dirty_worktree": dirty,
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }


def hash_of(path: Path) -> str:
    return f"sha256:{sha256_file(path)}"


def main() -> int:
    parser = argparse.ArgumentParser(description="FlowPilot make acceptance 编排器")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "artifacts" / "acceptance" / "latest")
    parser.add_argument("--run-id", default="")
    args = parser.parse_args()

    run_id = args.run_id or datetime.datetime.now(
        datetime.UTC).strftime("run-%Y%m%d-%H%M%S")
    output = args.output if args.output.name != "latest" else (
        ROOT / "artifacts" / "acceptance" / run_id)
    output.mkdir(parents=True, exist_ok=True)
    started = datetime.datetime.now(datetime.UTC).isoformat()

    print("== 1/4 收集候选（按类型枚举） ==")
    cases = collect_cases()
    errors = verify_collection(cases)
    if errors:
        trace = {
            "run_id": run_id,
            "collected": len(cases),
            "errors": errors,
        }
        (output / "collection-errors.json").write_bytes(
            stable_json_bytes(trace))
        print(f"  收集校验失败: {len(errors)} 项类型缺失/超量，已留痕 "
              f"{output / 'collection-errors.json'}", file=sys.stderr)
        for error in errors:
            print(f"    - {error}", file=sys.stderr)
        return 1
    declared = [c["case_id"] for c in cases]
    by_suite = {
        suite: sum(1 for c in cases if c["suite"] == suite)
        for suite in FIXED_SUITE_QUOTAS
    }
    print(f"  候选总数: {len(cases)}（{by_suite.get('functional', 0)} 功能增量 + "
          f"{by_suite.get('safety_fault', 0)} 安全补充，13 类配额全部齐备）")

    print("== 2/4 候选确定性判定（156 逐候选） ==")
    validator = OfflineRepositoryValidator(ROOT)
    results: list[CaseResult] = []
    verdicts: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for case in cases:
        result, failed, skip_reason = evaluate_case(validator, case)
        results.append(result)
        verdicts.append({
            "case_id": result.case_id,
            "suite": result.suite,
            "category": result.category,
            "dataset_ref": case.get("dataset_ref", {}),
            "status": result.status.value,
            "assertions": [
                {"assertion_id": a.assertion_id,
                 "gate_domain": a.gate_domain,
                 "passed": a.passed}
                for a in result.assertions
            ],
            "findings": failed,
            "skip_reason": skip_reason,
            "evidence_path": str(_evidence_path_of(case).relative_to(ROOT)),
        })
        if failed:
            failures.append({
                "case_id": case["case_id"], "findings": failed,
                "evidence_path": str(_evidence_path_of(case).relative_to(ROOT)),
            })
    counts = {status: 0 for status in CaseStatus}
    for result in results:
        counts[result.status] += 1
    print(
        f"  判定完成: {counts[CaseStatus.PASSED]} PASS / "
        f"{counts[CaseStatus.FAILED]} FAIL / "
        f"{counts[CaseStatus.SKIPPED]} SKIPPED（共 {len(results)} 条判定记录）"
    )
    eval_dir = output / "eval"
    eval_dir.mkdir(parents=True, exist_ok=True)
    verdicts_path = eval_dir / "verdicts.json"
    verdicts_path.write_bytes(stable_json_bytes(verdicts))
    print(f"  判定清单: {verdicts_path}")
    if failures:
        failures_path = output / "failures.json"
        failures_path.write_bytes(stable_json_bytes({"failures": failures}))
        print("  失败保留（failures.json）:")
        for f in failures:
            print(f"    - {f['case_id']}: {f['findings'][0][:80]}")

    print("== 3/4 跑六类测试 ==")
    try:
        test_results = run_tests(output)
    except CollectionError as exc:
        trace = {"run_id": run_id, "errors": [str(exc)]}
        (output / "collection-errors.json").write_bytes(
            stable_json_bytes(trace))
        print(f"  {exc}，已留痕 {output / 'collection-errors.json'}",
              file=sys.stderr)
        return 1
    test_failed = any(not t["passed"] for t in test_results)
    if test_failed:
        print("  ⚠️ 部分测试失败，见 test-results/*.xml", file=sys.stderr)

    print("== 4/4 组装 bundle ==")
    env = collect_environment()
    dataset_versions: dict[str, str] = {}
    dataset_hashes: dict[str, str] = {}
    for ds in ("m6-incremental-a", "m6-incremental-b", "m6-incremental-c"):
        manifest = load_json_strict(ROOT / "evals" / "datasets" / ds / "manifest.json")
        dataset_versions[ds] = manifest.get("dataset_id", ds)
        dataset_hashes[ds] = hash_of(ROOT / "evals" / "datasets" / ds / "manifest.json")
    finished = datetime.datetime.now(datetime.UTC).isoformat()
    metadata = {
        "run_id": run_id,
        "started_at": started,
        "finished_at": finished,
        "git_commit": env["git_commit"],
        "dirty_worktree": env["dirty_worktree"],
        "contract_content_digest": _contract_digest(),
        "dataset_versions": dataset_versions,
        "dataset_hashes": dataset_hashes,
        "dataset_manifest_hash": hash_of(
            ROOT / "evals" / "datasets" / "m6-incremental-c" / "manifest.json"),
        "fixture_manifest_hash": _fixture_hash(),
        "traceability_hash": hash_of(ROOT / "docs" / "acceptance" / "TRACEABILITY.md"),
        "evaluation_registry_hash": hash_of(
            ROOT / "contracts" / "registries" / "evaluation-registry.v1.json"),
        "commands": [f"python scripts/acceptance/run_acceptance.py --run-id {run_id}"],
        "random_seeds": [],
        "runtime_versions": {"python": env["python"]},
        "models": {},
        "prompt_versions": {},
    }

    # 环境与测试结果快照
    env_path = output / "environment.json"
    test_summary_path = output / "test-results-summary.json"
    env_path.write_bytes(stable_json_bytes(env))
    test_summary_path.write_bytes(
        stable_json_bytes({"suites": test_results}))

    extra_artifacts: dict[str, Path] = {"eval/verdicts.json": verdicts_path}
    for suite_result in test_results:
        extra_artifacts[suite_result["xml"]] = (
            output / suite_result["xml"])
    extra_artifacts["environment.json"] = env_path
    extra_artifacts["test-results-summary.json"] = test_summary_path
    if failures:
        extra_artifacts["failures.json"] = output / "failures.json"
    manifest = generate_acceptance_bundle(
        output_dir=output,
        metadata=metadata,
        declared_case_ids=declared,
        results=results,
        extra_artifacts=extra_artifacts,
    )
    gate = manifest["gate_result"]
    print(f"\n== 完成: run_id={run_id} gate={gate} ==")
    print(f"  manifest: {output / 'manifest.json'}")
    print(f"  REPORT:   {output / 'REPORT.md'}")
    print(f"  aggregate: {output / 'eval' / 'aggregate.json'}")
    return 0 if gate == "pass" and not test_failed else 1


def _contract_digest() -> str:
    """契约集摘要：直接取 contract-set.v1.json 的 content_digest
    （由 OfflineRepositoryValidator 校验其与内容一致）。"""
    try:
        contract_set = load_json_strict(ROOT / "contracts" / "contract-set.v1.json")
        digest = contract_set.get("content_digest")
        if isinstance(digest, str) and digest:
            return digest
    except (OSError, UnicodeError, ValueError):
        pass
    return "sha256:unknown"


def _fixture_hash() -> str:
    manifest = ROOT / "evals" / "fixtures" / "manifest.json"
    return hash_of(manifest) if manifest.is_file() else "sha256:unknown"


if __name__ == "__main__":
    raise SystemExit(main())
