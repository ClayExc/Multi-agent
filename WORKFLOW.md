# FlowPilot Agent Work Workflow

Status: Manual control plane, Symphony-inspired v1

## 1. Control plane

当前由用户和 `S1-ARCH` 共同充当任务控制面。工作事实来自：

1. GitHub Issue/Project 或 `docs/team/work-packages/<WP>.md`。
2. Git 分支、Worktree 和提交。
3. `docs/team/HANDOFF_TEMPLATE.md` 交接与 Evidence。
4. `contracts/contract-set.v1.json.content_digest`。

聊天会话、模型记忆和未落盘口头声明不是工作状态事实源。

## 2. Work item 必填字段

每个可执行工作项必须声明：

```text
WORK_PACKAGE=<WP-ID>
SESSION_ROLE=<S2-RUNTIME|S3-PLATFORM|S4-QUALITY|S5-CORE|S6-DATA|S7-INTEGRATION>
FEATURE_IDS=<FP-ID,...>
ATTEMPT_ID=<WP-ID>-a<number>
RISK_CLASS=<R0|R1|R2|R3>
BASE_COMMIT=<git-sha>
CONTRACT_CONTENT_DIGEST=sha256:<64hex>
BRANCH=codex/<session>/<work-package>
WORKTREE=<absolute-path>
WRITE_SCOPE=<paths>
DEPENDENCIES=<WP-ID,...|none>
ACCEPTANCE_COMMANDS=<commands>
EXECUTION_MODE=<PARALLEL|READ_ONLY_PARALLEL|ORDERED>
ORDER_INDEX=<n|none>
UNLOCK_CONDITION=<evidence-or-state|none>
COMMUNICATION_MODE=OUTCOME_FIRST
CHAIN_ID=<chain-id|none>
CHAIN_AUTHORITY_REF=<repository-relative-path|none>
HANDOFF_POLICY=<S1_GATE|CONSUMER_GATE|FINAL_GATE>
NEXT_ROLE=<session-role|S1-ARCH|none>
```

字段缺失时只能只读分析，不得进入 `IN_PROGRESS`。

## 3. State machine

```text
BACKLOG → READY → IN_PROGRESS → REVIEW → HANDOFF → ACCEPTED → MERGED
```

- `BLOCKED`：依赖未完成、需要新契约/权限或外部状态变化。
- `FAILED`：自动门禁失败；保留分支、日志和证据后允许重试。
- `CANCELLED`：用户或 S1 明确终止。

允许转换：

- `BACKLOG → READY`：范围、Owner、依赖、验收完整。
- `READY → IN_PROGRESS`：依赖完成，独立 Worktree 已创建，基线摘要匹配。
- `IN_PROGRESS → REVIEW`：责任会话自测完成并生成交接。
- `REVIEW → HANDOFF`：审查意见已处置，证据可复现。
- `HANDOFF → ACCEPTED`：S1 确认不变量、门禁和证据。
- `ACCEPTED → MERGED`：合并后主分支门禁通过。

任何内容摘要变化都会使未绑定新摘要的 Review 失效。

预授权链中的 `CONSUMER_ACCEPTED` 是派生的消费结论，不是新的工作包
状态。它只允许下一工作包启动，不能替代 `HANDOFF → ACCEPTED`。

## 4. Dispatch policy

只有满足以下条件的工作项可以启动写入：

1. 状态为 `READY`。
2. 所有依赖为 `ACCEPTED` 或 `MERGED`；预授权链中允许依赖处于
   `HANDOFF`，但必须已经取得授权消费者的 `CONSUMER_ACCEPTED`。
3. 责任角色与路径所有权一致。
4. 分支和 Worktree 未被其他任务占用。
5. ContractSet 摘要与工作项声明一致。
6. 没有未处理的阻断 RFC。

人工阶段同时写入的工作项不超过 3。其余会话可以只读审查、补测试设计或准备后续 Issue。

跨会话派发必须明确调度语义：

- `PARALLEL`：任务可同时写入各自独占路径；派发必须说明最终汇合门禁。
- `READ_ONLY_PARALLEL`：任务只读并行；禁止文件修改和 Git 写操作。
- `ORDERED`：任务必须按 `ORDER_INDEX` 执行。默认由 S1 确认
  `UNLOCK_CONDITION`；若存在有效的预授权链路记录，则由记录中指定的
  消费者确认并直接续行。

消息到达顺序、用户粘贴顺序或会话编号均不自动构成执行顺序。

### 4.1 预授权链路

S1 可以按
[`docs/team/CHAIN_EXECUTION_PROTOCOL.md`](./docs/team/CHAIN_EXECUTION_PROTOCOL.md)
一次性批准一条有序链。正常路径采用 `CONSUMER_GATE`：

1. 生产者完成自测并生成 Handoff。
2. 下一消费者核对精确 Head、摘要、范围和解锁证据。
3. 消费者给出 `CONSUMER_VERDICT=ACCEPT` 后，在同一轮进入授权的
   `MODE=IMPLEMENTATION`。
4. 直到 S7 最终组合门禁或发生例外，才返回 S1。

`R3` 不适用预授权续行。`R2` 必须预先固定 Reviewer、停止条件和最终
S7 门禁。

## 5. Risk gate and execution lease

- `R0`：只读分析与报告，可自动派发。
- `R1`：角色独占路径内的可逆代码和测试；门禁通过后可交接审查。
- `R2`：安全/数据路径、共享配置、外部副作用或跨组件接口；进入 `IN_PROGRESS` 和 `ACCEPTED` 都需要指定复核者。
- `R3`：公共契约不兼容变更、破坏性迁移、凭据/权限、发布与自动合并；开始和执行前均需要用户或 S1 明确批准。

Agent 不得自行降低风险等级。

预授权只减少正常路径中的人工中转，不降低风险门禁。公共契约变化、
破坏性迁移、凭据权限、发布和自动合并仍逐次审批。

人工模式下，`ATTEMPT_ID + branch + Worktree + IN_PROGRESS` 共同构成执行租约。发现会话失联或停滞时，不得直接启动第二个写入者；S1 先记录旧 Attempt 的最后提交和工作区状态，终止或接管旧租约，再建立新 Attempt。未来自动控制面应增加 `lease_owner`、`lease_expires_at` 与 `last_heartbeat_at`，但这些字段不能替代 Git 和 Evidence。

## 6. Run protocol

责任会话启动后：

1. 按 `AGENTS.md` 顺序读取必需文档。
2. 核对 `BASE_COMMIT`、`content_digest`、路径所有权和工作区状态。
3. 先运行可用基线门禁，记录缺失命令，不把未运行写成通过。
4. 只修改 `WRITE_SCOPE`。
5. 每次契约、数据库、依赖或共享文件需求先走 RFC/交接。
6. 运行正常、边界、失败、安全和恢复测试。
7. 生成 Handoff 和 Proof of Work 后停止写入，进入 `REVIEW`。

## 7. Recovery

- 会话退出或机器重启后，从 Issue/Work Package、Git、Worktree 和 Handoff 恢复。
- 不因聊天记录丢失而重建另一套状态。
- 自动重试前确认上一次副作用状态；`UNKNOWN` 必须先对账。
- 同一工作项重试复用原分支和 Worktree，除非 S1 明确创建新的 Attempt。
- 连续失败产生后续 Issue/RFC，不静默扩大权限或范围。

## 8. Proof of Work

最低证据：

- 基线和最终提交。
- 变更文件与契约/数据库/依赖变化。
- 测试命令、退出码和报告路径。
- 安全与恢复负例。
- CI/Review 结果。
- UI 或多模态变化的可复现截图/视频或结构化替代证据。

聊天中的“已完成”“应该通过”或模型自评不能替代证据。

## 9. Trust and safety

- Agent 不获得超出当前工作包的写权限。
- 契约、安全、迁移、凭据、发布和自动合并属于重要动作，保留人工审批。
- Agent 可以提出新 Issue/RFC，但不能自行批准、改变 Owner 或扩大 Scope。
- Worktree 内不保存长期凭据、真实 PII、生产 Prompt/Trace 或原始敏感附件。
- `S1-ARCH` 是最终集成和冲突裁决者，不是所有实现路径的直接写入者。

## 10. Reasoning and communication protocol

Agent 应在内部充分分析实现、契约、安全、恢复和证据，不向聊天或仓库倾倒原始隐藏思考过程。可审计的是输入、决策理由、证据、风险和动作，而不是逐 Token 推理。

默认沟通模式为 `OUTCOME_FIRST`：

1. 首行给出结果、状态或阻塞结论。
2. 只列能支持结论的提交、文件、测试、哈希和最小复现。
3. 已在范围内安全解决的问题放入 `ACTION_TAKEN`，不再向用户追问。
4. 未解决问题按 `P0/P1/P2/P3` 合并报告，并指定 Owner 与解锁条件。
5. `USER_INPUT_REQUIRED=none` 时会话继续推进，不因发送状态消息暂停。
6. 等待中的会话只在依赖、HEAD、门禁或风险发生变化时更新，不重复发送相同状态。
7. S1 只向实际 Owner 和必要 Reviewer 选择性派发；不得把所有更新广播给无关会话。
