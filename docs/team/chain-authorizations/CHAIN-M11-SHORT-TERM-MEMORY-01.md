# CHAIN-M11-SHORT-TERM-MEMORY-01

## 授权

```text
CHAIN_ID=CHAIN-M11-SHORT-TERM-MEMORY-01
STATUS=ACTIVE
AUTHORITY=S1-ARCH
EXECUTION_MODE=ORDERED
RISK_CLASS=R2
AUTO_WAKE=enabled
MAX_HOPS=14
USER_GATE=M11_FINAL_S1
USER_GATE_RESULT=pending
FEATURE_IDS=FP-CTX-001,FP-CTX-002,FP-CTX-003,FP-CTX-004,FP-CTX-005,FP-DATA-001,FP-SEC-003,FP-SEC-005,FP-UI-001,FP-EVAL-001,FP-EVAL-002
CONTROL_BASE=e7c2d017fef5480906c48ef09ed5eb0d5d9b8818
ACTIVATION_PARENT=0b36f85c22a7a972403b465982db8afba7bdab86
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
S1_CONTEXT_CAPSULE=.flowpilot-engineering/m11/s1-capsule.json
S1_CONTEXT_CAPSULE_DIGEST=sha256:2cf97f6f59efe1380dab9546fcc0cc440216b80084388a6e40227bb2b3d98c79
S1_CONTEXT_CAPSULE_BLOB_SHA256=sha256:c479011ad96fdd4fb9c8408ed7b6fcdb7f3b2b8aaff111d0833413530a4d08b2
REPOSITORY_MAP_DIGEST=sha256:62ff84605131523a52d773bfeea1c6a949639a8f896854bcdefdbefa4aac25b4
REPOSITORY_MAP_BLOB_SHA256=sha256:f2bef02f9accf98001b97cd0ae7cea4a28057d85b3868db373a2f9a76ec2a77b
CONTEXT_MODE_DEFAULT=DELTA
MAX_ACTIVE_PRINCIPALS=1
MAX_SUBAGENTS_PER_PRINCIPAL=2
MAX_WRITERS_PER_WORKTREE=1
FINAL_GATE=S7-INTEGRATION->S1-ARCH->USER
```

本链实现任务内短期记忆、摘要、Token 预算、Handoff 重建、恢复、清理和可观察投影。
公共 ContractSet 默认不变；M12 长期记忆、M13 用户画像、在线 Provider 效果结论和生产
归档不在范围内。任何公共 Schema、授权语义或破坏性 Migration 变化均按 P1 停链。

## 顺序

```text
S1 WP-121 activation
  -> S3 WP-122 working-memory security surface
  -> S2 WP-123 context memory core
  -> S6 WP-124 memory persistence
  -> S2 WP-125 runtime/checkpoint/handoff integration
  -> S5 WP-126 API/composition/workspace lock
  -> S4 WP-127 memory/context Web
  -> S4 WP-128 acceptance/ablation
  -> S7 WP-129 integration
  -> S1 final -> USER_GATE
```

全链使用线性 Head。S2 的核心和 Runtime 拆成两个 Attempt，中间由 S6 固定持久化 Port；
S4 的 Web 与验收热继续。完成、P0/P1、权限请求和用户门禁之外不发送跨任务消息。

## Step 授权

| Step | Work Package | Role | Mode | Write Scope 摘要 | Next |
|---|---|---|---|---|---|
| M11-01 | WP-122 | S3 | IMPLEMENTATION | `packages/security/**`,`tests/platform/**` | S2 WP-123 |
| M11-02 | WP-123 | S2 | IMPLEMENTATION | `packages/context/**`,`tests/runtime/**` | S6 WP-124 |
| M11-03 | WP-124 | S6 | IMPLEMENTATION | `packages/persistence/**`,`migrations/**`,`infra/**`,`tests/data/**` | S2 WP-125 |
| M11-04 | WP-125 | S2 | IMPLEMENTATION | `apps/worker/**`,`packages/graph/**`,`packages/context/**`,`tests/runtime/**` | S5 WP-126 |
| M11-05 | WP-126 | S5 | IMPLEMENTATION | `apps/api/**`,`packages/application/**`,`tests/core/**`,`pyproject.toml`,`uv.lock`,`Makefile` | S4 WP-127 |
| M11-06 | WP-127 | S4 | IMPLEMENTATION | `web/**`,`packages/observability/**`,`tests/experience/**`,`tests/acceptance/m11/**` | S4 WP-128 |
| M11-07 | WP-128 | S4 | HOT_CONTINUE | `packages/evaluation/**`,`evals/**`,`tests/acceptance/**`,`artifacts/acceptance/**`,`scripts/acceptance/run_acceptance.py` | S7 WP-129 |
| M11-08 | WP-129 | S7 | FINAL_GATE | `scripts/integration/**`,`tests/integration/**`,`artifacts/integration/**` | S1 |

共享 Workspace/Lock 只在 WP-126 由 S5 单写；Migration/Compose 只在 WP-124 由 S6 单写；
验收入口只在 WP-128 由 S4 单写。

## 停止条件

P0/P1、公共契约变化、路径越权、Memory 成为业务/授权事实源、跨租户成功非零、凭据或隐藏
推理写入 Turn/Snapshot/Manifest、claimed/inferred 越级为 verified、历史 Snapshot 覆盖最新
Checkpoint、Manifest 失败后仍调用模型、硬预算静默截断、删除后内容残留、固定分母缩减或
稳定门禁失败时立即停链。
