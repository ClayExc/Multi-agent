# CHAIN-M9T-ENGINEERING-CONTROL-01

## 授权

```text
CHAIN_ID=CHAIN-M9T-ENGINEERING-CONTROL-01
STATUS=COMPLETED
AUTHORITY=S1-ARCH
EXECUTION_MODE=ORDERED
RISK_CLASS=R2
AUTO_WAKE=enabled
MAX_HOPS=8
USER_GATE=M9T_FINAL_S1
FEATURE_ID=FP-OPS-002
BASE_COMMIT=f7ed60644cf196fba1bd7a7b50138c1f3a949f14
CONTEXT_MODE_DEFAULT=DELTA
MAX_ACTIVE_PRINCIPALS=1
MAX_SUBAGENTS_PER_PRINCIPAL=2
MAX_WRITERS_PER_WORKTREE=1
FINAL_GATE=S7-INTEGRATION->S1-ARCH->USER
```

用户批准先执行 M9 工程效率侧线。原 M9 的 Rego、Capability、DLP、Audit 和 Security
Event 保持未激活；本链不修改产品运行时、公共 ContractSet、Migration 或发布状态。

## 顺序

```text
S1 WP-090 activation
  -> S5 WP-091 repository map + Context Capsule
  -> S5 WP-092 test selection + Evidence Cache
  -> S4 WP-093 black-box acceptance
  -> S7 WP-094 integration
  -> S1 final -> USER_GATE
```

S5 在 WP-091/092 之间复用热上下文，不重新注册或全量读取。S4、S7 只在前置 Handoff
到达后激活；未激活会话不接收普通进度。

## Step 1：核心模型

```text
STEP_ID=M9T-01-S5-MAP-CAPSULE
WORK_PACKAGE=WP-091
ATTEMPT_ID=WP-091-a1
SESSION_ROLE=S5-CORE
WORKTREE=E:\workspace\Multi-agent-m9t-s5
BRANCH=codex/s5/wp-091-engineering-map
WRITE_SCOPE=packages/engineering-control/**,scripts/engineering/**,tests/core/engineering_control/**,tests/core/evidence/WP-091-a1-HANDOFF.md,pyproject.toml,uv.lock,.gitignore
MODE=IMPLEMENTATION
NEXT_STEP=M9T-02-S5-SELECT-CACHE
```

## Step 2：选择与缓存

```text
STEP_ID=M9T-02-S5-SELECT-CACHE
WORK_PACKAGE=WP-092
ATTEMPT_ID=WP-092-a1
SESSION_ROLE=S5-CORE
WORKTREE=E:\workspace\Multi-agent-m9t-s5
BRANCH=codex/s5/wp-091-engineering-map
WRITE_SCOPE=packages/engineering-control/**,scripts/engineering/**,tests/core/engineering_control/**,tests/core/evidence/WP-092-a1-HANDOFF.md,Makefile
MODE=HOT_CONTINUE
NEXT_ROLE=S4-QUALITY
```

## Step 3：黑盒验收

```text
STEP_ID=M9T-03-S4-ACCEPTANCE
WORK_PACKAGE=WP-093
ATTEMPT_ID=WP-093-a1
SESSION_ROLE=S4-QUALITY
WORKTREE=E:\workspace\Multi-agent-m9t-s4
BRANCH=codex/s4/wp-093-engineering-acceptance
WRITE_SCOPE=tests/acceptance/engineering_control/**,artifacts/acceptance/engineering-control/**
MODE=IMPLEMENTATION
NEXT_ROLE=S7-INTEGRATION
```

## Step 4：组合门禁

```text
STEP_ID=M9T-04-S7-INTEGRATION
WORK_PACKAGE=WP-094
ATTEMPT_ID=WP-094-a1
SESSION_ROLE=S7-INTEGRATION
WORKTREE=E:\workspace\Multi-agent-m9t-s7
BRANCH=codex/s7/wp-094-engineering-integration
WRITE_SCOPE=scripts/integration/verify_engineering_control.py,tests/integration/engineering_control/**,tests/integration/evidence/WP-094-a1-HANDOFF.md,tests/integration/evidence/WP-094-a1-PROOF.json,artifacts/integration/**
MODE=FINAL_GATE
NEXT_ROLE=S1-ARCH
USER_GATE_REQUIRED=yes
```

## 停止条件

P0/P1、公共契约变化、路径越权、测试漏选、缓存误命中、生成输出含 Secret/正文、未知
路径未升级、门禁失败或需要 OS 级读取拦截时立即停链。普通实现细节由 Owner 在授权范围
内解决，不回流 S1。
