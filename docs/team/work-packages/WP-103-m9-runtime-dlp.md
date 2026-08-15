# WP-103：Runtime 模型边界 DLP

## 元数据

- 状态：BLOCKED
- Owner：S2-RUNTIME
- Attempt：WP-103-a1
- 风险：R2
- Feature：FP-SEC-005、FP-SEC-006、FP-OPS-003
- 依赖：WP-102
- 执行：ORDERED
- 写入：`packages/context/**`、`packages/agent-runtime/**`、`packages/model-gateway/**`、`apps/worker/**`、`tests/runtime/**`、`tests/runtime/evidence/WP-103-a1-HANDOFF.md`

## 主写目标

复用 S3 的集中安全 Port，在 Prompt/Context 发往 Provider 前和模型结构化输出进入 Graph
前执行确定性 DLP 与注入检查，同时保留 LangGraph 唯一状态权威。

## 验收

- Prompt、摘要、Handoff、SDK 输入和模型输出覆盖正常、阻断、脱敏及 Provider 故障。
- Provider Session、隐藏思维链、凭据和未经允许的工具指令不能进入业务状态或 Trace。
- Interrupt/Resume、Checkpoint 和重试不会重复模型调用或绕过再次检查。
- Runtime 定向/恢复测试、Ruff、strict Mypy、Contract 与 Secret Scan 通过。

## 非目标

不改变 S3 规则、应用 API、数据库和 Web。完成后唤醒 S5 WP-104。
