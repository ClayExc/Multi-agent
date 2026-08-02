# WP-000 rc2 `1cad07bd` 实现基线审签证明

## 裁决

- ContractSet：`flowpilot-m0-contracts-v1-rc2`
- 内容摘要：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：`candidate / ACTIVE_ON_COMMIT`
- 发布级状态：`NOT_FROZEN`

## Review Attestation

| 角色 | 决定 | Evidence | SHA-256 |
|---|---|---|---|
| S2-RUNTIME | ACCEPT/PASS | `docs/review/attestations/RC2-1CAD-S2-RUNTIME.md` | `sha256:983876c3bb1f18123554bf5d68bff393decfd8c8cf4a2a86bdfccf70794237d7` |
| S3-PLATFORM | ACCEPT/PASS | `docs/review/attestations/RC2-1CAD-S3-PLATFORM.md` | `sha256:86d72307918c0bbba96e870e5c3d78b416d9e90a061f7e1b293821e4c01a63c6` |
| S4-QUALITY | ACCEPT/PASS | `docs/review/attestations/RC2-1CAD-S4-QUALITY.md` | `sha256:81104e62b83c6d93aa46f690e1d162d7104491e8d9855320bcc1b1424e31710c` |
| S5-CORE | ACCEPT/PASS | `docs/review/attestations/RC2-1CAD-S5-CORE.md` | `sha256:11b3a64ae7e9162d8b12d851788d3cebfa14386673a6bc868a0c5e9eb149a47d` |
| S6-DATA | ACCEPT/PASS | `docs/review/attestations/RC2-1CAD-S6-DATA.md` | `sha256:75e8f59a6c42960715268bce39d2e08b5cfe23b38f10c2885a72b71d3bf788e1` |

## 门禁

```text
CONTRACT_CONFORMANCE_OK schemas=20 cases=35 positive=18 negative=17 mutation_cases=19 mutation_positive=3 mutation_negative=16 semantic_cases=43 semantic_positive=0 semantic_negative=43 audit_chain_cases=5 audit_chain_positive=1 audit_chain_negative=4 manifest_cases=21 manifest_positive=1 manifest_negative=20 review_attestation_cases=10 review_attestation_positive=2 review_attestation_negative=8 retired_review_attestation_cases=5 retired_review_attestation_positive=0 retired_review_attestation_negative=5 features=52
```

Review 是生命周期字段，不进入稳定内容摘要。本证明恢复实现基线审签，但 Registry、
Dataset、Fixture、Traceability 和 Judge 校准尚未达到发布冻结条件，因此不得称为
`frozen` 或 `released`。
