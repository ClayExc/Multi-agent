# CHAIN-M1-PLATFORM-01

## 授权

```text
CHAIN_ID=CHAIN-M1-PLATFORM-01
STATUS=PAUSED
AUTHORITY=S1-ARCH
AUTHORITY_REF=docs/team/chain-authorizations/CHAIN-M1-PLATFORM-01.md
EXECUTION_MODE=ORDERED
RISK_CLASS=R2
AUTO_WAKE=enabled
MAX_HOPS=6
USER_GATE=FINAL_S1
CONTRACT_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
FINAL_GATE=S7-INTEGRATION->S1-ARCH
MAX_LOCAL_REPAIR_ATTEMPTS=1
PAUSE_REASON=USER_GATE_REQUIRED
```

本链交付 FlowPilot 的最小企业工具安全纵向切片。S1 在首次唤醒信封中
提供精确的 `ACTIVATION_COMMIT`；该提交是所有参与 Worktree 的共同起点，
避免把包含本记录的提交 SHA 写回自身造成循环引用。

正常路径由生产者直接唤醒下一消费者。`CONSUMER_ACCEPTED` 只解锁下一步，
不代表工作包已由 S1 正式接受、合并或发布。

## 顺序与线性候选

```text
S3-PLATFORM
  -> S6-DATA(REVIEW_ONLY)
  -> S5-CORE
  -> S4-QUALITY
  -> S7-INTEGRATION
  -> S1-ARCH(FINAL_GATE)
```

- S3 从 `ACTIVATION_COMMIT` 实现平台切片。
- S6 只读复核 S3 与既有 Ledger/事务/租户边界，不创建提交。
- S5 在 S6 接受后将自身分支 `--ff-only` 到 S3 Head，再提交 Workspace、
  锁文件和稳定测试入口。
- S4 将自身分支 `--ff-only` 到 S5 Head，再提交独立安全黑盒与证据生成器。
- S7 将自身分支 `--ff-only` 到 S4 Head，再提交组合验证器与证据。
- 任一 `--ff-only` 失败均视为 Head/顺序漂移，停止并上报 S1；不得用
  rebase、reset、强制合并或复制文件绕过。

## Step 1：S3-PLATFORM

```text
STEP_ID=M1-PLATFORM-01-S3
SESSION_ROLE=S3-PLATFORM
WORK_PACKAGE=WP-020
ATTEMPT_ID=WP-020-a1
BASE_COMMIT=WAKE_MESSAGE.ACTIVATION_COMMIT
UPSTREAM_HEADS=none
WORKTREE=E:\workspace\Multi-agent-s3
WRITE_SCOPE=apps/mcp-gateway/**,packages/tool-contracts/**,packages/policy/**,packages/security/**,mcp-servers/**,tests/platform/**
MODE=IMPLEMENTATION
UNLOCK_CONDITION=S3 branch and Worktree are clean at ACTIVATION_COMMIT; ContractSet digest matches
REVIEWER=S6-DATA
NEXT_ROLE=S6-DATA
NEXT_ATTEMPT_ID=WP-020-r1-s6
```

实施边界：

1. Gateway 是唯一工具入口；Tool Registry、输入/输出 Schema 与白名单
   采用默认拒绝。
2. 同时验证用户与 Agent 主体、租户、Purpose、Audience、上下文哈希及
   有效期；未知或无法执行的 Obligation fail-closed。
3. Approval 必须完整绑定动作摘要、Tool Schema Hash、PolicyDecision、
   策略版本、主体、租户和过期时间。
4. 写路径只消费 S6 Execution Ledger Port；重复请求、超时
   `UNKNOWN`、权威未执行证明和回读确认遵守 ADR-0002。
5. Audit 与 Security Event 分流且不可采样；拒绝发生在账本占位和上游
   调用之前时，逻辑写入数必须为 0。
6. 至少提供一个只读模拟 MCP；不得引入生产凭据、真实企业网络或第二套
   Persistence 实现。
7. 每个请求生成可关联的结构化生命周期，至少覆盖入口、身份校验、策略、
   审批绑定、账本、上游调用、回读、结果和安全事件；阶段结果使用稳定
   原因码、版本与脱敏证据引用，不能依赖自由文本解释。
8. 提供白名单 `debug_projection` 与阶段指标，使成功、拒绝、`UNKNOWN`、
   对账和恢复都可被重建；不得保存隐藏思维链、明文 Secret、原始敏感
   Context 或完整生产 Payload，且可观察信号不参与授权和业务终态判断。

## Step 2：S6-DATA 只读复核

```text
STEP_ID=M1-PLATFORM-02-S6-REVIEW
SESSION_ROLE=S6-DATA
WORK_PACKAGE=WP-020
ATTEMPT_ID=WP-020-r1-s6
BASE_COMMIT=WAKE_MESSAGE.ACTIVATION_COMMIT
UPSTREAM_HEADS=S3-PLATFORM:<Step-1-NEW_HEAD>
WORKTREE=E:\workspace\Multi-agent-s6
WRITE_SCOPE=none
MODE=REVIEW_ONLY
UNLOCK_CONDITION=S3 Handoff, Head, digest, scope and tests are reproducible
REVIEWER=S6-DATA
NEXT_ROLE=S5-CORE
NEXT_ATTEMPT_ID=WP-011-a4
```

S6 只检查：

- S3 没有建立私有账本、Redis 事实源或绕过租户事务上下文。
- Execution Ledger 的 key、状态转换、`UNKNOWN` 与回读证据能由既有 Port
  确定性实现。
- 拒绝路径不会产生有效账本占位、Outbox 或上游调用。
- 需要修改 S6 Port、Migration 或事务语义时立即暂停；不得在本 Step 写入。

复核通过后，S6 把原 S3 Head/Handoff 与自己的消费者结论一并唤醒 S5。

## Step 3：S5-CORE Workspace 闭包

```text
STEP_ID=M1-PLATFORM-03-S5
SESSION_ROLE=S5-CORE
WORK_PACKAGE=WP-011
ATTEMPT_ID=WP-011-a4
BASE_COMMIT=<Step-1-NEW_HEAD after ff-only>
UPSTREAM_HEADS=S3-PLATFORM:<Step-1-NEW_HEAD>
WORKTREE=E:\workspace\Multi-agent-s5
WRITE_SCOPE=pyproject.toml,uv.lock,Makefile,tests/core/evidence/WP-011-a4-HANDOFF.md
MODE=IMPLEMENTATION
UNLOCK_CONDITION=S6 consumer review ACCEPT and S5 ff-only reaches exact S3 Head
REVIEWER=S4-QUALITY
NEXT_ROLE=S4-QUALITY
NEXT_ATTEMPT_ID=WP-030-a2
```

实施边界：

1. 注册 S3 新增的可安装 Workspace 包和内部依赖，刷新并锁定完整闭包。
2. 把平台测试纳入稳定入口，并提供真实可运行的安全测试入口；不得用局部
   手工命令冒充 `make test-security`。
3. 复跑 Core、Runtime、Data、Platform、Contract、Ruff、严格 Mypy、
   Wheel 与 Secret Scan。
4. S3 包装或实现缺陷退回 S3；S5 只修共享 Workspace、锁和命令入口。

### Scope Amendment 01

```text
AMENDMENT_ID=CHAIN-M1-PLATFORM-01-S5-HANDOFF-01
AUTHORITY=S1-ARCH
STATUS=ACTIVE
ATTEMPT_ID=WP-011-a4
AUTHORIZED_PATH=tests/core/evidence/WP-011-a4-HANDOFF.md
RISK_CLASS=R2_UNCHANGED
PRODUCT_SCOPE=UNCHANGED
```

原 Step 只列出三个共享文件，却同时要求 S5 按 `HANDOFF_TEMPLATE.md`
生成仓库内证据，形成控制面自相矛盾。现只增加上述 S5 自有的精确证据文件；
不授权其他 `tests/core/**` 修改，不改变实现 Head、公共契约、数据库、Owner
或局部返修计数。S5 在现有实现 Head 后追加 Handoff 提交并继续唤醒 S4。

## Step 4：S4-QUALITY 安全黑盒

```text
STEP_ID=M1-PLATFORM-04-S4
SESSION_ROLE=S4-QUALITY
WORK_PACKAGE=WP-030
ATTEMPT_ID=WP-030-a2
BASE_COMMIT=<Step-3-NEW_HEAD after ff-only>
UPSTREAM_HEADS=S5-CORE:<Step-3-NEW_HEAD>
WORKTREE=E:\workspace\Multi-agent-s4
WRITE_SCOPE=tests/acceptance/**,artifacts/acceptance/**的生成器与结构
MODE=IMPLEMENTATION
UNLOCK_CONDITION=S5 workspace handoff ACCEPT and S4 ff-only reaches exact S5 Head
REVIEWER=S7-INTEGRATION
NEXT_ROLE=S7-INTEGRATION
NEXT_ATTEMPT_ID=WP-040-a4
```

S4 至少以独立黑盒覆盖：

- 双主体、跨租户、Purpose/Audience、上下文过期和角色伪造。
- Approval 的动作摘要、Schema Hash、策略版本、主体、租户和有效期篡改。
- 未知/冲突 Obligation、策略不可用、工具旁路、恶意 Tool 输出与 Secret。
- 重复写、`UNKNOWN`、权威未执行证明、回读确认和恢复重放。
- Trace 可采样而 Audit/Security 不可采样，拒绝码和双向关联稳定。
- 从结构化信号重建端到端 Gateway 时间线；缺失阶段、关联错乱、未知原因码、
  调试投影越界或敏感数据泄漏均必须失败。

确定性失败不能被 Judge 覆盖；本 Step 不填充或宣称 120/36 数据集完成。

## Step 5：S7-INTEGRATION

```text
STEP_ID=M1-PLATFORM-05-S7
SESSION_ROLE=S7-INTEGRATION
WORK_PACKAGE=WP-040
ATTEMPT_ID=WP-040-a4
BASE_COMMIT=<Step-4-NEW_HEAD after ff-only>
UPSTREAM_HEADS=S4-QUALITY:<Step-4-NEW_HEAD>
WORKTREE=E:\workspace\Multi-agent-s7
WRITE_SCOPE=scripts/integration/**,tests/integration/**,artifacts/integration/**的生成器与结构
MODE=IMPLEMENTATION
UNLOCK_CONDITION=S4 consumer handoff ACCEPT and S7 ff-only reaches exact S4 Head
REVIEWER=S1-ARCH
NEXT_ROLE=S1-ARCH
```

S7 复算 Head、路径、Handoff Hash、ContractSet、Workspace/Lock、Wheel、
联合测试、稳定命令、Secret、安全负例、机器可读执行时间线与证据闭包。
需要真实 Compose 时复用隔离资源并在结束后清理。S7 不批准合并。

## 自动唤醒与去重

- 每个生产者按 `flowpilot.thread-wake.v1` 发送一条唤醒信封。
- `DEDUP_KEY=CHAIN_ID/STEP_ID/ATTEMPT_ID/INPUT_HEAD`。
- 任务映射只在客户端按精确标题与项目核对，不写入 Git。
- 没有新增事实的等待状态不唤醒任何会话。
- 最后由 S7 唤醒 S1，且必须包含 `USER_GATE_REQUIRED=yes`。

## 局部返修

- 同一 Step 最多一次局部返修。
- S6 可把 Ledger 消费侧问题退回 S3；S4 可把平台行为问题退回 S3，把
  Workspace/命令问题退回 S5；S7 按责任路径退回相应生产者。
- 返修仍在原 Owner、原路径和原风险内完成，并产生新 Attempt/Head。
- 超过一次、无法唯一归责或需要改变顺序时，链路转为 `PAUSED`。

## 停止条件

除通用协议外，以下情况必须暂停并上报 S1：

1. 公共 ContractSet、Schema、ADR 或 Feature 完成定义需要变化。
2. 需要修改 S6 Port、Migration、RLS、事务语义或引入第二事实源。
3. 需要生产凭据、真实企业写端点、扩大网络出口或外部发布。
4. 出现跨租户成功、工具旁路、审批重放、重复逻辑写入或明文 Secret。
5. Head、Handoff Hash、工作树、路径所有权、锁文件或门禁不一致。
6. `--ff-only` 无法形成单一线性候选。
7. 风险升级为 R3 或局部返修次数耗尽。

## 最终门禁

S7 交回后，S1 独立复核不变量、范围、证据和主分支转换方案。S1 不自动
合并，不自动启动下一链；最终只向用户报告本轮完成、问题、重大决策与
下一步，并等待用户指令。

## S1 Final Gate

```text
FINAL_GATE_STATUS=PASS_AWAITING_USER
S7_HEAD=197a2eaafa354c590e8a130c4a1118cf0f0035d3
S1_COMPOSITION_HEAD=edc18fe37fdfd2e971908ee7f0264a41bd2e235c
S1_FINAL_CHECKS=37/37_PASS
JOINT_TESTS=279_PASS
MERGED_TO_MASTER=no
RELEASED=no
FROZEN=no
USER_GATE_REQUIRED=yes
```

S1 在独立 Final Worktree 把当前控制面与完整 S7 线性候选组合为一个
双父提交。主分支仍停留在 Scope Amendment 控制提交；本链不会在用户门禁
前自动合并或启动下一链。正式裁决见
[`WP-040-A4-S1-FINAL-REVIEW.md`](../../review/WP-040-A4-S1-FINAL-REVIEW.md)。
