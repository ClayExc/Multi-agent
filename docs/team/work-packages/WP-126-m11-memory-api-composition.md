# WP-126：短期记忆 API、清理与组合

- 状态：BLOCKED
- Attempt：WP-126-a1
- Owner：S5-CORE
- 风险：R2
- Feature：FP-CTX-001/002/004、FP-UI-001、FP-DATA-001
- 依赖：WP-125
- 执行：ORDERED

提供任务内记忆安全投影、Context Manifest 查询和清理 Application/API Port，完成 Worker/API/
Persistence 组合与 Workspace/Lock。API 只接受 Cookie-only 可信身份，不允许客户端写 verified
facts、策略、角色或审批。

写入 `apps/api/**`、`packages/application/**`、`tests/core/**`、`pyproject.toml`、`uv.lock`、
`Makefile`。覆盖错租户、过期 Context、并发清理、重复删除、稳定错误和最小返回字段。PASS 后
交接 S4。
