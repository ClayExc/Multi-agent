# WP-010-a4 S2-RUNTIME Durable Runtime 交接

## 基本信息

- Work Package：WP-010 / WP-P2-durable-runtime
- Attempt ID：WP-010-a4
- Agent ID：durable-runtime
- Chain ID：CHAIN-P2-DURABLE-RUNTIME-01
- Step ID：P2-DURABLE-02-RUNTIME
- DEDUP Key：
  `CHAIN-P2-DURABLE-RUNTIME-01/P2-DURABLE-02-RUNTIME/WP-010-a4/36e25279d6b4e02e7471c242ed2bd71dfc0a5dbc`
- 责任会话：S2-RUNTIME
- 接收会话：S7-INTEGRATION / recovery-verifier
- 执行模式：ORDERED
- 风险等级：R2
- 功能 ID：FP-OPS-002、FP-FLOW-002
- 基线 / 输入 Head：`36e25279d6b4e02e7471c242ed2bd71dfc0a5dbc`
- S6 实现提交：`f666ad49f3909815a2d597e0ee9f40955eb717a1`
- S2 实现提交：`e0354aaefa0eb2a559b251c9c02cd3069a3194d3`
- 分支：`codex/s2/wp-010-runtime-bootstrap`
- 最终提交：本文件所在提交；精确 SHA 由唤醒信封返回
- ContractSet 摘要：
  `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- 状态：完成，等待 S7 消费门禁

## 完成内容

- 新增 Durable Runtime 生产装配入口；Worker 只通过 S6
  `DataUnitOfWorkFactory`、`CoordinationRebuilder`、Lease/Checkpoint Port
  消费持久化与协调能力，没有数据库、Redis Driver 或基础设施直连。
- 新增不可空、不可重复的 `TrustedTenantInventory`。Worker 在获取租约前先验证
  Command digest/security binding，再通过 Data UoW 读取可信 Task 投影，逐字段
  回绑 tenant、task、purpose 与 SecurityContext；请求携带的 tenant 不能独自成为
  执行权威。
- Durable Runtime 首次取任务前按可信 tenant inventory 调用
  `CoordinationRebuilder`；Redis/协调状态丢失时从 PostgreSQL Task/Outbox 耐久事实
  分 tenant 重建，重建失败不会开始消费任务。
- 新 Worker 使用 S6 Lease Port 获取更高的 `run_generation`，再从
  tenant + task + trusted thread 的 latest checkpoint 恢复，并由 S6 fence 与
  Checkpoint CAS 保证序列单调；旧 generation 的 Worker 写入失败关闭。
- Worker 的 guard、租约获取、图执行均纳入统一队列 disposition；可重试失败
  回队列，确定性安全失败确认并停止，不再留下未处理 inflight envelope。
- Durable graph factory 强制显式传入 control checkpointer，生产恢复入口没有
  `InMemorySaver` 默认值；Studio-safe 的既有进程内 Checkpointer 路径未改动。
- 新增 Redis 丢失重建、跨 Worker 重启、新 generation/CAS、终态重复投递、
  不可信 tenant、Task/SecurityContext 错绑、旧 Worker 零写入和显式
  checkpointer 负例。g2/g3 未实现、未扩展。

## 未完成与非目标

- 未新增 g2/g3、写工具、审批、模型 Provider、企业网络或外部副作用。
- 未实现或选择生产 LangGraph control checkpointer Driver；本步骤只要求装配层
  显式注入，Provider Session、LangGraph control checkpoint 与业务 Task/
  GraphState checkpoint 仍保持分离。
- 未修改 ContractSet、Migration、RLS、PostgreSQL/Redis Adapter、Compose、
  Workspace、依赖或锁文件。
- 实际 PostgreSQL 17.5 + Redis 丢失 + 多进程旧 Worker 组合复现属于下一步
  S7 recovery-verifier；本步骤不单方面宣称跨组件 VERIFIED/RELEASED。
- `make acceptance` 仍未实现，未用手工检查替代 Acceptance PASS。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `apps/worker/src/flowpilot_worker/durable.py` | Durable Runtime、tenant rebuild、显式 checkpointer 装配 | S2 |
| `apps/worker/src/flowpilot_worker/persistence.py` | 可信 tenant inventory 与 Data UoW Task 执行守卫 | S2 |
| `apps/worker/src/flowpilot_worker/worker.py` | guard 前置及 guard/lease 失败的队列恢复语义 | S2 |
| `apps/worker/src/flowpilot_worker/__init__.py` | 导出 Durable Runtime 边界 | S2 |
| `tests/runtime/recovery/test_durable_runtime.py` | Redis 重建、重启/CAS、终态、安全和配置负例 | S2 |
| `tests/runtime/integration/test_persistence_adapter.py` | 旧 generation checkpoint 成功写入数为 0 | S2 |
| `tests/runtime/evidence/WP-010-a4-HANDOFF.md` | 本交接证据 | S2 |

## 契约、数据库与配置变化

- 公共契约：无变化；ContractSet content digest 保持不变。
- 数据库 / Migration / RLS：无变化；只消费 S6 已接受的 Port。
- Redis / Compose / 环境变量：无变化；只注入 `CoordinationRebuilder`。
- `pyproject.toml` / `uv.lock` / `Makefile`：无变化；无依赖请求。
- LangGraph Studio：无变化；既有 graph ID、拓扑、安全投影及 Studio-safe
  `InMemorySaver` 路径保持原样。

## 上下文与消费门禁

- 使用 `CONTEXT_MODE=DELTA`，验证
  `c5c118d808931492d7ee44455b1c2a9360625675` 是输入 Head 祖先。
- 只读取 Context Bootstrap、当前 Chain、Work Package、Agent Registry、直接
  S6 Handoff 与变更的强制文档片段；`CONTEXT_FULL_READS=0`，
  `CONTEXT_DUPLICATE_READS=0`。
- S6 Handoff SHA256 验证为
  `sha256:17759d0beca2644cfa5910bdf1d5327c924438a28eafc47434ea394b13ee1823`。
- ContractSet digest、S6 范围、祖先关系、分支与 clean 状态均通过；仅使用
  `--ff-only` 精确到输入 Head 后开始写入。
- 消费结论：`CONSUMER_VERDICT=ACCEPT`。

## 验证

| 命令 / 门禁 | 结果 | 证据 |
|---|---|---|
| `make test` | 环境未运行 | 当前 PowerShell 无 `make.exe`，未宣称稳定入口 PASS |
| Makefile `test` 的锁定底层命令 | PASS | 265 passed，含 Runtime 72 / Durable 5 |
| Makefile `test-contract` 的锁定底层命令 | PASS | 20 schemas / 35 cases / 43 semantic cases / 52 features |
| Makefile `test-security` 的锁定底层命令 | PASS | Platform security 68 passed |
| `pytest tests/runtime` | PASS | 72 passed |
| Durable + Persistence 定向测试 | PASS | 12 passed |
| Ruff（S2 源码与 Runtime 测试） | PASS | All checks passed |
| Mypy `--strict`（Worker + Graph） | PASS | 19 source files |
| `git diff --check` | PASS | 无 whitespace error |
| 变更路径高置信 Secret Scan | PASS | 0 matches |
| Contract / Migration / Infra / Shared / Lock 差异 | PASS | 0 changes |

Contract Conformance：

```text
CONTRACT_CONFORMANCE_OK schemas=20 cases=35 positive=18 negative=17 mutation_cases=19 mutation_positive=3 mutation_negative=16 semantic_cases=43 semantic_positive=0 semantic_negative=43 audit_chain_cases=5 audit_chain_positive=1 audit_chain_negative=4 manifest_cases=21 manifest_positive=1 manifest_negative=20 features=52
```

## 安全、失败与恢复证据

- Redis coordination 清空后，Worker 在 dequeue 前按可信 tenant inventory
  重建 1 个 RUNNABLE 信号；过期内存信号不被恢复。
- 第一个 Worker 的 Provider retry checkpoint 被第二个全新 Runtime/Worker
  实例恢复；新租约 `run_generation=2`，checkpoint sequence 严格增长并完成。
- 完成后的相同 Command 经第三个 Worker 重投不再次调用 Runtime，checkpoint
  sequence 不变，终态分支不重跑。
- 不在可信 inventory 的 tenant 在租约前以
  `GRAPH_SECURITY_BINDING_MISMATCH` 失败关闭，成功租约数与 checkpoint 写入数均
  为 0。
- Task projection 的 SecurityContext 与 Command 不一致时同样在租约前失败；
  原始安全上下文、凭据或数据库异常未进入安全错误消息。
- 旧/过期 generation 的 Worker checkpoint save 返回 `GRAPH_LEASE_LOST`，
  持久 checkpoint 集合保持为空，成功写入数为 0。

## 已知风险

- P2：当前 Windows 主机无 GNU Make；已按 Makefile 原样运行三个锁定底层
  命令。S7 环境有 Make 时应复跑稳定入口。
- P2：真实 PostgreSQL/Redis 多进程组合证据尚未在 S2 Worktree 复跑；S6 已
  提供 Data 侧实库证据，最终组合门禁由 S7 执行。
- P2：生产 control checkpointer 的具体 Driver 不在本步骤范围。装配入口拒绝
  缺省值，但部署者仍必须提供符合环境授权的实现；不得把 Studio-safe
  `InMemorySaver` 当作业务事实源。

## 学习候选

```text
LEARNING_CANDIDATE=耐久 Worker 必须在租约前把 Command 回绑到可信 tenant inventory 与 Task 投影
MATURITY=IMPLEMENTED
TRIGGER=Redis 丢失、Worker 重启或攻击者向执行队列注入错误 tenant/SecurityContext
MECHANISM=直接用队列 Command tenant 获取租约会在可信 Task 校验前污染协调状态；从全局重建又会破坏 tenant 隔离
STRUCTURE=部署配置提供完整 tenant inventory；CoordinationRebuilder 分 tenant 重建；Worker 通过 Data UoW 验证 Task 绑定后才获取 fenced lease 并恢复 latest checkpoint
EVIDENCE=e0354aaefa0eb2a559b251c9c02cd3069a3194d3；tests/runtime/recovery/test_durable_runtime.py
RESIDUAL_RISK=真实多进程 Postgres/Redis 故障注入需 S7 组合验证
TARGET=docs/architecture/ENGINEERING_PLAYBOOK.md
```

## 接收会话下一步

1. S7 核验 NEW_HEAD、Handoff SHA、ContractSet、线性父提交、授权范围和 clean
   状态，仅以 `--ff-only` 到达精确 Head。
2. 使用真实 PostgreSQL/Redis 复现：Redis 清空后只按可信 tenant 重建；新
   Worker 获取新 generation，从 tenant + task + thread latest checkpoint
   继续 CAS；旧 Worker 成功写入数为 0。
3. 验证 completed Task 不产生重建信号、不重跑业务节点，跨租户成功数为 0，
   checkpoint sequence 单调。
4. 正常 PASS 后按 Chain 交回 S1；仅 P0/P1、契约/共享文件变化、越权路径或
   新门禁失败时停链上报。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-P2-DURABLE-RUNTIME-01
STEP_ID=P2-DURABLE-02-RUNTIME
ATTEMPT_ID=WP-010-a4
AGENT_ID=durable-runtime
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=36e25279d6b4e02e7471c242ed2bd71dfc0a5dbc
INPUT_HEAD=36e25279d6b4e02e7471c242ed2bd71dfc0a5dbc
IMPLEMENTATION_HEAD=e0354aaefa0eb2a559b251c9c02cd3069a3194d3
CONTRACT_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
GATE=PASS
HANDOFF=tests/runtime/evidence/WP-010-a4-HANDOFF.md
NEXT_AGENT_ID=recovery-verifier
NEXT_ROLE=S7-INTEGRATION
NEXT_ATTEMPT_ID=WP-040-a7
ESCALATE_TO_S1=no
USER_INPUT_REQUIRED=none
```

## 可回滚方式

- 实现提交和 Handoff 提交可由 Chain Owner 按逆序 `git revert`；禁止
  reset/rebase。
- 本 Attempt 没有数据库、Migration、外部系统写入、Contract、Shared 或
  Lock 变化，无数据或依赖回滚。
