from __future__ import annotations

from pathlib import Path

import pytest

from packages.evaluation.canonical import load_json_strict
from packages.evaluation.evidence import build_evidence_record


ROOT = Path(__file__).resolve().parents[3]


def test_independent_verifier_can_build_structured_evidence(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.json"
    artifact.write_text('{"gate":"pass"}\n', encoding="utf-8", newline="\n")
    traceability = load_json_strict(
        ROOT / "docs" / "acceptance" / "traceability.v1.json"
    )

    record = build_evidence_record(
        repository_root=tmp_path,
        traceability=traceability,
        feature_id="FP-EVAL-003",
        evidence_id="evidence.fp-eval-003.primary.v1",
        test_id="test.fp-eval-003.primary.v1",
        artifact_path="artifact.json",
        run_id="acc_offline123",
        produced_at="2026-07-28T12:00:00Z",
        verifier_role="S1-ARCH",
    )

    assert record.artifact_hash.startswith("sha256:")
    assert record.verifier_role == "S1-ARCH"


def test_implementer_cannot_self_verify_feature_evidence(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.json"
    artifact.write_text('{"gate":"pass"}\n', encoding="utf-8", newline="\n")
    traceability = load_json_strict(
        ROOT / "docs" / "acceptance" / "traceability.v1.json"
    )

    with pytest.raises(ValueError, match="verifier_role must be S1-ARCH"):
        build_evidence_record(
            repository_root=tmp_path,
            traceability=traceability,
            feature_id="FP-EVAL-003",
            evidence_id="evidence.fp-eval-003.primary.v1",
            test_id="test.fp-eval-003.primary.v1",
            artifact_path="artifact.json",
            run_id="acc_offline123",
            produced_at="2026-07-28T12:00:00Z",
            verifier_role="S4-QUALITY",
        )
