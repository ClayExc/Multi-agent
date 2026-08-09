# CHAIN-M7-LOCAL-PRODUCT-01 Agent 注册表

```text
REGISTRY_STATUS=COMPLETED
FINAL_HEAD=e222411824b45c9fed5fd96c6c4fc39c7dfdc09b
FINAL_RESULT=M7_CANDIDATE_MERGED_RELEASE_GATE_FAIL
```

原计划登记五个能力 Agent。执行中出现集中凭据扫描缺口后，S1 按同一注册协议临时
加入 S3 `credential-guard-builder`，修复完成后退出；该变化没有恢复七会话广播。

## 调度结论

M7 以五个基础能力 Agent 和一个 S1 最终门禁启动，严格有序，同一时刻最多一个
写入者。P0 凭据边界暴露后，S3 作为 `credential-guard-builder` 动态加入两个修复
Attempt；它只接收阻断证据和精确输入 Head，没有接收普通进度广播。

```text
CHAIN_ID=CHAIN-M7-LOCAL-PRODUCT-01
REGISTRY_MODE=minimum-capability-set
EXECUTION_MODE=ORDERED
MAX_ACTIVE_WRITERS=1
COMMUNICATION=event-driven
BASE_SELECTED=runtime-builder,core-composer,data-composer,experience-builder,m7-verifier
DYNAMICALLY_SELECTED=credential-guard-builder
NOT_SELECTED=none
```

## 注册记录

### runtime-builder

```text
AGENT_ID=runtime-builder
SESSION_ROLE=S2-RUNTIME
CAPABILITIES=litellm,openai-agents-sdk,claude-agent-sdk,model-gateway,langgraph-worker,studio-projection
WRITE_SCOPE=packages/model-gateway/**,packages/agent-runtime/**,apps/worker/**,packages/graph/**,tests/runtime/**
RISK_CEILING=R2
INPUT_CONTRACTS=ProviderWire,AgentRuntimePort,ContextEnvelope,WP-070,WP-071,WP-072
OUTPUT_CONTRACTS=provider-adapters,local-runtime-composition,safe-studio-projection
EVIDENCE_CONTRACT=tests/runtime/evidence/<attempt>-HANDOFF.md
AVAILABILITY=selected
CONCURRENCY=single-writer
EXIT_CONDITION=对应 Step 门禁通过并产生精确 clean Head 与 Handoff
CONTEXT_MODE=DELTA
CONTEXT_BASE_COMMIT=052e61beff5711e3e69dbaf45b792ad8d1a309dc
```

### core-composer

```text
AGENT_ID=core-composer
SESSION_ROLE=S5-CORE
CAPABILITIES=python-workspace,dependency-lock,fastapi,application-port,command-intake
WRITE_SCOPE=apps/api/**,packages/application/**,tests/core/**,pyproject.toml,uv.lock,Makefile
RISK_CEILING=R2
INPUT_CONTRACTS=provider-adapter-head,Application-Ports,WP-070,WP-071
OUTPUT_CONTRACTS=locked-workspace,api-command-runtime-composition
EVIDENCE_CONTRACT=tests/core/evidence/<attempt>-HANDOFF.md
AVAILABILITY=dependency-wait
CONCURRENCY=single-writer
EXIT_CONDITION=锁文件或 API/Application Step 通过并产生精确 clean Head
CONTEXT_MODE=DELTA
CONTEXT_BASE_COMMIT=c6b250e3b3a5b7df93b60857b5ee438027ee2ff3
```

### data-composer

```text
AGENT_ID=data-composer
SESSION_ROLE=S6-DATA
CAPABILITIES=postgres,redis,checkpoint,rls,compose,environment-contract
WRITE_SCOPE=packages/persistence/**,infra/**,.env.example,tests/data/**
RISK_CEILING=R2
INPUT_CONTRACTS=WP-071,Application-Persistence-Ports,Runtime-Recovery-Ports
OUTPUT_CONTRACTS=local-data-composition,environment-template,recovery-evidence
EVIDENCE_CONTRACT=tests/data/evidence/<attempt>-HANDOFF.md
AVAILABILITY=dependency-wait
CONCURRENCY=single-writer
EXIT_CONDITION=本地数据装配与恢复门禁通过并产生精确 clean Head
CONTEXT_MODE=DELTA
CONTEXT_BASE_COMMIT=e41f0266e6e588417332043b68a3309b2d40bcf7
```

### experience-builder

```text
AGENT_ID=experience-builder
SESSION_ROLE=S4-QUALITY
CAPABILITIES=provider-blackbox,web,sse,observability,acceptance-runner,fixed-denominator
WRITE_SCOPE=web/**,packages/observability/**,packages/evaluation/**,scripts/acceptance/**,tests/experience/**,tests/acceptance/**
RISK_CEILING=R2
INPUT_CONTRACTS=WP-070,WP-072,WP-073,product-api-sse,provider-handoff
OUTPUT_CONTRACTS=provider-review,web-studio-experience,m7-product-executors
EVIDENCE_CONTRACT=tests/acceptance/<scope>/evidence/<attempt>-HANDOFF.md
AVAILABILITY=dependency-wait
CONCURRENCY=single-writer
EXIT_CONDITION=对应黑盒、体验或固定分母门禁通过并产生精确 clean Head
CONTEXT_MODE=DELTA
CONTEXT_BASE_COMMIT=8a351326ad33db195098ffd4c2f8a4b9f6b5a598
```

### m7-verifier

```text
AGENT_ID=m7-verifier
SESSION_ROLE=S7-INTEGRATION
CAPABILITIES=linear-candidate,release-reproduction,compose,studio,web,security,evidence-hash
WRITE_SCOPE=scripts/integration/**,tests/integration/**
RISK_CEILING=R2
INPUT_CONTRACTS=WP-070-through-WP-073 exact linear Head and Handoffs
OUTPUT_CONTRACTS=M7-RELEASE-HANDOFF,M7-PROOF
EVIDENCE_CONTRACT=tests/integration/evidence/WP-073-a1-release-HANDOFF.md
AVAILABILITY=dependency-wait
CONCURRENCY=single-writer
EXIT_CONDITION=M7 RELEASE 候选复现完成并唤醒 S1 final gate
CONTEXT_MODE=DELTA
CONTEXT_BASE_COMMIT=0b1d6ba3aa31536d9170027f0981c0e626b71f35
```

### credential-guard-builder（动态注册）

```text
AGENT_ID=credential-guard-builder
SESSION_ROLE=S3-PLATFORM
CAPABILITIES=credential-family-registry,recursive-secret-scan,safe-finding
WRITE_SCOPE=packages/security/**,tests/platform/**
RISK_CEILING=R3
OUTPUT_CONTRACTS=WP-074-a1,WP-074-a2
AVAILABILITY=completed
EXIT_CONDITION=集中扫描器通过 S4 TaskEvent/SSE 黑盒并退出当前链
```

S3 原本不在基础集合内。S4 发现同类凭据可穿过事件与 SSE 后，链路按停止条件暂停，
再由 S1 动态注册 S3；S5 只负责消费安全端口和清理错误回显，没有越权修改安全内核。

S1 只处理激活、P0/P1、范围变化和最终门禁；普通完成事件直接交给唯一下一 Agent。
