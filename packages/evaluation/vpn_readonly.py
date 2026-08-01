"""Strict loader for the local P1 VPN read-only candidate case set."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .canonical import sha256_file

VPN_CANDIDATE_CASE_COUNT = 20
_SHA_PREFIX = "sha256:"
_RESULT_REF_STATES = frozenset({"absent", "present", "stable"})


@dataclass(frozen=True, slots=True)
class VpnCaseExpected:
    task_status: str
    failure_code: str | None
    logical_knowledge_calls: int
    gateway_attempts: int
    result_ref: str
    citation_count: int

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> VpnCaseExpected:
        required = {
            "task_status",
            "failure_code",
            "logical_knowledge_calls",
            "gateway_attempts",
            "result_ref",
            "citation_count",
        }
        if set(value) != required:
            raise ValueError("VPN expected projection must use the fixed field set")
        for field in (
            "logical_knowledge_calls",
            "gateway_attempts",
            "citation_count",
        ):
            count = value[field]
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError(f"VPN expected {field} must be a non-negative integer")
        result_ref = value["result_ref"]
        if result_ref not in _RESULT_REF_STATES:
            raise ValueError("VPN expected result_ref state is unsupported")
        failure_code = value["failure_code"]
        if failure_code is not None and not isinstance(failure_code, str):
            raise ValueError("VPN expected failure_code must be text or null")
        task_status = value["task_status"]
        if task_status not in {"COMPLETED", "FAILED"}:
            raise ValueError("VPN candidate cases must reach a terminal Task status")
        return cls(
            task_status=task_status,
            failure_code=failure_code,
            logical_knowledge_calls=value["logical_knowledge_calls"],
            gateway_attempts=value["gateway_attempts"],
            result_ref=result_ref,
            citation_count=value["citation_count"],
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "task_status": self.task_status,
            "failure_code": self.failure_code,
            "logical_knowledge_calls": self.logical_knowledge_calls,
            "gateway_attempts": self.gateway_attempts,
            "result_ref": self.result_ref,
            "citation_count": self.citation_count,
        }


@dataclass(frozen=True, slots=True)
class VpnCaseDefinition:
    case_id: str
    suite: str
    category: str
    scenario: str
    assertions: tuple[str, ...]
    judge_scores: Mapping[str, float]
    expected: VpnCaseExpected

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> VpnCaseDefinition:
        required = {
            "case_id",
            "suite",
            "category",
            "scenario",
            "assertions",
            "judge_scores",
            "expected",
        }
        if set(value) != required:
            raise ValueError("VPN case must use the fixed candidate field set")
        for field in ("case_id", "suite", "category", "scenario"):
            if not isinstance(value[field], str) or not value[field]:
                raise ValueError(f"VPN case {field} must be non-empty text")
        assertions = value["assertions"]
        if (
            not isinstance(assertions, list)
            or not assertions
            or not all(isinstance(item, str) and item for item in assertions)
            or len(assertions) != len(set(assertions))
        ):
            raise ValueError("VPN case assertions must be a non-empty unique list")
        scores = value["judge_scores"]
        if not isinstance(scores, dict):
            raise ValueError("VPN case judge_scores must be an object")
        validated_scores: dict[str, float] = {}
        for rubric_id, score in scores.items():
            if (
                not isinstance(rubric_id, str)
                or isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not 0 <= float(score) <= 1
            ):
                raise ValueError("VPN Judge scores must be numeric values in [0, 1]")
            validated_scores[rubric_id] = float(score)
        expected = value["expected"]
        if not isinstance(expected, dict):
            raise ValueError("VPN expected projection must be an object")
        return cls(
            case_id=value["case_id"],
            suite=value["suite"],
            category=value["category"],
            scenario=value["scenario"],
            assertions=tuple(assertions),
            judge_scores=MappingProxyType(validated_scores),
            expected=VpnCaseExpected.from_mapping(expected),
        )


@dataclass(frozen=True, slots=True)
class VpnCaseSet:
    dataset_id: str
    version: str
    root: Path
    cases: tuple[VpnCaseDefinition, ...]
    file_hashes: Mapping[str, str]
    manifest_hash: str

    @property
    def case_ids(self) -> tuple[str, ...]:
        return tuple(case.case_id for case in self.cases)


def load_vpn_case_set(root: Path) -> VpnCaseSet:
    """Load only a hash-pinned, exactly-20-case local candidate set."""

    manifest_path = root / "manifest.json"
    manifest = _load_object(manifest_path)
    required_manifest = {
        "schema_version",
        "dataset_id",
        "version",
        "candidate_only",
        "case_count",
        "files",
    }
    if set(manifest) != required_manifest:
        raise ValueError("VPN candidate manifest uses an unexpected field set")
    if manifest["candidate_only"] is not True:
        raise ValueError("VPN local case set must remain candidate_only")
    if manifest["case_count"] != VPN_CANDIDATE_CASE_COUNT:
        raise ValueError("VPN candidate manifest must declare exactly 20 cases")
    files = manifest["files"]
    if not isinstance(files, dict) or set(files) != {
        "dataset-card.yaml",
        "vpn-cases.json",
    }:
        raise ValueError("VPN candidate manifest must pin its card and case file")
    verified_hashes: dict[str, str] = {}
    for relative_path, expected_hash in files.items():
        if not isinstance(expected_hash, str) or not expected_hash.startswith(
            _SHA_PREFIX
        ):
            raise ValueError("VPN candidate file hash must be sha256-prefixed")
        actual_hash = sha256_file(root / relative_path)
        if actual_hash != expected_hash:
            raise ValueError(f"VPN candidate file hash mismatch: {relative_path}")
        verified_hashes[relative_path] = actual_hash

    case_document = _load_object(root / "vpn-cases.json")
    if set(case_document) != {"schema_version", "dataset_id", "version", "cases"}:
        raise ValueError("VPN case document uses an unexpected field set")
    if (
        case_document["dataset_id"] != manifest["dataset_id"]
        or case_document["version"] != manifest["version"]
    ):
        raise ValueError("VPN case document does not match its manifest identity")
    raw_cases = case_document["cases"]
    if not isinstance(raw_cases, list) or len(raw_cases) != VPN_CANDIDATE_CASE_COUNT:
        raise ValueError("VPN case document must contain exactly 20 cases")
    cases = tuple(VpnCaseDefinition.from_mapping(value) for value in raw_cases)
    case_ids = [case.case_id for case in cases]
    scenarios = [case.scenario for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("VPN candidate case IDs must be unique")
    if len(scenarios) != len(set(scenarios)):
        raise ValueError("VPN candidate scenarios must be unique")
    if case_ids != sorted(case_ids):
        raise ValueError("VPN candidate cases must use stable case-ID order")
    return VpnCaseSet(
        dataset_id=str(manifest["dataset_id"]),
        version=str(manifest["version"]),
        root=root,
        cases=cases,
        file_hashes=MappingProxyType(verified_hashes),
        manifest_hash=sha256_file(manifest_path),
    )


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"VPN candidate file must contain an object: {path.name}")
    return value
