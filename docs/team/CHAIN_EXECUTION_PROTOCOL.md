# FlowPilot 预授权链路执行约定

## 1. 目的

七个顶层 Codex 会话默认互相独立。人工把每份交接先发给 S1，再由 S1
原样转发给下一会话，只会增加等待和重复沟通；支持任务唤醒的客户端可以
按独立协议自动投递下一步。

预授权链路把一组依赖明确的工作一次性批准。正常情况下，生产者直接
交给下一消费者；只有发生例外或到达最终集成门禁时才返回 S1。

本约定不改变路径所有权、风险等级、证据要求或 S1 的最终集成责任。

交接既可以由用户复制，也可以按
[`THREAD_WAKE_PROTOCOL.md`](./THREAD_WAKE_PROTOCOL.md)
由生产者自动唤醒下一 Codex 任务。唤醒只是通知，Git Head、Handoff、
Contract Digest 与 Evidence 仍是唯一工作事实。

## 2. 核心语义

- `HANDOFF`：生产者完成本轮实现和自测，交付候选 Head。
- `CONSUMER_ACCEPTED`：下一消费者确认该候选足以实现自己的适配范围。
- `ACCEPTED`：S1 根据跨角色复核和证据正式接受工作包。
- `MERGED`：候选已进入主分支，主分支门禁通过。

`CONSUMER_ACCEPTED` 只解锁预授权链的下一步，不提升功能状态，不代表
工作包已经被 S1 接受或可以合并。

## 3. 链路授权

每条链必须在 S1 独占路径中保存一份授权记录，至少包含：

```text
CHAIN_ID=<stable-id>
STATUS=<ACTIVE|PAUSED|COMPLETED|CANCELLED>
AUTHORITY=S1-ARCH
AUTHORITY_REF=<repository-relative-path>
EXECUTION_MODE=ORDERED
CONTRACT_CONTENT_DIGEST=sha256:<64hex>
FINAL_GATE=S7-INTEGRATION->S1-ARCH
MAX_LOCAL_REPAIR_ATTEMPTS=<number>
```

每一步还必须写明：

```text
STEP_ID=<stable-id>
SESSION_ROLE=<role>
WORK_PACKAGE=<wp>
ATTEMPT_ID=<attempt>
BASE_COMMIT=<sha-or-explicit-dynamic-input>
UPSTREAM_HEADS=<role:sha,...|none>
WORKTREE=<absolute-path>
WRITE_SCOPE=<paths>
UNLOCK_CONDITION=<deterministic-condition>
NEXT_ROLE=<role|S1-ARCH>
REVIEWER=<consumer-role|S7-INTEGRATION|S1-ARCH>
```

会话只能消费授权记录中已经存在的 Attempt、顺序和范围，不能自行添加
步骤、改变 Owner、扩大写入范围或降低风险等级。

## 4. 可预授权范围

- `R0`：可直接进入只读链。
- `R1`：S1 可预授权生产者到消费者的连续实施与验证。
- `R2`：只有验收条件、消费者 Reviewer、停止条件和最终 S7 门禁均已
  写入授权记录时，才能预授权。
- `R3`：不得自动续行。公共契约不兼容变更、破坏性迁移、凭据与权限、
  发布和自动合并必须逐次取得用户或 S1 明确批准。

使用自动唤醒时还必须声明 `AUTO_WAKE=enabled`、`MAX_HOPS` 和
`USER_GATE`。最后一个 S1 门禁不得自动批准下一轮。

## 5. 正常交接

生产者完成后输出：

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=<id>
STEP_ID=<id>
ATTEMPT_ID=<id>
NEW_HEAD=<sha>
BASE_COMMIT=<sha>
CONTRACT_CONTENT_DIGEST=sha256:<64hex>
GATE=<PASS|ENV_BLOCKED>
HANDOFF=<repository-relative-path>
NEXT_ROLE=<role>
NEXT_ATTEMPT_ID=<id>
ESCALATE_TO_S1=no
```

用户只需把该输出发给 `NEXT_ROLE`。消费者先执行只读校验：

1. `CHAIN_ID`、Step、Attempt 和自身角色匹配授权记录。
2. 上游 Head、ContractSet 摘要、分支和交接证据一致。
3. 上游变更未越过路径所有权，工作树洁净。
4. `UNLOCK_CONDITION` 有可核验的代码、测试或证据支持。
5. 未触发本约定第 7 节的停止条件。

校验通过后，消费者输出 `CONSUMER_VERDICT=ACCEPT`，并可在同一轮进入
授权记录指定的 `MODE=IMPLEMENTATION`，不再等待 S1 重复派发。

消费者不得把 `CONSUMER_ACCEPTED` 写成 `ACCEPTED`、`VERIFIED` 或
`MERGED`。

## 6. 局部返修

消费者发现的问题若同时满足以下条件，可以直接退回生产者修复：

- 问题属于原工作包、原写入范围和原风险等级。
- 不改变公共契约、ADR、共享文件 Owner 或数据库迁移性质。
- 授权记录中的 `MAX_LOCAL_REPAIR_ATTEMPTS` 尚未用尽。

消费者返回 `CONSUMER_VERDICT=REJECT`、最小复现、责任路径和解锁条件。
生产者使用原分支和新的修复提交处理，不建立第二个并行写入者。

超过局部返修次数或需要扩大范围时，链路转为 `PAUSED` 并上报 S1。

## 7. 必须停止并上报 S1

出现任一情况时，后续会话保持只读：

1. ContractSet 摘要、公共 Schema、ADR 或 Feature 完成定义变化。
2. 需要未授权路径、共享文件或新的外部系统写入。
3. 风险升为 `R3`，或原 `R2` 的安全、租户、状态权威、事务性质发生变化。
4. 门禁失败、证据缺失、Head 不匹配、工作树不洁净或提交范围越权。
5. 迁移变成非线性、破坏性或无法给出失败关闭的回滚策略。
6. 生产者和消费者对 Port 语义无法达成确定性一致。
7. 同一问题超过授权的局部返修次数。
8. 用户改变范围、顺序、Owner 或终止链路。

上报只包含结论、证据、风险和所需裁决，不提交隐藏思考过程。

## 8. 最终门禁

正常链路只在以下时点返回 S1：

- S7 完成组合、依赖闭包和证据复现。
- 链路触发第 7 节停止条件。
- 授权记录指定了额外的 S1 门禁。

S7 不负责批准合并。S1 根据候选 Heads、S7 报告和风险 Reviewer 结论决定
`ACCEPTED`、集成顺序及是否进入主分支。
