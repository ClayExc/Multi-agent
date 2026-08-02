# WP-030 offline commands

Validate the activated rc2 repository inputs and the two minimal synthetic Cases:

```text
python scripts/acceptance/validate_offline.py
```

Generate a deterministic bundle from explicit metadata, declared Case IDs, and
Case results:

```text
python scripts/acceptance/generate_bundle.py \
  --metadata <metadata.json> \
  --declared-cases <declared-case-ids.json> \
  --results <case-results.json> \
  --output <artifacts/acceptance/run-id>
```

The generator never discovers or deletes Cases. Missing declared results fail,
and a zero-Case input produces an `empty` report with a failed gate and no success
rate.

## M6-1 acceptance orchestrator

`make acceptance` runs the full M6 verification loop in one command
(`scripts/acceptance/run_acceptance.py`):

1. Collect the 156 candidates (A 69 + B 52 + C 35 = 120 functional + 36
   safety/fault), enumerating by type (suite x category) and verifying each
   quota against the Evaluation Registry. Any missing/extra type aborts with
   `collection-errors.json` left behind as evidence.
2. Preflight every candidate, then dispatch it to an explicitly registered
   product executor. Missing executors, incomplete result bindings, absent
   execution evidence, or an uncalibrated required Judge fail closed. Case
   definitions and expected fields are never treated as observations. The
   structured ledgers `eval/execution-results.jsonl` and `eval/verdicts.json`
   record all 156 candidates.
3. Run the six test suites (unit/contract/integration/e2e/recovery/security)
   into `test-results/*.xml`; a suite with no usable target directory aborts
   with the same `collection-errors.json` evidence.
4. Assemble the acceptance bundle (`manifest.json` + `REPORT.md` + `eval/`),
   with `manifest.artifact_hashes` covering every artifact 1:1. Every executor
   evidence reference is canonicalized under `execution/`, rejected on path
   escape, duplication, conflict, or absence, and included in that hash map.

Usage:

```text
make acceptance
python scripts/acceptance/run_acceptance.py [--run-id run-20260802-120000]
```
