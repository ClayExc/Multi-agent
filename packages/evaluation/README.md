# Offline evaluation boundary

This package implements the WP-030 offline quality boundary without Runtime,
Gateway, API, RLS, Outbox, Provider, or model dependencies.

Public responsibilities:

- validate ContractSet content/hash bindings, Schema references, Traceability,
  Registry, Dataset, Fixture, and minimal EvaluationCase inputs;
- aggregate every declared Case using `all_declared_cases`, counting `failed`,
  `skipped`, and `quarantined` as failures;
- keep Judge output semantic-only and subordinate to deterministic assertions;
- generate deterministic, secret-scanned acceptance bundle skeletons;
- create structured Feature evidence only for the declared independent verifier.

Run the dependency-free offline gate from the repository root:

```text
python scripts/acceptance/validate_offline.py
```

The two JSON files under `evals/fixtures/` are synthetic skeleton fixtures. They
are not entries in the candidate Dataset Manifest and do not claim completion of
the 120 functional or 36 safety/fault cases.
