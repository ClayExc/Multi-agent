from __future__ import annotations

import pytest
from flowpilot_engineering_control.capsule import CapsuleBuilder, CapsuleRequest
from flowpilot_engineering_control.errors import EngineeringControlError, ErrorCode
from flowpilot_engineering_control.evidence import (
    CacheDecision,
    CacheMissReason,
)
from flowpilot_engineering_control.report import (
    AttemptReportBuilder,
    ReadObservation,
)
from flowpilot_engineering_control.repository import RepositoryMapBuilder
from flowpilot_engineering_control.selection import (
    SelectionRequest,
)
from flowpilot_engineering_control.selection import (
    TestSelector as EngineeringTestSelector,
)

from .conftest import ExampleRepository


def _inputs(example_repository: ExampleRepository) -> tuple[object, object]:
    base = example_repository.git("rev-parse", "HEAD")
    example_repository.write(
        "packages/engineering-control/src/flowpilot_engineering_control/private.py",
        "VALUE = 'changed'\n",
    )
    target = example_repository.commit("report input")
    repository_map = RepositoryMapBuilder(example_repository.root).build()
    capsule = CapsuleBuilder(example_repository.root, repository_map).build(
        CapsuleRequest(
            base=base,
            target=target,
            owner="S5-CORE",
            work_package="WP-092",
            attempt_id="WP-092-test",
            risk_class="R2",
            contract_digest="sha256:" + "a" * 64,
            write_scope=("packages/engineering-control/**",),
        )
    )
    plan = EngineeringTestSelector(repository_map).select(
        SelectionRequest(capsule=capsule)
    )
    return capsule, plan


def test_report_does_not_claim_estimate_as_actual(
    example_repository: ExampleRepository,
) -> None:
    capsule, plan = _inputs(example_repository)
    report = AttemptReportBuilder.build(
        attempt_id="WP-092-test",
        capsule=capsule,
        plan=plan,
        actual_reads=None,
        selection_compute_ms=7,
        cache_decisions=(CacheDecision(False, (CacheMissReason.ENVIRONMENT_DRIFT,)),),
    )
    record = report.to_record()
    assert record["actual_read"] is None
    assert record["estimated_usage"] == {
        "estimator_id": "utf8-bytes-div-4-ceil",
        "estimator_version": "1",
        "input_bytes": capsule.counts["initial_read_bytes"],
        "tokens": (capsule.counts["initial_read_bytes"] + 3) // 4,
    }
    assert b"VALUE = 'changed'" not in report.to_bytes()


def test_report_records_actual_observation_digest_and_is_deterministic(
    example_repository: ExampleRepository,
) -> None:
    capsule, plan = _inputs(example_repository)
    observations = (
        ReadObservation("AGENTS.md", "a" * 64, 10),
        ReadObservation("pyproject.toml", "b" * 64, 20),
    )
    first = AttemptReportBuilder.build(
        attempt_id="WP-092-test",
        capsule=capsule,
        plan=plan,
        actual_reads=observations,
        selection_compute_ms=9,
    )
    second = AttemptReportBuilder.build(
        attempt_id="WP-092-test",
        capsule=capsule,
        plan=plan,
        actual_reads=tuple(reversed(observations)),
        selection_compute_ms=9,
    )
    assert first.to_bytes() == second.to_bytes()
    assert first.actual_read is not None
    assert first.actual_read.file_count == 2
    assert first.actual_read.byte_count == 30


def test_report_rejects_duplicate_actual_paths(
    example_repository: ExampleRepository,
) -> None:
    capsule, plan = _inputs(example_repository)
    observations = (
        ReadObservation("AGENTS.md", "a" * 64, 10),
        ReadObservation("AGENTS.md", "b" * 64, 20),
    )
    with pytest.raises(EngineeringControlError) as captured:
        AttemptReportBuilder.build(
            attempt_id="WP-092-test",
            capsule=capsule,
            plan=plan,
            actual_reads=observations,
            selection_compute_ms=1,
        )
    assert captured.value.code is ErrorCode.REPORT_INVALID
