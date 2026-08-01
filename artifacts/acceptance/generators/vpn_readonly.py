"""Candidate-only artifact generator for the fixed P1 VPN black-box suite."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from packages.evaluation import (
    CaseResult,
    VpnCaseSet,
    generate_acceptance_bundle,
)
from packages.evaluation.safety import find_unsafe_evidence

_PII_PATTERNS = (
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])"),
    re.compile(r"(?<!\w)\+[1-9]\d{9,14}(?!\d)"),
)


def generate_vpn_candidate_bundle(
    *,
    output_dir: Path,
    case_set: VpnCaseSet,
    results: Iterable[CaseResult],
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Generate evidence without presenting 20 candidates as the 120/36 release set."""

    result_list = list(results)
    if len(result_list) != len(case_set.cases):
        raise ValueError("VPN candidate bundle requires one result per fixed case")
    secret_findings, pii_findings = _scan_candidate_files(case_set)
    if secret_findings or pii_findings:
        raise ValueError("VPN candidate files failed Secret/PII scanning")
    candidate_metadata = {
        **dict(metadata),
        "candidate_dataset_id": case_set.dataset_id,
        "candidate_dataset_version": case_set.version,
        "candidate_case_count": len(case_set.cases),
        "candidate_only": True,
        "release_eligible": False,
        "candidate_file_hashes": dict(case_set.file_hashes),
        "candidate_manifest_hash": case_set.manifest_hash,
        "measurement_scope": "fixed_local_vpn_blackbox_20",
        "secret_scan_findings": len(secret_findings),
        "pii_scan_findings": len(pii_findings),
        "scan_scope": ["dataset-card.yaml", "vpn-cases.json", "case-results"],
    }
    return generate_acceptance_bundle(
        output_dir=output_dir,
        metadata=candidate_metadata,
        declared_case_ids=case_set.case_ids,
        results=result_list,
    )


def _scan_candidate_files(case_set: VpnCaseSet) -> tuple[list[str], list[str]]:
    card = (case_set.root / "dataset-card.yaml").read_text(encoding="utf-8")
    case_document = json.loads(
        (case_set.root / "vpn-cases.json").read_text(encoding="utf-8")
    )
    secret_findings = find_unsafe_evidence(card)
    secret_findings.extend(find_unsafe_evidence(case_document))
    pii_findings: list[str] = []
    for name, text in (
        ("dataset-card.yaml", card),
        ("vpn-cases.json", json.dumps(case_document, ensure_ascii=False)),
    ):
        for pattern in _PII_PATTERNS:
            if pattern.search(text):
                pii_findings.append(f"{name}: PII-like material detected")
    return secret_findings, pii_findings
