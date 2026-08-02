# Agent Registrations — M6 strict type hardening

```text
CHAIN_ID=CHAIN-M6-ACCEPTANCE-REMEDIATION-01
STEP_ID=M6-REM-02-TYPES
EXECUTION_MODE=PARALLEL
BASE_COMMIT=71afa72a4975a506796e1e02d8d475d142616652
MERGE_GATE=S1-ARCH
```

## runtime-type-hardener

```text
AGENT_ID=runtime-type-hardener
SESSION_ROLE=S2-RUNTIME
CAPABILITIES=python-strict-typing,langgraph-runtime,model-gateway
WRITE_SCOPE=packages/graph/**,packages/model-gateway/**,tests/runtime/**
RISK_CEILING=R1
INPUT_CONTRACTS=current product ports; no contract changes
OUTPUT_CONTRACTS=typed runtime implementation with unchanged behavior
EVIDENCE_CONTRACT=tests/runtime/evidence/WP-032-a1-S2-HANDOFF.md
EXIT_CONDITION=S2 slice Mypy/tests/Ruff pass or P0/P1 reported
```

## experience-type-hardener

```text
AGENT_ID=experience-type-hardener
SESSION_ROLE=S4-QUALITY
CAPABILITIES=python-strict-typing,web-shell,boundary-validation
WRITE_SCOPE=web/src/**,tests/experience/**
RISK_CEILING=R1
INPUT_CONTRACTS=current API payload models; no contract changes
OUTPUT_CONTRACTS=typed Web Shell adapters with unchanged behavior
EVIDENCE_CONTRACT=tests/experience/evidence/WP-032-a1-S4-HANDOFF.md
EXIT_CONDITION=S4 slice Mypy/tests/Ruff pass or P0/P1 reported
```

## core-type-hardener

```text
AGENT_ID=core-type-hardener
SESSION_ROLE=S5-CORE
CAPABILITIES=python-strict-typing,application-services,fastapi-boundaries
WRITE_SCOPE=packages/application/**,apps/api/**,tests/core/**
RISK_CEILING=R1
INPUT_CONTRACTS=current application and API ports; no contract changes
OUTPUT_CONTRACTS=typed Core/API implementation with unchanged behavior
EVIDENCE_CONTRACT=tests/core/evidence/WP-032-a1-S5-HANDOFF.md
EXIT_CONDITION=S5 slice Mypy/tests/Ruff pass or P0/P1 reported
```

未选择 S3、S6、S7：当前 25 个 Workspace 类型错误不在其路径内；它们不接收背景或等待通知。
