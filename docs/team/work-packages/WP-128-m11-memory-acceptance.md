# WP-128：短期记忆、长上下文与消融验收

- 状态：BLOCKED
- Attempt：WP-128-a1
- Owner：S4-QUALITY
- 风险：R2
- Feature：FP-CTX-001～005、FP-EVAL-001/002
- 依赖：WP-127
- 执行：ORDERED / HOT_CONTINUE

构建 50 轮长对话、摘要漂移、矛盾、Handoff、预算、重启、删除和跨租户黑盒；用相同模型、
任务、Prompt 目标和工具运行 Baseline/Optimized，报告 P50/P95 Token、质量、引用、安全、延迟
和成本，不预填 24%。

只为精确接通的 `long_context_handoff` Case 注册独立版本化执行器；固定 156 分母、Case、
skip/quarantine 和 M7～M10 执行器身份不得修改。写入 `packages/evaluation/**`、`evals/**`、
`tests/acceptance/**`、`artifacts/acceptance/**`、`scripts/acceptance/run_acceptance.py`。PASS 后
交接 S7。
