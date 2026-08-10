# FlowPilot 主 Agent 与子 Agent 协作协议

## 1. 适用对象

S1～S7 是长期存在的领域主 Agent，负责角色权限、工作包、Git Head、测试结论和
跨会话交接。子 Agent 是主 Agent 在单个 Attempt 内创建的临时执行者，只处理一个
边界清楚的子任务，完成后退出。

子 Agent 不会获得新的 `SESSION_ROLE`，也不会成为第八个长期会话。它的有效权限是
以下三者的交集：

```text
主 Agent 路径所有权 ∩ 当前 Work Package WRITE_SCOPE ∩ 子任务声明范围
```

## 2. 可以自主分派的工作

主 Agent 已完成消费者门禁并持有有效工作包时，可以在以下范围内自主调用子 Agent，
不需要再次请求 S1 或用户批准：

- 只读代码调查、接口核对、失败路径检查和测试矩阵设计。
- 互不依赖的测试复现、日志归因、依赖或安全检查。
- 当前工作包内一个边界明确的小型实现切片。
- 对主 Agent 修改结果的独立只读复核。

以下工作不能交给子 Agent 自行决定：

- 公共契约、ADR、Feature 状态、发布结论和跨角色接口取舍。
- 新依赖、共享文件、Migration、外部写入、生产凭据或付费调用。
- 超出当前工作包的顺手修复，或需要新 Worktree/新分支的并行实现。
- P0/P1、R3 和停止条件命中后的修复授权。

这些情况允许子 Agent 做只读最小复现，结论交回主 Agent，由主 Agent 按现有协议
上报或申请新工作包。

## 3. 子任务信封

每个子 Agent 必须收到一份短信封，不从整段聊天历史猜测任务：

```text
SUBAGENT_PROTOCOL=flowpilot.principal-subagent.v1
SUBAGENT_ID=<attempt-local-id>
TASK_DEDUP_KEY=<attempt/subtask/input-head>
PARENT_SESSION_ROLE=<S1-ARCH|...|S7-INTEGRATION>
PARENT_AGENT_ID=<registered-agent-id>
WORK_PACKAGE=<id>
ATTEMPT_ID=<id>
INPUT_HEAD=<sha>
TASK=<single-bounded-task>
EXECUTION_MODE=<READ_ONLY_PARALLEL|ORDERED_WRITE>
READ_SCOPE=<repo-relative-paths>
WRITE_SCOPE=<none|repo-relative-paths>
RISK_CEILING=<R0|R1|R2>
REQUIRED_OUTPUT=<findings|patch|test-result|review>
EXIT_CONDITION=<deterministic-condition>
GIT_AUTHORITY=none
WAKE_AUTHORITY=none
```

`WRITE_SCOPE` 不能宽于父工作包。需要跨 Owner 写入时，由主 Agent 停止分派并走
工作包或 Chain，而不是把多个角色塞进同一个子 Agent。

## 4. 热启动上下文

主 Agent 先按 [`CONTEXT_BOOTSTRAP_PROTOCOL.md`](./CONTEXT_BOOTSTRAP_PROTOCOL.md)
完成 `DELTA` 或 `FULL` 加载，再为子 Agent 生成 Context Capsule。Capsule 只包含：

1. 精确 `INPUT_HEAD`、当前工作包和子任务范围。
2. 与子任务直接相关的接口、约束、失败现象和验收条件。
3. 必须读取的代码、测试和直接证据路径。
4. 已确定且不得重复调查的事实。

Capsule 还应声明 `KNOWN_FACTS`、`DO_NOT_RECHECK` 和直接证据 Hash。只要输入 Head 的
相关 Blob、Contract Digest 和证据 Hash 没有变化，子 Agent必须复用既有结论。

客户端已经向子 Agent 传入当前 `AGENTS.md` 时不得重复读取。子 Agent 不重新读取
README、STRUCTURE、完整路线或历史 Handoff；发现必要上下文缺失时返回
`CONTEXT_GAP`，由主 Agent 补充最小材料。

## 5. 并发与写入

- 默认同时激活 1～2 个子 Agent；只有三个以上互相独立的只读检查才增加数量，且
  不得超过客户端可用槽位。
- 多个 `READ_ONLY_PARALLEL` 子 Agent 可以并行。
- 同一个 Worktree 同一时刻只能有一个写入者。主 Agent 分派 `ORDERED_WRITE` 后，
  自身和其他子 Agent 暂停文件写入，直到该子任务退出。
- 两个子 Agent 即使声称修改不同目录，也不能并行写同一个 Worktree。
- 需要真正并行写入时，提升为注册 Agent，使用独立 Worktree、分支和 Work Package。

子 Agent 不执行 `git add`、`commit`、`merge`、`rebase`、`reset`、`push`、Worktree
创建或删除。Git 写操作、冲突处理和最终提交均由主 Agent负责。

## 6. 主 Agent 责任

主 Agent 必须检查子 Agent 的结论和实际文件差异，复跑与风险相称的测试后才能提交。
子 Agent 的“通过”不直接成为 Handoff 或发布证据；只有主 Agent 可复现的命令、结果
和 Evidence 才能进入正式交接。

主 Agent 还负责：

- 合并重复发现，解决子 Agent 之间的冲突结论。
- 确认没有越权路径、隐藏依赖和意外脏文件。
- 将可复用机理写成 `LEARNING_CANDIDATE`，不保存子 Agent 的隐藏思考过程。
- 由自身向下一长期会话发送唯一唤醒消息；子 Agent 没有跨会话唤醒权。

S1 的子 Agent只能辅助调查、契约一致性检查和证据复算，架构与发布裁决仍由 S1
作出。S7 的子 Agent默认只读；若编写集成验证器，也必须遵守单写者规则，最终组合
结论仍由 S7 主 Agent和 S1 分别复核。

## 7. 复用优先

主 Agent在分派前先检查当前 Handoff、已接受测试、Decision/ADR、
`LEARNING_CANDIDATE` 和相关 Git 差异。满足以下条件时直接复用，不重新调查：

- 输入 Head 线性前进，相关代码、契约和配置 Blob 未变化。
- 既有证据 Hash 可复算，测试语义和环境前提未变化。
- 同一 `TASK_DEDUP_KEY` 已完成且没有新的反例。

必须独立复核的安全、数据和发布门禁仍然执行，但复核应切换观察边界。例如生产者
完成白盒单测后，消费者做黑盒 API/SSE 负例，不再原样重复生产者的内部测试。

同类错误第二次出现时，不再增加孤立样本补丁。主 Agent应提炼失败签名，检查共享
机理、调用边界和所有消费者，增加数据驱动回归矩阵。第三次仍出现等价绕过时停止
局部返修，按 P0/P1 升级架构或控制面处理。

并行子任务必须回答不同问题。两个子 Agent拿到相同 `TASK`、范围和验收条件属于
重复调度，除非工作包明确要求双人独立复核。

## 8. 交接记录

正式 Handoff 只记录子 Agent 使用摘要，不附聊天记录：

```text
SUBAGENTS_USED=<0|count>
SUBAGENT_MODES=<none|READ_ONLY_PARALLEL|ORDERED_WRITE|mixed>
SUBAGENT_TASKS=<short-id-list>
SUBAGENT_WRITERS=<0|1>
PARENT_REPRODUCED_RESULTS=<yes|no>
REUSED_DECISIONS=<none|evidence-or-decision-refs>
DUPLICATE_WORK_AVOIDED=<count>
```

建议同时记录子 Agent 实际读取文件数、重复读取数、返回冲突数和主 Agent 复跑命令。
这些数据用于判断分派是否节省时间与 Token，不作为减少安全门禁的理由。

## 9. 失败关闭

出现以下任一情况，主 Agent立即停止相关子任务：

- 子 Agent 修改未授权路径、执行 Git 写操作或尝试唤醒其他长期会话。
- 同一 Worktree 出现第二个写入者或无法解释的脏文件。
- 输入 Head、Contract Digest、接口版本或父工作包发生变化。
- 子 Agent 发现公共契约、安全边界、数据兼容性或外部副作用问题。
- 子 Agent 结果彼此冲突，且主 Agent 无法用确定性测试裁决。

停止后保留可复现证据，由主 Agent 按 P0～P3 和 Chain 规则处理。
