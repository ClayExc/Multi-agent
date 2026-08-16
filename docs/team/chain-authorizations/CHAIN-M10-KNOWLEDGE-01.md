# CHAIN-M10-KNOWLEDGE-01

## 授权

```text
CHAIN_ID=CHAIN-M10-KNOWLEDGE-01
STATUS=AWAITING_ACTIVATION
AUTHORITY=S1-ARCH
EXECUTION_MODE=ORDERED
RISK_CLASS=R2
AUTO_WAKE=enabled
MAX_HOPS=14
USER_GATE=M10_FINAL_S1
USER_GATE_RESULT=pending
FEATURE_IDS=FP-FLOW-003,FP-MCP-001,FP-MCP-002,FP-SEC-002,FP-SEC-003,FP-SEC-005,FP-SEC-006,FP-DATA-001,FP-UI-001,FP-EVAL-001,FP-EVAL-002
CONTROL_BASE=acabbcd7d424019c8707d02a55e38a8dbd727e38
ACTIVATION_HEAD=pending
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
CONTEXT_MODE_DEFAULT=DELTA
MAX_ACTIVE_PRINCIPALS=1
MAX_SUBAGENTS_PER_PRINCIPAL=2
MAX_WRITERS_PER_WORKTREE=1
FINAL_GATE=S7-INTEGRATION->S1-ARCH->USER
```

本链实现本地文本知识平台。公共 ContractSet 和 `knowledge.search.v1` Schema Pin 默认不变；
企业 Connector、OCR/多模态、M11 记忆和生产向量集群不在授权范围内。需要改变 Tool Schema、
公共契约、授权语义或执行破坏性 Migration 时按 P1 停链。

## 顺序

```text
S1 WP-110 activation
  -> S5 WP-111 knowledge core ports
  -> S6 WP-112 document persistence
  -> S6 WP-113 pgvector/index lifecycle
  -> S4 WP-114 retrieval engine
  -> S3 WP-115 secure Knowledge MCP
  -> S5 WP-116 API/composition/workspace lock
  -> S2 WP-117 runtime citations
  -> S4 WP-118 knowledge Web
  -> S4 WP-119 acceptance
  -> S7 WP-120 integration
  -> S1 final -> USER_GATE
```

全链使用线性 Head，不建立并行 Join。S6 与 S4 的相邻工作包热继续；其余角色只在自己的
输入 Head 到达后激活。完成、P0/P1、权限请求和用户门禁之外不发送跨任务消息。

## Step 授权

| Step | Work Package | Role | Mode | Write Scope 摘要 | Next |
|---|---|---|---|---|---|
| M10-01 | WP-111 | S5 | IMPLEMENTATION | `packages/domain/**`,`packages/application/**`,`apps/api/**`,`tests/core/**` | S6 WP-112 |
| M10-02 | WP-112 | S6 | IMPLEMENTATION | `packages/persistence/**`,`migrations/**`,`tests/data/**` | S6 WP-113 |
| M10-03 | WP-113 | S6 | HOT_CONTINUE | `packages/persistence/**`,`migrations/**`,`infra/**`,`tests/data/**` | S4 WP-114 |
| M10-04 | WP-114 | S4 | IMPLEMENTATION | `packages/retrieval/**`,`tests/acceptance/m10/**` | S3 WP-115 |
| M10-05 | WP-115 | S3 | IMPLEMENTATION | `mcp-servers/knowledge/**`,`apps/mcp-gateway/**`,`packages/security/**`,`tests/platform/**` | S5 WP-116 |
| M10-06 | WP-116 | S5 | IMPLEMENTATION | `apps/api/**`,`packages/application/**`,`tests/core/**`,`pyproject.toml`,`uv.lock`,`Makefile` | S2 WP-117 |
| M10-07 | WP-117 | S2 | IMPLEMENTATION | `apps/worker/**`,`packages/graph/**`,`packages/agent-runtime/**`,`packages/context/**`,`tests/runtime/**` | S4 WP-118 |
| M10-08 | WP-118 | S4 | IMPLEMENTATION | `web/**`,`tests/experience/**`,`tests/acceptance/m10/**` | S4 WP-119 |
| M10-09 | WP-119 | S4 | HOT_CONTINUE | `packages/evaluation/**`,`evals/**`,`tests/acceptance/**`,`artifacts/acceptance/**`,`scripts/acceptance/run_acceptance.py` | S7 WP-120 |
| M10-10 | WP-120 | S7 | FINAL_GATE | `scripts/integration/**`,`tests/integration/**`,`artifacts/integration/**` | S1 |

各工作包中的证据路径属于对应 Owner 的既有测试所有权。共享 Workspace 只在 WP-116 由
S5 单写；Compose 与 pgvector 环境只在 WP-113 由 S6 单写。

## 停止条件

P0/P1、公共契约变化、路径越权、跨租户候选非零、未授权元数据泄漏、旧引用静默重定向、
恶意文档进入可检索索引、原始正文进入 Checkpoint/Trace、Migration 非线性、索引状态覆盖
文档事实、固定分母缩减或门禁失败时立即停链。
