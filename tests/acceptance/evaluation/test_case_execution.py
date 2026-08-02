from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from packages.evaluation.canonical import sha256_file, stable_json_bytes
from packages.evaluation.execution import (
    CaseExecutionResult,
    CaseExecutorRegistry,
    ExecutionState,
    case_input_digest,
    collect_execution_evidence,
    merge_execution_evidence,
)
from packages.evaluation.reporting import (
    AssertionOutcome,
    CaseResult,
    CaseStatus,
    generate_acceptance_bundle,
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


class ForgedIdentityExecutor(ObservingExecutor):
    executor_id = "test.selected-executor"

    def execute(
        self,
        case: Mapping[str, Any],
        evidence_root: Path,
    ) -> CaseExecutionResult:
        valid = super().execute(case, evidence_root)
        return CaseExecutionResult(
            case_id=valid.case_id,
            executor_id="test.unregistered-attribution",
            executor_version="999",
            state=valid.state,
            input_digest=valid.input_digest,
            output_digest=valid.output_digest,
            assertion_results=valid.assertion_results,
            judge_scores=valid.judge_scores,
            evidence_refs=valid.evidence_refs,
        )


class EmptyIdentityExecutor(ObservingExecutor):
    executor_id = "none"
    executor_version = ""


class EmptyVersionExecutor(ObservingExecutor):
    executor_id = "test.valid-id"
    executor_version = "none"


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
    assert result.evidence_refs == ()
    assert result.output_digest is None


def test_output_digest_must_bind_primary_evidence(tmp_path: Path) -> None:
    case = _case()

    result = CaseExecutorRegistry([ForgedOutputExecutor()]).dispatch(case, tmp_path)

    assert result.state is ExecutionState.FAILED
    assert result.failure_code == "EXECUTION_RESULT_INVALID"
    assert "does not bind" in (result.failure_detail or "")
    assert result.evidence_refs == ()


def test_result_identity_must_match_selected_executor(tmp_path: Path) -> None:
    case = _case()

    result = CaseExecutorRegistry([ForgedIdentityExecutor()]).dispatch(
        case,
        tmp_path,
    )

    assert result.state is ExecutionState.FAILED
    assert result.failure_code == "EXECUTOR_IDENTITY_MISMATCH"
    assert result.executor_id == ForgedIdentityExecutor.executor_id
    assert result.executor_version == ForgedIdentityExecutor.executor_version
    assert result.evidence_refs == ()


def test_registry_rejects_empty_or_none_identity() -> None:
    with pytest.raises(ValueError, match="executor ID"):
        CaseExecutorRegistry([EmptyIdentityExecutor()])
    with pytest.raises(ValueError, match="executor version"):
        CaseExecutorRegistry([EmptyVersionExecutor()])


def test_repeated_execution_is_deterministic_and_keeps_evidence(tmp_path: Path) -> None:
    case = _case()
    registry = CaseExecutorRegistry([ObservingExecutor()])

    first = registry.dispatch(case, tmp_path / "first")
    second = registry.dispatch(case, tmp_path / "second")

    assert first.to_dict() == second.to_dict()
    assert (tmp_path / "first" / first.evidence_refs[0]).is_file()
    assert (tmp_path / "second" / second.evidence_refs[0]).is_file()


def test_executor_evidence_is_hashed_into_manifest(tmp_path: Path) -> None:
    case = _case()
    evidence_root = tmp_path / "evidence"
    execution = CaseExecutorRegistry([ObservingExecutor()]).dispatch(
        case,
        evidence_root,
    )
    artifacts = collect_execution_evidence([execution], evidence_root)
    result = CaseResult(
        case_id=case["case_id"],
        suite=case["suite"],
        category=case["category"],
        status=CaseStatus.PASSED,
        assertions=(
            AssertionOutcome(
                assertion_id="assert.task.terminal_status.v1",
                gate_domain="flow",
                passed=True,
            ),
        ),
        judge_scores={},
    )

    manifest = generate_acceptance_bundle(
        output_dir=tmp_path / "bundle",
        metadata=_metadata(),
        declared_case_ids=[case["case_id"]],
        results=[result],
        extra_artifacts=artifacts,
    )

    artifact_name = "execution/observed-echo.json"
    assert manifest["artifact_hashes"][artifact_name] == sha256_file(
        evidence_root / "observed-echo.json"
    )


def test_duplicate_execution_evidence_reference_is_rejected(tmp_path: Path) -> None:
    case = _case()
    execution = CaseExecutorRegistry([ObservingExecutor()]).dispatch(case, tmp_path)

    with pytest.raises(ValueError, match="duplicate execution evidence"):
        collect_execution_evidence([execution, execution], tmp_path)


def test_missing_execution_evidence_is_rejected(tmp_path: Path) -> None:
    case = _case()
    missing = CaseExecutionResult(
        case_id=case["case_id"],
        executor_id="test.observing-executor",
        executor_version="1",
        state=ExecutionState.COMPLETED,
        input_digest=case_input_digest(case),
        output_digest=None,
        assertion_results={"assert.task.terminal_status.v1": False},
        judge_scores={},
        evidence_refs=("missing.json",),
    )

    with pytest.raises(ValueError, match="missing or empty"):
        collect_execution_evidence([missing], tmp_path)


def test_execution_evidence_path_escape_is_rejected(tmp_path: Path) -> None:
    case = _case()
    escaped = CaseExecutionResult(
        case_id=case["case_id"],
        executor_id="test.observing-executor",
        executor_version="1",
        state=ExecutionState.COMPLETED,
        input_digest=case_input_digest(case),
        output_digest=None,
        assertion_results={"assert.task.terminal_status.v1": False},
        judge_scores={},
        evidence_refs=("../escape.json",),
    )

    with pytest.raises(ValueError, match="unsafe execution evidence"):
        collect_execution_evidence([escaped], tmp_path)


def test_failed_result_references_do_not_enter_evidence_closure(
    tmp_path: Path,
) -> None:
    case = _case()
    failed = CaseExecutionResult(
        case_id=case["case_id"],
        executor_id="test.observing-executor",
        executor_version="1",
        state=ExecutionState.FAILED,
        input_digest=case_input_digest(case),
        output_digest=None,
        assertion_results={"assert.task.terminal_status.v1": False},
        judge_scores={},
        evidence_refs=("../untrusted.json",),
        failure_code="EXECUTION_RESULT_INVALID",
        failure_detail="untrusted result",
    )

    assert collect_execution_evidence([failed], tmp_path) == {}


def test_execution_evidence_cannot_replace_existing_artifact(tmp_path: Path) -> None:
    case = _case()
    execution = CaseExecutorRegistry([ObservingExecutor()]).dispatch(case, tmp_path)
    evidence = collect_execution_evidence([execution], tmp_path)

    with pytest.raises(ValueError, match="artifact conflict"):
        merge_execution_evidence(
            {"execution/observed-echo.json": tmp_path / "other.json"},
            evidence,
        )


def _metadata() -> dict[str, object]:
    return {
        "run_id": "wp031-evidence-closure",
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
