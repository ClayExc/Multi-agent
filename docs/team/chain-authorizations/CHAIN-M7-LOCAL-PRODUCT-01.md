# CHAIN-M7-LOCAL-PRODUCT-01

## 授权

```text
CHAIN_ID=CHAIN-M7-LOCAL-PRODUCT-01
STATUS=COMPLETED_USER_MERGED
AUTHORITY=S1-ARCH
AUTHORITY_REF=docs/team/chain-authorizations/CHAIN-M7-LOCAL-PRODUCT-01.md
EXECUTION_MODE=ORDERED
RISK_CLASS=R2
AUTO_WAKE=enabled
MAX_HOPS=12
USER_GATE=M7_FINAL_S1
FINAL_HEAD=e222411824b45c9fed5fd96c6c4fc39c7dfdc09b
FINAL_RESULT=M7_CANDIDATE_MERGED_RELEASE_GATE_FAIL
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
FINAL_GATE=S7-INTEGRATION->S1-ARCH
MAX_LOCAL_REPAIR_ATTEMPTS=1
CONTEXT_MODE_DEFAULT=DELTA
CONTEXT_PROTOCOL=docs/team/CONTEXT_BOOTSTRAP_PROTOCOL.md
```

用户已批准 M7 热启动。正式产品范围固定为智能工单、知识库问答、新员工入职、
权限变更和审批辅助；VPN 仅保留为历史回归 Fixture。M7 不启动 M8，不修改公共
契约，不连接真实企业系统，也不在未显式启用时产生付费 Provider 调用。

注册能力与未选择角色以
[`Agent 注册表`](../agent-registrations/CHAIN-M7-LOCAL-PRODUCT-01.md) 为准。

## 顺序

```text
S2 WP-070 provider
  -> S5 dependency lock
  -> S2 WP-070 conformance
  -> S4 provider blackbox
  -> S5 WP-071 core/API
  -> S6 WP-071 data/env
  -> S2 WP-071 runtime
  -> S2 WP-072 safe projection
  -> S4 WP-072 Web/Studio
  -> S4 WP-073 executors
  -> S7 M7 RELEASE
  -> S1 final -> USER_GATE
```

## Steps

### 1. Provider 与 SDK Adapter

```text
STEP_ID=M7-01-S2-PROVIDER
AGENT_ID=runtime-builder
SESSION_ROLE=S2-RUNTIME
WORK_PACKAGE=WP-070
ATTEMPT_ID=WP-070-a1
BASE_COMMIT=WAKE_MESSAGE.ACTIVATION_COMMIT
WORKTREE=E:\workspace\Multi-agent-m7-s2
BRANCH=codex/s2/wp-070-provider-runtime-adapters
WRITE_SCOPE=packages/model-gateway/**,packages/agent-runtime/**,tests/runtime/**
MODE=IMPLEMENTATION
UNLOCK_CONDITION=clean worktree; ff-only exact activation Head; digest match
NEXT_AGENT_ID=core-composer
NEXT_ROLE=S5-CORE
HANDOFF=tests/runtime/evidence/WP-070-a1-HANDOFF.md
CONTEXT_MODE=DELTA
CONTEXT_BASE_COMMIT=052e61beff5711e3e69dbaf45b792ad8d1a309dc
CONTEXT_REQUIRED_READS=chain,WP-070,registry,changed-mandatory-docs
```

实现 LiteLLM、OpenAI Agents SDK 与 Claude Agent SDK 的统一端口；产品逻辑只使用
`flowpilot.primary.fast`，DeepSeek Provider ID 为 `deepseek-v4-flash`。在线 Smoke
必须显式启用；默认门禁使用 Fake Transport，凭据不得进入 State、Trace 或证据。

### 2. Workspace 与依赖锁

```text
STEP_ID=M7-02-S5-LOCK
AGENT_ID=core-composer
SESSION_ROLE=S5-CORE
WORK_PACKAGE=WP-070
ATTEMPT_ID=WP-070-a1-lock
BASE_COMMIT=<Step-1-NEW_HEAD>
WORKTREE=E:\workspace\Multi-agent-m7-s5
BRANCH=codex/s5/m7-core-composition
WRITE_SCOPE=pyproject.toml,uv.lock,Makefile,tests/core/evidence/**
MODE=IMPLEMENTATION
UNLOCK_CONDITION=S2 Handoff accepted; ff-only exact S2 Head
NEXT_AGENT_ID=runtime-builder
NEXT_ROLE=S2-RUNTIME
HANDOFF=tests/core/evidence/WP-070-a1-lock-HANDOFF.md
CONTEXT_MODE=DELTA
CONTEXT_BASE_COMMIT=c6b250e3b3a5b7df93b60857b5ee438027ee2ff3
CONTEXT_REQUIRED_READS=chain,WP-070,registry,S2-handoff
```

只固定实际使用的依赖和版本，复算锁文件、许可证、漏洞和全新环境导入；不修改
Adapter 代码或放宽质量门禁。

### 3. Provider Conformance

```text
STEP_ID=M7-03-S2-CONFORMANCE
AGENT_ID=runtime-builder
SESSION_ROLE=S2-RUNTIME
WORK_PACKAGE=WP-070
ATTEMPT_ID=WP-070-a2
BASE_COMMIT=<Step-2-NEW_HEAD>
WORKTREE=E:\workspace\Multi-agent-m7-s2
WRITE_SCOPE=packages/model-gateway/**,packages/agent-runtime/**,tests/runtime/**
MODE=IMPLEMENTATION
UNLOCK_CONDITION=S5 lock Handoff accepted; ff-only exact S5 Head
NEXT_AGENT_ID=experience-builder
NEXT_ROLE=S4-QUALITY
HANDOFF=tests/runtime/evidence/WP-070-a2-HANDOFF.md
CONTEXT_MODE=DELTA
CONTEXT_BASE_COMMIT=<Step-1-NEW_HEAD>
CONTEXT_REQUIRED_READS=chain,WP-070,registry,S5-handoff
```

### 4. Provider 黑盒复核

```text
STEP_ID=M7-04-S4-PROVIDER-REVIEW
AGENT_ID=experience-builder
SESSION_ROLE=S4-QUALITY
WORK_PACKAGE=WP-070
ATTEMPT_ID=WP-070-q1
BASE_COMMIT=<Step-3-NEW_HEAD>
WORKTREE=E:\workspace\Multi-agent-m7-s4
BRANCH=codex/s4/m7-experience-evaluation
WRITE_SCOPE=tests/acceptance/provider_runtime/**
MODE=IMPLEMENTATION
UNLOCK_CONDITION=S2 conformance Handoff accepted; ff-only exact S2 Head
NEXT_AGENT_ID=core-composer
NEXT_ROLE=S5-CORE
HANDOFF=tests/acceptance/provider_runtime/evidence/WP-070-q1-HANDOFF.md
CONTEXT_MODE=DELTA
CONTEXT_BASE_COMMIT=8a351326ad33db195098ffd4c2f8a4b9f6b5a598
CONTEXT_REQUIRED_READS=chain,WP-070,registry,S2-handoff
```

必须独立验证缺密钥、超时、限流、结构错误、预算、Session 失效和零凭据泄漏。

### 5. API 与应用装配

```text
STEP_ID=M7-05-S5-CORE-COMPOSITION
AGENT_ID=core-composer
SESSION_ROLE=S5-CORE
WORK_PACKAGE=WP-071
ATTEMPT_ID=WP-071-a1-core
BASE_COMMIT=<Step-4-NEW_HEAD>
WORKTREE=E:\workspace\Multi-agent-m7-s5
WRITE_SCOPE=apps/api/**,packages/application/**,tests/core/**,pyproject.toml,uv.lock,Makefile
MODE=IMPLEMENTATION
UNLOCK_CONDITION=WP-070 blackbox PASS; ff-only exact S4 Head
NEXT_AGENT_ID=data-composer
NEXT_ROLE=S6-DATA
HANDOFF=tests/core/evidence/WP-071-a1-core-HANDOFF.md
CONTEXT_MODE=DELTA
CONTEXT_BASE_COMMIT=<Step-2-NEW_HEAD>
CONTEXT_REQUIRED_READS=chain,WP-071,registry,S4-handoff
```

### 6. 数据、环境与恢复装配

```text
STEP_ID=M7-06-S6-DATA-COMPOSITION
AGENT_ID=data-composer
SESSION_ROLE=S6-DATA
WORK_PACKAGE=WP-071
ATTEMPT_ID=WP-071-a1-data
BASE_COMMIT=<Step-5-NEW_HEAD>
WORKTREE=E:\workspace\Multi-agent-m7-s6
BRANCH=codex/s6/wp-071-data-composition
WRITE_SCOPE=packages/persistence/**,infra/**,.env.example,tests/data/**
MODE=IMPLEMENTATION
UNLOCK_CONDITION=S5 core Handoff accepted; ff-only exact S5 Head
NEXT_AGENT_ID=runtime-builder
NEXT_ROLE=S2-RUNTIME
HANDOFF=tests/data/evidence/WP-071-a1-data-HANDOFF.md
CONTEXT_MODE=DELTA
CONTEXT_BASE_COMMIT=e41f0266e6e588417332043b68a3309b2d40bcf7
CONTEXT_REQUIRED_READS=chain,WP-071,registry,S5-handoff
```

`.env.example` 只声明变量名和安全默认值；真实密钥不进入仓库。Compose、RLS、
Checkpoint、Redis 丢失和跨租户成功数 0 必须复验。

### 7. Worker 与 LangGraph 产品装配

```text
STEP_ID=M7-07-S2-RUNTIME-COMPOSITION
AGENT_ID=runtime-builder
SESSION_ROLE=S2-RUNTIME
WORK_PACKAGE=WP-071
ATTEMPT_ID=WP-071-a1-runtime
BASE_COMMIT=<Step-6-NEW_HEAD>
WORKTREE=E:\workspace\Multi-agent-m7-s2
WRITE_SCOPE=apps/worker/**,packages/graph/**,tests/runtime/**
MODE=IMPLEMENTATION
UNLOCK_CONDITION=S6 data Handoff accepted; ff-only exact S6 Head
NEXT_AGENT_ID=runtime-builder
NEXT_ROLE=S2-RUNTIME
HANDOFF=tests/runtime/evidence/WP-071-a1-runtime-HANDOFF.md
CONTEXT_MODE=DELTA
CONTEXT_BASE_COMMIT=<Step-3-NEW_HEAD>
CONTEXT_REQUIRED_READS=chain,WP-071,registry,S6-handoff
```

正式首链是企业知识库问答；VPN 只能作为历史回归输入，不能成为路由或页面硬编码。

### 8. Studio 安全投影

```text
STEP_ID=M7-08-S2-STUDIO-PROJECTION
AGENT_ID=runtime-builder
SESSION_ROLE=S2-RUNTIME
WORK_PACKAGE=WP-072
ATTEMPT_ID=WP-072-a1-runtime
BASE_COMMIT=<Step-7-NEW_HEAD>
WORKTREE=E:\workspace\Multi-agent-m7-s2
WRITE_SCOPE=apps/worker/**,packages/graph/**,tests/runtime/**
MODE=IMPLEMENTATION
UNLOCK_CONDITION=WP-071 runtime gates PASS
NEXT_AGENT_ID=experience-builder
NEXT_ROLE=S4-QUALITY
HANDOFF=tests/runtime/evidence/WP-072-a1-runtime-HANDOFF.md
CONTEXT_MODE=DELTA
CONTEXT_BASE_COMMIT=<Step-7-NEW_HEAD>
CONTEXT_REQUIRED_READS=chain,WP-072,registry
```

### 9. Web、SSE 与可观测体验

```text
STEP_ID=M7-09-S4-WEB-STUDIO
AGENT_ID=experience-builder
SESSION_ROLE=S4-QUALITY
WORK_PACKAGE=WP-072
ATTEMPT_ID=WP-072-a1
BASE_COMMIT=<Step-8-NEW_HEAD>
WORKTREE=E:\workspace\Multi-agent-m7-s4
WRITE_SCOPE=web/**,packages/observability/**,tests/experience/**,tests/acceptance/**
MODE=IMPLEMENTATION
UNLOCK_CONDITION=S2 projection Handoff accepted; ff-only exact S2 Head
NEXT_AGENT_ID=experience-builder
NEXT_ROLE=S4-QUALITY
HANDOFF=tests/acceptance/m7/evidence/WP-072-a1-HANDOFF.md
CONTEXT_MODE=DELTA
CONTEXT_BASE_COMMIT=<Step-4-NEW_HEAD>
CONTEXT_REQUIRED_READS=chain,WP-072,registry,S2-handoff
```

### 10. 产品执行器与固定分母

```text
STEP_ID=M7-10-S4-EXECUTORS
AGENT_ID=experience-builder
SESSION_ROLE=S4-QUALITY
WORK_PACKAGE=WP-073
ATTEMPT_ID=WP-073-a1-quality
BASE_COMMIT=<Step-9-NEW_HEAD>
WORKTREE=E:\workspace\Multi-agent-m7-s4
WRITE_SCOPE=packages/evaluation/**,scripts/acceptance/**,tests/acceptance/**
MODE=IMPLEMENTATION
UNLOCK_CONDITION=WP-072 experience gates PASS
NEXT_AGENT_ID=m7-verifier
NEXT_ROLE=S7-INTEGRATION
HANDOFF=tests/acceptance/m7/evidence/WP-073-a1-quality-HANDOFF.md
CONTEXT_MODE=DELTA
CONTEXT_BASE_COMMIT=<Step-9-NEW_HEAD>
CONTEXT_REQUIRED_READS=chain,WP-073,registry
```

156 条 Case 分母保持固定；M7 尚未支持的业务链必须明确失败，不能跳过或缩分母。

### 11. M7 RELEASE 组合复现

```text
STEP_ID=M7-11-S7-RELEASE
AGENT_ID=m7-verifier
SESSION_ROLE=S7-INTEGRATION
WORK_PACKAGE=WP-073
ATTEMPT_ID=WP-073-a1-release
BASE_COMMIT=<Step-10-NEW_HEAD>
WORKTREE=E:\workspace\Multi-agent-m7-s7
BRANCH=codex/s7/wp-073-m7-final-gate
WRITE_SCOPE=scripts/integration/**,tests/integration/**
MODE=IMPLEMENTATION
GATE_LEVEL=RELEASE
UNLOCK_CONDITION=S4 executor Handoff accepted; ff-only exact S4 Head
NEXT_AGENT_ID=S1-ARCH
NEXT_ROLE=S1-ARCH
HANDOFF=tests/integration/evidence/WP-073-a1-release-HANDOFF.md
CONTEXT_MODE=DELTA
CONTEXT_BASE_COMMIT=0b1d6ba3aa31536d9170027f0981c0e626b71f35
CONTEXT_REQUIRED_READS=chain,WP-070,WP-071,WP-072,WP-073,registry,S4-handoff
```

## 停止条件

出现公共契约变化、S3 安全边界缺口、R3、路径越权、真实凭据泄漏、跨租户成功数
大于 0、破坏性迁移、门禁失败或外部付费调用未获明确启用时立即暂停并上报 S1。
普通 P2/P3 在原范围内修复；同一问题最多一次局部返修。

## 自动唤醒

- 只有完成、P0/P1、范围请求或最终用户门禁发送跨任务消息。
- 每一步仅唤醒唯一下一 Agent，使用 `DELTA` 和同一 `DEDUP_KEY` 规则。
- S7 完成后唤醒 S1；S1 独立复算并停在用户门禁，不自动启动 M8。
