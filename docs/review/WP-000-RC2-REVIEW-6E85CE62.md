# WP-000 rc2 `6e85ce62` 候选就绪记录

- 裁决角色：S1-ARCH
- ContractSet：`flowpilot-m0-contracts-v1-rc2`
- 内容摘要：`sha256:6e85ce625879c108431ed79ab934127ddd5705d3ee3ddd4e1df347b5f1e2ac42`
- 状态：`candidate / AWAITING_FIVE_ROLE_DELTA_REVIEW`
- Review：S2～S6 全部 `PENDING`
- 发布状态：`NOT_FROZEN`

## 修复结论

旧 ContractSet 曾把 Review 条目的摘要机械更新为 `f3c2…`，但 Evidence 文件内容仍
声明 `0a82…`；旧验证器只比对文件 Hash，造成审签内容未绑定的假通过。本候选统一
校验 Evidence 内的角色、结论、摘要和必需字段，并拒绝缺失、重复与错配。

## S1 已运行门禁

```text
CONTRACT_CONFORMANCE_OK schemas=20 cases=35 positive=18 negative=17 mutation_cases=19 mutation_positive=3 mutation_negative=16 semantic_cases=43 semantic_positive=0 semantic_negative=43 audit_chain_cases=5 audit_chain_positive=1 audit_chain_negative=4 manifest_cases=21 manifest_positive=1 manifest_negative=20 review_attestation_cases=6 review_attestation_positive=1 review_attestation_negative=5 retired_review_attestation_cases=5 retired_review_attestation_positive=0 retired_review_attestation_negative=5 features=52
```

验证器与 Case Matrix 的文件 SHA-256、ContractSet Artifact Hash 和稳定内容摘要已
独立复算一致。五个旧 `RC2-0A82-*` Attestation 在文件 Hash 正确的条件下仍全部被
新摘要拒绝。

## 下一门禁

按 [`RC2_DELTA_REVIEW_6E85CE62.md`](../team/RC2_DELTA_REVIEW_6E85CE62.md)
并行执行五角色只读复审。S1 收到五份同摘要 ACCEPT 后，创建新的 Attestation
文件、写回生命周期 Review 字段并再次复跑门禁；在此之前不得恢复 ACTIVE 或声称
契约已冻结。
