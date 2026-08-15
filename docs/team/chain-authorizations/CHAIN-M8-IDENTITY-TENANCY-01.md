# CHAIN-M8-IDENTITY-TENANCY-01

## 授权

```text
CHAIN_ID=CHAIN-M8-IDENTITY-TENANCY-01
STATUS=COMPLETE
AUTHORITY=S1-ARCH
EXECUTION_MODE=PARALLEL_JOIN_ORDERED
RISK_CLASS=R2
AUTO_WAKE=enabled
MAX_HOPS=14
USER_GATE=M8_FINAL_S1
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
CONTEXT_MODE_DEFAULT=DELTA
SUBAGENT_PROTOCOL=flowpilot.principal-subagent.v1
MAX_SUBAGENTS_PER_PRINCIPAL=2
MAX_WRITERS_PER_WORKTREE=1
MAX_LOCAL_REPAIR_ATTEMPTS=1
FINAL_GATE=S7-INTEGRATION->S1-ARCH->USER
```

用户已批准启动 M8。范围只包含本地身份、租户与恢复重验；不启动 M9，不连接真实企业
IdP，不执行付费 Provider 调用，不改变公共 ContractSet。整体继续保持
`RELEASED=false`、`FROZEN=false`。

## 完成记录

M8 已按 WP-080～WP-088 完成。S7 最终候选为
`75aef77253c55e80e023b70e6f773e8947841ffa`，真实 Keycloak/JWKS、生产 BFF、
PostgreSQL/Redis 恢复、跨租户拒绝和资源清理均通过。固定分母仍为 30 条通过、
126 条失败，M9 未启动。S1 final 记录见
[`WP-088-A1-S1-FINAL-REVIEW.md`](../../review/WP-088-A1-S1-FINAL-REVIEW.md)。

## 执行图

```text
S1 WP-080 DONE
  → PARALLEL { S6 WP-081 Keycloak || S3 WP-082 identity boundary }
  → S1 JOIN-1
  → PARALLEL { S5 WP-083 API/BFF || S6 WP-084 RLS binding }
  → S1 JOIN-2
  → PARALLEL { S2 WP-085 runtime || S4 WP-086 Web }
  → S1 JOIN-3
  → S4 WP-087 blackbox acceptance
  → S7 WP-088 integration
  → S1 final → USER_GATE
```

只有同一 `{}` 内的步骤可并行。Join 由 S1 在隔离分支消费两个 clean Head 并生成下一
精确 Base；普通进度不发给未激活角色。P0/P1、公共契约变化、共享路径冲突和第二次
等价返修立即停链。

## Step 1A：Keycloak

```text
STEP_ID=M8-01A-S6-KEYCLOAK
AGENT_ID=identity-data-builder
SESSION_ROLE=S6-DATA
WORK_PACKAGE=WP-081
ATTEMPT_ID=WP-081-a1
WORKTREE=E:\workspace\Multi-agent-m8-s6
BRANCH=codex/s6/m8-identity-data
WRITE_SCOPE=infra/**,.env.example,tests/data/**
MODE=IMPLEMENTATION
NEXT_ROLE=S1-ARCH
HANDOFF=tests/data/evidence/WP-081-a1-HANDOFF.md
```

## Step 1B：可信身份边界

```text
STEP_ID=M8-01B-S3-IDENTITY
AGENT_ID=identity-security-builder
SESSION_ROLE=S3-PLATFORM
WORK_PACKAGE=WP-082
ATTEMPT_ID=WP-082-a1
WORKTREE=E:\workspace\Multi-agent-m8-s3
BRANCH=codex/s3/m8-identity-security
WRITE_SCOPE=packages/security/**,apps/mcp-gateway/**,tests/platform/**
MODE=IMPLEMENTATION
NEXT_ROLE=S1-ARCH
HANDOFF=tests/platform/evidence/WP-082-a1-HANDOFF.md
```

## Join 1

```text
STEP_ID=M8-JOIN-01-S1
UNLOCK_CONDITION=WP-081 and WP-082 clean PASS Handoffs; path intersection 0; digest match
OUTPUT=S1 exact join Head
NEXT_PARALLEL=WP-083,WP-084
```

## Step 2A：API/BFF

```text
STEP_ID=M8-02A-S5-API
AGENT_ID=identity-api-builder
SESSION_ROLE=S5-CORE
WORK_PACKAGE=WP-083
ATTEMPT_ID=WP-083-a1
WORKTREE=E:\workspace\Multi-agent-m8-s5
BRANCH=codex/s5/m8-api-identity
WRITE_SCOPE=apps/api/**,packages/application/**,tests/core/**,pyproject.toml,uv.lock,Makefile
MODE=IMPLEMENTATION
NEXT_ROLE=S1-ARCH
HANDOFF=tests/core/evidence/WP-083-a1-HANDOFF.md
```

## Step 2B：RLS 绑定

```text
STEP_ID=M8-02B-S6-RLS
AGENT_ID=identity-data-builder
SESSION_ROLE=S6-DATA
WORK_PACKAGE=WP-084
ATTEMPT_ID=WP-084-a1
WORKTREE=E:\workspace\Multi-agent-m8-s6
BRANCH=codex/s6/m8-identity-data
WRITE_SCOPE=packages/persistence/**,migrations/**,infra/**,.env.example,tests/data/**
MODE=IMPLEMENTATION
NEXT_ROLE=S1-ARCH
HANDOFF=tests/data/evidence/WP-084-a1-HANDOFF.md
```

## Join 2

```text
STEP_ID=M8-JOIN-02-S1
UNLOCK_CONDITION=WP-083 and WP-084 clean PASS Handoffs; path intersection 0; digest match
OUTPUT=S1 exact join Head
NEXT_PARALLEL=WP-085,WP-086
```

## Step 3A：Runtime

```text
STEP_ID=M8-03A-S2-RUNTIME
AGENT_ID=identity-runtime-builder
SESSION_ROLE=S2-RUNTIME
WORK_PACKAGE=WP-085
ATTEMPT_ID=WP-085-a1
WORKTREE=E:\workspace\Multi-agent-m8-s2
BRANCH=codex/s2/m8-runtime-identity
WRITE_SCOPE=apps/worker/**,packages/graph/**,packages/context/**,packages/agent-runtime/**,packages/model-gateway/**,tests/runtime/**
MODE=IMPLEMENTATION
NEXT_ROLE=S1-ARCH
HANDOFF=tests/runtime/evidence/WP-085-a1-HANDOFF.md
```

## Step 3B：Web

```text
STEP_ID=M8-03B-S4-WEB
AGENT_ID=identity-experience-builder
SESSION_ROLE=S4-QUALITY
WORK_PACKAGE=WP-086
ATTEMPT_ID=WP-086-a1
WORKTREE=E:\workspace\Multi-agent-m8-s4
BRANCH=codex/s4/m8-identity-experience
WRITE_SCOPE=web/**,tests/experience/**,tests/acceptance/**
MODE=IMPLEMENTATION
NEXT_ROLE=S1-ARCH
HANDOFF=tests/acceptance/m8/evidence/WP-086-a1-HANDOFF.md
```

## Join 3、验收与 Final

```text
STEP_ID=M8-JOIN-03-S1
UNLOCK_CONDITION=WP-085 and WP-086 clean PASS Handoffs
NEXT_STEP=M8-04-S4-ACCEPTANCE

STEP_ID=M8-04-S4-ACCEPTANCE
WORK_PACKAGE=WP-087
ATTEMPT_ID=WP-087-a1
WORKTREE=E:\workspace\Multi-agent-m8-s4
WRITE_SCOPE=packages/evaluation/**,packages/observability/**,evals/**,tests/acceptance/**,tests/experience/**,artifacts/acceptance/**
NEXT_ROLE=S7-INTEGRATION

STEP_ID=M8-05-S7-INTEGRATION
WORK_PACKAGE=WP-088
ATTEMPT_ID=WP-088-a1
WORKTREE=E:\workspace\Multi-agent-m8-s7
BRANCH=codex/s7/m8-integration
WRITE_SCOPE=scripts/integration/**,tests/integration/**,artifacts/integration/**
NEXT_ROLE=S1-ARCH

STEP_ID=M8-06-S1-FINAL
MODE=FINAL_GATE
USER_GATE_REQUIRED=yes
NEXT_MILESTONE=M9_NOT_AUTO_STARTED
```

## 热启动与内部子 Agent

每个主 Agent 只读取本 Chain、当前 WP、Registry、直接 Handoff 和 Base→Target 的强制
差异。`KNOWN_FACTS` 与 `DO_NOT_RECHECK` 在相关 Blob/Hash 未变化时必须复用。主 Agent
可自主调用最多两个子 Agent，但子任务必须有不同 `TASK_DEDUP_KEY`；同一 Worktree 只
允许一个写入者，子 Agent 没有 Git 或跨会话唤醒权，正式结果由主 Agent 复现。
