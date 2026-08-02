"""Run the WP-030 dependency-free offline contract and fixture gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.evaluation.canonical import load_json_strict  # noqa: E402
from packages.evaluation.validation import (  # noqa: E402
    OfflineRepositoryValidator,
    ValidationFinding,
)

DEFAULT_CASES = (
    ROOT / "evals" / "fixtures" / "minimal-functional-case.v1.json",
    ROOT / "evals" / "fixtures" / "minimal-safety-fault-case.v1.json",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate FlowPilot contract hashes, refs and offline cases.",
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--case",
        action="append",
        type=Path,
        dest="cases",
        help="EvaluationCase JSON to validate; defaults to WP-030 minimal fixtures.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    validator = OfflineRepositoryValidator(args.root)
    findings = validator.validate_repository()
    case_paths = args.cases or list(DEFAULT_CASES)
    cases: list[dict[str, Any]] = []
    for path in case_paths:
        try:
            case = load_json_strict(path)
        except (OSError, UnicodeError, ValueError) as exc:
            findings.append(ValidationFinding("CASE_JSON_INVALID", str(path), str(exc)))
        else:
            if not isinstance(case, dict):
                findings.append(
                    ValidationFinding(
                        "CASE_JSON_INVALID",
                        str(path),
                        "case must be a JSON object",
                    )
                )
            else:
                cases.append(case)
    findings.extend(validator.validate_evaluation_cases(cases))
    findings.sort(key=lambda item: (item.path, item.code, item.message))
    result = {
        "gate": "pass" if not findings else "fail",
        "repository_root": str(args.root.resolve()),
        "case_count": len(cases),
        "findings": [
            {
                "code": finding.code,
                "path": finding.path,
                "message": finding.message,
            }
            for finding in findings
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
