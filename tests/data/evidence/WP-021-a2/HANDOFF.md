# WP-021-a2 S6-DATA 阶段性交接

## 基本信息

- Work Package：WP-021
- Attempt ID：WP-021-a2
- 风险等级：R2
- 执行模式：ORDERED
- 顺序：1
- 责任会话：S6-DATA
- 接收会话：S1-ARCH；S1 接受后由 S2-RUNTIME 进入下一有序步骤
- 功能 ID：FP-SEC-002、FP-DATA-001、FP-DATA-003
- 分支：`codex/s6/wp-021-data-bootstrap`
- 基线提交：`3e0101999061a44a3a5b2fd455ec792e3f73954e`
- 控制基线 `master` 解析值：`7b550a3133b9ac0d0742a4f522aa3771e795e79d`
- 契约内容摘要：`sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- H1 提交：`c55eb99d0820df8070a7be88bd796766f4269d1b`
- H2 / NEW_HEAD：本文件所在提交；精确 SHA 由最终交接消息返回
- 状态：S6 范围实现和实库证据完成，等待 S1 验收

## 完成内容

- Memory/PostgreSQL Task Repository 新增租户限定的
  `get(tenant_id, task_id) -> Task | None`，并使用
  `Task.from_mapping()` 恢复完整 Task v1。
- PostgreSQL 查询对缺失、畸形、不完整、行身份错租户、错 Task 和
  projection 身份错配全部失败关闭；真实 RLS 查询不返回跨租户 Task。
- Execution Ledger 只使用
  `PlannedAction.from_mapping(...).digest()`；删除对 PlannedAction 原始
  Mapping 的直接 `canonical_sha256` 调用。
- 四种 `resource.id` / `resource.owner_id` 省略或显式 `null` 组合均使用
  同一领域摘要；已与 S5
  `0be20f5b56d330f4da494ce4c3d46b183b09ae8b` 临时组合复算。
- Persistence Port 升级为 `flowpilot.persistence-ports.m0.v2`。
  `CheckpointRecord` 显式携带 `checkpoint_sequence`；
  `put(..., expected_sequence=...)` 返回 `expected_sequence + 1`。
- Memory CAS 在同一 UoW 锁内完成。PostgreSQL CAS 在同一事务内锁定活动
  Lease 行，同时绑定 tenant/task/thread、holder/token、run_generation 和
  expiry，再通过带当前序号条件的 `INSERT ... SELECT` 原子写入。
- 相同身份和内容的当前序列重放返回原记录；同身份不同内容返回稳定
  `DATA_CONFLICT`；错误首序号、旧序号和已前进后的旧重放返回稳定
  `DATA_VERSION_CONFLICT`；过期或旧 Worker 返回 `DATA_STALE_FENCE`。
- `latest(tenant_id, task_id, thread_id)` 绑定三项身份，只按
  `checkpoint_sequence DESC` 排序。真实数据库验证同一租户、同一 Thread
  下两个 Task 的 Checkpoint 不串读。
- 新增线性升级 `0002_checkpoint_sequence_cas`：回填序号、唯一约束、
  Task/Thread 复合外键和确定性索引；保留所有 RLS 策略。
- `packages/persistence` 未导入 `packages/graph`；GraphState/LeaseToken
  转换仍由 S2 Worker 装配层负责。

## 未完成与非目标

- 未修改 S2/S5 分支、公共契约、根 Workspace、锁文件、Makefile、Infra
  或其他角色路径。
- S2 的 GraphState/LeaseToken 转换、Clock/TTL 注入及错误映射等待 S1 接受
  本 Head 后进入下一有序步骤。
- S5 最终九包 Workspace 与 `uv.lock` 刷新仍等待 S2/S6 Heads 稳定。
- Compose 当前仅自动挂载 `0001`；由于本 Attempt 的 WRITE_SCOPE 不含
  `infra/**`，`0002` 通过明确迁移命令应用。后续集成应由获授权的迁移
  runner/Compose 工作包接入。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/persistence/**` | TaskQuery、领域摘要、Checkpoint CAS v2 | S6-DATA |
| `migrations/0002_checkpoint_sequence_cas.sql` | 单一线性升级 | S6-DATA |
| `migrations/0002_checkpoint_sequence_cas.down.sql` | 失败关闭的开发回滚 | S6-DATA |
| `migrations/README.md` | 升级顺序与回滚条件 | S6-DATA |
| `tests/data/**` | TaskQuery、摘要组合、CAS、迁移、实库及恢复证据 | S6-DATA |

## 契约、数据库与配置变化

- 公共契约：无变化。
- 内部 Port：`flowpilot.persistence-ports.m0.v1` →
  `flowpilot.persistence-ports.m0.v2`。
- Migration Head：`0001_persistence_baseline` →
  `0002_checkpoint_sequence_cas`，保持单一线性后继。
- 数据库：`checkpoints.checkpoint_sequence bigint NOT NULL`；
  `(tenant_id, task_id, checkpoint_sequence)` 唯一；Checkpoint
  tenant/task/thread 复合外键；最新索引以三项身份和序号排序。
- 兼容迁移：现有 Checkpoint 按
  `run_generation, created_at, checkpoint_id` 只在升级时确定性回填序号；
  运行时不再依赖这些字段选取 latest。
- 环境变量和根共享文件：无变化。

## 验证

| 命令/场景 | 结果 | 证据 |
|---|---|---|
| `python -B -m pytest tests/data tests/core -q` | PASS：78 passed | `tests/data/**`、`tests/core/**` |
| `python -m ruff check --no-cache packages/persistence tests/data` | PASS | H2 工作树 |
| `python -m mypy --strict packages/persistence/src/flowpilot_persistence` | PASS：8 source files | `packages/persistence/src/**` |
| `python contracts/conformance/validate.py` | PASS：20 schemas、35 cases、52 features | `contracts/conformance/**` |
| S5 `0be20f5…` 临时源码组合 | PASS：TaskQuery 1；null combinations 4；唯一 digest `sha256:78947390c2539442392e3755c3e8fb5a5ec15d3b31708dec01e747e289a9ca66` | 临时目录位于 Windows Temp，未提交 |
| 空卷 Compose 五服务健康检查 | PASS：PostgreSQL、Redis、Keycloak、OPA、OTel 均 healthy | `infra/compose/compose.yaml` |
| `0001` 重跑，`0002` 连续执行两次 | PASS | `migrations/0001_persistence_baseline.sql`、`0002_checkpoint_sequence_cas.sql` |
| `verify_postgres.sql` | PASS：RLS、跨租户、审批 expiry、UNKNOWN 负例 | `tests/data/integration/verify_postgres.sql` |
| `verify_postgres_adapter.py` | PASS：完整 Task、同 Thread 双 Task 隔离、CAS 1→2、安全重放、序号冲突、generation=2、账本 VERIFIED/attempts=2 | `tests/data/integration/verify_postgres_adapter.py` |
| 含同 Thread 双 Task 时执行 `0002...down.sql` | EXPECTED FAIL；随后验证 `checkpoint_sequence`/migration 记录为 `1:1`，事务完整回滚 | down 脚本失败门禁 |
| 独立临时数据库 `0001→0002→down` | PASS；验证列/记录/旧唯一约束为 `0:0:1`；临时数据库已删除 | down 正常回滚 |
| Redis `SET→FLUSHDB→DBSIZE` | PASS：Redis 为 0；PostgreSQL Task 数仍为 4 | Redis 丢失回归 |
| `docker compose ... config --quiet` | PASS | Compose 配置 |

- `make test-security`：未实现，当前 Makefile 不含该入口；本 Attempt 未越权
  修改共享 Makefile，数据安全测试通过直接 Pytest 执行。

## 证据哈希

- `migrations/0002_checkpoint_sequence_cas.sql`：
  `sha256:e5ca8fca2de8e913caedd488821356e441b2adc5ae72a20d015fe4df5b403112`
- `migrations/0002_checkpoint_sequence_cas.down.sql`：
  `sha256:beb71df8b0f82fdc11f9b59a3f323f9d43857356b76d136742f43fc67ff1f22c`
- `tests/data/integration/verify_postgres_adapter.py`：
  `sha256:dfca2573ecc226ebddc673fbe893004bfd425fb2ea7576ade02eaab386a584cd`

## 安全与失败路径

- 已验证：不存在 Task、畸形/不完整 projection、行与 projection 的
  tenant/task 错配、RLS 跨租户读取、Checkpoint 跨租户/错 Task/错 Thread、
  错误首序号、旧 CAS、同身份异内容、过期 Lease、旧 generation、旧 Worker
  fencing、Redis 全量丢失、down 不可无损回退。
- Secret/PII：未新增真实凭据、生产 PII、Prompt、Trace 或绝对路径。
- PostgreSQL 仍是 Task/Checkpoint 事实源；Redis 清空不会损害恢复事实。

## 已关闭阻断

- `S1-WP040-A0-001`
- `S1-WP040-A0-002`
- `S1-WP040-A0-003`
- `S1-WP040-A0-004_PROVIDER_SIDE`

## 已知问题与风险

- `S1-WP040-A0-004` 的 S2 消费侧尚未开始；必须等待 S1 接受本 Head。
- `S1-WP040-A0-005` 属于 S5 最终 Workspace/锁闭包，不属于本写入范围。
- `0002` down 在同一 tenant/thread 存在多个 Task 时有意失败关闭；删除、
  合并或重映射业务事实需要独立破坏性迁移审批。
- 生产并发规模、故障切换和备份恢复仍不属于 WP-021-a2。

## 接收会话下一步

1. S1-ARCH 复核 H1/H2、Migration 与实库证据并明确接受或退回。
2. 仅在 S1 接受后，S2-RUNTIME 实现 Worker 组合适配器并关闭
   `S1-WP040-A0-004` 消费侧。
3. S2/S6 Heads 稳定后由 S5-CORE 刷新最终 Workspace 与 `uv.lock`。
4. S7-INTEGRATION 只能在前序接受后重新构造只读组合树。

## 可回滚方式

- 代码：由 S1 使用 `git revert` 逆序回滚 H2、H1；禁止 reset/rebase。
- 开发数据库：先确认不存在同 tenant/thread 多 Task，再显式执行
  `0002_checkpoint_sequence_cas.down.sql`。失败时事务不产生部分结构变化。
- 生产数据库：需要独立破坏性迁移工作包、备份和恢复证据。
