# WP-120：M10 组合验证

- 状态：BLOCKED
- Attempt：WP-120-a1
- Owner：S7-INTEGRATION
- 风险：R2
- Feature：FP-FLOW-003、FP-MCP-001/002、FP-SEC-003、FP-DATA-001、FP-EVAL-001/002
- 依赖：WP-119
- 执行：ORDERED / FINAL_GATE

在精确线性 Head 上复算 Contract、Lock、Migration、知识 Schema Pin、固定分母和授权范围；
使用隔离 PostgreSQL/pgvector、Redis、API、Gateway、Worker 与 Web 验证真实本地闭环。

写入 `scripts/integration/**`、`tests/integration/**`、`artifacts/integration/**`。验证导入、更新、
撤销、删除、重建、混合检索、稳定引用、跨租户 0、恶意文档 0、恢复和清理残留 0。S7 只向
S1 交接，不批准自身结果，也不自动启动 M11。
