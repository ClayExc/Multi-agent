# CHAIN-M9-GOVERNANCE-01

## 授权

```text
CHAIN_ID=CHAIN-M9-GOVERNANCE-01
STATUS=ACTIVE
AUTHORITY=S1-ARCH
EXECUTION_MODE=ORDERED
RISK_CLASS=R3
AUTO_WAKE=enabled
MAX_HOPS=12
USER_GATE=M9_FINAL_S1
FEATURE_IDS=FP-SEC-004,FP-SEC-005,FP-SEC-006,FP-MCP-006,FP-OBS-002,FP-OBS-003
CONTROL_BASE=b7ab61248793456db4e011b3e03a50421b98f963
ACTIVATION_HEAD=<WP-100 activation commit>
CONTEXT_MODE_DEFAULT=DELTA
MAX_ACTIVE_PRINCIPALS=1
MAX_SUBAGENTS_PER_PRINCIPAL=2
MAX_WRITERS_PER_WORKTREE=1
FINAL_GATE=S7-INTEGRATION->S1-ARCH->USER
```

本链只实现本地治理产品能力。生产 OPA、Vault/KMS、SIEM、企业 Connector、HA 和
M10～M20 不在授权范围内。公共 ContractSet 默认不变；Owner 发现必须修改公共契约时
按 P1 停链并提交 RFC。

## 顺序

```text
S1 WP-100 activation
  -> S3 WP-101 versioned policy
  -> S3 WP-102 capability + DLP gateway
  -> S2 WP-103 runtime DLP
  -> S5 WP-104 governance API
  -> S6 WP-105 audit persistence
  -> S6 WP-106 local OPA/Secret infra
  -> S4 WP-107 governance Web
  -> S4 WP-108 security acceptance
  -> S7 WP-109 integration
  -> S1 final -> USER_GATE
```

全链严格有序并保持线性 Head。S3、S6、S4 在各自相邻工作包间热继续，不重新注册或
全量读取。每个主 Agent 可以使用最多两个回答不同问题的只读子 Agent；主 Agent 是唯一
写入者并负责提交与 Handoff。

## Step 授权

| Step | Work Package | Role | Mode | Write Scope 摘要 | Next |
|---|---|---|---|---|---|
| M9-01 | WP-101 | S3 | IMPLEMENTATION | `packages/policy/**`,`tests/platform/**` | S3 WP-102 |
| M9-02 | WP-102 | S3 | HOT_CONTINUE | `packages/security/**`,`apps/mcp-gateway/**`,`packages/tool-contracts/**`,`tests/platform/**` | S2 |
| M9-03 | WP-103 | S2 | IMPLEMENTATION | `packages/context/**`,`packages/agent-runtime/**`,`packages/model-gateway/**`,`apps/worker/**`,`tests/runtime/**` | S5 |
| M9-04 | WP-104 | S5 | IMPLEMENTATION | `packages/application/**`,`apps/api/**`,`tests/core/**`,`pyproject.toml`,`uv.lock`,`Makefile` | S6 |
| M9-05 | WP-105 | S6 | IMPLEMENTATION | `packages/persistence/**`,`migrations/**`,`tests/data/**` | S6 WP-106 |
| M9-06 | WP-106 | S6 | HOT_CONTINUE | `infra/**`,`.env.example`,`tests/data/**` | S4 |
| M9-07 | WP-107 | S4 | IMPLEMENTATION | `packages/observability/**`,`web/**`,`tests/experience/**`,`tests/acceptance/m9/**` | S4 WP-108 |
| M9-08 | WP-108 | S4 | HOT_CONTINUE | `packages/evaluation/**`,`evals/**`,`tests/acceptance/**`,`artifacts/acceptance/**` | S7 |
| M9-09 | WP-109 | S7 | FINAL_GATE | `scripts/integration/**`,`tests/integration/**`,`artifacts/integration/**` | S1 |

各工作包的 Handoff/Proof 路径已在对应文档显式授权，不受上表摘要省略影响。

## 停止条件

P0/P1、公共契约变化、路径越权、策略默认允许、未知 Obligation、Capability 重放、凭据
或隐藏思维链泄漏、拒绝后产生账本/上游调用、Audit/Security 可采样或可改写、Migration
失败、固定分母缩减、工程控制面漏选安全测试时立即停链。普通实现细节由当前 Owner
解决，不回流 S1。
