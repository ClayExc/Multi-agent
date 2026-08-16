# WP-129：M11 组合验证

- 状态：BLOCKED
- Attempt：WP-129-a1
- Owner：S7-INTEGRATION
- 风险：R2
- Feature：FP-CTX-001～005、FP-DATA-001、FP-SEC-003、FP-EVAL-001/002
- 依赖：WP-128
- 执行：ORDERED / FINAL_GATE

在精确线性 Head 上复算 Contract、Lock、Migration、固定分母、Artifact Hash 和授权范围；使用
隔离 PostgreSQL/Redis、API、Worker、LangGraph 与 Web 验证 50 轮、重启、Handoff、CAS、TTL、
删除、跨租户 0、Secret 0 和清理残留 0。

写入 `scripts/integration/**`、`tests/integration/**`、`artifacts/integration/**`。S7 只向 S1
交接，不批准自身结果，也不自动启动 M12。
