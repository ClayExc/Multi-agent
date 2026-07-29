"""Generate an offline acceptance bundle from explicit JSON inputs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.evaluation.reporting import (  # noqa: E402
    CaseResult,
    generate_acceptance_bundle,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate deterministic FlowPilot offline acceptance artifacts.",
    )
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--declared-cases", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    declared_case_ids = json.loads(args.declared_cases.read_text(encoding="utf-8"))
    raw_results = json.loads(args.results.read_text(encoding="utf-8"))
    if not isinstance(declared_case_ids, list):
        raise SystemExit("--declared-cases must contain a JSON array")
    if not isinstance(raw_results, list):
        raise SystemExit("--results must contain a JSON array")
    manifest = generate_acceptance_bundle(
        output_dir=args.output,
        metadata=metadata,
        declared_case_ids=declared_case_ids,
        results=[CaseResult.from_dict(item) for item in raw_results],
    )
    print(
        json.dumps(
            {
                "gate_result": manifest["gate_result"],
                "manifest": str((args.output / "manifest.json").resolve()),
                "report_state": manifest["report_state"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
