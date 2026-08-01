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

## M6 incremental-A candidate corpus (goal e1)

`incremental_a.py` curates and validates the incremental-A candidate corpus:
48 functional candidates (knowledge_qa_citation 24, clarification 16,
ticket_write_verification 8) and 21 safety/fault candidates (tenant_isolation 6,
rbac_abac_sod 6, prompt_injection_malicious_mcp 6,
approval_replay_tamper_duplicate_write 3), materialized under
`evals/datasets/m6-incremental-a/`.

Every candidate is a full EvaluationCase v1 instance bound to a Feature
(FP-EVAL-001/002), the released tenant/principal fixtures, registry rule
assertions, an offline data-source fixture under `evals/fixtures/`, and a safety
classification (`security-class:` / `gate:` tags). All 69 candidates pass
`OfflineRepositoryValidator.validate_evaluation_cases`; generation is
deterministic and fully offline (see `dataset-card.yaml` rebuild section).

## M6 incremental-B candidate corpus (goal B1)

`incremental_b.py` curates and validates the incremental-B candidate corpus:
40 functional candidates (business_read 16, ticket_write_verification 8,
approval_recovery 8, long_context_handoff 8) and 12 safety/fault candidates
(approval_replay_tamper_duplicate_write 3, dependency_failure_unknown 6,
secret_dlp_audit 3), materialized under `evals/datasets/m6-incremental-b/`.
It follows the same EvaluationCase v1 binding rules as incremental A and adds
released long-context/handoff assertions (`assert.context.within_budget.v1`,
`assert.handoff.fields_allowed.v1`) and UNKNOWN-reconciliation assertions
(`assert.event.sequence_complete.v1`); new offline fault profiles for the
dependency-failure and secret/DLP/audit categories live under
`evals/fixtures/fault-profiles/`. All 52 candidates pass
`OfflineRepositoryValidator.validate_evaluation_cases` (0 findings).
Cumulative with incremental A: 88 functional + 33 safety = 121 candidates.
