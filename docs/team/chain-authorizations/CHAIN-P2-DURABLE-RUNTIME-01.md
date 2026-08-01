# CHAIN-P2-DURABLE-RUNTIME-01

## 授权

```text
CHAIN_ID=CHAIN-P2-DURABLE-RUNTIME-01
STATUS=ACTIVE
AUTHORITY=S1-ARCH
AUTHORITY_REF=docs/team/chain-authorizations/CHAIN-P2-DURABLE-RUNTIME-01.md
FLOW_LITE_GOAL_ID=g1
FLOW_LITE_APPROVED_AT=2026-08-01T09:19:07Z
EXECUTION_MODE=ORDERED
RISK_CLASS=R2
AUTO_WAKE=enabled
MAX_HOPS=4
USER_GATE=FINAL_S1
CONTRACT_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
FINAL_GATE=S7-INTEGRATION->S1-ARCH
MAX_LOCAL_REPAIR_ATTEMPTS=1
EFFICIENCY_POLICY=EVENT_DRIVEN_COMPACT_V1
```

本授权只覆盖 Flow Lite 计划中经用户明确批准的 `g1`。`g2`（Outbox→SSE）和
`g3`（安全 Ticket 写入）仍为待批准目标，不得在本链顺带实施。

## 目标与非目标

目标、功能 ID、架构约束和测试边界以
[`WP-P2-durable-runtime.md`](../work-packages/WP-P2-durable-runtime.md) 为准。
注册能力和未选择角色以
[`Agent 注册表`](../agent-registrations/CHAIN-P2-DURABLE-RUNTIME-01.md) 为准。

## 顺序

```text
data-recovery(S6/WP-021-a3)
  -> durable-runtime(S2/WP-010-a4)
  -> recovery-verifier(S7/WP-040-a7)
  -> S1-ARCH(FINAL_GATE)
  -> USER_GATE
```

这是严格有序、单写者链。只有 `COMPLETED`、`P0/P1`、范围/权限请求或最终用户
门禁产生跨任务消息；不得轮询、广播等待状态或向未注册会话发送背景材料。

## Step 1：data-recovery

```text
STEP_ID=P2-DURABLE-01-DATA
AGENT_ID=data-recovery
SESSION_ROLE=S6-DATA
WORK_PACKAGE=WP-021
ATTEMPT_ID=WP-021-a3
BASE_COMMIT=WAKE_MESSAGE.ACTIVATION_COMMIT
UPSTREAM_HEADS=none
WORKTREE=E:\workspace\Multi-agent-s6
WRITE_SCOPE=packages/persistence/**,tests/data/**
MODE=IMPLEMENTATION
UNLOCK_CONDITION=clean worktree; current Head is ancestor of ACTIVATION_COMMIT; ff-only reaches exact ACTIVATION_COMMIT; ContractSet digest matches
NEXT_AGENT_ID=durable-runtime
NEXT_ROLE=S2-RUNTIME
NEXT_ATTEMPT_ID=WP-010-a4
HANDOFF=tests/data/evidence/WP-021-a3-HANDOFF.md
```

S6 必须先审计现有 Port，避免重复实现；只补齐 Runtime 所需的确定性缺口：
可信 Task/Thread 查询、Lease acquire/assert/release、Generation fencing、Checkpoint
CAS/序列和 Outbox→Redis 信号重建。生产代码已有能力时以缺口测试和 Handoff
证明为主。不得创建迁移、修改 Compose/Lock/契约或扩大数据模型。

## Step 2：durable-runtime

```text
STEP_ID=P2-DURABLE-02-RUNTIME
AGENT_ID=durable-runtime
SESSION_ROLE=S2-RUNTIME
WORK_PACKAGE=WP-010
ATTEMPT_ID=WP-010-a4
BASE_COMMIT=<Step-1-NEW_HEAD after ff-only>
UPSTREAM_HEADS=S6-DATA:<Step-1-NEW_HEAD>
WORKTREE=E:\workspace\Multi-agent-s2
WRITE_SCOPE=apps/worker/**,packages/graph/**,tests/runtime/**
MODE=IMPLEMENTATION
UNLOCK_CONDITION=S6 Handoff consumer ACCEPT and S2 ff-only reaches exact S6 Head
NEXT_AGENT_ID=recovery-verifier
NEXT_ROLE=S7-INTEGRATION
NEXT_ATTEMPT_ID=WP-040-a7
HANDOFF=tests/runtime/evidence/WP-010-a4-HANDOFF.md
```

S2 将 Worker 接到 S6 类型化 Checkpoint/Lease/Outbox 边界；生产恢复入口不得
默认依赖 `InMemorySaver`，`studio-safe` 的内存模式不受影响。必须使用新 Worker
实例复现进程重启，证明 Redis 丢失可重建、旧 Worker 被 fencing、Checkpoint
序列单调且已完成分支不重跑。不得直连数据库、添加依赖或修改共享文件。

## Step 3：recovery-verifier

```text
STEP_ID=P2-DURABLE-03-VERIFY
AGENT_ID=recovery-verifier
SESSION_ROLE=S7-INTEGRATION
WORK_PACKAGE=WP-040
ATTEMPT_ID=WP-040-a7
BASE_COMMIT=<Step-2-NEW_HEAD after ff-only>
UPSTREAM_HEADS=S2-RUNTIME:<Step-2-NEW_HEAD>
WORKTREE=E:\workspace\Multi-agent-s7
WRITE_SCOPE=scripts/integration/**,tests/integration/**
MODE=IMPLEMENTATION
GATE_LEVEL=RELEASE
UNLOCK_CONDITION=S2 Handoff consumer ACCEPT and S7 ff-only reaches exact S2 Head
NEXT_AGENT_ID=S1-ARCH
NEXT_ROLE=S1-ARCH
HANDOFF=tests/integration/evidence/WP-040-a7-HANDOFF.md
```

S7 复算精确线性 Head、路径、Handoff Hash、ContractSet、产品/恢复/安全测试、
隔离 Compose 与清理结果；至少显式报告跨租户成功读取数、旧 Worker 成功写入数、
已完成分支重复执行数和 Redis 恢复后的 Task 数。S7 不批准合并。

## 停止条件

除通用协议外，以下情况立即暂停并上报 S1：

1. 需要契约、ADR、Migration、Compose、Workspace/Lock、新依赖或未授权路径。
2. PostgreSQL、Task、Checkpoint、Redis、Provider Session 或 Studio Thread 的权威
   边界发生冲突。
3. 跨租户读取、旧 Worker 写入或恢复重复副作用大于 0。
4. 无法用现有 Port 完成恢复，或需要改变领域状态/公开 API。
5. Head、Handoff、工作树、路径、证据或门禁不一致。

## 自动唤醒

- 每一步只唤醒唯一 `NEXT_AGENT_ID`，不得回传日常进度给 S1。
- `DEDUP_KEY=CHAIN_ID/STEP_ID/ATTEMPT_ID/NEW_HEAD`。
- 正常路径由 S6 直接唤醒 S2、S2 直接唤醒 S7、S7 唤醒 S1。
- S1 final gate 必须停在用户门禁，不自动合并、不自动批准 g2/g3。
