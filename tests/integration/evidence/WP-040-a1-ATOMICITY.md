# WP-040-a1 Cross-component Failure Case

## Identity

- Case ID: `WP040-A1-CF-001`
- Severity: `P1` when whole input Heads are proposed as separate mainline merges
- Candidate: `56c90b1355213357415778bda43fc3acf96aa8ed`
- ContractSet:
  `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- Owner of final decision: S1-ARCH

## Outcome

There is no ordering of the three complete input Heads that keeps every newly
introduced package and the root Workspace/lock closure independently runnable
after every mainline merge.

This does not invalidate the final candidate. The three full input deltas are
pairwise path-disjoint, and the complete candidate passes all reproduced gates.
It means S1 must integrate the complete candidate atomically, or construct an
equivalent atomic merge, instead of replaying the S7 temporary merge parents as
three separately accepted mainline states.

## Dependency evidence

1. S5 provides the Application/Domain Port changes consumed by S6.
2. S6 provides `flowpilot-persistence`, consumed directly by S2 Worker.
3. The S5 Head also installs the final nine-member root Workspace and `uv.lock`.
4. The isolated S5 Head lacks six member trees supplied by S2/S6:
   `apps/worker`, `packages/agent-runtime`, `packages/context`,
   `packages/graph`, `packages/model-gateway`, and `packages/persistence`.
5. S2 and S6 do not own or update the final root Workspace/lock.

Therefore:

- Placing S5 before the final step creates a root Workspace that references
  missing members.
- Placing S5 last leaves already merged S2/S6 packages outside the final root
  Workspace/lock until that last step.
- S2 before S6 introduces a direct package dependency whose implementation is
  absent.

The remediation chain order `S6 -> S2 -> S5` was the implementation and handoff
dependency order. It is not proof that three separately accepted mainline
states are fully closed.

## Reproduction

```powershell
python scripts/integration/verify_wp040.py `
  --output-dir artifacts/integration/runs/WP-040-a1
```

Expected evidence:

```text
WP040_COMPOSITION_PASS checks=36 failed=0
```

The generated Manifest records:

```text
recommended_mainline_mode=ATOMIC_FINAL_CANDIDATE
safe_whole_input_sequential_order=null
temporary_construction_is_mainline_order=false
```

## Unlock condition

S1 either:

1. accepts the complete S7 candidate as one atomic mainline transition; or
2. constructs an equivalent final tree in a private integration branch and
   reruns the WP-040 manifest and joint gates before a single mainline update.

The intermediate S7 merge commits are construction evidence only. They are not
individual release or mainline acceptance points.
