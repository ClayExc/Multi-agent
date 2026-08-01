from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from artifacts.acceptance.generators import generate_vpn_candidate_bundle
from packages.evaluation import (
    VPN_CANDIDATE_CASE_COUNT,
    CaseResult,
    CaseStatus,
    DeterministicScorer,
    VpnCaseDefinition,
    load_vpn_case_set,
)

from .blackbox import VpnBlackBoxObservation, run_vpn_case

ROOT = Path(__file__).resolve().parents[3]
CASE_ROOT = ROOT / "evals" / "datasets" / "functional" / "vpn-readonly-p1"
REGISTRY_PATH = ROOT / "contracts" / "registries" / "evaluation-registry.v1.json"
CASE_SET = load_vpn_case_set(CASE_ROOT)
REGISTRY = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
SCORER = DeterministicScorer.from_registry(REGISTRY)


def _score(
    case: VpnCaseDefinition,
    observation: VpnBlackBoxObservation,
) -> CaseResult:
    return SCORER.score(
        case_id=case.case_id,
        suite=case.suite,
        category=case.category,
        assertion_results=observation.assertion_results,
        judge_scores=case.judge_scores,
    )


def test_vpn_candidate_manifest_pins_exactly_twenty_ordered_cases() -> None:
    assert VPN_CANDIDATE_CASE_COUNT == 20
    assert len(CASE_SET.cases) == 20
    assert CASE_SET.case_ids == tuple(f"vpn-p1-{index:03d}" for index in range(1, 21))
    assert set(CASE_SET.file_hashes) == {"dataset-card.yaml", "vpn-cases.json"}
    assert CASE_SET.manifest_hash.startswith("sha256:")


@pytest.mark.parametrize("case", CASE_SET.cases, ids=CASE_SET.case_ids)
async def test_fixed_vpn_blackbox_case(case: VpnCaseDefinition) -> None:
    observation = await run_vpn_case(case)

    assert observation.expected_projection() == case.expected.to_mapping()
    assert observation.assertion_results
    assert all(observation.assertion_results.values())
    scored = _score(case, observation)
    assert scored.status is CaseStatus.PASSED


async def test_vpn_candidate_bundle_is_complete_but_never_release_eligible(
    tmp_path: Path,
) -> None:
    results = []
    for case in CASE_SET.cases:
        results.append(_score(case, await run_vpn_case(case)))

    manifest = generate_vpn_candidate_bundle(
        output_dir=tmp_path / "vpn-candidate",
        case_set=CASE_SET,
        results=results,
        metadata={
            "run_id": "run-wp030-a4-vpn-fixed",
            "started_at": "2026-07-28T08:30:00Z",
            "finished_at": "2026-07-28T08:30:00Z",
            "git_commit": "c5c118d808931492d7ee44455b1c2a9360625675",
            "dirty_worktree": False,
            "contract_content_digest": (
                "sha256:0a82e7f58c4223362721c95a50e9a820"
                "d714e550e72eebc7a90ab01e283100fc"
            ),
            "dataset_versions": {CASE_SET.dataset_id: CASE_SET.version},
            "dataset_hashes": dict(CASE_SET.file_hashes),
            "dataset_manifest_hash": CASE_SET.manifest_hash,
            "fixture_manifest_hash": CASE_SET.manifest_hash,
            "traceability_hash": "sha256:" + "1" * 64,
            "evaluation_registry_hash": "sha256:" + "2" * 64,
            "commands": ["python -m pytest tests/acceptance -q"],
            "random_seeds": [0],
            "runtime_versions": {},
            "models": {},
            "prompt_versions": {},
        },
    )

    aggregate = json.loads(
        (tmp_path / "vpn-candidate" / "eval" / "aggregate.json").read_text(
            encoding="utf-8"
        )
    )
    assert aggregate["denominator_policy"] == "all_declared_cases"
    assert aggregate["declared_case_count"] == 20
    assert aggregate["passed"] == 20
    assert aggregate["failure_count"] == 0
    assert manifest["candidate_only"] is True
    assert manifest["release_eligible"] is False
    assert manifest["measurement_scope"] == "fixed_local_vpn_blackbox_20"
    assert manifest["secret_scan_findings"] == 0
    assert manifest["pii_scan_findings"] == 0


def test_vpn_judge_cannot_override_execution_or_deterministic_failures() -> None:
    case = CASE_SET.cases[-1]
    all_passing = {assertion_id: True for assertion_id in case.assertions}

    execution_failed = SCORER.score(
        case_id=case.case_id,
        suite=case.suite,
        category=case.category,
        assertion_results=all_passing,
        execution_status=CaseStatus.FAILED,
        judge_scores=case.judge_scores,
    )
    deterministic_failed = SCORER.score(
        case_id=case.case_id,
        suite=case.suite,
        category=case.category,
        assertion_results={**all_passing, case.assertions[0]: False},
        execution_status=CaseStatus.PASSED,
        judge_scores=case.judge_scores,
    )

    assert execution_failed.judge_scores == {
        "judge.semantic.citation_support.v1": 1.0
    }
    assert execution_failed.status is CaseStatus.FAILED
    assert deterministic_failed.status is CaseStatus.FAILED


def test_vpn_candidate_loader_rejects_hash_drift(tmp_path: Path) -> None:
    copied = tmp_path / "vpn-readonly-p1"
    shutil.copytree(CASE_ROOT, copied)
    with (copied / "vpn-cases.json").open("a", encoding="utf-8") as stream:
        stream.write("\n")

    with pytest.raises(ValueError, match="file hash mismatch"):
        load_vpn_case_set(copied)
