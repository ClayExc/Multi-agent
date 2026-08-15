"""Generate the deterministic WP-093 acceptance proof from raw black-box cases."""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

from tests.acceptance.engineering_control.blackbox import build_proof, canonical_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    destination = Path(args.output).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="flowpilot-wp093-") as temporary:
        proof = build_proof(Path(temporary))
    content = canonical_json(proof)
    temporary_output = destination.with_suffix(destination.suffix + ".tmp")
    temporary_output.write_bytes(content)
    os.replace(temporary_output, destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
