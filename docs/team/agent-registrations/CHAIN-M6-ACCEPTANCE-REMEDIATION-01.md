# Agent Registration — CHAIN-M6-ACCEPTANCE-REMEDIATION-01

```text
CHAIN_ID=CHAIN-M6-ACCEPTANCE-REMEDIATION-01
AGENT_ID=acceptance-remediator
SESSION_ROLE=S4-QUALITY
CAPABILITIES=acceptance-orchestration,case-execution,evidence-integrity,negative-testing
WRITE_SCOPE=scripts/acceptance/**,packages/evaluation/**,tests/acceptance/evaluation/**,artifacts/acceptance/**
RISK_CEILING=R2
INPUT_CONTRACTS=contracts/registries/evaluation-registry.v1.json,contracts/registries/evaluation-dataset-manifest.v1.json,contracts/registries/evaluation-fixture-manifest.v1.json
OUTPUT_CONTRACTS=CaseExecutionResult,AcceptanceManifest,AcceptanceReport
EVIDENCE_CONTRACT=tests/acceptance/evidence/WP-031-a1-HANDOFF.md
AVAILABILITY=available
CONCURRENCY=single-writer
EXIT_CONDITION=WP-031 completion definition satisfied or P0/P1 blocker reported
```

未选择 S2/S3/S5/S6/S7：本 Step 不修改其路径，也不需要其等待或接收背景。
S1 只在完成、P0/P1 或权限请求时接收消息。
