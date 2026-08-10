# FlowPilot Codex 会话自动唤醒协议

## 1. 目标

Codex 客户端允许一个既有任务向另一个既有任务发送后续指令并唤醒空闲任务。FlowPilot 用它减少人工复制交接，但不把聊天消息变成工作状态或授权事实。

只有 S1～S7 领域主 Agent可以发送跨任务唤醒。主 Agent内部的子 Agent将结果返回
父任务，`WAKE_AUTHORITY=none`，不能直接进入 Chain 下一 Step。

推荐循环：

```mermaid
flowchart LR
    U["用户 + S1 决策门禁"] --> S2["S2 实施"]
    S2 -->|"Head + Handoff"| S3["S3 消费/实施"]
    S3 -->|"Head + Handoff"| S7["S7 组合验证"]
    S7 -->|"Final evidence"| S1["S1 最终裁决"]
    S1 -->|"USER_GATE_REQUIRED"| U
```

到达最后一个 S1 后必须等待用户共同决策。用户明确批准下一轮后，S1 才能唤醒新的首个责任会话。

## 2. 两个平面

| 平面 | 内容 | 是否权威 |
|---|---|---|
| 工作状态 | Work Package、Git Head、Contract Digest、Handoff Hash、Evidence、门禁结果 | 是 |
| 唤醒通知 | Codex task ID、消息、到达状态、对话摘要 | 否 |

任务未收到消息不改变 Git 状态；消息重复到达也不能重复执行同一 Attempt。聊天关闭、摘要压缩或客户端重启后，消费者必须从工作状态恢复。

## 3. 链授权

S1 在启动前写入或明确声明：

```text
CHAIN_ID=<stable-id>
GOAL=<可验收目标>
AUTHORITY=S1-ARCH
EXECUTION_MODE=ORDERED
AUTO_WAKE=enabled
RISK_CLASS=<R0|R1|R2>
MAX_HOPS=<positive-int>
USER_GATE=FINAL_S1
ORDER=S2-RUNTIME->S3-PLATFORM->S7-INTEGRATION->S1-ARCH
STOP_CONDITIONS=P0/P1,contract_change,path_violation,gate_failure,risk_upgrade
```

R3、破坏性数据操作、生产凭据、外部发布和公共契约不兼容变化不能预授权自动唤醒链。

## 4. 唤醒信封

生产者只向下一个消费者发送一条结构化消息：

```text
WAKE_PROTOCOL=flowpilot.thread-wake.v1
CHAIN_ID=<id>
STEP_ID=<id>
ATTEMPT_ID=<id>
DEDUP_KEY=<chain/step/attempt/input-head>
PRODUCER_ROLE=<role>
CONSUMER_ROLE=<role>
EXECUTION_MODE=ORDERED
RISK_CLASS=<class>
BASE_COMMIT=<sha>
INPUT_HEAD=<sha>
CONTRACT_CONTENT_DIGEST=sha256:<64hex>
CONTEXT_MODE=<DELTA|FULL>
CONTEXT_BASE_COMMIT=<consumer-last-accepted-context-sha|none>
CONTEXT_TARGET_COMMIT=<exact-input-head>
CONTEXT_REQUIRED_READS=<chain,work-package,registry,direct-handoff>
HANDOFF=<repo-relative-path>
HANDOFF_SHA256=sha256:<64hex>
UNLOCK_CONDITION=<deterministic-condition>
MODE=<REVIEW_ONLY|IMPLEMENTATION|FINAL_GATE>
USER_GATE_REQUIRED=<yes|no>
```

自由文本只能补充目标和已知风险，不能放宽信封中的范围、风险和停止条件。

## 5. 消费者算法

消费者被唤醒后依次执行：

1. 核对自身 `SESSION_ROLE`、Worktree、分支和允许路径。
2. 检查 `DEDUP_KEY`；已经消费过的消息只返回原结果，不重复写入。
3. 验证 Base/Input Head、Contract Digest、Handoff Hash、工作树洁净度和解锁条件。
4. 按 [`CONTEXT_BOOTSTRAP_PROTOCOL.md`](./CONTEXT_BOOTSTRAP_PROTOCOL.md) 验证
   Context Base→Target，并只加载直接材料和变化片段；新 Attempt 不等于 `FULL`。
5. 门禁不满足时停止，不唤醒下一会话；一次性批量报告阻断。
6. 门禁满足时执行授权 Attempt，生成新的 Head、Handoff 和证据。
7. 只有 `CONSUMER_ACCEPTED` 且不命中停止条件，才向链中的下一个角色发送唤醒信封。
8. 最后一个生产者唤醒 S1；S1 运行 final gate 后输出 `USER_GATE_REQUIRED=yes` 并停止。

主 Agent使用子 Agent时，必须先汇总并复现其结果，再由主 Agent生成 Head/Handoff；
子 Agent输出不能直接替代生产者门禁。

唤醒发送成功只表示消息已投递，不表示消费者已经接受或完成。

## 6. 循环保护

- `MAX_HOPS` 防止 S1→S2→S3→S7→S1 之外的意外回环。
- 同一 `CHAIN_ID/STEP_ID/ATTEMPT_ID/INPUT_HEAD` 只消费一次。
- 返修增加 Attempt，不覆盖旧 Head 和旧证据。
- 每个 Step 只有一个合法下一角色；不能由模型临时选择新的会话。
- P0/P1、契约变化、路径越权、风险升级、门禁失败和脏工作树立即断链。
- 没有新增事实的等待状态不触发消息。
- S1 final 与用户门禁之间禁止自动超时批准。

## 7. Task 映射

Codex task ID 和 Host ID 属于本地客户端运行状态，不提交 Git，也不写进可移植契约。S1 派发前通过客户端核对：

- 任务标题与 `SESSION_ROLE` 一致。
- 工作目录/Worktree 与角色一致。
- 目标任务不是另一个项目的同名会话。
- 目标任务没有正在执行冲突 Work Package。

找不到唯一目标时停止并请用户指定；不能只按模糊标题发送。

## 8. 用户门禁

用户不需要为每轮填写“目标”或机器字段。S1 根据已接受的工作包、路线图、当前阻断和上一轮决策确定下一条候选链，并补齐 Chain/Step/Attempt、Heads、路径、测试、停止条件和任务映射。

S1 final 只向用户报告四项：

```text
本轮完成：
- 已完成并验证的功能。

本轮问题：
- 新发现的问题、影响和当前处理状态；没有则写“无新增问题”。

需要重大决策：
- 只有会改变范围、架构、安全、成本或外部副作用的选择；没有则写“无”。

下一步：
- 推荐启动的工作、角色顺序和前置条件。
```

原始 Head、Hash、测试明细和命令保存在 Handoff/Evidence 中。用户询问问题细节或证据时，S1 再按需展开，不在每轮默认粘贴。

用户可以直接回复：

- `继续`：按 S1 推荐的下一步启动新链。
- `查看问题细节`：不启动新链，先展开问题与证据。
- `调整方向：...`：S1 重算工作包和顺序。
- `停止`：不再唤醒任何会话。

如果下一步涉及 R3、生产/外部写入、破坏性操作或不可兼容契约变化，S1 必须提出明确决策题，不能把用户的普通“继续”解释为扩大授权。

## 9. 失败恢复

- 发送失败：生产者保留 Handoff，不改变 Step 状态；S1 或用户可按同一 `DEDUP_KEY` 重发。
- 消费者环境不可用：状态为 `ENV_BLOCKED`，不跳过该消费者。
- 客户端重启：S1 从仓库 Chain 记录和最新 Head 恢复，不依赖对话记忆。
- 用户拒绝 final：S1 创建新 Attempt 或终止 Chain，不修改已经完成的历史证据。
