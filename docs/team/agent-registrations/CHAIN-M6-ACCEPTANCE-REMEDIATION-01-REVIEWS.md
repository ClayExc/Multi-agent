# Agent Registrations — rc2 `6e85ce62` DELTA reviews

```text
CHAIN_ID=CHAIN-M6-ACCEPTANCE-REMEDIATION-01
STEP_ID=M6-REM-04-REVIEWS
EXECUTION_MODE=READ_ONLY_PARALLEL
CONTRACT_CONTENT_DIGEST=sha256:6e85ce625879c108431ed79ab934127ddd5705d3ee3ddd4e1df347b5f1e2ac42
WRITE_SCOPE=none
MERGE_GATE=S1-ARCH
```

| Agent ID | SESSION_ROLE | Capability | Exit condition |
|---|---|---|---|
| `runtime-contract-reviewer` | S2-RUNTIME | Runtime/Context/Graph contract implementability | exact machine verdict returned |
| `platform-contract-reviewer` | S3-PLATFORM | Tool/Policy/Approval/Audit security binding | exact machine verdict returned |
| `quality-contract-reviewer` | S4-QUALITY | Conformance negatives/evidence integrity | exact machine verdict returned |
| `core-contract-reviewer` | S5-CORE | Domain/Application/API contract implementability | exact machine verdict returned |
| `data-contract-reviewer` | S6-DATA | Persistence/Migration/data contract implementability | exact machine verdict returned |

所有 Agent 只读共享同一候选；不接收命令日志或历史全量上下文。输出仅通过任务消息
返回 S1，S1 是新 Attestation 文件的唯一写入者。
