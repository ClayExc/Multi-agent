# WP-071-a1-data S6 数据、环境与恢复装配交接

## 基本信息

- Work Package：WP-071
- Attempt ID：WP-071-a1-data
- Chain ID：CHAIN-M7-LOCAL-PRODUCT-01
- Step ID：M7-06-S6-DATA-COMPOSITION
- DEDUP Key：
  `CHAIN-M7-LOCAL-PRODUCT-01/M7-06-S6-DATA-COMPOSITION/WP-071-a1-data/00573adbe23565318d0e7552d1adc8093b1f71e1`
- 责任会话：S6-DATA
- 接收会话：S2-RUNTIME
- 交接策略：CONSUMER_GATE
- 功能 ID：FP-FLOW-001、FP-FLOW-005、FP-OBS-001、FP-OPS-001
- 基线提交：`00573adbe23565318d0e7552d1adc8093b1f71e1`
- 实现提交：`181eac3bff76957992fba0e6abaea43414f6c5d5`
- 分支：`codex/s6/wp-071-data-composition`
- 最终提交：本文件所在提交；精确 SHA 由唤醒信封返回
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- Context 模式：DELTA；Context Base
  `e41f0266e6e588417332043b68a3309b2d40bcf7`
- 状态：完成，等待 S2 消费门禁

## 完成内容

- 完成 S5 Handoff 消费门禁：核验分支、clean 状态、线性祖先、精确输入 Head、
  Handoff SHA256 和 ContractSet 摘要，并只用 `--ff-only` 到达输入 Head。
- 新增 `compose_application_unit_of_work_factories`，把既有
  `DataUnitOfWorkFactory` 收窄并装配为 S5 产品组合需要的三类端口：
  - Command `UnitOfWorkFactory`；
  - 只读 `TaskQueryUnitOfWorkFactory`；
  - `TaskEventUnitOfWorkFactory`。
- 三类工厂每次调用均创建新的底层事务，不跨请求或能力复用 UoW 实例。
- Task Event UoW 在同一底层事务和同一租户绑定内组合 Task 查询、Outbox 回读与
  发布确认、Consumer Inbox 去重；未提交时发布确认和去重记录一起回滚并可重投。
- 将持久化层 `OutboxDelivery` 显式投影为 S5 `OutboxEventView`。未复制事件摘要、
  Canonical JSON 或 Contract 算法。
- 在 Application 适配边界补充空租户和事务内换租户失败关闭，使 Memory 与
  PostgreSQL 组合证据保持相同的租户事务语义；PostgreSQL 原有 `set_config`、
  强制 RLS 和事务绑定不变。
- 扩展真实 PostgreSQL 验证器，覆盖三类组合端口、事件事务回滚/重投、Consumer
  Inbox、Outbox 视图和事务内换租户拒绝。
- 使用全新隔离 Compose project 复验 5 服务健康、正向/重复迁移、RLS、
  Checkpoint CAS、Lease/Fencing、Redis 清空恢复、Worker 恢复、终态不重跑和事件
  重投；验证后删除本轮容器、卷和网络。
- 未读取真实凭据、未启动在线 Provider smoke、未产生 Provider 或付费调用。

## 未完成与非目标

- 本 Step 不实现 S2 Worker/LangGraph 产品装配、`ExecutionPort`、Provider/MCP 调用
  或可信 `RequestSecurityPort`；这些属于紧随其后的 S2 Step。
- 本 Step 不实现 OIDC、真实企业 Connector、业务写动作、生产 TLS/HA/备份或外部
  审计锚定。
- 本 Step 不表示 WP-071、M7 固定分母或发布门禁已经完成。
- 在线 Provider smoke 按授权保持关闭；真实 Provider 质量与 Endpoint 可用性没有
  在本 Step 宣称。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/persistence/src/flowpilot_persistence/composition.py` | 三类最小能力 UoW、租户绑定和 Outbox 视图适配 | S6-DATA |
| `packages/persistence/src/flowpilot_persistence/__init__.py` | 导出组合工厂与结果对象 | S6-DATA |
| `packages/persistence/README.md` | 记录 M7 组合事务与事实源边界 | S6-DATA |
| `tests/data/unit/test_application_composition.py` | 正常、回滚、重投、空租户、换租户负例 | S6-DATA |
| `tests/data/integration/verify_postgres_adapter.py` | 真实 PostgreSQL 三端口组合证据 | S6-DATA |
| `tests/data/evidence/WP-071-a1-data-HANDOFF.md` | 本交接 | S6-DATA |

## 契约、数据库与配置变化

- 契约版本：无修改；ContractSet 摘要保持不变。
- Migration：无新增或修改；现有单一线性 `0001 -> 0002` Head 已在空卷实库正向
  应用并重复执行通过。
- 数据库/RLS：无 Schema 或策略变化；现有 PostgreSQL 事实源、事务、强制 RLS、
  Inbox/Outbox、Checkpoint/Lease/Fencing 语义保持不变。
- Compose：无文件变化；使用现有 Compose 在隔离 project 中复验 5 个服务。
- 环境变量：`.env.example` 无变化；测试只使用进程级本地占位值，没有写入仓库。
- 兼容性：加法式 Python API；既有 Memory/PostgreSQL Data UoW、S2 Recovery Port
  和 S5 Application Port 保持兼容。

## 验证

环境：Windows、CPython 3.12.11、uv 0.12.1、Docker Engine 29.6.2；在线
Provider smoke 默认关闭。

| 命令 | 结果 | 证据 |
|---|---|---|
| `uv ... pytest tests/data -q` | PASS | 76 passed |
| `.\scripts\quality.ps1 test-all` | PASS | 824 passed、1 个显式在线 skip；Contract Conformance PASS（20 schemas、35 cases、52 features） |
| `.\scripts\quality.ps1 lint` | PASS | Ruff PASS；strict Mypy 122 source files PASS |
| `.\scripts\quality.ps1 test-security` | PASS | 114 passed |
| `.\scripts\quality.ps1 audit` | PASS | 0 known vulnerabilities；editable workspace distributions 按配置跳过 |
| 隔离 `docker compose config/up --wait` | PASS | PostgreSQL、Redis、Keycloak、OPA、OTel 共 5 服务 Healthy |
| 空卷应用 `0002`，再重复执行 `0001`、`0002` | PASS | 线性前向升级和重复执行均 `ON_ERROR_STOP=1` 通过 |
| `tests/data/integration/verify_postgres.sql` | PASS | RLS、跨租户读写、过期绑定、UNKNOWN 转换等数据库负例通过 |
| `tests/data/integration/verify_postgres_adapter.py` | PASS | `POSTGRES_ADAPTER_OK`；三类 UoW、事件回滚/重投、Checkpoint/Fence、Ledger 通过 |
| `scripts/integration/verify_durable_recovery.py` | PASS | `generation=1->2`、`checkpoint=3->6`、旧 Worker 写入 0、终态重跑 0、跨租户读取 0 |
| Redis 终态与隔离资源清理 | PASS | Redis `DBSIZE=0`；cleanup containers=0、volumes=0、networks=0 |

## 安全与失败路径

- 已验证负向路径：空租户；同一 UoW 换租户；跨租户 Task/Checkpoint/RLS 读写；
  未提交 Outbox/Consumer Inbox 回滚；事件重投；Inbox 重复指纹；Checkpoint 旧 CAS；
  旧 generation/fence；终态恢复不重跑；Redis 清空后从 PostgreSQL 恢复；
  Approval/PlannedAction 过期绑定；UNKNOWN 禁止盲重试。
- 事实源边界：PostgreSQL 仍是唯一业务事实源；Redis 最终键数可归零且清空不影响
  Task、Checkpoint、Outbox 或执行事实。
- Secret/PII 检查：安全集 114 passed；未修改 `.env.example`，未提交本地 DSN、
  密码、令牌、真实 PII、Prompt、Trace 或原始附件。
- 跨租户成功读取和写入：0。

## 已知问题

- P2：本地 Compose 证据不等于生产 HA、TLS、备份或灾难恢复；这些不是 M7
  WP-071 的发布承诺。
- P2：在线 Provider smoke 按授权显式跳过；后续只有在单独授权并使用测试租户、
  预算和脱敏证据时才能执行。
- P2：真实身份/OIDC 属于 M8。S2 产品组合必须继续注入可信
  `RequestSecurityPort`，不得把浏览器 Tenant/Header 提升为事实。

## 学习候选

```text
LEARNING_CANDIDATE=宽 Data UoW 需要显式收窄后再组合应用事件端口
MATURITY=VERIFIED
TRIGGER=持久化 Outbox 返回 OutboxDelivery，而 S5 TaskEventOutboxPort 返回 OutboxEventView；运行时归一化可工作但静态协议不能证明组合边界
MECHANISM=宽持久化接口暴露额外元数据且返回类型不同，直接把同一工厂注入多个最小能力 Protocol 会隐藏类型与租户事务差异
STRUCTURE=由 S6 提供三个最小能力工厂；Task Event 适配器共享一个底层事务与租户绑定，只做 Outbox 视图投影
EVIDENCE=181eac3bff76957992fba0e6abaea43414f6c5d5；tests/data/unit/test_application_composition.py；真实 POSTGRES_ADAPTER_OK
RESIDUAL_RISK=调用方仍须每次调用工厂创建新 UoW，不能缓存或跨请求复用返回实例
TARGET=docs/architecture/ENGINEERING_PLAYBOOK.md 4.2/4.5
```

## 接收会话下一步

1. 核验本 S6 最终 Head、本 Handoff SHA256、ContractSet、线性祖先、授权路径和
   clean 状态；只用 `--ff-only` 精确到达 S6 Head。
2. 在 S2 `M7-07-S2-RUNTIME-COMPOSITION` / `WP-071-a1-runtime` 中创建现有
   `PostgresDataUnitOfWorkFactory`，调用
   `compose_application_unit_of_work_factories`，把三个字段分别注入 S5
   `create_product_app`；不要共享一次调用返回的 UoW 实例。
3. 原始 `DataUnitOfWorkFactory` 继续供 Durable Worker、Task Event Publisher、
   Checkpoint/Lease/Fencing 与 `CoordinationRebuilder` 使用；Redis 只接收可重建协调
   信号，不保存 Task/Checkpoint/终态。
4. 接入 S2 `ExecutionPort` 与可信 `RequestSecurityPort`，完成正式企业知识问答
   Worker/LangGraph 链及 Provider/MCP 失败关闭；VPN 只作历史回归，不得硬编码。
5. 正常完成后按预授权链继续；Contract/S3 边界、越权路径、破坏性迁移、跨租户
   成功数大于 0、门禁失败或未授权付费调用必须立即停链上报 S1。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M7-LOCAL-PRODUCT-01
STEP_ID=M7-06-S6-DATA-COMPOSITION
ATTEMPT_ID=WP-071-a1-data
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=00573adbe23565318d0e7552d1adc8093b1f71e1
IMPLEMENTATION_HEAD=181eac3bff76957992fba0e6abaea43414f6c5d5
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/data/evidence/WP-071-a1-data-HANDOFF.md
NEXT_ROLE=S2-RUNTIME
NEXT_ATTEMPT_ID=WP-071-a1-runtime
ESCALATE_TO_S1=no
```

## 可回滚方式

- 按逆序 revert 本 Handoff 提交和实现提交
  `181eac3bff76957992fba0e6abaea43414f6c5d5`；禁止 reset、rebase 或覆盖其他
  会话提交。没有 Migration、Schema、RLS、Compose 或环境变量变化需要数据回滚。
