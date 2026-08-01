# CHAIN-P2-DURABLE-RUNTIME-01 Agent 注册表

## 调度结论

本链只注册三个执行 Agent；固定 S1～S7 仍作为路径 Owner 与风险档案，不代表
全部参与。调度为严格 `ORDERED`，同一时刻最多一个写入者，正常完成事件直接
唤醒唯一下一跳。

```text
CHAIN_ID=CHAIN-P2-DURABLE-RUNTIME-01
FLOW_LITE_GOAL_ID=g1
REGISTRY_MODE=minimum-capability-set
EXECUTION_MODE=ORDERED
MAX_ACTIVE_WRITERS=1
COMMUNICATION=event-driven
SELECTED=data-recovery,durable-runtime,recovery-verifier
NOT_SELECTED=S3-PLATFORM,S4-QUALITY,S5-CORE
```

## 注册记录

### data-recovery

```text
AGENT_ID=data-recovery
SESSION_ROLE=S6-DATA
CAPABILITIES=postgres-checkpoint,lease-fencing,outbox,redis-rebuild,rls,recovery-test
WRITE_SCOPE=packages/persistence/**,tests/data/**
RISK_CEILING=R2
INPUT_CONTRACTS=ContractSet-v1,Application-Persistence-Ports
OUTPUT_CONTRACTS=typed-checkpoint-lease-recovery-boundary,WP-021-a3-HANDOFF
EVIDENCE_CONTRACT=tests/data/evidence/WP-021-a3-HANDOFF.md
AVAILABILITY=selected
CONCURRENCY=single-writer
EXIT_CONDITION=数据恢复边界与负向证据通过并产生精确 Head
```

### durable-runtime

```text
AGENT_ID=durable-runtime
SESSION_ROLE=S2-RUNTIME
CAPABILITIES=langgraph-checkpoint,worker-recovery,lease-consumer,redis-loss,graph-replay
WRITE_SCOPE=apps/worker/**,packages/graph/**,tests/runtime/**
RISK_CEILING=R2
INPUT_CONTRACTS=data-recovery exact Head and typed persistence boundary
OUTPUT_CONTRACTS=durable-worker-adapter,WP-010-a4-HANDOFF
EVIDENCE_CONTRACT=tests/runtime/evidence/WP-010-a4-HANDOFF.md
AVAILABILITY=dependency-wait
CONCURRENCY=single-writer
EXIT_CONDITION=进程重启和 Redis 丢失恢复通过且已完成分支不重放
```

### recovery-verifier

```text
AGENT_ID=recovery-verifier
SESSION_ROLE=S7-INTEGRATION
CAPABILITIES=linear-candidate-verification,compose,rls,recovery,evidence-reproduction
WRITE_SCOPE=scripts/integration/**,tests/integration/**
RISK_CEILING=R2
INPUT_CONTRACTS=durable-runtime exact Head and both upstream Handoffs
OUTPUT_CONTRACTS=WP-040-a7-HANDOFF,WP-040-a7-PROOF
EVIDENCE_CONTRACT=tests/integration/evidence/WP-040-a7-HANDOFF.md
AVAILABILITY=dependency-wait
CONCURRENCY=single-writer
EXIT_CONDITION=RELEASE 候选复现完成并唤醒 S1 final gate
```

## 未选择原因

- `S3-PLATFORM`：本链不改变 MCP、Policy、审批或工具安全边界。
- `S4-QUALITY`：本链使用确定性恢复和安全断言，不改变数据集、Judge、Web 或
  Acceptance 聚合器；独立复核由 S7 完成。
- `S5-CORE`：现有 Domain/Application Port 足够，本链不改变 API、领域状态机、
  Workspace 或锁文件。

若实施事实证明上述判断不成立，链路暂停并由 S1 重新注册能力，不把未选会话
临时塞入现有 Step。
