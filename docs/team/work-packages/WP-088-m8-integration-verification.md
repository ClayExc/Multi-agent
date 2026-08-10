# WP-088：M8 组合验证

## 元数据

- 状态：BLOCKED
- Attempt：WP-088-a1
- Owner：S7-INTEGRATION
- Reviewer：S1-ARCH
- 风险：R2
- Feature：FP-SEC-001、FP-SEC-002、FP-SEC-007、FP-OPS-001、FP-EVAL-002
- 依赖：WP-087
- 执行：ORDERED / FINAL_GATE
- 子 Agent：默认只读，最多 2 个；验证器写入仍遵守单写者

## 目标与输出

在独立组合树复算精确 Heads、Handoff Hash、Contract digest、依赖锁、Migration、空环境
Keycloak/PostgreSQL/Redis 和 M8 黑盒，生成 Handoff/Proof 后交回 S1；S7 不批准自身结果。

## 允许路径

`scripts/integration/**`、`tests/integration/**`、`artifacts/integration/**` 生成器。

## 必须测试

M8 静态 Manifest、锁定环境、相关 unit/security/acceptance/integration、空卷 Keycloak
导入、RLS、Worker 恢复、跨租户 0、用户 Token 到 MCP 0、Secret Scan 和资源清理 0。

## 非目标

修生产代码、改变 Contract、合并、发布或自动启动 M9。
