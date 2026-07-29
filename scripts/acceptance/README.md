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
rate. `make acceptance` remains outside WP-030 until its shared-file work package
is assigned.
