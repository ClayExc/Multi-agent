"""Structured Feature evidence records for independent verification."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .canonical import sha256_file
from .safety import require_safe_evidence


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    feature_id: str
    evidence_id: str
    test_id: str
    artifact_path: str
    artifact_hash: str
    run_id: str
    produced_at: str
    verifier_role: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def build_evidence_record(
    *,
    repository_root: Path,
    traceability: Mapping[str, Any],
    feature_id: str,
    evidence_id: str,
    test_id: str,
    artifact_path: str,
    run_id: str,
    produced_at: str,
    verifier_role: str,
) -> EvidenceRecord:
    features = {
        feature["feature_id"]: feature for feature in traceability.get("features", [])
    }
    feature = features.get(feature_id)
    if feature is None:
        raise ValueError(f"unknown feature_id: {feature_id}")
    declared_evidence = {
        item["evidence_id"] for item in feature.get("evidence", [])
    }
    declared_tests = {item["test_id"] for item in feature.get("tests", [])}
    if evidence_id not in declared_evidence:
        raise ValueError(f"undeclared evidence_id for {feature_id}: {evidence_id}")
    if test_id not in declared_tests:
        raise ValueError(f"undeclared test_id for {feature_id}: {test_id}")
    if verifier_role != feature.get("verification_owner"):
        raise ValueError(
            f"verifier_role must be {feature.get('verification_owner')} "
            f"for {feature_id}"
        )
    if verifier_role == feature.get("implementation_owner"):
        raise ValueError("feature implementer cannot verify their own evidence")
    root = repository_root.resolve()
    artifact = (root / artifact_path).resolve()
    if root not in artifact.parents or not artifact.is_file():
        raise ValueError(
            f"evidence artifact does not exist in repository: {artifact_path}"
        )
    record = EvidenceRecord(
        feature_id=feature_id,
        evidence_id=evidence_id,
        test_id=test_id,
        artifact_path=artifact_path,
        artifact_hash=sha256_file(artifact),
        run_id=run_id,
        produced_at=produced_at,
        verifier_role=verifier_role,
    )
    require_safe_evidence(record.to_dict())
    return record
