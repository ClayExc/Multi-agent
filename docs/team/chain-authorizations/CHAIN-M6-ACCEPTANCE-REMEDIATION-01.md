# CHAIN-M6-ACCEPTANCE-REMEDIATION-01

```text
CHAIN_ID=CHAIN-M6-ACCEPTANCE-REMEDIATION-01
STATUS=ACTIVE
EXECUTION_MODE=ORDERED
RISK_CLASS=R2
BASE_COMMIT=b7fef3da91895b85a48e6c4974a61e5f1071b4e3
CONTRACT_CONTENT_DIGEST=sha256:f3c2dd6eb7d398d9a0a0891110cbc913bb998ed72208ea179a644c97af655e56
USER_GATE_REQUIRED=no
FINAL_USER_GATE_REQUIRED=yes
```

## Ordered steps

1. `M6-REM-01-S4`：WP-031 验收器与证据 fail-closed 修复。
2. `M6-REM-02-TYPES`：按 S2/S4/S5 路径 Owner 修复 strict Mypy；仅在 Step 1 接受后激活。
3. `M6-REM-03-S1-CONTRACT`：S1 修复审签语义门禁并生成新候选摘要。
4. `M6-REM-04-REVIEWS`：S2～S6 对新摘要执行 DELTA 复审。
5. `M6-REM-05-JUDGE`：人工 Judge 双轮盲审与校准门禁；未达阈值保持 no-effect。
6. `M6-REM-06-S7`：独立组合与最终验收；结束后停在用户门禁。

## 当前授权

- Step 1 已由 S1 验收并以 `--ff-only` 集成至 `71afa72a4975a506796e1e02d8d475d142616652`。
- 现授权 Step 2 按 [`WP-032`](../work-packages/WP-032-strict-type-hardening.md) 的三个互斥分片 `PARALLEL` 执行。
- Step 3～6 仍由前一步 S1 验收结果逐步解锁，不允许提前写入。

## 停止条件

- 公共契约、架构不变量或安全边界需要非兼容变化。
- 写入范围越权、工作树不洁净或输入 Head 不一致。
- 真实 Case 执行需要尚不存在的产品能力，且无法在 S4 路径内失败关闭。
- 任一 P0/P1 未形成可复现证据。
