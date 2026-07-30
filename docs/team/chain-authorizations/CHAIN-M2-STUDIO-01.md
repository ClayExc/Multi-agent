# CHAIN-M2-STUDIO-01

## 授权

```text
CHAIN_ID=CHAIN-M2-STUDIO-01
STATUS=ACTIVE
AUTHORITY=S1-ARCH
AUTHORITY_REF=docs/team/chain-authorizations/CHAIN-M2-STUDIO-01.md
EXECUTION_MODE=ORDERED
RISK_CLASS=R2
AUTO_WAKE=enabled
MAX_HOPS=5
USER_GATE=FINAL_S1
CONTRACT_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
FINAL_GATE=S7-INTEGRATION->S1-ARCH
MAX_LOCAL_REPAIR_ATTEMPTS=1
```

本链交付可由自动化复现的 LangGraph Studio 非黑箱开发入口。Studio
只观察和调试安全投影，不成为业务 Task、审批、租户、Checkpoint、Lease
或工具执行的事实源。

## 顺序

```text
S5-CORE
  -> S2-RUNTIME
  -> S4-QUALITY
  -> S7-INTEGRATION
  -> S1-ARCH(FINAL_GATE)
```

这是严格有序链。S5 是共享依赖单写者；S2 是图和 Studio 入口单写者；
S4 在完整入口上做独立黑盒；S7 只在精确线性候选上做组合复现。

## Step 1：S5-CORE 开发依赖闭包

```text
STEP_ID=M2-STUDIO-01-S5
SESSION_ROLE=S5-CORE
WORK_PACKAGE=WP-011
ATTEMPT_ID=WP-011-a5
BASE_COMMIT=WAKE_MESSAGE.ACTIVATION_COMMIT
UPSTREAM_HEADS=none
WORKTREE=E:\workspace\Multi-agent-s5
WRITE_SCOPE=pyproject.toml,uv.lock,Makefile,tests/core/evidence/WP-011-a5-HANDOFF.md
MODE=IMPLEMENTATION
UNLOCK_CONDITION=S5 branch and Worktree ff-only reach ACTIVATION_COMMIT; ContractSet digest matches
REVIEWER=S2-RUNTIME
NEXT_ROLE=S2-RUNTIME
NEXT_ATTEMPT_ID=WP-012-a1
```

S5 必须：

1. 把官方本地 Agent Server 所需的 `langgraph-cli[inmem]` 放入开发依赖，
   锁定兼容版本，并记录用途、许可证、替代方案和攻击面。
2. 提供稳定的本地 Studio 启动/Smoke 命令入口；默认关闭远程 Trace，
   不读取生产环境文件，不自动创建公网 Tunnel。
3. 复跑 Workspace/Lock、已有产品测试、Contract、Ruff、严格 Mypy、
   Wheel 与 Secret Scan。S5 不创建 `langgraph.json` 或 Studio 图代码。

## Step 2：S2-RUNTIME Studio 实现

```text
STEP_ID=M2-STUDIO-02-S2
SESSION_ROLE=S2-RUNTIME
WORK_PACKAGE=WP-012
ATTEMPT_ID=WP-012-a1
BASE_COMMIT=<Step-1-NEW_HEAD after ff-only>
UPSTREAM_HEADS=S5-CORE:<Step-1-NEW_HEAD>
WORKTREE=E:\workspace\Multi-agent-s2
WRITE_SCOPE=apps/worker/**,packages/graph/**,packages/agent-runtime/**,packages/context/**,tests/runtime/**,langgraph.json
MODE=IMPLEMENTATION
UNLOCK_CONDITION=S5 dependency Handoff ACCEPT and S2 ff-only reaches exact S5 Head
REVIEWER=S4-QUALITY
NEXT_ROLE=S4-QUALITY
NEXT_ATTEMPT_ID=WP-030-a3
```

S2 必须：

1. `langgraph.json` 暴露稳定图 ID `flowpilot_it_service`，Studio 和 Worker
   使用同一个 graph factory；故意分叉入口的测试必须失败。
2. 实现默认拒绝的 `debug_projection`，仅展示节点、路由、预算、重试、
   Interrupt、Handoff、checkpoint sequence、`run_generation` 和脱敏引用。
3. `studio-safe` 默认使用合成租户、Fake Runtime/Tool 和关闭的外部网络；
   `studio-integration` 必须显式选择，仍不得绕过 Application/MCP Gateway。
4. 自动化覆盖图拓扑、暂停/恢复、节点重进、旧 Lease/Fencing、预算终止、
   未知状态字段隐藏、Secret/PII 扫描和生产 Profile 状态编辑拒绝。

## Step 3：S4-QUALITY 独立黑盒

```text
STEP_ID=M2-STUDIO-03-S4
SESSION_ROLE=S4-QUALITY
WORK_PACKAGE=WP-030
ATTEMPT_ID=WP-030-a3
BASE_COMMIT=<Step-2-NEW_HEAD after ff-only>
UPSTREAM_HEADS=S2-RUNTIME:<Step-2-NEW_HEAD>
WORKTREE=E:\workspace\Multi-agent-s4
WRITE_SCOPE=tests/acceptance/**,artifacts/acceptance/**的生成器与结构
MODE=IMPLEMENTATION
UNLOCK_CONDITION=S2 Studio Handoff ACCEPT and S4 ff-only reaches exact S2 Head
REVIEWER=S7-INTEGRATION
NEXT_ROLE=S7-INTEGRATION
NEXT_ATTEMPT_ID=WP-040-a5
```

S4 必须从本地 Agent Server API 黑盒验证图 ID、拓扑、运行路径、
Interrupt/Resume、checkpoint 对齐、安全投影和失败关闭。测试不得依赖截图、
隐藏思维链、生产凭据或人工点击；截图只可作为非权威学习材料。

## Step 4：S7-INTEGRATION

```text
STEP_ID=M2-STUDIO-04-S7
SESSION_ROLE=S7-INTEGRATION
WORK_PACKAGE=WP-040
ATTEMPT_ID=WP-040-a5
BASE_COMMIT=<Step-3-NEW_HEAD after ff-only>
UPSTREAM_HEADS=S4-QUALITY:<Step-3-NEW_HEAD>
WORKTREE=E:\workspace\Multi-agent-s7
WRITE_SCOPE=scripts/integration/**,tests/integration/**,artifacts/integration/**的生成器与结构
MODE=IMPLEMENTATION
UNLOCK_CONDITION=S4 consumer Handoff ACCEPT and S7 ff-only reaches exact S4 Head
REVIEWER=S1-ARCH
NEXT_ROLE=S1-ARCH
```

S7 复算 Head、范围、Handoff Hash、ContractSet、Workspace/Lock、联合测试、
Secret Scan 和拓扑快照；在全新环境启动无浏览器本地 Agent Server，验证
API/图加载后关闭进程并证明无残留资源。S7 不批准合并。

## 停止条件

除通用协议外，以下情况立即暂停并上报 S1：

1. 需要修改公共 ContractSet、Schema、ADR 或数据库事实源语义。
2. Studio/Agent Server 要求生产凭据、真实 PII、外部发布或自动公网 Tunnel。
3. Studio 与 Worker 不能共享同一 graph factory，或 Thread 被当作业务 Task。
4. 调试投影泄漏 Secret、原始敏感 Context、完整工具 Payload 或隐藏思维链。
5. 生产 Profile 状态编辑能够改变 Task、Checkpoint、Approval 或 Ledger。
6. Head、Handoff、工作树、路径、锁文件或门禁不一致。
7. `--ff-only` 无法形成单一线性候选，或局部返修次数耗尽。

## 自动唤醒

- 每一步只唤醒上面列出的唯一 `NEXT_ROLE`。
- `DEDUP_KEY=CHAIN_ID/STEP_ID/ATTEMPT_ID/INPUT_HEAD`。
- 正常路径不返回 S1；S7 最终唤醒 S1。
- S1 final gate 必须停在 `USER_GATE_REQUIRED=yes`，不得自动合并或启动新链。
