# WP-120-a1 M10 Integration Verification Handoff

## Identity

- `SESSION_ROLE=S7-INTEGRATION`
- `CHAIN_ID=CHAIN-M10-KNOWLEDGE-01`
- `STEP_ID=M10-10-S7-INTEGRATION`
- `WORK_PACKAGE=WP-120`
- `ATTEMPT_ID=WP-120-a1`
- `INPUT_HEAD=ba725376af0bc8e8b7d118f3b965f35dd542682c`
- `CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- `NEXT_ROLE=S1-ARCH`

## Outcome

`PASS_HANDOFF`

WP-120 independently reproduced the committed M10 acceptance composition and
the current local integration boundary. S7 does not approve Release and does
not activate M11.

## Consumer gate

- S7 prior Head `df2283049d717e62cf16ff6361de5d04ac2e4203` was an ancestor of the exact input.
- Consumption used only `git merge --ff-only ba725376af0bc8e8b7d118f3b965f35dd542682c`.
- WP-119 Handoff SHA-256 matched `94ecb7832505cb09fd07eb53940d9248af6995e7897adc26d3392eb041033967`.
- WP-119 Proof SHA-256 matched `dbd785bd2f493674e9a2a03d38977fd2aa74c67b0adf5aa638264d96fabe1df8`.
- Contract digest matched; the input worktree was clean.

## Independent fixed-denominator and Artifact reproduction

S7 did not run the official acceptance Runner a second time. The exact S4
bundle remained available in its producer Worktree and was inspected from a
different verifier boundary:

- Recomputed all `55` Manifest Artifact hashes from the actual files: `0` mismatches.
- Recomputed `156` execution records: `40 completed`, `116 not_executed`, `0` skip, `0` quarantine.
- All 116 non-executed records used `EXECUTOR_NOT_REGISTERED`; no unsupported Case was presented as passing.
- Independently loaded the current Case registry and recomputed four exact
  executor registrations: M7=`24`, M8=`6`, M9=`9`, M10=`1`.
- Exactly `40` Cases matched one executor, `116` matched none, and `0` matched more than one.
- Six recorded engineering gates were PASS.
- Manifest gate remained `fail`; `RELEASED=false`; `FROZEN=false`.
- S4 Runner Head to the final input changed only the two authorized WP-119 evidence files; Contract, Migration, Lock, Workspace, product, Knowledge MCP, Persistence, API, Worker, evaluation and Web protected objects did not drift.

Machine proof: `artifacts/integration/WP-120-a1-PROOF.json`.

## Current M10 composition tests

The following current-tree combination was run once:

```text
uv run --frozen python -m pytest
  tests/core/test_knowledge_api.py
  tests/core/test_knowledge_core.py
  tests/data/security/test_knowledge_migration.py
  tests/data/security/test_pgvector_migration.py
  tests/data/unit/test_knowledge_content_projection.py
  tests/data/unit/test_knowledge_index.py
  tests/data/unit/test_knowledge_persistence.py
  tests/platform/test_knowledge_retrieval_mcp.py
  tests/platform/test_knowledge_search.py
  tests/acceptance/m10/test_retrieval_engine.py
  tests/acceptance/m10/test_knowledge_acceptance_executor.py
  tests/acceptance/m10/test_knowledge_web_blackbox.py -q
```

Result: `175 passed in 25.81s`.

This covers import/update/retire/delete/rebuild, stable citations, hybrid
retrieval, MCP/Gateway policy, malicious content rejection, cross-tenant zero,
diagnostics, recovery behavior and the Web boundary. It is a layered local
composition test, not a claim that every layer ran in one OS process.

## Isolated PostgreSQL/pgvector and Redis

A unique `flowpilot-wp120-a1` Compose project used an empty PostgreSQL volume
and the current `infra/compose/compose.yaml`. Only PostgreSQL and Redis were
started, with local placeholder credentials that were not stored in evidence.

- PostgreSQL and Redis health checks: PASS.
- `vector` extension: present.
- Migration `0001 -> ... -> 0007`: initialization PASS.
- Knowledge core tables checked: `5/5` present.
- Checked Knowledge tables with enabled and forced RLS: `5/5`.
- Keyword and vector indexes: `2/2`.
- Redis probe was written, `FLUSHDB` executed, final `DBSIZE=0`.
- Cleanup by Compose project labels: containers=`0`, volumes=`0`, networks=`0`.

The product behavior tests and real datastore checks are reported separately;
the datastore check is not mislabeled as an API/Web end-to-end black box.

## Other gates

- `tests/integration/m10`: `3 passed`.
- `uv lock --check`: PASS, `170` packages resolved.
- Contract Conformance: PASS, `20` schemas / `35` cases / `43` semantic cases / `52` features.
- Ruff on changed S7 source/tests: PASS.
- Strict Mypy on the two changed Python roots with external imports skipped:
  PASS, `Success: no issues found in 2 source files`.
- `git diff --check`: PASS.
- Secret scan: no new finding families in changed files; no credentials are present in Proof/Handoff.

## Changed paths

- `scripts/integration/verify_m10_composition.py`
- `tests/integration/m10/test_wp120_composition.py`
- `artifacts/integration/WP-120-a1-PROOF.json`
- `tests/integration/evidence/WP-120-a1-HANDOFF.md`

All paths are S7-owned. No production, Contract, Lock, Migration, Compose,
acceptance or other Owner file changed.

## Risks and non-claims

- The fixed Manifest remains failed solely because 116 executors are not registered.
- The only explicit online Provider smoke remains outside this local gate.
- A strict Mypy run that followed the entire imported acceptance graph surfaced
  three inherited errors in `tests/acceptance/platform_security/blackbox.py`
  and `tests/acceptance/m9/governance_security_probe.py`; neither file nor its
  production dependency changed in WP-120. The scoped S7 roots pass strict
  checking, so this is recorded as an advisory rather than relabeled PASS.
- This result means `ACCEPT_FOR_S1_FINAL_REVIEW`, not merged, released or frozen.
- S7 does not approve its own evidence and did not start M11.

## Reuse and duplicate avoidance

- Reused the producer's single official Runner execution while independently
  hashing every Artifact and recomputing registry matching from current source.
- Reused Owner unit/static conclusions only where protected Git objects were unchanged.
- Did not repeat the 575-test unit group, full acceptance Runner, full repository test, Wheel, or online Provider gate.

## Sub-agent summary

No sub-agent was used.

## Learning candidate

`LEARNING_CANDIDATE=Release integration should separate artifact-closure recomputation, current registry recomputation, layered product behavior, and live datastore evidence instead of collapsing them into one ambiguous end-to-end claim.`

## Next action

S1 independently checks the committed verifier, Proof and Handoff, then decides
the final M10 state. Do not automatically activate M11.
