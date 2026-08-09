# WP-071-a1-core-r1 S5-CORE Task 初始化返修交接

## 基本信息

- Work Package：WP-071
- Attempt ID：WP-071-a1-core-r1
- Chain ID：CHAIN-M7-LOCAL-PRODUCT-01
- Step ID：M7-05R-S5-TASK-INITIALIZATION
- DEDUP Key：
  `CHAIN-M7-LOCAL-PRODUCT-01/M7-05R-S5-TASK-INITIALIZATION/WP-071-a1-core-r1/37186a75965a7b46e0f49ef1eada86fb7518700d`
- 责任会话：S5-CORE
- 接收会话：S6-DATA
- 交接策略：CONSUMER_GATE
- 功能 ID：FP-FLOW-001、FP-FLOW-005、FP-OBS-001、FP-OPS-001
- 基线提交：`37186a75965a7b46e0f49ef1eada86fb7518700d`
- 分支：`codex/s5/m7-core-composition`
- 最终提交：本文件所在提交；精确 SHA 由唤醒信封返回
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- Context 模式：DELTA；Context Base
  `00573adbe23565318d0e7552d1adc8093b1f71e1`
- 状态：S5 返修完成，等待 S6 实现消费者端口并关闭联合门禁

## 完成内容

- 为 Command Tx-A 增加最小、强类型、tenant-bound 的 Task 初始化能力：
  `TaskRepositoryPort.initialize(tenant_id, task)` 返回确定性的
  `INITIALIZED` / `CONFLICT` disposition，禁止覆盖现有 Task。
- `CommandIntakeService` 对 CREATE 在同一 Unit of Work 内依次完成：
  - Command/Idempotency 重放检查；
  - Task 不存在检查；
  - 固定占用 `version=-1` Command Slot；
  - 构造并初始化完整 Task v1 初始投影；
  - 写入 `StoredCommand`；
  - 单次 commit。
  任一初始化、Command Inbox 或 commit 前异常均由 UoW 回滚 Task、Command 和
  Version Slot；Execution Port 只在 Tx-A 成功提交后调用。
- 初始 Task 固定为 `status=RECEIVED`、`version=0`、`run_generation=0`；
  `waiting_on/result_ref/error/completed_at/active_run_id/latest_checkpoint_id` 均为空，
  `domain/intent/risk_level` 不在 Intake 阶段推断。
- `task_id/tenant_id/security_context/purpose` 来自已验证 `TaskCommand`；
  `thread_id` 由服务端 `ThreadIdFactory` 生成；ReleaseRef 和初始
  DataClassification 来自可信 `TaskInitializationConfig`。请求不能覆盖这些值，
  且初始分类超过 SecurityContext ceiling 时返回
  `CORE_SECURITY_BINDING_MISMATCH`，持久化与 Execution 调用均为 0。
- 相同 Command/Idempotency 重放先命中原 `StoredCommand`，返回原
  CommandAcceptance、Task 和 thread，不重复初始化或调用 Execution Port；不同
  CREATE 占用同一 tenant/task 返回稳定 `CORE_TASK_ALREADY_EXISTS`，不覆盖 Task。
- Tx-A 不发布 `task.created.v1`。首个 Checkpoint 与 `task.created.v1` Outbox 仍由
  Worker Tx-B 在 S6 Unit of Work 中原子提交，避免第二状态机和重复事件。
- `compose_core_application` 与 `create_product_app` 现在要求显式注入可信初始化
  配置与 thread 工厂。直接构造 Service 只有在 UoW 工厂自身提供可信初始化能力时
  才兼容；否则构造阶段失败关闭。模块级未配置 API 行为保持不变。
- 增强最小 Fake：事务工作副本内初始化 Task/Version，支持初始化和 Command 写入
  故障注入，可确定性证明回滚；Fake 的可信配置只用于离线测试。

## 未完成与非目标

- S5 不实现 Memory/PostgreSQL Task INSERT、RLS、Migration、数据库权限或实库事务；
  这些是本 Handoff 唯一 S6 消费闭包。
- 不修改 `contracts/**`、公共 Task v1、TaskCommand/OpenAPI 字段、S2 Runtime、
  S6 Persistence 或 S4 Acceptance 路径。
- 不改变后续 Task 状态投影更新、Checkpoint、Lease、Outbox 或执行账本状态机。
- 不实现真实 Provider、MCP、企业网络、写工具或外部付费调用；在线 Smoke 保持
  默认关闭。
- 当前全仓联合门禁的两项 S6 失败是有序消费者缺口，不表示 S5 自有门禁失败；
  S6 完成后必须复跑并关闭，才可继续 S2 Runtime。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/application/src/flowpilot_application/ports.py` | Task 初始化 disposition、thread 工厂与 Repository Port | S5-CORE |
| `packages/application/src/flowpilot_application/models.py` | 可信 Task 初始化配置 | S5-CORE |
| `packages/application/src/flowpilot_application/services.py` | CREATE Tx-A 原子初始化、绑定与稳定错误 | S5-CORE |
| `packages/application/src/flowpilot_application/composition.py` | 显式注入初始化配置和 thread 工厂 | S5-CORE |
| `packages/application/src/flowpilot_application/errors.py` | 稳定初始化协议错误 | S5-CORE |
| `packages/application/src/flowpilot_application/testing.py` | 原子 Fake、可信测试配置与故障注入 | S5-CORE |
| `packages/application/src/flowpilot_application/__init__.py` | 导出新增 Application 类型 | S5-CORE |
| `apps/api/src/flowpilot_api/composition.py` | 产品组合根显式注入可信初始化能力 | S5-CORE |
| `apps/api/src/flowpilot_api/app.py` | 初始化协议错误映射为脱敏 502 | S5-CORE |
| `tests/core/conftest.py` | 可控 SecurityContext ceiling Fixture | S5-CORE |
| `tests/core/test_application.py` | 正常、重放、冲突、安全、协议和双故障回滚测试 | S5-CORE |
| `tests/core/test_product_composition.py` | CREATE 后立即可读 Task v0 产品组合测试 | S5-CORE |
| `tests/core/test_api.py` | API Fake 组合适配 | S5-CORE |
| `tests/core/test_security.py` | 安全测试组合适配 | S5-CORE |
| `tests/core/evidence/WP-071-a1-core-r1-HANDOFF.md` | 本交接证据 | S5-CORE |

## 契约、数据库与配置变化

- 契约版本：无修改；ContractSet 摘要保持不变。
- Application Python Port：新增 Task `initialize` 能力、初始化 disposition、可信
  配置与 thread 工厂；S6 Command UoW 必须实现新能力。
- Domain Task v1 / TaskCommand / OpenAPI：无字段、枚举或语义放宽。
- Migration / 数据库 / RLS：S5 无修改，待 S6 实现。
- 环境变量、依赖、`pyproject.toml`、`uv.lock`、`Makefile`：无变化。
- 兼容性：S5 Fake 为旧的 S2/S4 离线直接构造提供可信测试能力；没有该能力的
  生产 UoW 失败关闭。产品组合根始终显式注入，浏览器请求不能提供初始化权威值。

## 验证

环境：Windows、CPython 3.12、uv locked Workspace；在线 Provider Smoke 默认关闭。

| 命令 | 结果 | 证据 |
|---|---|---|
| `uv ... pytest tests/core -q` | PASS | 88 passed |
| S2 Runtime + S4 VPN 受影响回归 | PASS | 26 passed |
| `uv ... pytest <test-security targets> -q` | PASS | 114 passed |
| `uv ... contracts/conformance/validate.py` | PASS | 20 schemas、43 semantic negatives、52 features |
| `uv ... ruff check apps packages/application packages/domain tests/core` | PASS | 0 errors |
| `uv ... mypy --strict packages/application/src apps/api/src packages/domain/src` | PASS | 27 source files |
| S5 Domain/Application/API wheel 构建 | PASS | 3/3 wheels |
| 全仓 `pytest -q` | CONSUMER_REQUIRED | 828 passed、1 explicit online skip、2 S6 failures |
| 全仓 strict Mypy | CONSUMER_REQUIRED | 122 files 中仅 S6 `_ApplicationTaskRepository.initialize` 缺口 |
| `git diff --check` 与路径审计 | PASS | 仅 S5 授权路径；无 whitespace error |

Contract Conformance：

```text
CONTRACT_CONFORMANCE_OK schemas=20 cases=35 positive=18 negative=17 mutation_cases=19 mutation_positive=3 mutation_negative=16 semantic_cases=43 semantic_positive=0 semantic_negative=43 audit_chain_cases=5 audit_chain_positive=1 audit_chain_negative=4 manifest_cases=21 manifest_positive=1 manifest_negative=20 review_attestation_cases=10 review_attestation_positive=2 review_attestation_negative=8 retired_review_attestation_cases=5 retired_review_attestation_positive=0 retired_review_attestation_negative=5 features=52
```

## 安全与失败路径

- 已验证正常：CREATE 后在 Execution 调用前形成完整 Task v0，API 立即按 tenant/task
  读到 `RECEIVED` 投影；同命令重放保留原 thread，Execution 调用一次。
- 已验证边界：非 CREATE 不初始化；CREATE 固定使用 `version=-1` Slot；不同 CREATE
  同 Task 不覆盖；未配置可信初始化能力时构造阶段失败关闭。
- 已验证失败：Task initialize 失败和 Command add 失败均回滚 Task、Task Version、
  StoredCommand、Idempotency Key 和 Version Slot，Execution 调用为 0；非法 thread
  工厂返回稳定、脱敏 `CORE_TASK_INITIALIZATION_PROTOCOL_ERROR`。
- 已验证安全：可信分类超过 SecurityContext ceiling 时返回稳定绑定错误；请求不能
  提供 thread/release/classification；S2/S4 安全回归和全仓安全入口 114 passed。
- Secret/PII：`test-security` 包含高置信 Secret 扫描并通过；本 Attempt 未读取或
  写入真实密钥、PII、Prompt、Trace 或隐藏思考过程。

## 已知问题

- `tests/data/unit/test_application_composition.py` 的旧组合调用尚未显式传入
  `TaskInitializationConfig` 与 `ThreadIdFactory`。
- `MemoryDataUnitOfWorkFactory` / PostgreSQL Application Task Repository 尚未实现
  `initialize`，因此全仓 strict Mypy 也在 S6 组合适配器产生唯一缺口。
- 上述两项是本次有序 S6 Consumer Gate 的预期输入；在 S6 关闭前不得声称 WP-071
  联合门禁 PASS，也不得恢复 S2 Runtime。

## 学习候选

```text
LEARNING_CANDIDATE=Command 接收必须原子建立权威 Task 初始投影
MATURITY=IMPLEMENTED
TRIGGER=CREATE 已进入 Command Inbox，但 Worker 首次持久化前找不到权威 Task，失败为 GRAPH_CHECKPOINT_UNAVAILABLE
MECHANISM=Command 与 Task 初始投影分离提交会让 Worker 观察到只存在 Command、不存在 Task 的中间状态，Checkpoint/Lease 无法安全绑定版本与租户
STRUCTURE=Tx-A 在同一 UoW 提交 Task v0、StoredCommand 与 version=-1 Slot；Tx-B 继续提交首 Checkpoint 与 task.created.v1 Outbox
EVIDENCE=tests/core/test_application.py; tests/core/test_product_composition.py; tests/core/evidence/WP-071-a1-core-r1-HANDOFF.md
RESIDUAL_RISK=Memory/PostgreSQL 原子 INSERT、RLS 与实库回滚仍待 S6 验证
TARGET=docs/architecture/ENGINEERING_PLAYBOOK.md
```

## 接收会话下一步

1. 核验 S5 `NEW_HEAD`、本 Handoff SHA256、ContractSet、线性祖先、分支、授权
   路径和 clean 状态；只用 `--ff-only` 精确到 S5 Head。
2. 进入 `WP-071-a1-data-r1`，在 Memory 与 PostgreSQL Application Task Repository
   实现 tenant-bound `initialize`：仅 INSERT Task v0，已存在返回 `CONFLICT`，绝不
   覆盖；与 StoredCommand、`version=-1` Slot 使用同一 Data UoW/commit/rollback。
3. 显式装配可信初始化配置/thread 工厂，并验证正常、重复、冲突、跨租户、Task
   或 Command 任一失败回滚；PostgreSQL 实库验证 RLS 和 API 角色最小 INSERT 权限。
4. 关闭本 Handoff 记录的 2 个 pytest 消费失败和唯一 strict Mypy 缺口；复跑 Core、
   Runtime、Data、Security、Contract 与实库门禁，确认 Worktree clean。
5. PASS 后直接唤醒原 `WP-071-a1-runtime`，固定
   `NEXT_TASK_THREAD_ID=019fa697-7be1-7811-8afe-5d8763bbfd9f`，不返回 S1。
   P0/P1、新契约/S3 边界、越权、破坏性迁移、门禁失败或外部付费调用才停链上报。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M7-LOCAL-PRODUCT-01
STEP_ID=M7-05R-S5-TASK-INITIALIZATION
ATTEMPT_ID=WP-071-a1-core-r1
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=37186a75965a7b46e0f49ef1eada86fb7518700d
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/core/evidence/WP-071-a1-core-r1-HANDOFF.md
NEXT_ROLE=S6-DATA
NEXT_ATTEMPT_ID=WP-071-a1-data-r1
NEXT_TASK_THREAD_ID=019fa697-7be1-7811-8afe-5d8763bbfd9f
ESCALATE_TO_S1=no
```

## 可回滚方式

- Revert 本 Handoff/实现提交；禁止 reset、rebase 或 force-push。本返修没有数据库、
  Migration、共享依赖或外部系统写入，无数据回滚。
