# WP-011-a2 / WP-021-a1 S5↔S6 对齐

## 基本信息

- S5 Work Package：WP-011 / WP-011-a2
- S6 Work Package：WP-021 / WP-021-a1
- 责任会话：S5-CORE（共享 Python Workspace 单写者）
- 对齐会话：S6-DATA
- 风险等级：R2
- S5 分支：`codex/s5/wp-011-core-bootstrap`
- S5 对齐前提交：`02f29b68c611806bd9a67fb8e96629d4647e0551`
- S5 对齐实现提交：`c97c551a5d89298934d99a3d3606e833921d2a2b`
- S6 分支：`codex/s6/wp-021-data-bootstrap`
- S6 实现提交：`2cd2210e895f2a9d613e59178e27374b8685679b`
- S6 HANDOFF 提交：`3e0101999061a44a3a5b2fd455ec792e3f73954e`
- ContractSet 摘要：
  `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- 对齐结论：`ACCEPT_WITH_S6_FOLLOWUP`

S5 共享依赖、Domain 摘要和只读查询事务边界已经对齐。S6 的 H1
Command Repository/Inbox/UoW 适配通过联合测试；WP-011-a2 新增的完整 Task
投影查询仍需 S6 后续提交，不能在当前状态宣称 API→Persistence 全链路完成。

## 依赖请求裁决

- 请求：S6 `packages/persistence/DEPENDENCY_REQUEST.md`
  / `WP-021-DR-001`
- 决定：`ACCEPT`
- Workspace：加入 `packages/persistence` Member 和
  `flowpilot-persistence` Workspace Source。
- 生产依赖：
  - `sqlalchemy[asyncio]>=2.0,<3`，锁定 2.0.51。
  - `psycopg[binary,pool]>=3.2,<4`，锁定 Psycopg/Binary 3.3.4 和
    Pool 3.3.1。
  - `redis>=5.2,<6`，锁定 5.3.1。
- 稳定测试发现范围：加入 `tests/data`，保留 `tests/core` 和
  `tests/runtime`。
- Make 目标统一使用 `uv --all-packages`，集成树会安装所有已存在的
  Workspace 包，不依赖测试 `sys.path` 注入冒充可安装。

没有加入 Alembic；WP-021 使用显式 forward-only SQL Migration，当前没有
共享 Migration Runner 需求。

## 依赖、许可证与攻击面

| 依赖 | 用途 | 锁定版本 / 许可证 | 替代方案 | 攻击面与控制 |
|---|---|---|---|---|
| SQLAlchemy asyncio | 异步事务和未来 Driver Wrapper | 2.0.51 / MIT | Repository 直接使用 Psycopg | ORM/SQL 构造和连接状态；S6 只允许包内固定语句、绑定参数和每事务 Tenant 绑定 |
| Psycopg binary + pool | PostgreSQL 协议、异步连接和连接池 | 3.3.4 / LGPL-3.0-only；分发的 LICENSE 含 LGPL Section 3 Exception | asyncpg | 编译 Wheel、协议解析和池状态复用；锁文件固定制品，事务退出必须回滚/关闭，不接受调用方 SQL/Role/Table |
| redis-py | 可重建调度信号和缓存协调 | 5.3.1 / MIT | 自研 RESP Client | Redis 命令和 Key 组合；固定 Namespace、编码 Tenant/Task Segment，Redis 不保存业务事实或终态 |
| greenlet | SQLAlchemy asyncio 传递依赖 | 3.5.4 / MIT AND PSF-2.0 | 直接 Driver | 原生扩展；由锁文件和 Wheel 门禁固定 |
| PyJWT | redis-py 传递依赖 | 2.13.0 / MIT | 无（传递依赖） | 当前 FlowPilot 代码不调用 JWT API，不扩大身份权威边界 |
| tzdata | Psycopg 传递依赖 | 2026.3 / Apache-2.0 | 系统时区库 | 仅时区数据；Domain 仍强制带时区 UTC |

`pip-audit` 对独立 S5 环境和 S2+S5+S6 临时组合环境均报告
`No known vulnerabilities found`。本地 Editable `flowpilot-*` 包按工具规则
跳过漏洞数据库查询，由 Ruff、Mypy、测试和 Secret Scan 覆盖。

## 已解决：PlannedAction 摘要一致性

### S5-S6-ALIGN-001

- S6 报告：S5 `ActionResource.to_mapping()` 会省略值为 `null` 的可选
  `id`/`owner_id`，导致 Domain `PlannedAction.digest()` 与公共 RC2
  PlannedAction 原始映射的 RFC 8785 摘要不同。
- 证据：官方 Fixture 的 `resource.id=null`，Policy/Approval 绑定摘要为
  `sha256:25d521416733830fb9190d1e57b51ff406967dd3e1a2499822e15994d1c7f711`；
  修复前 Domain 计算为
  `sha256:fdc201c83782353f0a6d99ba9fcacd2adc77fc7bf97754959ea8cf5a6a04506b`。
- 修复：Domain 的规范化 Action Resource 映射始终显式输出
  `type`、`id`、`owner_id`，其中缺失值为 JSON `null`。
- 回归测试：官方 PlannedAction 完整 Round-trip，且 Domain Digest 与
  PolicyDecision/Approval 的固定摘要完全相等。

S6 后续应删除对原始 Mapping 单独计算摘要的分叉，改用
`PlannedAction.digest()` 或先规范化为 `PlannedAction.to_mapping()`，确保
Policy、Approval、Ledger 只有一个摘要算法。

## 已解决：Task 查询事务边界

- 保留 H1 `TaskRepositoryPort.get_version`、`CommandInboxPort` 和写
  `UnitOfWork` 的现有方法与语义。
- 新增只读 `TaskQueryUnitOfWork` / Factory；`tasks` 是只读属性，
  允许具体 Repository 类型以结构化 Protocol 协变。
- `TaskQueryService` 每次查询打开并退出 Unit of Work，Repository Adapter
  继续拥有 Tenant 绑定、事务回滚和连接清理。
- Fake、API 正常/缺失/跨 Tenant 查询及 Repository 故障映射测试通过。

## S6 必须跟进

### S5-S6-ALIGN-002：完整 Task 投影查询

S6 当前 `MemoryTaskRepository` 和 `PostgresTaskRepository` 只有
`get_version()`，不满足 `TaskQueryPort.get(tenant_id, task_id)`。严格 Mypy
结构化检查对两个 Repository 均返回 `arg-type`，因此当前不能把
`Memory/PostgresDataUnitOfWorkFactory` 注入 `TaskQueryService`。

S6 后续提交必须：

1. 为 Memory Repository 保存并按 `(tenant_id, task_id)` 返回完整不可变
   `flowpilot_domain.Task`，跨 Tenant 返回 `None`。
2. 为 Postgres Repository 查询 `flowpilot.tasks.projection`，使用
   `Task.from_mapping()` 严格验证完整公共 v1 投影；不得用表列拼出较宽松的
   第二套 Task 对象。
3. 把 Data Test 中只有 Tenant/Task/Version/Run Generation 的最小 JSONB
   Seed 更新为完整合法 Task v1；增加畸形投影、Tenant/Task 不一致和跨 Tenant
   负例。
4. 增加类型门禁，证明 Memory/Postgres UoW 满足
   `TaskQueryUnitOfWork`，并增加 API→TaskQueryService→Persistence
   黑盒只读测试。
5. 将 Execution Ledger 的 PlannedAction 校验切换到上述统一 Domain Digest。

此跟进属于 S6 所有权路径，S5 没有修改 `packages/persistence/**`、
`migrations/**`、`infra/**` 或 `tests/data/**`。

## 验证

### S5 独立工作树

| 命令 | 结果 |
|---|---|
| `make bootstrap` | PASS；Python 3.12.11，锁解析 67 个包 |
| `make test` | PASS；44 passed |
| `make test-contract` | PASS；`CONTRACT_CONFORMANCE_OK` |
| Ruff | PASS |
| 严格 Mypy | PASS；23 source files |
| `uv lock --locked` + Hash 前后比较 | PASS；`sha256:6858e8748f8a08e2a037b5b26d26b39762fe61d5509bf6bd0248a1af39edeec8` |
| Secret Pattern Scan | PASS；0 matches |
| `pip-audit` | PASS；0 known vulnerabilities |

### 工作树外 S2+S5+S6 临时组合 Workspace

临时目录只复制各责任会话已提交源码和必要契约证据；没有 Merge/Rebase，
没有修改 S2/S6 工作树。

| 命令 | 结果 |
|---|---|
| `uv lock` | PASS；73 个包，9 个内部 `flowpilot-*` 可安装包 |
| `make bootstrap` | PASS；`--all-packages` 安装 9 个内部包 |
| `make test` | PASS；108 passed（Core+Runtime+Data） |
| `make test-contract` | PASS；20 schemas、35 cases、52 features |
| Ruff | PASS；S2/S5/S6 源码与测试 |
| 严格 Mypy | PASS；55 source files |
| `uv build --all-packages --wheel` | PASS；9 个 Wheel |
| `pip-audit` | PASS；0 known vulnerabilities |
| S6 Task Query Protocol 定向类型检查 | EXPECTED FAIL；Memory/Postgres Repository 均缺少 `TaskQueryPort` |

真实 PostgreSQL/Redis 容器验证没有在 S5 重复执行；S6 HANDOFF 已提供其
隔离环境的 RLS、Migration、Fencing、Redis Loss 和恢复证据，最终是否接受
由 S1/S4 复核。

## 锁文件集成说明

当前 S5 分支没有 S2/S6 所有权源码。可复现的本分支锁包含全部第三方依赖，
但不会包含尚不存在的内部 Worker/Runtime/Persistence Workspace 包条目。
临时组合树已经证明完整锁可解析 73 个包。

S1 后续集成 S5、S2、S6 源码后，应把集成树返回 S5 执行一次最终
`uv lock`，再运行三条 Make 门禁。直接把临时组合锁提交到独立 S5 分支会让
`uv lock --locked` 因多出的内部成员判定锁过期，因此本次没有伪造该状态。

## 边界与后续

- 公共契约、架构、验收文档和其他角色目录均未修改。
- S6 `WP-021-DR-001` 的共享依赖部分已经完成。
- H1 Command Intake→S6 Memory UoW 的提交、回滚、Tenant Scope 和十次重放
  在组合测试中通过。
- 完整 API→Postgres Task Read 仍由 `S5-S6-ALIGN-002` 阻断。
- 本对齐完成后停止；由用户与 S1 讨论验收和后续派单，不在本 Attempt
  提前开发 S6 修复。

## 可回滚方式

- S5 对齐实现：
  `git revert c97c551a5d89298934d99a3d3606e833921d2a2b`。
- 本证据可独立 Revert。
- 未执行数据库写入、Migration 或 S2/S6 分支变更，无数据回滚。
