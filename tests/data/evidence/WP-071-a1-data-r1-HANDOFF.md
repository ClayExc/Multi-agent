# WP-071-a1-data-r1 S6 Task 初始化修复候选交接

## 基本信息

- Work Package：WP-071
- Attempt ID：WP-071-a1-data-r1
- Chain ID：CHAIN-M7-LOCAL-PRODUCT-01
- Step ID：M7-06R-S6-CANDIDATE-HANDOFF
- DEDUP Key：
  `CHAIN-M7-LOCAL-PRODUCT-01/M7-06R-S6-TASK-INITIALIZATION/WP-071-a1-data-r1/726f875ab689eca3627a96af2efe8137fb1756de`
- 责任会话：S6-DATA
- 接收会话：S7-INTEGRATION
- 交接策略：ORDERED_LOCAL_REPAIR
- 功能 ID：FP-FLOW-001、FP-FLOW-005、FP-OBS-001、FP-OPS-001
- 输入提交：`726f875ab689eca3627a96af2efe8137fb1756de`
- 实现提交：`ac8220fc34f306c0a92ac780c4d5d87aa803055e`
- 分支：`codex/s6/wp-071-data-composition`
- 最终提交：本文件所在提交；精确 SHA 由唤醒信封返回
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- Context 模式：DELTA；Context Base
  `37186a75965a7b46e0f49ef1eada86fb7518700d`
- S1 裁决：`ACCEPT_IMPLEMENTATION_PENDING_EXTERNAL_VALIDATOR`
- 状态：S6 候选完成；`FULL_GATE=BLOCKED_BY_OUTDATED_S7_VALIDATOR`

## 完成内容

- 为 Memory 与 PostgreSQL Task Repository 实现租户绑定、仅插入的
  `initialize(tenant_id, task)`：只接受完整合法的 `RECEIVED` Task v0，首次写入
  返回 `INITIALIZED`，任何既有 Task、Task version 或数据库唯一性冲突稳定返回
  `CONFLICT`，不覆盖已有投影。
- S5 Application UoW 适配器显式转发 `initialize` 并沿用同一事务租户 Scope，关闭
  `_ApplicationTaskRepository.initialize` 的严格 Mypy 协议缺口。
- Command Tx-A 现在能在同一 UoW 中原子保存 Task v0、`version=-1` Slot 和
  `StoredCommand`；Command 写入失败或 Task 初始化失败时三类事实一起回滚。
- 保持事件边界不变：Tx-A 不写 `task.created.v1` 或其他 Outbox；首 Checkpoint 与
  `task.created.v1` 仍由后续 Worker Tx-B 原子提交，不引入第二状态机。
- 新增线性迁移 `0003_api_task_initialization`，只授予 `flowpilot_api` 对
  `flowpilot.tasks` 的 `INSERT`，不授予 UPDATE、DELETE 或 TRUNCATE；既有强制 RLS
  和 tenant `WITH CHECK` 继续生效。
- 为 `0002.down` 增加 0003 后继保护；未先回滚 0003 时，0002 降级会在任何
  Schema 变化前失败关闭。
- 空卷 Compose 现在按 `0001 -> 0002 -> 0003` 自动应用唯一线性迁移链。
- 扩展真实 PostgreSQL 适配器证据：API 身份完成 Task v0 初始化与回读；相同
  Command 重放不再生成 thread 或二次派发；全局 Command 冲突、跨租户初始化失败
  均证明 Task、Slot、Command、Outbox 遗留数为 0。

## 未完成与非目标

- 未修改 `scripts/integration/**` 或 `tests/integration/**`。旧 WP-040 验证器仍固定
  0002 为 Migration Head 并固定 0002 down 文件哈希，必须由 S7 在下一有序步骤
  更新后复算确定性报告。
- 在 S7 修复旧验证器并由 S6 复跑全部门禁前，不唤醒 S2，不恢复
  `WP-071-a1-runtime`，也不宣称 WP-071 联合门禁通过。
- 本 Step 不实现 Worker Tx-B、LangGraph、Provider/MCP、OIDC、生产 HA/TLS、备份
  或灾难恢复；在线 Provider smoke 保持关闭，真实 Provider/付费调用为 0。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/persistence/src/flowpilot_persistence/serialization.py` | Task v0 权威投影判定 | S6-DATA |
| `packages/persistence/src/flowpilot_persistence/memory.py` | Memory Task 初始化与冲突语义 | S6-DATA |
| `packages/persistence/src/flowpilot_persistence/postgres.py` | PostgreSQL 仅插入 Task 初始化 | S6-DATA |
| `packages/persistence/src/flowpilot_persistence/composition.py` | Application Task Repository 端口适配 | S6-DATA |
| `migrations/0003_api_task_initialization.sql` | API 最小 INSERT 权限与线性 Head | S6-DATA |
| `migrations/0003_api_task_initialization.down.sql` | 撤销最小权限的开发降级 | S6-DATA |
| `migrations/0002_checkpoint_sequence_cas.down.sql` | 0003 后继失败关闭保护 | S6-DATA |
| `migrations/README.md` | 0001→0003 升降级顺序 | S6-DATA |
| `infra/compose/compose.yaml` | 空卷挂载 0002、0003 正向迁移 | S6-DATA |
| `infra/compose/README.md` | Compose 迁移顺序说明 | S6-DATA |
| `tests/data/unit/test_application_composition.py` | Task 初始化、查询、重放组合证据 | S6-DATA |
| `tests/data/unit/test_s5_unit_of_work.py` | Memory 原子回滚与跨租户负例 | S6-DATA |
| `tests/data/unit/test_postgres_adapter.py` | PostgreSQL 初始化、冲突与畸形投影负例 | S6-DATA |
| `tests/data/security/test_migration_security.py` | 迁移线性、最小权限和降级保护 | S6-DATA |
| `tests/data/e2e/test_compose_baseline.py` | 空卷三段正向迁移挂载 | S6-DATA |
| `tests/data/integration/verify_postgres.sql` | 真实 API 最小权限与 RLS 写入负例 | S6-DATA |
| `tests/data/integration/verify_postgres_adapter.py` | 真实 Tx-A、重放与双故障回滚 | S6-DATA |
| `tests/data/evidence/WP-071-a1-data-r1-HANDOFF.md` | 本交接 | S6-DATA |

## 契约、数据库与配置变化

- 公共契约：无修改；ContractSet 摘要保持不变。
- Schema：无表、列、约束或 RLS Policy 变化。
- 权限：0003 只增加 `GRANT INSERT ON flowpilot.tasks TO flowpilot_api`；down 先
  REVOKE 再删除迁移登记。
- Migration：当前唯一线性 Head 为 0003；三个正向迁移均原子且可重复执行。
- Compose：空卷初始化目录只挂载 0001、0002、0003 正向文件；不挂载 down 文件。
- 环境：未修改 `.env.example`，实库测试只使用进程级本地占位值，未提交 DSN、
  密码、令牌或生产配置。
- 兼容性：S5 已定义的 `TaskInitializationDisposition` 和 Task Repository Port 被
  直接实现；没有复制公共契约或摘要算法。

## 验证结果

环境：Windows、CPython 3.12.11、Docker Engine 29.6.2；在线 Provider smoke
保持关闭。

| 命令/证据 | 结果 |
|---|---|
| `uv run pytest tests/data -q` | PASS：85 passed |
| 全仓 `uv ... pytest -q` | BLOCKED：836 passed、1 explicit online skip、3 failed；失败仅为旧 WP-040 迁移清单/固定报告哈希 |
| `scripts/quality.ps1 lint` | PASS：Ruff；strict Mypy 122 source files |
| `scripts/quality.ps1 test-contract` | PASS：20 schemas、35 cases、52 features |
| `scripts/quality.ps1 test-security` | PASS：116 passed |
| `scripts/quality.ps1 audit` | PASS：0 known vulnerabilities；editable workspace distributions 按配置跳过 |
| 隔离 Compose `up -d --wait` | PASS：PostgreSQL、Redis、Keycloak、OPA、OTel 5 服务 Healthy |
| 0001、0002、0003 重复正向执行 | PASS：`ON_ERROR_STOP=1`，无部分迁移 |
| 0002 down 在 0003 仍登记时 | EXPECTED FAIL：后继保护命中，迁移记录仍为 2、`checkpoint_sequence` 仍为 1 |
| 0003 down / up | PASS：down 后 API INSERT=`false`、记录=0；up 后 INSERT=`true`、记录=1 |
| `tests/data/integration/verify_postgres.sql` | PASS：API 最小权限、RLS 跨租户写入 0，既有安全负例保持通过 |
| `tests/data/integration/verify_postgres_adapter.py` | PASS：`POSTGRES_ADAPTER_OK`；Task v0、重放、双故障回滚、Checkpoint/Fence、Ledger、协调重建通过 |

## 全仓阻断证据

- `tests/integration/test_wp040_composition.py` 有 3 个失败：候选 Verdict、固定
  manifest/report 哈希、S1 final Verdict。
- 验证器内部实际失败检查只有：
  - `migrations.file_hashes`：旧清单固定 0002 down 哈希；
  - `migrations.linear_head`：旧清单固定 0002 为 Head，实际授权 Head 为 0003。
- S1 已确认 0003 是授权的单线性后继，且 0002 down 的后继保护是必要安全变化；
  不允许豁免此门禁，应由 S7 更新独占验证器后重新复算。

## 安全与失败路径

- 重复 CREATE 相同 Command：安全重放，Task/thread/Execution 均不重复。
- 不同 CREATE 指向既有 Task 或命中全局 Command 唯一性：稳定冲突，不覆盖 Task。
- Task 初始化租户不一致或非完整 Task v0：失败关闭，不执行插入。
- Command add 失败或 Task initialize 失败：Task、Slot、Command、Outbox 部分写入均为 0。
- `flowpilot_api` 的 Task UPDATE、DELETE、TRUNCATE 权限均为 0；跨租户 INSERT
  成功数为 0。
- PostgreSQL 仍是事实源；Redis 仍只接收可重建协调信号。
- 未提交 Secret、PII、真实 Prompt/Trace、原始附件或本地绝对路径。

## 已知风险

- P1：旧 S7 WP-040 迁移验证器尚未识别 0003；在其更新并由 S6 复跑全仓前，
  当前候选不能继续到 S2。
- P2：本地 Compose 证据不等于生产 HA、TLS、备份或灾难恢复。
- P2：Worker Tx-B 尚未在本轮恢复；S2 必须继续保证首 Checkpoint 与
  `task.created.v1` 同事务，且不得重复发布事件。

## 学习候选

`LEARNING_CANDIDATE=none`

## S7 下一步

1. 核验本 S6 最终 Head、Handoff SHA256、ContractSet、线性祖先、授权范围和 clean
   状态；只用 `--ff-only` 精确到达 S6 Head。
2. 在 `M7-06V-S7-MIGRATION-VERIFIER` / `WP-040-migration-r1` 中只修改
   `scripts/integration/**`、`tests/integration/**`，将 WP-040 迁移清单更新为授权的
   `0001 -> 0002 -> 0003`，复算必要的文件哈希与确定性报告哈希。
3. 不修改 S6 Migration、RLS、Port 或事务实现；验证器必须继续失败关闭，不能跳过
   Migration Head、文件哈希或 S1 final 检查。
4. S7 PASS 后回唤当前 S6；S6 将 `--ff-only` 消费精确 S7 Head，复跑原 3 个失败、
   Data 门禁和全仓门禁。全部 PASS 后才唤醒原 S2 `WP-071-a1-runtime`。

## 机器可读交接摘要

```text
OUTCOME=PASS_S6_CANDIDATE_PENDING_S7
CHAIN_ID=CHAIN-M7-LOCAL-PRODUCT-01
STEP_ID=M7-06R-S6-CANDIDATE-HANDOFF
ATTEMPT_ID=WP-071-a1-data-r1
NEW_HEAD=<this-handoff-commit>
INPUT_HEAD=726f875ab689eca3627a96af2efe8137fb1756de
IMPLEMENTATION_HEAD=ac8220fc34f306c0a92ac780c4d5d87aa803055e
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
FULL_GATE=BLOCKED_BY_OUTDATED_S7_VALIDATOR
HANDOFF=tests/data/evidence/WP-071-a1-data-r1-HANDOFF.md
NEXT_AGENT_ID=migration-verifier
NEXT_ROLE=S7-INTEGRATION
NEXT_ATTEMPT_ID=WP-040-migration-r1
ESCALATE_TO_S1=no
USER_INPUT_REQUIRED=none
```

## 可回滚方式

- 代码候选可按逆序 revert 本 Handoff 提交与实现提交
  `ac8220fc34f306c0a92ac780c4d5d87aa803055e`；禁止 reset、rebase 或覆盖其他会话
  提交。
- 已应用到开发数据库时，先确认仅撤销本地 API Task 初始化能力，再执行
  `0003_api_task_initialization.down.sql`。这会撤销 INSERT 权限但不删除业务表或数据；
  生产或保留数据环境仍须 S1 明确批准后执行任何降级。
