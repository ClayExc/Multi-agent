from __future__ import annotations

import importlib.util
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

from packages.evaluation.canonical import sha256_file, stable_json_bytes
from packages.evaluation.execution import (
    CaseExecutionResult,
    CaseExecutorRegistry,
    ExecutionState,
    case_input_digest,
    collect_execution_evidence,
)
from packages.evaluation.reporting import CaseStatus, generate_acceptance_bundle

ROOT = Path(__file__).resolve().parents[3]


def _load_runner() -> ModuleType:
    path = ROOT / "scripts" / "acceptance" / "run_acceptance.py"
    spec = importlib.util.spec_from_file_location("flowpilot_acceptance_runner", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CleanValidator:
    def validate_evaluation_cases(self, cases: list[dict[str, Any]]) -> list[Any]:
        assert len(cases) == 1
        return []


class ObservedResultExecutor:
    executor_id = "test.runner-observer"
    executor_version = "1"

    def __init__(
        self,
        *,
        assertion_passed: bool = True,
        judge_scores: Mapping[str, float] | None = None,
    ) -> None:
        self.assertion_passed = assertion_passed
        self.judge_scores = dict(judge_scores or {})

    def supports(self, case: Mapping[str, Any]) -> bool:
        return "scenario:observed" in case.get("tags", [])

    def execute(
        self,
        case: Mapping[str, Any],
        evidence_root: Path,
    ) -> CaseExecutionResult:
        observation = {
            "case_id": case["case_id"],
            "actual_terminal_status": (
                "COMPLETED" if self.assertion_passed else "FAILED"
            ),
        }
        evidence_root.mkdir(parents=True, exist_ok=True)
        evidence = evidence_root / "observation.json"
        evidence.write_bytes(stable_json_bytes(observation))
        return CaseExecutionResult(
            case_id=str(case["case_id"]),
            executor_id=self.executor_id,
            executor_version=self.executor_version,
            state=ExecutionState.COMPLETED,
            input_digest=case_input_digest(case),
            output_digest=sha256_file(evidence),
            assertion_results={
                "assert.task.terminal_status.v1": self.assertion_passed
            },
            judge_scores=self.judge_scores,
            evidence_refs=("observation.json",),
        )


class MissingEvidenceExecutor(ObservedResultExecutor):
    executor_id = "test.missing-evidence"

    def execute(
        self,
        case: Mapping[str, Any],
        evidence_root: Path,
    ) -> CaseExecutionResult:
        valid = super().execute(case, evidence_root)
        return CaseExecutionResult(
            case_id=valid.case_id,
            executor_id=self.executor_id,
            executor_version=self.executor_version,
            state=valid.state,
            input_digest=valid.input_digest,
            output_digest=valid.output_digest,
            assertion_results=valid.assertion_results,
            judge_scores=valid.judge_scores,
            evidence_refs=("missing-observation.json",),
        )


def _case(
    *,
    judge: bool = False,
    suite: str = "functional",
    scenario: str = "unregistered",
) -> dict[str, Any]:
    return {
        "case_id": "case.runner.001",
        "suite": suite,
        "category": "knowledge_qa_citation",
        "input": "synthetic request",
        "expected": {"terminal_status": "COMPLETED"},
        "deterministic_assertions": [
            {"assertion_id": "assert.task.terminal_status.v1", "parameters": {}}
        ],
        "judge_rubrics": (
            [{"rubric_id": "judge.semantic.answer_relevance.v1"}]
            if judge
            else []
        ),
        "tags": [f"scenario:{scenario}"],
    }


def test_case_definition_without_executor_is_failed_not_passed(tmp_path: Path) -> None:
    runner = _load_runner()

    result, execution, findings, _ = runner.evaluate_case(
        CleanValidator(),
        _case(),
        executors=CaseExecutorRegistry(),
        evidence_root=tmp_path,
        judge_calibrated=False,
    )

    assert result.status is CaseStatus.FAILED
    assert execution.failure_code == "EXECUTOR_NOT_REGISTERED"
    assert any("EXECUTOR_NOT_REGISTERED" in item for item in findings)


def test_uncalibrated_judge_case_records_explicit_gate_failure(
    tmp_path: Path,
) -> None:
    runner = _load_runner()

    result, _, findings, _ = runner.evaluate_case(
        CleanValidator(),
        _case(judge=True, scenario="observed"),
        executors=CaseExecutorRegistry(
            [
                ObservedResultExecutor(
                    judge_scores={"judge.semantic.answer_relevance.v1": 0.9}
                )
            ]
        ),
        evidence_root=tmp_path,
        judge_calibrated=False,
    )

    assert result.status is CaseStatus.FAILED
    assert "JUDGE_NOT_CALIBRATED" in findings
    assert not any("JUDGE_SCORE_BINDING_MISMATCH" in item for item in findings)


def test_real_execution_with_observed_assertions_can_pass(tmp_path: Path) -> None:
    runner = _load_runner()

    result, execution, findings, _ = runner.evaluate_case(
        CleanValidator(),
        _case(scenario="observed"),
        executors=CaseExecutorRegistry([ObservedResultExecutor()]),
        evidence_root=tmp_path,
        judge_calibrated=False,
    )

    assert execution.state is ExecutionState.COMPLETED
    assert findings == []
    assert result.status is CaseStatus.PASSED


def test_observed_assertion_failure_cannot_pass(tmp_path: Path) -> None:
    runner = _load_runner()

    result, _, findings, _ = runner.evaluate_case(
        CleanValidator(),
        _case(scenario="observed"),
        executors=CaseExecutorRegistry(
            [ObservedResultExecutor(assertion_passed=False)]
        ),
        evidence_root=tmp_path,
        judge_calibrated=False,
    )

    assert findings == []
    assert result.status is CaseStatus.FAILED


def test_judge_cannot_make_a_safety_case_pass(tmp_path: Path) -> None:
    runner = _load_runner()

    result, _, findings, _ = runner.evaluate_case(
        CleanValidator(),
        _case(suite="safety_fault", scenario="observed"),
        executors=CaseExecutorRegistry(
            [
                ObservedResultExecutor(
                    judge_scores={"judge.semantic.answer_relevance.v1": 1.0}
                )
            ]
        ),
        evidence_root=tmp_path,
        judge_calibrated=True,
    )

    assert result.status is CaseStatus.FAILED
    assert "JUDGE_FORBIDDEN_FOR_NON_FUNCTIONAL_GATE" in findings


def test_invalid_evidence_fails_case_but_bundle_and_report_still_close(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    case = _case(scenario="observed")

    result, execution, findings, _ = runner.evaluate_case(
        CleanValidator(),
        case,
        executors=CaseExecutorRegistry([MissingEvidenceExecutor()]),
        evidence_root=tmp_path / "execution",
        judge_calibrated=False,
    )

    assert result.status is CaseStatus.FAILED
    assert execution.state is ExecutionState.FAILED
    assert execution.evidence_refs == ()
    assert execution.failure_code == "EXECUTION_RESULT_INVALID"
    assert any("missing or empty" in item for item in findings)
    execution_artifacts = collect_execution_evidence(
        [execution],
        tmp_path / "execution",
    )
    assert execution_artifacts == {}

    output = tmp_path / "bundle"
    manifest = generate_acceptance_bundle(
        output_dir=output,
        metadata=_metadata(),
        declared_case_ids=[case["case_id"]],
        results=[result],
        extra_artifacts=execution_artifacts,
    )

    assert manifest["gate_result"] == "fail"
    assert runner.exit_code_for_manifest(manifest) == 1
    assert "- Gate: `fail`" in (output / "REPORT.md").read_text(encoding="utf-8")


def test_hash_helpers_return_single_valid_prefix_and_real_fixture_manifest() -> None:
    runner = _load_runner()

    fixture_hash = runner._fixture_hash()

    assert fixture_hash.startswith("sha256:")
    assert not fixture_hash.startswith("sha256:sha256:")
    assert len(fixture_hash) == 71


def test_process_exit_uses_persisted_manifest_gate() -> None:
    runner = _load_runner()

    assert runner.exit_code_for_manifest({"gate_result": "pass"}) == 0
    assert runner.exit_code_for_manifest({"gate_result": "fail"}) == 1


def _metadata() -> dict[str, object]:
    return {
        "run_id": "wp031-invalid-evidence",
        "started_at": "2026-08-02T00:00:00Z",
        "finished_at": "2026-08-02T00:00:01Z",
        "git_commit": "0" * 40,
        "dirty_worktree": False,
        "contract_content_digest": "sha256:" + "0" * 64,
        "dataset_versions": {},
        "dataset_hashes": {},
        "dataset_manifest_hash": "sha256:" + "1" * 64,
        "fixture_manifest_hash": "sha256:" + "2" * 64,
        "traceability_hash": "sha256:" + "3" * 64,
        "evaluation_registry_hash": "sha256:" + "4" * 64,
    }
