# CHAIN-M11-SHORT-TERM-MEMORY-01 Agent 注册表

```text
REGISTRY_STATUS=ACTIVE
REGISTRY_MODE=minimum-capability-set
EXECUTION_MODE=ORDERED
MAX_ACTIVE_PRINCIPALS=1
MAX_ACTIVE_WRITERS=1
MAX_SUBAGENTS_PER_PRINCIPAL=2
COMMUNICATION=event-driven
SELECTED=memory-security-builder,memory-context-builder,memory-data-builder,memory-runtime-builder,memory-core-composer,memory-quality-builder,memory-integration-verifier
CURRENTLY_ACTIVE=memory-context-builder
READY_NOT_DISPATCHED=none
NOT_YET_ACTIVATED=memory-data-builder,memory-runtime-builder,memory-core-composer,memory-quality-builder,memory-integration-verifier
UNSELECTED=none
```

| Agent ID | Role | 主写目标 | 当前状态 | 退出条件 |
|---|---|---|---|---|
| memory-security-builder | S3-PLATFORM | Working Memory 内容安全表面与凭据/DLP 回归 | COMPLETED_WP122 | WP-122 clean Handoff |
| memory-context-builder | S2-RUNTIME | Snapshot、摘要、预算与 Memory Port | ACTIVE_WP123 | WP-123 clean Handoff |
| memory-data-builder | S6-DATA | Turn/Snapshot/Manifest、RLS、CAS、TTL | DEPENDENCY_WAIT | WP-124 clean Handoff |
| memory-runtime-builder | S2-RUNTIME | Graph/Worker/Checkpoint/Handoff 集成 | DEPENDENCY_WAIT | WP-125 clean Handoff |
| memory-core-composer | S5-CORE | API、清理用例、组合与 Workspace | DEPENDENCY_WAIT | WP-126 clean Handoff |
| memory-quality-builder | S4-QUALITY | Web、50 轮、消融、固定分母证据 | DEPENDENCY_WAIT | WP-127/128 clean Handoff |
| memory-integration-verifier | S7-INTEGRATION | 本地组合、保护树和最终复算 | DEPENDENCY_WAIT | WP-129 PASS Handoff |

各领域主 Agent 可以在有效工作包内调用最多两个临时子 Agent。子 Agent 使用最小 Capsule，
不执行 Git 写操作；同一 Worktree 仍只有领域主 Agent 一个写入者。
