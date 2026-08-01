# FlowPilot Agent 注册与最小调度协议

## 1. 目标

固定七会话提供稳定的路径所有权，却不应迫使每条链重复向七个长期上下文
发送背景、等待和完成消息。本协议把角色降为能力档案，把实际执行者改为按
工作包动态选择的注册 Agent，并保持契约、安全和 Git 事实源不变。

## 2. 注册记录

每个可调度 Agent 至少声明：

```text
AGENT_ID=<stable-or-attempt-local-id>
CAPABILITIES=<typed-capability-list>
WRITE_SCOPE=<repo-relative-globs|none>
RISK_CEILING=<R0|R1|R2>
INPUT_CONTRACTS=<refs>
OUTPUT_CONTRACTS=<refs>
EVIDENCE_CONTRACT=<repo-relative-template>
AVAILABILITY=<available|busy|offline>
CONCURRENCY=<read-only|single-writer>
EXIT_CONDITION=<deterministic-condition>
```

`SESSION_ROLE` 仍决定路径 Owner 和强制 Reviewer。临时 Agent 不能通过注册获得
比 Owner 更宽的权限；需要跨 Owner 写入时必须拆成有序工作包。

## 3. 最小选择算法

S1 或后续控制面按以下顺序选择执行者：

1. 从目标功能、路径、风险和证据类型推导必需能力。
2. 排除范围冲突、风险上限不足、离线或已有写任务的 Agent。
3. 选择覆盖全部必需能力的最小集合；独立只读复核可以并行。
4. 仅向被选择者发送输入 Head、证据引用、解锁条件和退出条件。
5. 只有缺少能力、单会话范围超过可靠审查阈值或需要独立 Reviewer 时才注册
   临时 Agent。

永久编号不是拆分工作的默认方式。临时 Agent 完成交接后退出注册，不形成
新的长期聊天依赖。

## 4. 事件驱动通信

- 正常执行期间不轮询会话，不发送“仍在工作”消息。
- 只有 `COMPLETED`、`P0/P1`、权限/范围请求和用户门禁触发跨任务消息。
- 唤醒信封只包含 Chain/Step/Attempt、Head、Handoff/Proof Hash、Contract
  Digest、解锁条件和下一动作；详细日志留在仓库证据中。
- 消费者首次进入 Attempt 仍按 `AGENTS.md` 完整读取强制文档；同一 Attempt
  恢复时可用 Git Blob/内容摘要证明未变化，只重新加载变化文件和直接证据。
- 消息发送失败不改变工作状态；S1 可以用同一 `DEDUP_KEY` 恢复唯一下一跳。

## 5. Flow Lite 边界

Flow Lite 是本地辅助层，可以执行只读分析、生成待批准计划和运行已授权的
本地验证。它不是权限或状态权威，不能：

- 自动批准目标、合并、推送、发布或删除 Worktree。
- 放宽 AGENTS、Work Package、ContractSet、路径所有权或风险门禁。
- 与预授权链同时写同一工作包。

迁移采用“Flow Lite 计划/验证，FlowPilot 治理/执行”的兼容模式；后续只有在
仓库证据证明等价时，才把更多调度职责移交给注册控制面。

## 6. 验收

每条新链至少记录：被选 Agent、未选原因、消息数量、重复读取量、等待时间、
返修次数和最终证据引用。优化目标不是减少安全门禁，而是减少不改变判断的
上下文、轮询和重复复算。

出现以下情况立即回退到 S1 人工调度：契约变化、R3、路径冲突、注册身份不
唯一、证据 Hash 不一致、消费者无法确定性恢复或两个调度器竞争同一写租约。
