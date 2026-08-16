# FlowPilot 工作包索引

## 当前阶段

- 里程碑：M11 短期记忆
- 阶段状态：`M11_ACTIVE`
- 架构责任：`S1-ARCH`
- 已接受基线：M0～M10 工程候选、P2 持久化恢复与 M9T 工程控制面
- 当前链：`CHAIN-M11-SHORT-TERM-MEMORY-01`
- 下一工作包：WP-122 / S3-PLATFORM（`READY_NOT_DISPATCHED`）
- 批准来源：用户已批准启动 M11 短期记忆链
- 发布状态：未发布、未 frozen；M12～M20 未激活

## 工作包状态

| 工作包 | 责任会话 | 状态 | 依赖 | 目标 |
|---|---|---|---|---|
| [WP-000](./WP-000-m0-contract-freeze.md) | S1-ARCH | IN_PROGRESS | 无 | 实现基线已评审；发布级冻结等待质量资产 |
| [WP-010](./WP-010-runtime-bootstrap.md) | S2-RUNTIME | MERGED_P2 | WP-021-a3 | Graph/Runtime/Context/Worker；P2 持久化恢复 Attempt `a4` |
| [WP-012](./WP-012-langgraph-studio-observability.md) | S2-RUNTIME | ACCEPTED_M2 | M2 已合并 | Studio 非黑箱入口、安全状态投影与恢复调试 |
| [WP-011](./WP-011-core-bootstrap.md) | S5-CORE | MERGED_P1 | P1 已合并 | Domain/Application/API/Domain Pack；P1 Attempt `a6` |
| [WP-020](./WP-020-platform-bootstrap.md) | S3-PLATFORM | ACCEPTED_M1 / MERGED_P1 | P1 已合并 | Gateway/Policy/Security；P1 知识工具 Attempt `a2` |
| [WP-021](./WP-021-data-bootstrap.md) | S6-DATA | MERGED_P2 | P1 已合并 | Persistence 恢复边界与负向证据 Attempt `a3` |
| [WP-030](./WP-030-quality-bootstrap.md) | S4-QUALITY | MERGED_P1 | P1 已合并 | 20 条候选 Case、黑盒质量与证据 Attempt `a4` |
| [WP-031](./WP-031-acceptance-remediation.md) | S4-QUALITY | ACCEPTED | M6 候选已合并 | 真实执行门禁、Gate 一致性与验收证据修复；未接入场景保持 0 PASS |
| [WP-032](./WP-032-strict-type-hardening.md) | S2/S4/S5 | ACCEPTED | WP-031-a1 | 116 个 Workspace 源码文件严格类型基线修复 |
| [WP-033](./WP-033-contract-attestation-integrity.md) | S1-ARCH | ACCEPTED | WP-032 | Contract Review 证据内容、角色、结论与摘要绑定 |
| [WP-034](./WP-034-five-role-contract-delta-review.md) | S2～S6 | ACCEPTED | WP-033 | 新摘要五角色只读 DELTA 复审 |
| [WP-035](./WP-035-judge-calibration-trust-boundary.md) | S4-QUALITY | DEFERRED_TO_M19 | WP-034 | 流水线问题已识别；真实产品输出和 Judge 校准随 M19 产品评测处理 |
| [WP-036](./WP-036-control-plane-reconciliation.md) | S1-ARCH | DONE | M0～M6/P2 | 事实源、工程质量入口、CI 与 M7 拆包收口 |
| [WP-037](./WP-037-principal-subagent-contract.md) | S1-ARCH | DONE | M7 final | DELTA 热启动、领域主 Agent 自主调用子 Agent 与复用优先契约 |
| [WP-080](./WP-080-m8-identity-contract-gate.md) | S1-ARCH | DONE | WP-037 | M8 OIDC、双主体、SecurityContext 与租户/RLS 信任边界 |
| [WP-081](./WP-081-m8-local-keycloak.md) | S6-DATA | ACCEPTED_M8 | WP-080 | 本地 Keycloak Realm、双租户与服务 Client |
| [WP-082](./WP-082-m8-trusted-identity-boundary.md) | S3-PLATFORM | ACCEPTED_M8 | WP-080 | JWT/JWKS、ContextSource、工作负载与 Gateway 身份边界 |
| [WP-083](./WP-083-m8-api-oidc-intake.md) | S5-CORE | ACCEPTED_M8 | WP-081/082 | API/BFF 登录会话与可信 Command Intake |
| [WP-084](./WP-084-m8-tenant-rls-binding.md) | S6-DATA | ACCEPTED_M8 | WP-081/082 | Context Store、事务租户绑定与 RLS 恢复 |
| [WP-085](./WP-085-m8-runtime-tenant-propagation.md) | S2-RUNTIME | ACCEPTED_M8 | WP-083/084 | Worker/Graph 身份传播与恢复重验 |
| [WP-086](./WP-086-m8-web-login-experience.md) | S4-QUALITY | ACCEPTED_M8 | WP-081/083 | Web 登录、会话失效与重新认证体验 |
| [WP-087](./WP-087-m8-security-acceptance.md) | S4-QUALITY | ACCEPTED_M8 | WP-081～086 | 身份租户黑盒和固定 Case 执行器 |
| [WP-088](./WP-088-m8-integration-verification.md) | S7-INTEGRATION | ACCEPTED_M8 | WP-087 | M8 空环境组合与证据复算 |
| [WP-090](./WP-090-m9t-engineering-control-gate.md) | S1-ARCH | DONE | M8 final | M9T 架构、Feature、注册与工作包门禁 |
| [WP-091](./WP-091-m9t-repository-map-capsule.md) | S5-CORE | ACCEPTED_M9T | WP-090 | 确定性仓库地图与 Delta Context Capsule |
| [WP-092](./WP-092-m9t-test-selection-evidence-cache.md) | S5-CORE | ACCEPTED_M9T | WP-091 | 测试选择、Evidence Cache 与 Attempt 报告 |
| [WP-093](./WP-093-m9t-engineering-control-acceptance.md) | S4-QUALITY | ACCEPTED_M9T | WP-092 | 黑盒、变异矩阵、效率与安全验收 |
| [WP-094](./WP-094-m9t-engineering-control-integration.md) | S7-INTEGRATION | ACCEPTED_M9T | WP-093 | 组合复算与最终证据 |
| [WP-100](./WP-100-m9-governance-gate.md) | S1-ARCH | DONE | WP-094 | M9 架构、注册、范围与退出门禁 |
| [WP-101](./WP-101-m9-versioned-policy.md) | S3-PLATFORM | ACCEPTED_M9 | WP-100 | 版本化 Rego/OPA、发布回滚与 deny-overrides |
| [WP-102](./WP-102-m9-capability-dlp-gateway.md) | S3-PLATFORM | ACCEPTED_M9 | WP-101 | Capability、Secret Provider、DLP 与 Gateway 强制执行 |
| [WP-103](./WP-103-m9-runtime-dlp.md) | S2-RUNTIME | ACCEPTED_M9 | WP-102 | Prompt、Context 与模型输出 DLP 边界 |
| [WP-104](./WP-104-m9-governance-api.md) | S5-CORE | ACCEPTED_M9 | WP-103 | 治理查询 Port、API 与 Workspace 闭包 |
| [WP-105](./WP-105-m9-audit-persistence.md) | S6-DATA | ACCEPTED_M9 | WP-104 | Audit/Security 追加式存储、查询与完整性 |
| [WP-106](./WP-106-m9-local-governance-infra.md) | S6-DATA | ACCEPTED_M9 | WP-105 | 本地 OPA、Secret 配置与空环境启动 |
| [WP-107](./WP-107-m9-governance-web.md) | S4-QUALITY | ACCEPTED_M9 | WP-106 | 治理页面、信号查询与错误体验 |
| [WP-108](./WP-108-m9-security-acceptance.md) | S4-QUALITY | ACCEPTED_M9 | WP-107 | M9 黑盒安全、固定分母执行器与证据 |
| [WP-109](./WP-109-m9-integration-verification.md) | S7-INTEGRATION | ACCEPTED_M9 | WP-108 | 真实本地组合、保护树与最终复算 |
| [WP-110](./WP-110-m10-knowledge-gate.md) | S1-ARCH | DONE | WP-109 | M10 架构、注册、范围与退出门禁 |
| [WP-111](./WP-111-m10-knowledge-core.md) | S5-CORE | ACCEPTED_M10 | WP-110 | 知识文档领域、应用 Port 与生命周期语义 |
| [WP-112](./WP-112-m10-document-persistence.md) | S6-DATA | ACCEPTED_M10 | WP-111 | 文档版本事实、ACL、RLS 与事务 |
| [WP-113](./WP-113-m10-pgvector-index.md) | S6-DATA | ACCEPTED_M10 | WP-112 | pgvector、关键词索引与重建生命周期 |
| [WP-114](./WP-114-m10-retrieval-engine.md) | S4-QUALITY | ACCEPTED_M10 | WP-113 | 混合检索、重排、去重与引用复验 |
| [WP-115](./WP-115-m10-knowledge-mcp.md) | S3-PLATFORM | ACCEPTED_M10 | WP-114 | 安全 Knowledge MCP 与现有 Schema Pin |
| [WP-116](./WP-116-m10-knowledge-composition.md) | S5-CORE | ACCEPTED_M10 | WP-115 | 管理 API、产品组合与 Workspace 闭包 |
| [WP-117](./WP-117-m10-runtime-citations.md) | S2-RUNTIME | ACCEPTED_M10 | WP-116 | Runtime 知识查询、无证据行为与稳定引用 |
| [WP-118](./WP-118-m10-knowledge-web.md) | S4-QUALITY | ACCEPTED_M10 | WP-117 | 知识管理与检索诊断 Web |
| [WP-119](./WP-119-m10-knowledge-acceptance.md) | S4-QUALITY | ACCEPTED_M10 | WP-118 | M10 固定分母执行器与黑盒验收 |
| [WP-120](./WP-120-m10-integration-verification.md) | S7-INTEGRATION | ACCEPTED_M10 | WP-119 | M10 本地组合、保护树与最终复算 |
| [WP-121](./WP-121-m11-short-term-memory-gate.md) | S1-ARCH | DONE | WP-120 | M11 状态权威、架构、注册与退出门禁 |
| [WP-122](./WP-122-m11-memory-security-surface.md) | S3-PLATFORM | READY_NOT_DISPATCHED | WP-121 | Working Memory 集中内容安全表面 |
| [WP-123](./WP-123-m11-context-memory-core.md) | S2-RUNTIME | BLOCKED | WP-122 | Turn/Snapshot/Manifest、摘要与预算核心 |
| [WP-124](./WP-124-m11-memory-persistence.md) | S6-DATA | BLOCKED | WP-123 | PostgreSQL、RLS、CAS、TTL 与清理 |
| [WP-125](./WP-125-m11-memory-runtime.md) | S2-RUNTIME | BLOCKED | WP-124 | Runtime、Checkpoint、Handoff 与恢复集成 |
| [WP-126](./WP-126-m11-memory-api-composition.md) | S5-CORE | BLOCKED | WP-125 | API、清理、组合与 Workspace 闭包 |
| [WP-127](./WP-127-m11-memory-web.md) | S4-QUALITY | BLOCKED | WP-126 | 上下文与短期记忆 Web |
| [WP-128](./WP-128-m11-memory-acceptance.md) | S4-QUALITY | BLOCKED | WP-127 | 50 轮、消融与固定分母验收 |
| [WP-129](./WP-129-m11-integration-verification.md) | S7-INTEGRATION | BLOCKED | WP-128 | M11 本地组合与最终复算 |
| [WP-040](./WP-040-integration-verification.md) | S7-INTEGRATION | ACCEPTED_P2 | WP-010-a4 | RELEASE 恢复组合复现与 S1 final 输入 Attempt `a7` |
| [WP-P2](./WP-P2-durable-runtime.md) | 注册链 | DONE | Flow Lite `g1` 已批准 | PostgreSQL Checkpoint、Worker 重启与 Redis 丢失恢复垂直包 |
| [WP-070](./WP-070-m7-provider-runtime-adapters.md) | S2-RUNTIME | MERGED_M7_CANDIDATE | WP-036 | LiteLLM/DeepSeek 与 OpenAI/Claude Agents SDK Adapter |
| [WP-071](./WP-071-m7-local-product-composition.md) | S5/S6/S2 | MERGED_M7_CANDIDATE | WP-070 | API/Worker/Graph/Data/只读 MCP 本地装配 |
| [WP-072](./WP-072-m7-web-studio-observability.md) | S4/S2 | MERGED_M7_CANDIDATE | WP-071 | Web、SSE、Studio 与安全可观测体验 |
| [WP-073](./WP-073-m7-product-executors-final-gate.md) | S4/S7 | MERGED / RELEASE_GATE_FAIL | WP-072 | 24 条产品执行器、156 固定分母与组合门禁 |

`IN_PROGRESS` 表示 WP-000 已完成实现基线评审证明，但尚未满足发布级冻结条件。`BLOCKED` 在此只描述工作包前置条件，不代表项目或 Codex 目标进入 blocked 状态。

rc1 已被 S2、S3、S4 一致拒绝并完成 S1 裁决；当前评审目标是 `flowpilot-m0-contracts-v1-rc2`。旧结论不得作为 rc2 的接受证据。

## M7～M11 状态

M7 已按严格 `ORDERED` 和最小 Agent 注册集合完成：

```text
WP-070 Provider/SDK Adapter
  -> WP-071 本地运行链
  -> WP-072 Web/Studio
  -> WP-073 产品执行器/S7 门禁
  -> S1 final/user gate
```

WP-070～WP-073、WP-080～WP-088、WP-100～WP-109 及对应 S7/S1 final 均已完成。
固定 156 条结果为 40 通过、116 明确失败、0 跳过、0 隔离，因此发布 Gate 继续失败。
M9T、M9 与 M10 已完成。M11 已由用户批准，按 WP-122→WP-129 严格线性执行；
S3/WP-122 已准备但尚未取得写租约，必须等待用户明确唤醒。

历史 M0/M1/M2 链和证据仍保留在各授权记录与 Handoff 中，不再作为当前
启动说明。Registry、完整 Dataset、Fixture 和 Traceability 完成后才能进行
发布级 `frozen` 复审。

每次向多个会话派发时必须显式标注 `PARALLEL`、`READ_ONLY_PARALLEL` 或 `ORDERED`。消息到达顺序不代表执行顺序；`ORDERED` 派发必须写明前置交付和解锁条件。WP-040 可以只读并行复核，写模式计入“最多三个写会话”上限。

## 共享文件单写者

| 文件/范围 | M0 写入者 | 说明 |
|---|---|---|
| `pyproject.toml`、`uv.lock`、`Makefile` | S1-ARCH / WP-036 | 本轮收口质量入口；后续恢复 S5-CORE 默认所有权 |
| `.env.example`、根级 Compose/容器配置 | S6-DATA / WP-021 | 环境和部署依赖 |
| `scripts/acceptance/**` | S4-QUALITY / WP-030 | 证据生成入口；不得同时修改 Makefile |
| `contracts/**`、本目录 | S1-ARCH / WP-000 | 公共契约与工作包仲裁 |

WP-036 完成后，共享 Python Workspace 与依赖锁恢复由 S5-CORE 单写；其他角色需在
工作包中显式申请，不能并行修改。
