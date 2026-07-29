# WP-010-a2 S2-RUNTIME 交接

## 基本信息

- Chain：`CHAIN-WP040-A0-REMEDIATION-01`
- Step：`WP040-REM-02-S2`
- Work Package：WP-010
- Attempt：WP-010-a2
- 责任会话：S2-RUNTIME
- 授权接收会话：S5-CORE（WP-011-a3）
- 功能 ID：FP-FLOW-001、FP-FLOW-002、FP-AGT-002、FP-CTX-001
- 分支：`codex/s2/wp-010-runtime-bootstrap`
- 基线提交：`34bec05003cb59b3e16f1a16ae166b1f77465c46`
- 上游提交：`S6-DATA:e41f0266e6e588417332043b68a3309b2d40bcf7`
- 实现提交：`790f1e17dcebdb6f856168795ef73f38c1472f02`
- 生成物清理提交：`c759659763477f544b33357f547e799662275565`
- 契约摘要：`sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- 状态：实现和范围内门禁完成；链路交接因非 S2 的 `.idea/**`
  Worktree 变化触发洁净度停止条件

## 完成内容

- 已对 S6 精确 Head、ContractSet 摘要、路径范围、Handoff 哈希和
  Checkpoint/Lease v2 Port 完成消费者校验，并输出
  `CONSUMER_VERDICT=ACCEPT`。
- 在 Worker 装配层新增 `PersistenceLeaseAdapter`，将 Graph
  `LeaseToken` 映射到 S6 `LeaseFence`，统一注入 UTC Clock 和正数 TTL。
- 新增 `PersistenceCheckpointAdapter`，通过 S6 `DataUnitOfWork`
  查询可信 Task 投影，解析并绑定 tenant/task/thread，再执行同一 UoW
  内的 Lease fence 校验、Checkpoint CAS 和提交。
- Checkpoint 外层记录与内层 `GraphState` 重复校验 tenant、task、
  thread、generation、sequence、graph version 和 SecurityContext
  引用/hash；身份或存储内容不一致时失败关闭。
- 将 CAS 冲突、租约冲突/过期、旧 generation/fence、存储协议和不可用
  错误映射为稳定 Graph 错误；不返回 S6 原始异常或连接信息。
- 保留 S6 为持久化实现 Owner；`packages/persistence/src` 未反向依赖
  `flowpilot_graph` 或 `flowpilot_worker`。
- 新增正常、CAS 幂等重放、错误身份、thread 重绑定、租约过期、旧
  generation、原始存储异常净化和 Worker 重启恢复测试。
- 向 S5 提交结构化 `WP-010-a2-DR-001`，请求在共享 Workspace/锁中解析
  `flowpilot-persistence` 与既有 S2 包；本 Attempt 未请求新第三方依赖。

## 未完成与非目标

- 根 `pyproject.toml`、`uv.lock`、`Makefile` 未修改；这些共享文件由
  链路 Step 3 的 S5-CORE 处理。
- Durable queue signal adapter、真实 Provider、MCP Gateway 和企业网络
  接入不是本 Attempt 的目标。
- S2 adapter 尚未直接组合 PostgreSQL 实例；S6 Data 套件已覆盖其
  PostgreSQL Checkpoint/Lease 实现，最终九包与实库组合由 S5/S7 门禁复算。
- LangGraph Studio 可视调试不是本 Attempt 的授权范围。后续 S2 工作包应
  导出真实编译图，提供稳定节点/条件边名称、Interrupt 与恢复路径，以及
  脱敏状态视图，使多 Agent 链路可观察而非黑箱；不得暴露凭据、PII 或隐藏
  思维链。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `apps/worker/src/flowpilot_worker/persistence.py` | S6 Checkpoint/Lease v2 adapter | S2-RUNTIME |
| `apps/worker/src/flowpilot_worker/__init__.py` | 导出持久化 adapter/config | S2-RUNTIME |
| `apps/worker/pyproject.toml` | 声明本地 `flowpilot-persistence` 依赖 | S2-RUNTIME |
| `apps/worker/README.md` | 记录装配与 durable 边界 | S2-RUNTIME |
| `packages/graph/src/flowpilot_graph/ports.py` | LeaseToken 对齐 S6 token/timestamps | S2-RUNTIME |
| `packages/graph/src/flowpilot_graph/testing.py` | 确定性 Fake 对齐新 LeaseToken | S2-RUNTIME |
| `tests/runtime/conftest.py` | 可核验的 S5/S6 源码注入与 Task fixture | S2-RUNTIME |
| `tests/runtime/integration/test_persistence_adapter.py` | 消费侧集成、安全与恢复测试 | S2-RUNTIME |
| `tests/runtime/evidence/WP-010-a2-DEPENDENCY_REQUEST.md` | S5 Workspace/锁请求 | S2-RUNTIME |

`34bec050..c759659` 的最终树差异只包含以上 S2 所有路径。实现提交曾误带
测试生成的 `__pycache__/*.pyc`，已在紧随其后的
`c759659763477f544b33357f547e799662275565` 全部删除；最终候选树和基线
差异不含生成字节码。

## 契约、数据库与配置变化

- 公共契约：无修改；继续消费冻结 rc2 v1 ContractSet。
- Persistence Port：消费
  `flowpilot.persistence-ports.m0.v2`，未修改 S6 Port。
- Migration：无。
- 环境变量：生产环境无新增；Runtime 测试支持
  `FLOWPILOT_DOMAIN_SRC`、`FLOWPILOT_APPLICATION_SRC` 和
  `FLOWPILOT_PERSISTENCE_SRC` 以精确复算未合并分支源码。
- 共享配置：无修改。
- 依赖：Worker 包内声明已有本地 `flowpilot-persistence`；共享
  Workspace/锁闭包见 `WP-010-a2-DR-001`。

## 验证

验证解释器为 Python 3.12.11。

| 命令 | 结果 | 证据 |
|---|---|---|
| `pytest -q tests/runtime`，精确注入 S5 `0be20f5...` 与 S6 `e41f026...` 源码 | PASS：43 passed | Runtime 正常、边界、失败、安全、恢复 |
| `pytest -q -p no:cacheprovider tests/core`（S5 Worktree） | PASS：44 passed | Core 回归 |
| `pytest -q -p no:cacheprovider tests/data`（S6 Worktree） | PASS：56 passed | Data 回归 |
| `python contracts/conformance/validate.py` | PASS：20 schemas、35 cases、43 semantic cases、52 features | 完整 `CONTRACT_CONFORMANCE_OK` 输出 |
| Ruff 检查全部 S2 包与 `tests/runtime` | PASS：All checks passed | Ruff 0.16.0 |
| Mypy `--strict` 检查全部 S2 源码 | PASS：25 source files | Mypy 1.20.2 |
| `git diff --check 34bec050..c759659` | PASS | 无 whitespace 错误 |
| 候选范围检查 | PASS | 最终差异仅 S2 WRITE_SCOPE |
| S6 源码反向依赖扫描 | PASS：0 matches | 无 `flowpilot_graph`/`flowpilot_worker` import |
| 高置信 Secret pattern scan | PASS：0 matches | S2 修改路径 |
| `make test`、`make test-contract` | ENV_BLOCKED：Windows 环境无 `make` 命令 | 不冒充稳定入口通过；由 S5 Step 3 复算 |

契约门禁完整输出：

```text
CONTRACT_CONFORMANCE_OK schemas=20 cases=35 positive=18 negative=17 mutation_cases=19 mutation_positive=3 mutation_negative=16 semantic_cases=43 semantic_positive=0 semantic_negative=43 audit_chain_cases=5 audit_chain_positive=1 audit_chain_negative=4 manifest_cases=21 manifest_positive=1 manifest_negative=20 features=52
```

## 安全与失败路径

- 已验证负向路径：Task 投影身份损坏、thread 重绑定、Checkpoint stale
  content/CAS、租约过期、旧 generation/fence、无可信 Task 投影和底层
  存储异常。
- 已验证恢复：Checkpoint 幂等重放、Worker 重建 adapter/graph 后从持久
  Checkpoint 恢复、Provider 可重试失败后的第二次处理。
- 错误净化测试用虚构连接串 sentinel 验证安全消息不含协议、用户名或
  `secret`；仓库不含真实凭据。
- 未验证风险：S2 adapter 与真实 PostgreSQL 的联合运行留给 S5/S7；这是
  组合证据缺口，不改变本轮 Port 语义。

## 链路停止条件

实施开始时 S2 Worktree 洁净且 Head/分支/摘要匹配。实施期间 IDE 在该
Worktree 生成或更新了以下非 S2 路径：

```text
R  .idea/Multi-agent.iml -> .idea/flowpilot-workspace.iml
 M .idea/modules.xml
?? .idea/flowpilot-agent-runtime.iml
?? .idea/flowpilot-application.iml
?? .idea/flowpilot-context.iml
?? .idea/flowpilot-domain.iml
?? .idea/flowpilot-graph.iml
?? .idea/flowpilot-model-gateway.iml
?? .idea/flowpilot-worker.iml
```

S2 未创建、编辑、暂存、提交、恢复或删除这些变化；其内容完整保留。
但 `CHAIN_EXECUTION_PROTOCOL.md` 第 7.4 条明确把“工作树不洁净”定义为
必须暂停并上报 S1 的条件。因此当前不能输出正常
`OUTCOME=PASS_HANDOFF` 或把 S5 写入解锁伪装为已满足。

## 已知问题

- `WP-010-a2-DR-001` 等待 S5 Workspace/锁闭包。
- 当前 Windows Host 无 `make`；稳定命令需要 S5/S7 环境复算。
- `.idea/**` 非 S2 变化需要 Workspace Owner/S1 决定保留、提交或恢复；
  S2 无权处理。

## 接收会话下一步

1. S1/Workspace Owner 处理或明确豁免上述 `.idea/**` 洁净度阻断。
2. 阻断关闭后，S5 按链路 Step 3 只读核验
   `NEW_HEAD=<handoff-commit>`、本文件、范围和摘要，再输出
   `CONSUMER_VERDICT=ACCEPT`。
3. S5 完成 `WP-010-a2-DR-001`、九包 Workspace/锁和稳定门禁。
4. S7 在最终组合门禁复算真实 PostgreSQL、迁移、Core/Runtime/Data 和
   Contract Conformance。
5. S1 为后续 LangGraph Studio 可视调试分配独立 S2 Work Package；
   不回填到本 Attempt。

## 可回滚方式

- 按逆序 revert 本交接提交、`c759659763477f544b33357f547e799662275565`
  和 `790f1e17dcebdb6f856168795ef73f38c1472f02`。
- 禁止 reset/rebase 或处理 `.idea/**` 用户/IDE 变化。
