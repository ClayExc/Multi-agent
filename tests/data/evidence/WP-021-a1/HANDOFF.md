# WP-021 S6-DATA 阶段性交接

## 基本信息

- Work Package：WP-021
- Attempt ID：WP-021-a1
- 风险等级：R2
- 责任会话：S6-DATA
- 接收会话：S1-ARCH；后续接口接收方 S2-RUNTIME、S3-PLATFORM、S4-QUALITY、S5-CORE
- 功能 ID：FP-SEC-002、FP-DATA-001、FP-DATA-003、FP-OPS-001
- 分支/提交：`codex/s6/wp-021-data-bootstrap` / `2cd2210e895f2a9d613e59178e27374b8685679b`
- 基线提交：`93597a5023320d48875b292dc08106f03227a3fb`
- 契约内容摘要：`sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- 状态：部分完成（S6 实现与验证基线完成；依赖接入和跨会话验收待办）

## 完成内容

- 提供与 S5 结构化端口兼容的 Task Repository、Command Inbox 和 Unit-of-Work 实现；同一事务覆盖任务、命令幂等、Outbox 与回滚。
- 提供 S3 优先接入的 Execution Ledger Port，持久化 PlannedAction、PolicyDecision、Approval、执行尝试、权威回读与 `UNKNOWN` 对账状态。
- 将 Approval 与 PlannedAction 的 `expires_at` 精确绑定到不可变账本字段和复合外键；数据库与端口层均覆盖不一致负例。
- 提供 S2 优先接入的 Checkpoint/Lease Port，包含租约代次、Fencing Token、过期续租、Worker 恢复和旧持有者拒绝。
- 建立 PostgreSQL 事实源迁移：强制 RLS、租户复合键、事务 Inbox/Outbox、执行账本、Checkpoint、Lease、审计哈希链及最小权限角色。
- 提供 Redis 可重建协调适配器；Redis 仅保存调度提示，清空后可从 PostgreSQL 事实重建。
- 提供开发 Compose 基线，包含 PostgreSQL、Redis、Keycloak、OPA 和 OpenTelemetry Collector；服务只绑定 `127.0.0.1`。
- 已在真实 PostgreSQL/Redis 容器中重复执行迁移，并验证跨租户隔离、幂等投递、租约恢复、Fencing、`UNKNOWN` 对账、Redis 丢失和 PostgreSQL 事实保留。

## 未完成与非目标

- 未修改根 `pyproject.toml`、`uv.lock` 或 `Makefile`。Workspace 成员和生产依赖接入已记录在 `packages/persistence/DEPENDENCY_REQUEST.md`，由 S5-CORE 处理。
- 未修改公共契约、架构、ADR 或验收文档；本交接不代表 S1 已接受 WP-021。
- 未实现生产级 HA、备份编排、审计外部锚定、镜像签名或供应链证明。
- 未替代 S4 的跨组件黑盒故障注入、长期并发竞争和生产恢复演练。
- PostgreSQL 下迁移会删除本基线对象，仅供显式批准的开发回滚，不应直接用于生产。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/persistence/**` | 持久化端口、内存/数据库适配器、序列化、Redis 协调及依赖请求 | S6-DATA |
| `migrations/0001_persistence_baseline.sql` | PostgreSQL 事实表、约束、触发器、RLS、角色和权限 | S6-DATA |
| `migrations/0001_persistence_baseline.down.sql` | 显式开发回滚 | S6-DATA |
| `infra/**` | 五服务 Compose、OPA/OTel 配置与运维边界说明 | S6-DATA |
| `tests/data/**` | 单元、迁移安全、事务、恢复和真实数据库验证 | S6-DATA |
| `.env.example`、`.gitignore` | WP-021 指定的 Compose 开发变量与本地数据忽略规则 | S6-DATA（工作包授权共享文件） |

## 契约、数据库与配置变化

- 契约版本：公共契约未修改；新增内部端口版本 `flowpilot.persistence-ports.m0.v1`。
- Migration：新增 `0001_persistence_baseline.sql` 与显式 down 脚本；迁移可重复执行。
- 环境变量：新增本地 Compose 的数据库、Redis、Keycloak、OPA 和 OTel 配置示例。默认宿主端口为 PostgreSQL `15432`、Redis `16379`、Keycloak `18081`、OPA `18181`、OTLP gRPC/HTTP `14317`/`14318`。
- 兼容性：Python 3.12+；根 Workspace 尚未接入本包。SQLAlchemy async、Psycopg 和 redis-py 的版本锁定由 S5 接收依赖请求后完成。
- 持久化边界：PostgreSQL 是业务、账本和恢复事实源；Redis 数据可全部丢失并重建，不参与业务终态判定。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| `python -B -m pytest tests/data tests/core -q` | PASS：50 passed | `tests/data/**`、`tests/core/**` |
| `python -m ruff check --no-cache packages/persistence tests/data` | PASS | `packages/persistence/**`、`tests/data/**` |
| `python -m mypy --strict packages/persistence/src/flowpilot_persistence`（含仓库源码 `MYPYPATH`） | PASS：8 source files | `packages/persistence/src/flowpilot_persistence/**` |
| `python contracts/conformance/validate.py` | PASS：20 schemas、35 cases、52 features | `contracts/conformance/**` |
| `docker compose --env-file .env.example -f infra/compose/compose.yaml config --quiet` | PASS | `infra/compose/compose.yaml` |
| 对空数据卷启动五服务并检查健康状态 | PASS：五个服务均 healthy | `infra/compose/compose.yaml` |
| 两次执行 `migrations/0001_persistence_baseline.sql` | PASS：首次建库、二次幂等 | `migrations/0001_persistence_baseline.sql` |
| `verify_postgres.sql` | PASS：双租户 RLS、跨租户写入、过期时间不一致和 `UNKNOWN` 盲重试负例 | `tests/data/integration/verify_postgres.sql` |
| `verify_postgres_adapter.py` | PASS：单次派发、租约 generation=2、Checkpoint 恢复、账本 attempts=2 且终态 VERIFIED | `tests/data/integration/verify_postgres_adapter.py` |
| Redis 写入后 `FLUSHDB`，再查询 PostgreSQL | PASS：协调键清空，PostgreSQL 任务事实仍存在 | `tests/data/recovery/test_checkpoint_lease_redis.py` |
| `git diff --cached --check` | PASS | 实现提交 |

## 安全与失败路径

- 已验证负向路径：事务回滚、十次重复投递只执行一次、跨租户读写为零、旧 Fencing Token、过期租约、审批/动作过期时间不一致、缺失必需审批、`UNKNOWN` 未对账重试、非法执行状态转换、Outbox 序号间隙、Checkpoint 密钥形态拒绝、Redis 全量丢失。
- 未验证风险：生产规模并发与锁等待、数据库故障切换、备份恢复 RPO/RTO、审计外部锚定、生产身份提供方集成。
- Secret/PII 检查：对实现、迁移、基础设施和数据测试执行模式扫描；未发现真实密钥、令牌或 PII。测试中的伪密钥形态仅用于拒绝用例。

## 已知问题

- S5 `PlannedAction.digest()` 当前会从资源映射中省略值为 `null` 的可选字段，而公共 RC2 契约的规范化摘要包含这些字段；同一原始 PlannedAction 因而可能产生不同 `action_digest`。S6 适配器按公共契约对完整原始映射执行 `canonical_sha256`，未越权修改 S5。S1/S5 应在接入前裁决并统一摘要算法。
- 根 Workspace 未包含 `packages/persistence`，生产数据库/Redis 驱动也未进入 `uv.lock`；在 S5 接受依赖请求前只能使用外部隔离验证环境。
- 审计哈希链已由数据库内事务和不可变触发器保护，但外部锚定与独立验证作业仍待后续工作包。

## 接收会话下一步

1. S1-ARCH 复核 RLS、事务、Inbox/Outbox、执行账本、迁移与恢复不变量，并裁决 S5 PlannedAction 摘要差异。
2. S5-CORE 接收 `packages/persistence/DEPENDENCY_REQUEST.md`，在其所有权范围内接入 Workspace 和锁文件。
3. S3-PLATFORM 以 `ExecutionLedgerPort` 接入写工具执行，并验证审批、策略、动作和回读的精确绑定。
4. S2-RUNTIME 以 `CheckpointLeasePort` 接入 Worker，验证 Interrupt 后恢复和旧 Worker Fencing。
5. S4-QUALITY 增加跨组件黑盒故障测试，包括 PostgreSQL 重启、Redis 丢失、重复投递、审批重放和 `UNKNOWN` 恢复。

## 可回滚方式

- 代码回滚：由 S1 在集成分支使用 `git revert 2cd2210e895f2a9d613e59178e27374b8685679b`，不执行 reset/rebase。
- 开发数据库回滚：仅在确认无保留数据且获得显式批准后执行 `migrations/0001_persistence_baseline.down.sql`。
- Compose 清理：`docker compose --env-file .env.example -f infra/compose/compose.yaml down --volumes --remove-orphans`；该操作删除本地开发卷中的测试数据。
