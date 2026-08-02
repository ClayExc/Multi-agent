# Agent Registration — Judge calibration trust boundary

```text
CHAIN_ID=CHAIN-M6-ACCEPTANCE-REMEDIATION-01
STEP_ID=M6-REM-05-JUDGE-PIPELINE
AGENT_ID=judge-calibration-hardener
SESSION_ROLE=S4-QUALITY
CAPABILITIES=llm-as-judge,blind-review,evidence-integrity,evaluation-testing
WRITE_SCOPE=evals/runners/**,packages/evaluation/**,tests/acceptance/evaluation/**
RISK_CEILING=R2
INPUT_CONTRACTS=WP-031 CaseExecutionResult and Acceptance evidence bundle
OUTPUT_CONTRACTS=trusted blind-set input, human-reference boundary, judge-prediction calibration
EVIDENCE_CONTRACT=tests/acceptance/evidence/WP-035-a1-HANDOFF.md
CONCURRENCY=single-writer
EXIT_CONDITION=WP-035 completion definition satisfied or P0/P1 reported
```

S2/S3/S5/S6/S7 未被选择；本 Step 只修改 S4 评测边界，不向其他角色发送背景或等待通知。
