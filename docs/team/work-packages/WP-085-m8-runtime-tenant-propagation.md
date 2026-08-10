# WP-085：M8 Runtime 身份传播与恢复重验

## 元数据

- 状态：BLOCKED
- Attempt：WP-085-a1
- Owner：S2-RUNTIME
- Reviewer：S4-QUALITY、S1-ARCH
- 风险：R2
- Feature：FP-SEC-001、FP-SEC-007、FP-OPS-001
- 依赖：WP-083、WP-084 Join
- 执行：与 WP-086 `PARALLEL`
- 子 Agent：`read-only/bounded-write`，最多 2 个；同一 Worktree 单写者

## 目标与输出

Worker 在取租约、Graph 恢复、Handoff 和工具提案前解析当前 SecurityContext；Graph、
Context、Checkpoint 只保存 ref/hash 与既有安全字段。MCP Client Transport 使用独立
工作负载身份，不携带用户 Token。

## 允许路径

`apps/worker/**`、`packages/graph/**`、`packages/context/**`、`packages/agent-runtime/**`、
`packages/model-gateway/**`、`tests/runtime/**`。

## 必须测试

正常传播、撤销/过期、模型/State 篡改 tenant/role、Handoff 重建、Interrupt/Resume、
Worker 重启、历史 Checkpoint、错 workload audience，以及 State/Trace/Checkpoint 中
Bearer/Refresh/Client Secret 出现次数 0。

## 非目标

身份签发、API 会话、Keycloak、RLS、策略判定。
