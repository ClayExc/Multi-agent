# WP-000 rc2 五角色复审记录：BABF5689

## 评审目标

- ContractSet：`flowpilot-m0-contracts-v1-rc2`
- 内容摘要：`sha256:babf5689a720b66bb2dfa3f195caf729949f143d830493098446fe9f6c824d94`
- 评审模式：只读实现基线复审
- 结果：`REJECTED_BY_REVIEW`

## 角色结论

| 角色 | 结论 | Gate | 处置 |
|---|---|---|---|
| S2-RUNTIME | `ACCEPT` | `PASS` | 结论只绑定本摘要；新摘要需重审 |
| S3-PLATFORM | `REJECT` | `PASS` | 接受 `S3-RC2-001`；修正 Approval Tool Schema Hash 绑定并补语义负例 |
| S4-QUALITY | `ACCEPT` | `PASS` | 结论只绑定本摘要；新摘要需重审 |
| S5-CORE | `ACCEPT` | `PASS` | 结论只绑定本摘要；新摘要需重审 |
| S6-DATA | `ACCEPT` | `PASS` | 结论只绑定本摘要；新摘要需重审 |

## 阻断处置

`approval.sod.valid.tool_schema_hash` 与 `tool_request.bound_identities.valid.planned_action.tool.schema_hash` 不一致，而原语义门禁未比较两者。严格 Gateway 会拒绝官方正例，因此该摘要不能成为实现基线。

S1 处置：

1. 将 Approval 正例及相关负例的 Tool Schema Hash 对齐 PlannedAction。
2. 在 Approval 与 ToolRequest 跨对象语义门禁中强制比较 Tool Schema Hash。
3. 强制 Approval、PlannedAction、PolicyDecision 的 `policy_version` 和 `expires_at` 一致。
4. 增加 Schema Hash、策略版本和过期绑定错配负例。
5. 修正 `contracts/README.md` 的五评审者说明。
6. 重新计算 Artifact Hash 和 ContractSet `content_digest`，五角色重新评审。

本记录不构成 Review Attestation；ContractSet 的五条 Review 保持 `PENDING`。
