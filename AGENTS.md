# FlowPilot Codex 工程约定

## 1. 启动与身份

本文件适用于仓库内所有 Codex 任务。默认角色为 `S1-ARCH`；其他任务必须在首条
指令声明一个且仅一个 `SESSION_ROLE`：

- `S1-ARCH`：架构、契约、验收与集成。
- `S2-RUNTIME`：LangGraph、Agent Runtime、Context、Model Gateway、Worker。
- `S3-PLATFORM`：MCP Gateway、工具契约、安全与策略。
- `S4-QUALITY`：Web、评测、可观测性与跨组件质量。
- `S5-CORE`：领域、应用、API、Domain Pack、Python Workspace。
- `S6-DATA`：持久化、Migration、PostgreSQL/Redis、Infra。
- `S7-INTEGRATION`：组合验证、依赖闭包与证据复算。

首次注册且没有可信基线时，依次读取 `README.md`、`STRUCTURE.md`、
`docs/acceptance/TRACEABILITY.md`、`docs/team/CODEX_SESSIONS.md`、对应 Session
Contract 和当前 Work Package 引用。长期任务的新 Attempt 默认按
[`CONTEXT_BOOTSTRAP_PROTOCOL.md`](docs/team/CONTEXT_BOOTSTRAP_PROTOCOL.md) 使用
`DELTA`；只有首次注册、非线性基线、权限/Contract Major/架构安全边界变化或证据
不可验证时使用 `FULL`。客户端已注入本文件时不得从磁盘重复读取。

子 Agent 不执行上述全量启动。领域主 Agent完成自己的 `DELTA/FULL` 后，按
[`PRINCIPAL_SUBAGENT_PROTOCOL.md`](docs/team/PRINCIPAL_SUBAGENT_PROTOCOL.md)
提供最小 Context Capsule。

所有任务采用复用优先：相关 Blob、Contract Digest、证据 Hash 和前提未变化时，
引用已有结论，不重复读取、复现或判断。强制独立审查要换观察边界，不能原样重跑
生产者工作。

## 2. 当前事实

- M0～M10 工程候选与 M9T 工程控制面已完成；M11 短期记忆已激活，M12～M20
  未激活。
- M7 有 24 条知识问答产品执行器，M8 新增 6 条租户隔离执行器，M9 新增 9 条治理
  安全执行器，M10 新增 1 条知识安全执行器；固定 156 条 Case 当前为 40 条通过、
  116 条明确失败，因此
  `RELEASED=false`、`FROZEN=false`。
- 当前只运行 WP-122（S3）；其余 M11 角色按精确线性 Head 等待。现状以
  [`PROJECT_HANDOFF.md`](docs/roadmap/PROJECT_HANDOFF.md) 和机器追踪清单为准。
- `DESIGNED / IMPLEMENTED / VERIFIED / RELEASED` 只按
  [`ACCEPTANCE.md`](docs/acceptance/ACCEPTANCE.md) 提升。
- 24%、82.5%→90%、0.86→0.91 是参考目标，不能预填为结果。
- 所有工作关联至少一个 `FP-<DOMAIN>-NNN`；新需求由 S1 先分配 Feature ID。

## 3. 路径所有权

| Owner | 独占路径 |
|---|---|
| S1 | `README.md`、`STRUCTURE.md`、`WORKFLOW.md`、`AGENTS.md`、`contracts/**`、`docs/architecture/**`、`docs/acceptance/**`、`docs/decisions/**`、`docs/roadmap/**`、`docs/review/**`、`docs/team/**` |
| S2 | `apps/worker/**`、`packages/graph/**`、`packages/agent-runtime/**`、`packages/model-gateway/**`、`packages/context/**`、`tests/runtime/**` |
| S3 | `apps/mcp-gateway/**`、`packages/tool-contracts/**`、`packages/policy/**`、`packages/security/**`、`mcp-servers/**`、`tests/platform/**` |
| S4 | `web/**`、`packages/retrieval/**`、`packages/observability/**`、`packages/evaluation/**`、`evals/**`、`tests/acceptance/**`、`tests/experience/**`、`artifacts/acceptance/**` 生成器 |
| S5 | `apps/api/**`、`packages/domain/**`、`packages/application/**`、`packages/engineering-control/**`、`scripts/engineering/**`、`domain-packs/it-service/**`、`tests/core/**` |
| S6 | `packages/persistence/**`、`migrations/**`、`infra/**`、`tests/data/**` |
| S7 | `scripts/integration/**`、`tests/integration/**`、`artifacts/integration/**` 生成器 |

共享文件 `pyproject.toml`、`uv.lock`、`Makefile`、`.env.example`、`.gitignore`、
`.worktreeinclude` 和根级 Docker/CI 配置必须由工作包指定单一写入者。默认依次为：
Workspace/依赖锁归 S5，Compose/环境归 S6，验收入口归 S4，最终冲突归 S1。

范围外问题先只读定位，再交给 Owner；不得顺手修改。S7 没有独立 Worktree、工作包
和 `MODE=IMPLEMENTATION` 时只能只读。

## 4. 架构不变量

1. LangGraph 是唯一跨业务节点的持久化状态机。
2. Agent 不直连业务数据库、上游 MCP、企业网络或密钥；业务工具只经 MCP Gateway。
3. 模型不能决定授权、审批、租户或任务终态。
4. 写动作绑定 `action_digest`、策略决策、幂等键和回读结果。
5. Interrupt 前不得存在非幂等副作用。
6. PostgreSQL 是业务事实源；Redis 只保存可重建状态。
7. Provider Session、Studio Thread 和聊天上下文都不是业务 Checkpoint。
8. Handoff 重新构建 Context 和工具集合。
9. Trace 可采样；Audit/Security Event 不可采样。
10. Prompt、Trace、Checkpoint、事件、日志和错误不得包含明文密钥或隐藏思维链。
11. LLM-as-Judge 不判定安全、授权、状态或工具实际成功。
12. 跨租户成功读取和写入必须为 0。

改变不变量必须有 ADR，不得以临时实现绕过。

## 5. 契约、代码与测试

- `contracts/**` 是跨进程对象的唯一公共契约。非 S1 需要变更时先提交 RFC；不兼容
  变化升级 Major，Tool Schema 变化重算 Hash 并使旧审批失效。
- Python 保持 3.12+ 兼容与完整类型标注。Domain 不依赖 FastAPI、LangGraph、
  SQLAlchemy、Redis、MCP 或 Provider SDK；Application 只依赖 Port。
- Graph 节点小而可重放，确定性路由优先。外部错误映射稳定错误码，不泄漏原异常。
- 时间使用带时区 UTC；日志结构化；不提交密钥、真实 PII、生产 Prompt/Trace、
  原始附件。新生产依赖必须记录用途、许可证、替代方案和攻击面。
- 每项改动至少覆盖正常、边界、失败；涉及租户、工具、审批或数据时必须有安全负例。
  恢复、重复投递和 `UNKNOWN` 按风险补测。

稳定门禁：

```bash
make test
make test-contract
make test-security
make acceptance
```

命令不存在或环境缺失时明确写“未实现”或 `ENV_BLOCKED`，不能以手工检查冒充通过。

## 6. Git、Work Package 与链路

- 并行写入使用独立 Worktree/分支；分支名为 `codex/<session>/<work-package>`。
- 一个 Work Package 只解决一个垂直目标或强相关 Feature 集合；同一会话同时只有一个
  写工作包。开始前声明 ID、Owner、Feature、路径、输入输出、测试和非目标。
- 不 force-push、reset、rebase 或覆盖其他会话分支；不修改无关用户变更。
- 提交格式：`<type>(<scope>): <outcome> [FP-XXX-NNN]`，type 使用
  `feat/fix/test/docs/refactor/chore/security`。
- 跨会话执行必须声明 `PARALLEL`、`READ_ONLY_PARALLEL` 或 `ORDERED`。预授权链遵循
  [`CHAIN_EXECUTION_PROTOCOL.md`](docs/team/CHAIN_EXECUTION_PROTOCOL.md)；消费者门禁
  只解锁下一步，不等于接受或允许合并。
- P0/P1、R3、契约变化、路径越权、风险升级和门禁失败立即停链。S7 完成组合复现后
  交回 S1；S1 保留合并与发布裁决。
- Flow Lite 可辅助计划和验证，不替代 Work Package、路径所有权、Git Head、Contract
  Digest、风险门禁或用户批准。

模板：[`WORK_PACKAGE_TEMPLATE.md`](docs/team/WORK_PACKAGE_TEMPLATE.md)。

## 7. 领域主 Agent 与子 Agent

S1～S7 都是各自领域的主 Agent。主 Agent完成消费者门禁后，可以在当前工作包和
路径范围内自主调用临时子 Agent，无需重复请求 S1 或用户批准。

硬限制：

- 子 Agent 权限是“父角色所有权 ∩ 工作包范围 ∩ 子任务范围”，不能扩大。
- 默认用于只读并行调查、测试复现、独立复核和一个边界明确的小实现。
- 同一 Worktree 同一时刻只有一个写入者；多个只读子 Agent可以并行。
- 子 Agent 不执行 Git 写操作，不创建 Worktree/分支，不唤醒长期会话，不决定契约、
  ADR、Feature 状态或发布结论。
- 每个子任务有 `TASK_DEDUP_KEY`、`KNOWN_FACTS` 和 `DO_NOT_RECHECK`；输入未变时复用
  已有结果。并行子任务必须回答不同问题。
- 主 Agent检查差异并复跑测试，只有主 Agent提交和 Handoff。子 Agent 的隐藏思考过程
  不进入仓库或证据。
- 需要并行写、跨 Owner 或新增长期责任时，提升为注册 Agent 和独立 Worktree。
- 同类错误第二次出现时改为共享机理修复和数据驱动回归；第三次等价绕过停止局部
  补丁，按 P0/P1 升级。

完整信封、Context Capsule、并发和失败规则见
[`PRINCIPAL_SUBAGENT_PROTOCOL.md`](docs/team/PRINCIPAL_SUBAGENT_PROTOCOL.md)。

## 8. 注册、唤醒与交接

- 新链按 [`AGENT_REGISTRY_PROTOCOL.md`](docs/team/AGENT_REGISTRY_PROTOCOL.md) 选择最小
  主 Agent 集合；未选择会话不接收背景、等待或完成通知。
- 普通进度不轮询。只有完成、P0/P1、权限请求和用户门禁发送跨任务消息。
- 只有领域主 Agent 可以按
  [`THREAD_WAKE_PROTOCOL.md`](docs/team/THREAD_WAKE_PROTOCOL.md) 唤醒唯一下一长期任务。
- Handoff 使用 [`HANDOFF_TEMPLATE.md`](docs/team/HANDOFF_TEMPLATE.md)，记录完成/未完成、
  修改路径、契约/数据库/配置变化、命令结果、风险、证据、下一动作、Chain 字段和
  子 Agent 使用摘要，以及复用的结论和避免的重复工作。不得保存原始隐藏推理。
- 可复用失败机理写入 `LEARNING_CANDIDATE`；没有新增经验填 `none`。

## 9. 审查与沟通

- S2 的 Graph/State 由 S1 或 S4 复核；S5 核对应用 Port。
- S3 的授权、租户、凭据和写路径由 S1 复核，S4 增加黑盒安全测试。
- S4 的 Judge、指标和报告聚合由 S1 复核。
- S5 的领域转换、Command Intake 与 API 错误由 S1 或 S2 复核。
- S6 的 RLS、事务、Inbox/Outbox、Migration 与恢复由 S1 复核，S4 增加故障测试。
- S7 的组合、依赖闭包和证据由 S1 独立复算；S7 不能批准自身结果。
- S1 的契约和 ADR 至少由对应实现 Owner 验证可实现性。

范围内的确定性问题直接解决。多个问题一次报告，格式为
`OUTCOME → EVIDENCE → RISKS → NEXT_ACTION`。严重度：P0 为跨租户/凭据/越权/破坏性
风险，P1 为正确性/契约/恢复阻断，P2 为非阻断缺陷，P3 为建议。

S1 到达用户门禁时只报告：`本轮完成 / 本轮问题 / 需要重大决策 / 下一步`。没有重大
决策时写“无”，机器 Head、Hash 和完整命令留在证据中。
