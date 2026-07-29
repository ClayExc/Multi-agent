# Integration evidence artifacts

`scripts/integration/verify_wp040.py` writes deterministic composition manifests
and evidence reports below `artifacts/integration/runs/`.

Generated run output is intentionally ignored. The S7 Handoff records the exact
command, candidate commit, and SHA-256 values needed to reproduce a run from a
clean checkout.
