# WP-119-a1 WP109 Historical Oracle Isolation Handoff

## Chain

- `SESSION_ROLE=S7-INTEGRATION`
- `CHAIN_ID=CHAIN-M10-KNOWLEDGE-01`
- `STEP_ID=M10-09B-S7-WP109-ORACLE-ISOLATION`
- `WORK_PACKAGE=WP-119-R2`
- `ATTEMPT_ID=WP-119-a1-integration-r1`
- `BLOCKER=S7-WP119-A1-001`
- `FEATURE_IDS=FP-KNOW-010`
- `BASE_COMMIT=a71656ef292cc06b6f6831c58aadc827c0bc9f0d`
- `CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- `NEXT_ROLE=S1-ARCH`

## Outcome

`PASS_HANDOFF`

`S7-WP119-A1-001` is closed. WP-109 no longer imports the ambient M10
acceptance runner or evaluation registry when reproducing the M9 evidence.
The verifier materializes the recorded M9 S7 candidate
`59f898ab8b24eb08ef5df7fc74eeeed39ea8b88b` from `git archive` into an
ephemeral directory and runs the historical runner, evaluation objects, Case
set, and executor registry in an isolated Python process rooted at that
snapshot.

## Preserved historical claims

- Official denominator: `156` unique Cases.
- Historical executors: M7=`24`, M8=`6`, M9=`9`; exactly three executors.
- Historical outcome: `39 completed / 117 explicit_failed / 0 skipped / 0 quarantined`.
- Registry policy: `unique_exact_case_digest`.
- Executor IDs and versions remain pinned to the three M9 registrations at
  version `1.0.0`.
- Duplicate matches, dangerous output, cross-tenant success, and Judge use: `0`.
- Manifest Gate remains `FAIL`; `RELEASED=false`; `FROZEN=false`.

M10's fourth executor and `40/116` state remain owned by WP-119/WP-120 and are
not incorporated into this historical verifier.

## Protection boundary

The parent verifier still independently proves:

- WP-108 input ancestry to the recorded WP-109 candidate;
- WP-109 candidate delta contains only authorized S7 paths;
- contracts, migrations, lock, OPA bundle, apps, and packages input objects
  retain their recorded Git object IDs;
- the historical WP-108 Handoff and Proof bytes match their pinned hashes.

Historical source execution cannot bypass those Git checks. Existing
non-ancestor, unauthorized successor, and protected-object drift negatives are
retained. New regressions reject executor ID drift, executor version drift, and
duplicate Case matching.

## Changed paths

- `scripts/integration/verify_m9_composition.py`
- `tests/integration/m9/test_wp109_composition.py`
- `tests/integration/evidence/WP-119-a1-WP109-ORACLE-HANDOFF.md`

No production, Contract, lock, migration, acceptance runner, evaluation, or
current M10 candidate file changed.

## Verification

- Exact reproduced failure before repair:
  - `test_wp109_recomputes_unique_official_registry`: FAIL with
    `product executor registry identity drifted` after ambient M10 registration.
- `uv run --frozen python -m pytest tests/integration/m9 -q`
  - PASS: `8 passed in 14.09s`.
- `uv run --frozen ruff check scripts/integration/verify_m9_composition.py tests/integration/m9/test_wp109_composition.py`
  - PASS.
- `git diff --check`
  - PASS.
- `flowpilot_security.scan_secret_material` changed-file finding-set delta
  against the exact Base
  - PASS: `0` new finding families.

No current official 156 Runner, Compose, online Provider, or Release gate was
run.

## Risks

- The archive subprocess depends on the recorded Git object remaining locally
  reachable, which is already required by the ancestry and object protection
  gates.
- This verifies M9 history only. It intentionally makes no claim about the M10
  executor outcome.
- S7 does not approve its own composition result.

## Reuse and duplicate avoidance

- Reused the pinned WP-108 Handoff/Proof hashes and M9 protected object IDs.
- Did not rerun or reinterpret the current M10 official Runner.
- Did not alter the fixed M9 expectations to match current repository state.

## Sub-agent summary

No sub-agent was used.

## Learning candidate

`Historical executable evidence must resolve both source files and Python import roots from the recorded revision; pinning only the candidate Head is insufficient.`

## Next action

S1 independently reproduces the committed WP-109 integration suite and reviews
the archive/import isolation. Do not wake S4 from this handoff.
