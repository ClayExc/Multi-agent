# WP-021-a3 S6-DATA Durable Runtime 交接

## 基本信息

- Work Package：WP-021
- Attempt ID：WP-021-a3
- Chain ID：CHAIN-P2-DURABLE-RUNTIME-01
- Step ID：P2-DURABLE-01-DATA
- 责任会话：S6-DATA / `data-recovery`
- 接收会话：S2-RUNTIME / `durable-runtime`
- 交接策略：CONSUMER_GATE
- 功能 ID：FP-FLOW-005、FP-DATA-001、FP-DATA-002、FP-DATA-003、FP-SEC-002
- 初始激活提交：`c51026cfa50be6e7e060266f16e2f82b68cfcac9`
- 增量上下文/实施基线：`74326bb188d3db76d19ca4a4138bf38d11e52d6b`
- 实现提交：`f666ad49f3909815a2d597e0ee9f40955eb717a1`
- 分支：`codex/s6/wp-021-data-bootstrap`
- 最终提交：本文件所在提交；精确 SHA 由唤醒信封返回
- ContractSet 摘要：
  `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- 状态：完成，等待 S2 消费门禁

## 增量上下文门禁

- `CONTEXT_MODE=DELTA`。
- `c51026c...` 是 `74326bb...` 的祖先；S6 工作树从前者仅以
  `--ff-only` 到达后者，分支和工作树门禁通过。
- 完整读取新增的 `docs/team/CONTEXT_BOOTSTRAP_PROTOCOL.md`；读取当前 Chain
  Authorization 与 Agent Registry 的 Base→Target 变化片段。Work Package、
  Session Contract、README、STRUCTURE 和 Traceability 未触发 FULL 重读。
- `CONTEXT_FULL_READS=0`；`CONTEXT_DUPLICATE_READS=0`。
- `python contracts/conformance/validate.py` 复算并确认 ContractSet 内容摘要
  与唤醒信封一致。

## 完成内容

1. 审计确认既有 `DataUnitOfWork` 已提供可信 Task/Thread 查询、Lease
   acquire/assert/release、Checkpoint CAS/sequence、Outbox 与租户事务边界；未
   复制 S2 Graph 类型，也未导入 `flowpilot_graph`。
2. 修复正常 Lease release 删除事实行导致 `run_generation` 重置的问题：release
   现在撤销旧 token、立即过期但保留行；后续 acquire 在同一 PostgreSQL 行上
   原子递增 generation。旧 token、重复 release 和旧 Worker 均失败关闭。
3. 增加类型化 `TaskPersistencePort`、`RecoverySignalPort` 与
   `CoordinationRebuilder`。PostgreSQL 恢复查询使用每 Task 最高 Outbox sequence，
   不过滤 `published_at`，再以 `Task.from_mapping()` 恢复并核对 tenant/task/thread/
   status/run_generation，只为当前 `RUNNABLE` Task 生成协调信号。
4. Redis 仍只保存可丢弃提示。恢复器先完成全部 PostgreSQL 事实读取和身份校验，
   再按 tenant 独立替换 Redis namespace；一个 tenant 的恢复不会清除另一个
   tenant 的信号。
5. 新增正常 release 接管、已发布 Outbox 重建、终态不重入、未来可用时间、
   缺失 Task、跨租户投影、PostgreSQL SQL 形状和实库 generation=3 证据。

## 未完成与非目标

- S2 Worker/LangGraph 的生产恢复入口、GraphState/LeaseToken 转换与新 Worker
  重启轨迹属于下一有序 Step；本提交未修改 `apps/worker/**`、`packages/graph/**`
  或 `tests/runtime/**`。
- S7 的隔离 Compose RELEASE 组合复现和最终计数属于 Step 3。
- Flow Lite `g2`（Outbox→SSE）和 `g3`（安全 Ticket 写入）未获授权，未实施。
- 未新增 Migration、Compose、依赖、Workspace/Lock、Contract 或公共领域 API。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/persistence/README.md` | 记录 Outbox 重建与 release fencing 语义 | S6-DATA |
| `packages/persistence/src/flowpilot_persistence/ports.py` | 增加类型化 Task/恢复信号和 tenant 重建边界 | S6-DATA |
| `packages/persistence/src/flowpilot_persistence/recovery.py` | 新增 PostgreSQL→Redis 恢复协调器 | S6-DATA |
| `packages/persistence/src/flowpilot_persistence/memory.py` | 内存事实源的 generation 保留与恢复查询 | S6-DATA |
| `packages/persistence/src/flowpilot_persistence/postgres.py` | 实库 release 撤销、Task/Outbox 恢复查询 | S6-DATA |
| `packages/persistence/src/flowpilot_persistence/redis_coordination.py` | tenant 独立 namespace 重建 | S6-DATA |
| `packages/persistence/src/flowpilot_persistence/__init__.py` | 导出新增内部边界 | S6-DATA |
| `tests/data/recovery/test_durable_recovery_boundary.py` | release/Redis 丢失/终态/失败关闭证据 | S6-DATA |
| `tests/data/unit/test_postgres_recovery_boundary.py` | PostgreSQL SQL 与身份负例 | S6-DATA |
| `tests/data/integration/verify_postgres_adapter.py` | 实库已发布 Outbox 与 generation=3 | S6-DATA |
| `tests/data/evidence/WP-021-a3-HANDOFF.md` | 本交接 | S6-DATA |

## 契约、数据库与配置变化

- ContractSet：无变化；内容摘要保持 `sha256:0a82e7...`。
- Persistence Port：保留 `flowpilot.persistence-ports.m0.v2`；新增内部、向后兼容
  的类型化恢复方法，未复制公共 Schema。
- Migration/数据库结构：无变化；只改变既有 `task_leases` 行的 release DML 和
  既有 `tasks`/`outbox_events` 的只读恢复查询。
- Redis：无新事实字段；仍只有 tenant/task、run_generation、available_at 提示。
- 环境变量、Compose、依赖和 Lock：无变化。

## 验证

| 命令/场景 | 结果 | 证据 |
|---|---|---|
| `uv run --frozen python -m pytest -q tests/data` | PASS：63 passed | `tests/data/**` |
| 新增恢复定向测试 | PASS：7 passed | 新增 recovery/unit 测试 |
| `uv run --all-packages --all-groups --locked python -B -m pytest -q` | PASS：260 passed | 全仓 Python 测试 |
| `python contracts/conformance/validate.py` | PASS：20 schemas、35 cases、52 features | ContractSet |
| `ruff check packages/persistence/src tests/data` | PASS | S6 写入范围 |
| `mypy --strict packages/persistence/src` | PASS：9 source files | Persistence 边界 |
| 空卷 Compose `up -d --wait` | PASS：PostgreSQL、Redis、Keycloak、OPA、OTel 全部 healthy | 本地隔离 Compose |
| `0002_checkpoint_sequence_cas.sql` 连续执行两次 | PASS | 既有线性 Migration |
| `verify_postgres.sql` | PASS：RLS、跨租户、审批 expiry、UNKNOWN 负例 | 实库 SQL |
| `verify_postgres_adapter.py` | PASS：`generation=3 rebuilt=1 ledger=verified attempts=2` | 实库适配器 |
| Redis `SET→DBSIZE→FLUSHDB→DBSIZE` | PASS：`1→0`；PostgreSQL Task Outbox 保持 `1:1`（总数:已发布） | Redis 丢失回归 |
| 测试环境清理 | PASS：测试容器、网络和新建临时 PostgreSQL 卷已移除 | Compose cleanup |

补充：Windows 环境没有 `make`，以上使用 Makefile 对应的锁定 `uv` 命令直接
执行。全仓无范围 `ruff check .` 仍报告 47 个激活基线已有问题，均位于
`contracts/**`、`packages/evaluation/**`、`packages/observability/**`、
`scripts/acceptance/**`、`tests/acceptance/**` 等非 S6 路径；S6 范围 Ruff PASS，
本提交没有新增该债务。

## 安全与失败路径

- 跨租户成功读取/写入：0；PostgreSQL RLS 与错误 tenant 投影均失败关闭。
- 旧 Worker 成功写入：0；过期、已 release、旧 token/旧 generation 均被拒绝。
- 已完成 Task 重建信号：0；只有当前合法 `RUNNABLE` 投影可重建。
- Redis 丢失后的 PostgreSQL 事实损失：0；已发布 Outbox 仍参与重建。
- 缺失或畸形 Task、Outbox→Task 身份错配、重复 Task 信号在清空 Redis 前失败。
- tenant A 重建不会删除 tenant B 信号。
- Secret/PII：变更扫描未发现真实凭据、生产 PII、绝对路径、Prompt、Trace 或
  私钥材料。

## 已知问题与风险

- `CoordinationRebuilder` 的 tenant 输入必须来自可信 Worker 配置/注册事实，不能
  直接使用请求方字段。tenant namespace 独立替换限制了误用影响，但 S2 仍须在
  适配层明确可信来源。
- S6 保持小型 `AsyncRedisClient` 注入协议，没有新增 Redis SDK 依赖；真实 Redis
  的客户端装配与 Worker 恢复时序由 S2/S7 组合验证。
- 全仓 Ruff 的 47 个基线问题为 P2、非本 Step 阻断；Owner 仍是对应路径会话。
- P0/P1：无。

## 学习候选

```text
LEARNING_CANDIDATE=Lease release 删除行会重置持久化 fencing generation
MATURITY=VERIFIED
TRIGGER=正常 Worker release 后新 Worker acquire 得到 generation=1
MECHANISM=task_leases 行同时承载活动租约和唯一持久化 generation 计数；DELETE 擦除计数历史
STRUCTURE=撤销旧 token 并立即过期但保留行；后续 acquire 通过原子 UPSERT 将 generation+1
EVIDENCE=f666ad49f3909815a2d597e0ee9f40955eb717a1；tests/data/recovery/test_durable_recovery_boundary.py；实库 generation=3
RESIDUAL_RISK=若未来允许删除并复用同一 task_id，必须另设不可回退的 generation 事实；当前 Task 身份不复用
TARGET=docs/architecture/ENGINEERING_PLAYBOOK.md 4.2
```

## 接收会话下一步

1. S2 核对本 Handoff SHA、ContractSet、线性父提交和洁净 Worktree，仅以
   `--ff-only` 到达精确 S6 NEW_HEAD。
2. Worker 只通过 `DataUnitOfWorkFactory`、`CoordinationRebuilder`、Lease 与
   Checkpoint Port 接入；不得直连 PostgreSQL 或把 Redis/Provider Session 当事实。
3. tenant 必须来自可信执行上下文。Redis 丢失时先重建对应 tenant namespace，
   再由新 Worker acquire 新 generation、加载 tenant+task+thread 绑定的 latest
   checkpoint 并继续 CAS。
4. 用新 Worker 实例证明重启、Redis 丢失、旧 Worker fencing、Checkpoint 序列
   单调和 completed branch 不重跑；`studio-safe` 内存模式保持不变。
5. 正常完成后只唤醒 S7-INTEGRATION / WP-040-a7；P0/P1、范围/权限、契约或
   Migration 需求才暂停并上报 S1。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-P2-DURABLE-RUNTIME-01
STEP_ID=P2-DURABLE-01-DATA
ATTEMPT_ID=WP-021-a3
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=74326bb188d3db76d19ca4a4138bf38d11e52d6b
INPUT_HEAD=74326bb188d3db76d19ca4a4138bf38d11e52d6b
IMPLEMENTATION_HEAD=f666ad49f3909815a2d597e0ee9f40955eb717a1
CONTRACT_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
CONTEXT_MODE=DELTA
CONTEXT_BASE_COMMIT=c51026cfa50be6e7e060266f16e2f82b68cfcac9
CONTEXT_TARGET_COMMIT=74326bb188d3db76d19ca4a4138bf38d11e52d6b
GATE=PASS
HANDOFF=tests/data/evidence/WP-021-a3-HANDOFF.md
NEXT_AGENT_ID=durable-runtime
NEXT_ROLE=S2-RUNTIME
NEXT_ATTEMPT_ID=WP-010-a4
ESCALATE_TO_S1=no
```

## 可回滚方式

- Chain Owner 可先 revert 本 Handoff 提交，再 revert 实现提交
  `f666ad49...`；禁止 reset/rebase。
- 没有 Schema、Migration、Contract、依赖或外部发布回滚。
- 本轮只创建并删除了本地合成测试数据卷；该临时数据不可恢复且不需要恢复。
