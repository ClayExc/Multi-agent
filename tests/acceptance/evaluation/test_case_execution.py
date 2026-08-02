from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from packages.evaluation.canonical import sha256_file, stable_json_bytes
from packages.evaluation.execution import (
    CaseExecutionResult,
    CaseExecutorRegistry,
    ExecutionState,
    case_input_digest,
)


def _case(*, scenario: str = "observed_echo") -> dict[str, Any]:
    return {
        "case_id": "case.execution.001",
        "suite": "functional",
        "category": "knowledge_qa_citation",
        "input": "synthetic request",
        "expected": {"terminal_status": "COMPLETED"},
        "deterministic_assertions": [
            {"assertion_id": "assert.task.terminal_status.v1", "parameters": {}}
        ],
        "judge_rubrics": [],
        "tags": [f"scenario:{scenario}"],
    }


class ObservingExecutor:
    executor_id = "test.observing-executor"
    executor_version = "1"

    def supports(self, case: Mapping[str, Any]) -> bool:
        return "scenario:observed_echo" in case.get("tags", [])

    def execute(
        self,
        case: Mapping[str, Any],
        evidence_root: Path,
    ) -> CaseExecutionResult:
        observation = {
            "case_id": case["case_id"],
            "actual_terminal_status": "COMPLETED",
        }
        evidence_root.mkdir(parents=True, exist_ok=True)
        evidence = evidence_root / "observed-echo.json"
        evidence.write_bytes(stable_json_bytes(observation))
        return CaseExecutionResult(
            case_id=str(case["case_id"]),
            executor_id=self.executor_id,
            executor_version=self.executor_version,
            state=ExecutionState.COMPLETED,
            input_digest=case_input_digest(case),
            output_digest=sha256_file(evidence),
            assertion_results={"assert.task.terminal_status.v1": True},
            judge_scores={},
            evidence_refs=("observed-echo.json",),
        )


class ForgedBindingExecutor(ObservingExecutor):
    executor_id = "test.forged-binding-executor"

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
            state=ExecutionState.COMPLETED,
            input_digest="sha256:" + "0" * 64,
            output_digest=valid.output_digest,
            assertion_results=valid.assertion_results,
            judge_scores={},
            evidence_refs=valid.evidence_refs,
        )


class ForgedOutputExecutor(ObservingExecutor):
    executor_id = "test.forged-output-executor"

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
            state=ExecutionState.COMPLETED,
            input_digest=valid.input_digest,
            output_digest="sha256:" + "f" * 64,
            assertion_results=valid.assertion_results,
            judge_scores={},
            evidence_refs=valid.evidence_refs,
        )


def test_unregistered_case_is_not_executed_and_never_passes() -> None:
    case = _case(scenario="not_registered")

    result = CaseExecutorRegistry().dispatch(case, Path("unused"))

    assert result.state is ExecutionState.NOT_EXECUTED
    assert result.failure_code == "EXECUTOR_NOT_REGISTERED"
    assert result.assertion_results == {"assert.task.terminal_status.v1": False}


def test_registered_executor_binds_actual_observation_and_evidence(
    tmp_path: Path,
) -> None:
    case = _case()

    result = CaseExecutorRegistry([ObservingExecutor()]).dispatch(case, tmp_path)

    assert result.state is ExecutionState.COMPLETED
    assert result.input_digest == case_input_digest(case)
    assert result.output_digest == sha256_file(tmp_path / "observed-echo.json")
    assert result.assertion_results == {"assert.task.terminal_status.v1": True}
    assert (tmp_path / result.evidence_refs[0]).is_file()


def test_input_binding_mismatch_fails_closed(tmp_path: Path) -> None:
    case = _case()

    result = CaseExecutorRegistry([ForgedBindingExecutor()]).dispatch(case, tmp_path)

    assert result.state is ExecutionState.FAILED
    assert result.failure_code == "EXECUTION_RESULT_INVALID"
    assert "input digest mismatch" in (result.failure_detail or "")


def test_output_digest_must_bind_primary_evidence(tmp_path: Path) -> None:
    case = _case()

    result = CaseExecutorRegistry([ForgedOutputExecutor()]).dispatch(case, tmp_path)

    assert result.state is ExecutionState.FAILED
    assert result.failure_code == "EXECUTION_RESULT_INVALID"
    assert "does not bind" in (result.failure_detail or "")


def test_repeated_execution_is_deterministic_and_keeps_evidence(tmp_path: Path) -> None:
    case = _case()
    registry = CaseExecutorRegistry([ObservingExecutor()])

    first = registry.dispatch(case, tmp_path / "first")
    second = registry.dispatch(case, tmp_path / "second")

    assert first.to_dict() == second.to_dict()
    assert (tmp_path / "first" / first.evidence_refs[0]).is_file()
    assert (tmp_path / "second" / second.evidence_refs[0]).is_file()
