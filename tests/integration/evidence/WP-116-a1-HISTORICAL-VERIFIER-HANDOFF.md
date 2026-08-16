# WP-116-a1 Historical Verifier Isolation Handoff

## Chain

- `CHAIN_ID=CHAIN-M10-KNOWLEDGE-01`
- `STEP_ID=M10-06D-S7-HISTORICAL-VERIFIER-ISOLATION`
- `WORK_PACKAGE=WP-116-R3`
- `ATTEMPT_ID=WP-116-a1-integration-fixture`
- `SESSION_ROLE=S7-INTEGRATION`
- `FEATURE_IDS=FP-KNOW-010`
- `BASE_COMMIT=d57782c3cf08fc52ee4a89dd5410ef0bb4f34ae4`
- `CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- `NEXT_ROLE=S1-ARCH`

## Outcome

`PASS_HANDOFF`

The ten reproduced failures were historical-fixture time drift, not M10 product
failures. WP-094 and WP-109 now validate their recorded S7 candidate commits by
default. WP-040 candidate, final, workspace, migration, and deterministic
artifact checks run against a temporary detached checkout of the recorded
historical fixture commit. The current M10 checkout is no longer treated as a
historical fact.

## Historical anchors

- WP-094 input: `80eba3066bc7dfe3ed91985343881b89d280ac17`
- WP-094 candidate: `b7ab61248793456db4e011b3e03a50421b98f963`
- WP-109 input: `f0b9c529e6408dd8faa53a734bb4e8dcb3844864`
- WP-109 candidate: `59f898ab8b24eb08ef5df7fc74eeeed39ea8b88b`
- WP-040 fixture: `41a11fc66536178299d91ce8600ce46107f34f2d`

The WP-040 snapshot is materialized with a local shared clone and detached
checkout in pytest's temporary directory. Migration missing/tamper/extra-head
negative cases copy only that snapshot and mutate only their temporary copy.
Historical migration hashes, candidate heads, and artifact hashes were not
updated to M10 values.

## Changed paths

- `scripts/integration/verify_engineering_control.py`
- `scripts/integration/verify_m9_composition.py`
- `scripts/integration/verify_wp040.py`
- `tests/integration/engineering_control/test_wp094_verifier.py`
- `tests/integration/m9/test_wp109_composition.py`
- `tests/integration/test_wp040_composition.py`
- `tests/integration/evidence/WP-116-a1-HISTORICAL-VERIFIER-HANDOFF.md`

No product, Contract, lock, workspace, migration, infrastructure, or acceptance
file changed.

## Verification

- `uv run --frozen python -m pytest tests/integration/engineering_control tests/integration/m9 tests/integration/test_wp040_composition.py -q`
  - PASS: `51 passed in 74.63s`
  - Includes the ten originally failing cases and the retained non-ancestor,
    unauthorized-path, protected-object-drift, missing-migration,
    migration-tamper, and illegal-successor failure-closed cases.
- `uv run --frozen ruff check scripts/integration/verify_engineering_control.py scripts/integration/verify_m9_composition.py scripts/integration/verify_wp040.py tests/integration/engineering_control/test_wp094_verifier.py tests/integration/m9/test_wp109_composition.py tests/integration/test_wp040_composition.py`
  - PASS: all checks passed.
- `git diff --check`
  - PASS.
- `flowpilot_security.scan_secret_material` changed-file finding-set delta
  against `d57782c3cf08fc52ee4a89dd5410ef0bb4f34ae4`
  - PASS: `0` new finding families; Handoff scan also returned `0` findings.

Per the work package, no full repository test, Compose, Release gate, or current
candidate generation was run.

## Risks and claims

- Historical verifiers remain milestone-specific and do not validate the M10
  candidate; WP-120 owns the current/future candidate.
- No ancestry, authorized-path, protected-tree, migration-chain, or migration
  hash check was relaxed.
- `RELEASED=false`; `FROZEN=false`; S7 does not approve its own result.
- `LEARNING_CANDIDATE=Historical evidence tests must resolve files and candidate identity from an immutable recorded revision, never from ambient HEAD.`

## Sub-agent summary

No sub-agent was used for this remediation.

## Next action

S1 independently reproduces the committed historical verifier suites and
reviews the recorded revision boundaries. Do not wake S5 from this handoff.
