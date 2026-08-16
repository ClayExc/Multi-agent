# WP-104：治理查询 Port 与 API

## 元数据

- 状态：ACCEPTED_M9
- Owner：S5-CORE
- Attempt：WP-104-a1
- 风险：R2
- Feature：FP-SEC-004、FP-OBS-002、FP-OBS-003
- 依赖：WP-103
- 执行：ORDERED
- 写入：`packages/application/**`、`apps/api/**`、`tests/core/**`、`tests/core/evidence/WP-104-a1-HANDOFF.md`、`pyproject.toml`、`uv.lock`、`Makefile`

## 主写目标

定义治理查询 Application Port 和受控 FastAPI 读接口，返回策略版本、策略决定、Audit、
Security Event 和关联链的安全投影；同时收口 M9 Workspace/Lock。

## 验收

- Cookie-only 可信身份进入，tenant/role/purpose/context 每次请求重验。
- 普通用户、跨租户、过期/撤销 Context、伪造游标和敏感查询字段均拒绝。
- API 不返回 Rego 输入全文、Prompt、原始参数/结果、凭据或隐藏思维链。
- Core/API 测试、Ruff、strict Mypy、锁检查、Wheel 与 Secret Scan 通过。

## 非目标

不实现数据库 Repository、OPA Infra 或 Web。完成后唤醒 S6 WP-105。
