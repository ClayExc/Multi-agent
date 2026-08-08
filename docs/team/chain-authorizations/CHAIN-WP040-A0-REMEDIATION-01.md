# CHAIN-WP040-A0-REMEDIATION-01

## 授权

```text
CHAIN_ID=CHAIN-WP040-A0-REMEDIATION-01
STATUS=COMPLETED
AUTHORITY=S1-ARCH
AUTHORITY_REF=docs/review/WP-040-A0-S1-REVIEW.md
EXECUTION_MODE=ORDERED
RISK_CLASS=R2
CONTRACT_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
FINAL_GATE=S7-INTEGRATION->S1-ARCH
MAX_LOCAL_REPAIR_ATTEMPTS=1
COMPLETION_REASON=WP040_A1_ACCEPTED_AND_SUPERSEDED_BY_M1_M2_P1_P2
```

本链按
[预授权链路执行约定](../CHAIN_EXECUTION_PROTOCOL.md)
运行。除停止条件外，S6、S2、S5、S7 之间直接交接，不经过 S1 中转。

`CONSUMER_ACCEPTED` 只允许下一步启动，不代表上游工作包已经正式
`ACCEPTED` 或可合并。

## Step 1：S6-DATA

```text
STEP_ID=WP040-REM-01-S6
SESSION_ROLE=S6-DATA
WORK_PACKAGE=WP-021
ATTEMPT_ID=WP-021-a2
BASE_COMMIT=3e0101999061a44a3a5b2fd455ec792e3f73954e
NEW_HEAD=e41f0266e6e588417332043b68a3309b2d40bcf7
WORKTREE=E:\workspace\Multi-agent-s6
STATUS=CONSUMER_READY
NEXT_ROLE=S2-RUNTIME
NEXT_ATTEMPT_ID=WP-010-a2
```

S1 已完成代码和交接复核，确认以下消费侧前置已经落地：

- `TaskQueryPort.get()` 的 Memory/PostgreSQL 实现及完整 Task v1 恢复。
- Ledger 统一使用 `PlannedAction.digest()`。
- tenant/task/thread 绑定的 Checkpoint 查询。
- Lease、`run_generation` 与 `checkpoint_sequence` 的事务内 CAS。
- 单一线性 Migration `0002_checkpoint_sequence_cas`。

独立复现结果：

- Contract Conformance：PASS，20 Schema、43 个语义负例及 Manifest/Audit
  门禁通过。
- 当前 S1 默认解释器缺少 `pytest`、`ruff`、`mypy` 和 `rfc8785`，相关
  命令记为 `ENV_BLOCKED`；S6 Handoff 中的 78 tests、Ruff、Mypy 和实库
  结果留待 S2 消费测试及 S7 最终组合复现，不冒充 S1 已独立复跑。

裁决：

```text
S1_DECISION=ACCEPT_FOR_CHAIN_CONSUMPTION
FORMAL_WORK_PACKAGE_ACCEPTANCE=DEFERRED_TO_FINAL_GATE
S1-WP040-A0-001=CLOSED_FOR_CONSUMPTION
S1-WP040-A0-002=CLOSED_FOR_CONSUMPTION
S1-WP040-A0-003=CLOSED_FOR_CONSUMPTION
S1-WP040-A0-004_PROVIDER_SIDE=CLOSED_FOR_CONSUMPTION
```

Compose 尚未自动挂载 `0002`，保留为 P2 后续项；它不阻塞 S2 的
Worker 适配，但必须在 M0 Compose 验收前关闭。

## Step 2：S2-RUNTIME

```text
STEP_ID=WP040-REM-02-S2
SESSION_ROLE=S2-RUNTIME
WORK_PACKAGE=WP-010
ATTEMPT_ID=WP-010-a2
RISK_CLASS=R2
BASE_COMMIT=34bec05003cb59b3e16f1a16ae166b1f77465c46
UPSTREAM_HEADS=S6-DATA:e41f0266e6e588417332043b68a3309b2d40bcf7
WORKTREE=E:\workspace\Multi-agent-s2
WRITE_SCOPE=apps/worker/**,packages/graph/**,packages/agent-runtime/**,packages/model-gateway/**,packages/context/**,tests/runtime/**
MODE=IMPLEMENTATION
UNLOCK_CONDITION=Step 1 is CONSUMER_READY and S2 read-only verification accepts the exact S6 Head
REVIEWER=S6-DATA
NEXT_ROLE=S5-CORE
NEXT_ATTEMPT_ID=WP-011-a3
NEW_HEAD=c3da3118eac5ee7d57c6b333c2aac3a0f119d799
STATUS=CONSUMER_READY
```

实施范围：

1. 在 S2 Worker 装配层桥接 `GraphState/LeaseToken` 与
   `CheckpointRecord/LeaseFence`。
2. 解析并严格绑定 tenant/task/thread，注入 Clock/TTL。
3. 映射 CAS、Lease 过期、旧 Worker fencing 和存储错误，不泄漏 S6
   原始异常。
4. 覆盖 Checkpoint CAS、错误身份、租约过期、旧 generation、重启恢复和
   幂等重放。
5. `packages/persistence` 不得反向依赖 `packages/graph`。

S2 完成后直接把标准链路交接发给 S5；正常结果不返回 S1。

S2 交付复核：

- `34bec050…c3da3118` 仅包含 S2 授权路径。
- Runtime 43、Core 44、Data 56 个测试通过；Ruff、严格 Mypy 和
  Contract Conformance 通过。
- `make` 在当前 Windows 环境不存在，稳定入口记为 `ENV_BLOCKED`，由
  S5/S7 复算。
- `.idea/**` 已按仓库清理策略从全部 Worktree 移除，不再作为链路证据
  或工程输入。

## Step 3：S5-CORE

```text
STEP_ID=WP040-REM-03-S5
SESSION_ROLE=S5-CORE
WORK_PACKAGE=WP-011
ATTEMPT_ID=WP-011-a3
RISK_CLASS=R2
BASE_COMMIT=0be20f5b56d330f4da494ce4c3d46b183b09ae8b
UPSTREAM_HEADS=S2-RUNTIME:c3da3118eac5ee7d57c6b333c2aac3a0f119d799,S6-DATA:e41f0266e6e588417332043b68a3309b2d40bcf7
WORKTREE=E:\workspace\Multi-agent-s5
WRITE_SCOPE=pyproject.toml,uv.lock,Makefile,WP-011授权的S5独占路径
MODE=IMPLEMENTATION
UNLOCK_CONDITION=S2 consumer handoff passes S5 workspace and port verification
REVIEWER=S7-INTEGRATION
NEXT_ROLE=S7-INTEGRATION
NEXT_ATTEMPT_ID=WP-040-a1
```

实施范围：

1. 在完整九包源码集合上刷新 `uv.lock`。
2. 保持 S5 为 Python Workspace、公共依赖和稳定测试入口的单一写入者。
3. 运行锁文件、wheel、Core/Runtime/Data、类型、契约和 Secret 门禁。
4. 记录仍未实现的全仓命令，不以局部命令冒充通过。

S5 完成后直接交给 S7；正常结果不返回 S1。

## Step 4：S7-INTEGRATION

```text
STEP_ID=WP040-REM-04-S7
SESSION_ROLE=S7-INTEGRATION
WORK_PACKAGE=WP-040
ATTEMPT_ID=WP-040-a1
RISK_CLASS=R2
BASE_COMMIT=55125ae3992311eab03cc888ea9c908486b4b727
UPSTREAM_HEADS=S2-RUNTIME:c3da3118eac5ee7d57c6b333c2aac3a0f119d799,S5-CORE:<Step-3-NEW_HEAD>,S6-DATA:e41f0266e6e588417332043b68a3309b2d40bcf7
WORKTREE=E:\workspace\Multi-agent-s7
WRITE_SCOPE=scripts/integration/**,tests/integration/**,artifacts/integration/**的生成器与结构
MODE=IMPLEMENTATION
UNLOCK_CONDITION=S5 final workspace handoff passes exact Head, digest and scope verification
REVIEWER=S1-ARCH
NEXT_ROLE=S1-ARCH
```

S7 从干净控制基线构造临时组合树，复现单分支与联合门禁，输出组合
Manifest、依赖闭包、迁移 Head、证据哈希和可合并性建议。S7 不修改输入
分支，不批准合并。

## 停止条件

除通用停止条件外，本链遇到以下情况必须回到 S1：

- S2 需要修改 S6 Port，而不是在 Worker 装配层适配。
- S5 发现必须改变公共契约、数据库迁移或共享文件 Owner。
- `0002` 被证明是非线性、破坏性或无法失败关闭。
- tenant/task/thread、CAS、Lease/Fencing 或恢复测试出现 P0/P1 失败。
- 任一步的 ContractSet 摘要不再匹配本授权。
