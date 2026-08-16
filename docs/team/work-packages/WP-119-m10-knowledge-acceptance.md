# WP-119：M10 固定分母验收

- 状态：BLOCKED
- Attempt：WP-119-a1
- Owner：S4-QUALITY
- 风险：R2
- Feature：FP-EVAL-001/002、FP-SEC-003
- 依赖：WP-118
- 执行：ORDERED / HOT_CONTINUE

为真实接通的 M10 能力注册独立版本化执行器，并在唯一 156 Case Runner 中运行。不得修改
固定分母、Case、skip/quarantine 或 M7/M8/M9 执行器身份；未实现 Case 继续明确失败。

写入 `packages/evaluation/**`、`evals/**`、`tests/acceptance/**`、`artifacts/acceptance/**`、
`scripts/acceptance/run_acceptance.py`。必须覆盖跨租户、过期、低相关、恶意文档、引用漂移、
删除/重建和确定性排序。PASS Handoff 唤醒 S7 WP-120。
