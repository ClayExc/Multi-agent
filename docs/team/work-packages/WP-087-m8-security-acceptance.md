# WP-087：M8 身份租户黑盒验收

## 元数据

- 状态：BLOCKED
- Attempt：WP-087-a1
- Owner：S4-QUALITY
- Reviewer：S1-ARCH
- 风险：R2
- Feature：FP-SEC-001、FP-SEC-002、FP-SEC-007、FP-EVAL-002
- 依赖：WP-081～WP-086 Join
- 执行：ORDERED
- 子 Agent：只读/测试实现，最多 2 个；同一 Worktree 单写者

## 目标

从 Keycloak→API→Worker/Graph→MCP→PostgreSQL 建立独立黑盒矩阵，并为 M8 适用的
固定 Case 注册产品执行器；固定 156 分母不得缩减或 skip。

## 允许路径

`packages/evaluation/**`、`packages/observability/**`、`evals/**`、`tests/acceptance/**`、
`tests/experience/**`、`artifacts/acceptance/**` 生成器。

## 必须测试

所有产品入口 OIDC；跨租户读写 0；伪造角色/tenant、错 audience、过期/撤销、上下文
篡改、模型提权、连接复用和恢复绕过均失败；证据中零 Token/Secret。

## 非目标

修改生产实现、补 M9/业务链执行器、Judge 校准、宣称整体 RELEASED/FROZEN。
