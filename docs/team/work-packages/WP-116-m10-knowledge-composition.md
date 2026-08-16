# WP-116：知识 API、组合与 Workspace 闭包

- 状态：BLOCKED
- Attempt：WP-116-a1
- Owner：S5-CORE
- 风险：R2
- Feature：FP-UI-001、FP-DATA-001、FP-SEC-003
- 依赖：WP-115
- 执行：ORDERED

提供本地知识管理/诊断 API、生产组合入口、端口装配和全仓依赖锁。管理写操作重验 Cookie
身份、SecurityContext、策略、职责与幂等；普通查询只返回授权安全投影。

写入 `apps/api/**`、`packages/application/**`、`tests/core/**`、`pyproject.toml`、`uv.lock`、
`Makefile`。不实现 Web、数据库、MCP 或 Runtime。验证导入/更新/撤销/删除/重建、稳定错误、
并发和依赖闭包。PASS 后唤醒 S2 WP-117。
