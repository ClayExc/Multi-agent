# FlowPilot 项目交接总览

## 1. 当前结论

```text
SNAPSHOT=M0_M10_CANDIDATE_M11_ACTIVE
STATUS=M11_SHORT_TERM_MEMORY_ACTIVE
S7_HEAD=bbb8b2b860389a98e8e283c36a28b1d71232ea1c
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
NEXT_MILESTONE=M11_SHORT_TERM_MEMORY
ACTIVE_DEVELOPMENT_CHAIN=CHAIN-M11-SHORT-TERM-MEMORY-01
NEXT_WORK_PACKAGE=WP-122
DISPATCH_STATE=READY_NOT_DISPATCHED
RELEASED=false
FROZEN=false
```

FlowPilot 已完成 M0～M8 工程候选：公共契约与当前 16 成员 Python Workspace、
安全 MCP 平台、PostgreSQL/RLS/Inbox/Outbox/Lease/Checkpoint、LangGraph Studio、
历史知识检索样例与安全写入、Context/Handoff、新员工复合申请、Fixture Web，以及 120 条
功能任务和 36 条安全/故障任务的版本化语料与 Hash 冻结。M7 进一步加入 Provider/SDK
Adapter、知识问答产品组合、真实 API/SSE Web 模式、集中凭据扫描和首批产品执行器；
M8 接入本地 Keycloak、可信身份、Cookie-only 会话、租户传播、RLS 与恢复重验；
M9T 增加仓库地图、Delta Context Capsule、测试选择、Evidence Cache 和 Attempt 报告；
M9 完成版本化策略、Capability、Secret/DLP、追加式审计、治理查询与 Web 证据；
M10 完成本地文档事实、ACL/RLS、pgvector 混合检索、稳定引用、Knowledge MCP、
Runtime、管理 API、Web 诊断与组合验证。

整体仍不是发布版本。固定分母中已有 24 条知识问答、6 条租户隔离、9 条治理安全和
1 条知识安全 Case 具备产品执行器，另外 116 条明确返回 `EXECUTOR_NOT_REGISTERED`；在线 Provider Smoke 和 Judge 人工校准也
没有完成。`make acceptance` 会保留全部 156 条结果并返回失败，不能把候选合入解释为
`RELEASED` 或整体 `FROZEN`。真实企业 Connector 已明确排除在 M7～M20 外，
不把“尚未接企业系统”列为本地演示产品的发布阻断。

本文件是“现在做到哪里、如何运行、还缺什么、下一步怎么走”的主入口。详细
设计仍由 ADR/架构文档负责，历史过程仍由 Chain/Handoff/Proof 负责。

## 2. 已完成并进入主分支的能力

| 增量 | 能力 | 可宣称边界 |
|---|---|---|
| M0 | 当前 16 成员 Python Workspace、Domain/Application/API/Runtime/Persistence 骨架 | 工程与端口基线，不等于完整业务产品 |
| M1 Platform | MCP Gateway、Policy、Security、审批绑定、账本与回读骨架 | 安全平台切片，不等于真实企业工具已接入 |
| M2 Studio | Worker 同源 LangGraph、Interrupt/Resume、Handoff、重试与安全投影 | 可视化调试入口，不连接生产凭据或事实源 |
| P1 | 信息补全、知识检索、租户/ACL 过滤、引用回答与稳定结果引用；VPN 为历史 Fixture | 确定性只读闭环，不包含工单写入 |
| M3 | Outbox→SSE、安全写入、审批绑定、幂等和回读 | 合成工具与安全闭环，不等于真实企业工单已接入 |
| M4 | Sandbox Provider、Context 硬预算、受限 Handoff 与多 Agent 节点 | 零凭据、零网络候选；真实模型尚未接入 |
| M5 | Fixture Web 与新员工设备/权限复合申请 | 产品交互和第二场景代码已合入，尚未接成真实本地产品 |
| M6 | 120+36 语料、Hash 冻结、Judge 校准工具、`make acceptance` 与 Ruff 收口 | 产品执行器缺失，Judge 仍为占位校准，不能报告成功率 |
| M7 | LiteLLM/Agents SDK Adapter、API/Worker/Graph/Data 组合、Web API/SSE、Studio 权威恢复、集中凭据扫描与 24 条知识问答执行器 | 开发候选已合入；132 条 Case 未注册、在线 Provider 未验证、没有一键产品启动入口 |
| M8 | 本地 Keycloak、OIDC/JWKS、Cookie-only 会话、双主体身份、可信 SecurityContext、租户传播、RLS 与真实恢复验证 | 本地候选已验收；不包含生产 IdP/HA，126 条后续 Case 未注册 |
| M9 | 版本化 Rego/OPA、Capability、Secret/DLP、追加式 Audit/Security Store、治理查询与 Web、9 条治理安全执行器 | 本地候选已验收；不包含生产 Vault/KMS/SIEM/HA，117 条后续 Case 未注册 |
| M10 | PostgreSQL/pgvector 知识事实、版本/ACL/RLS、生命周期、混合检索、稳定引用、Knowledge MCP、Runtime、API 与 Web | 本地候选已验收；116 条后续 Case 未注册，在线 Provider 与真实企业知识源未接入 |

## 3. P2 已合并能力

P2 使用最小注册链 `S6 data-recovery → S2 durable-runtime → S7
recovery-verifier → S1`，没有激活 S3/S4/S5；候选已通过用户门禁进入主分支。

已验证行为：

- Redis 清空后，从 PostgreSQL Task/Outbox 为可信 tenant 重建运行信号。
- 新 Worker 从同一 `tenant_id + task_id + thread_id` 的最新 Checkpoint 续跑。
- `run_generation` 从 1 增至 2，Checkpoint sequence 从 3 增至 6。
- 旧 Worker 成功写入 0，陈旧 CAS 成功写入 0。
- Task 终态后重建信号、节点重跑和 Checkpoint 新写入均为 0。
- 跨租户 Task/Checkpoint 成功读取为 0。
- 生产恢复入口显式使用持久化 Checkpointer；`studio-safe` 仍允许内存模式。

S7 RELEASE 证据：

| 门禁 | 结果 |
|---|---|
| P2 静态组合 | 33/33 PASS |
| 全量 Python | 265 passed |
| Platform Security | 68 passed |
| Acceptance | 89 passed |
| Integration | 60 passed |
| Contract Conformance | 20 schemas / 35 cases / 43 semantic negatives / 52 features |
| Ruff / strict Mypy | P2 范围 PASS / 89 source files PASS |
| Supply Chain | 14 wheels；pip-audit 0；Secret 0 |
| Compose | 5 healthy；RLS/恢复 PASS；清理 containers/volumes/networks 0 |

权威证据：

- [`WP-040-a7-HANDOFF.md`](../../tests/integration/evidence/WP-040-a7-HANDOFF.md)
- [`WP-040-a7-PROOF.json`](../../tests/integration/evidence/WP-040-a7-PROOF.json)
- [`CHAIN-P2-DURABLE-RUNTIME-01`](../team/chain-authorizations/CHAIN-P2-DURABLE-RUNTIME-01.md)
- [`WP-040-A7-S1-FINAL-REVIEW.md`](../review/WP-040-A7-S1-FINAL-REVIEW.md)

### M7 本地产品候选

M7 使用 `S2/S5/S6/S4/S7` 主链，并在发现凭据扫描缺口时按注册制临时加入 S3。
候选已经用户批准并以 fast-forward 进入 `master`。

- LiteLLM、OpenAI Agents SDK 与 Claude Agent SDK 均通过统一端口和离线边界测试；
  在线供应端调用保持关闭。
- API、Worker、LangGraph、PostgreSQL/Redis 与只读知识 Gateway 已有显式组合根。
- Task 初始化、Checkpoint、Lease/Fencing、历史 Resume 拒绝和终态零重放已验证。
- Web 支持 Fixture 与真实 API/SSE 两种模式；Studio 只接受权威恢复输入，并展示安全投影。
- 集中凭据注册表覆盖结构化前缀嵌入、事件构造、队列、重放、SSE 和错误输出。
- 固定分母结果为 156 条：24 通过、132 明确失败、0 跳过、0 隔离；39 项证据 Hash 闭合。

权威证据：

- [`WP-072-a1-HANDOFF.md`](../../tests/acceptance/m7/evidence/WP-072-a1-HANDOFF.md)
- [`WP-073-a1-quality-PROOF.json`](../../tests/acceptance/m7/evidence/WP-073-a1-quality-PROOF.json)
- [`WP-073-a1-release-HANDOFF.md`](../../tests/integration/evidence/WP-073-a1-release-HANDOFF.md)
- [`WP-073-a1-release-VERIFICATION.json`](../../tests/integration/evidence/WP-073-a1-release-VERIFICATION.json)

### M8 本地身份与租户候选

M8 已完成 Keycloak、身份验证、API/BFF、RLS、Runtime 传播、Web 登录体验和组合验证。
真实本地环境证明 Code+PKCE、同秒刷新、并发刷新、注销撤销、Token/JWKS 负例、Worker
恢复与跨租户拒绝；模型和工具调用均为 0。固定分母新增 6 条租户隔离执行器。

权威证据：

- [`WP-087-a1-HANDOFF.md`](../../tests/acceptance/m8/evidence/WP-087-a1-HANDOFF.md)
- [`WP-087-a1-PROOF.json`](../../tests/acceptance/m8/evidence/WP-087-a1-PROOF.json)
- [`WP-088-a1-HANDOFF.md`](../../tests/integration/evidence/WP-088-a1-HANDOFF.md)
- [`WP-088-a1-PROOF.json`](../../tests/integration/evidence/WP-088-a1-PROOF.json)

## 4. 关键架构边界

1. LangGraph 是唯一跨业务节点状态机；Task 是外部投影。
2. PostgreSQL 是 Task、Checkpoint、审批、账本与 Outbox 的事实源。
3. Redis 只保存可重建信号、缓存和限流状态。
4. Agent/Worker 不直连业务数据库、上游 MCP、企业网络或密钥。
5. 所有业务工具只经 MCP Gateway；模型不能决定授权、租户或终态。
6. 写动作必须绑定动作摘要、策略、审批、幂等键、执行账本和回读结果。
7. Trace 可采样；Audit/Security Event 不可采样且不保存隐藏思维链或密钥。
8. Provider Session、Studio Thread 和聊天上下文都不是业务 Checkpoint。

## 5. 运行与验证入口

```powershell
uv sync --all-packages --all-groups --locked
uv run --frozen python -m pytest -q
uv run --frozen python contracts/conformance/validate.py
uv run --frozen python -m pytest tests/platform -q
uv run --frozen python -m pytest tests/acceptance -q
uv run --frozen python -m pytest tests/integration -q
```

LangGraph Studio：

```powershell
make studio
make studio-smoke
```

当前 `make acceptance` 已实现。M7 已注册 24 条知识问答执行器；其余 132 条仍按设计
生成显式失败证据，因此命令返回非零状态。Windows 没有 `make.exe` 时，应运行
`uv run --frozen python -B scripts/acceptance/run_acceptance.py`，不能把编排器可运行
写成产品验收通过。

## 6. 目录与责任

| 范围 | Owner | 内容 |
|---|---|---|
| `apps/worker`、`packages/graph/runtime/context/model-gateway` | S2 | Graph、Worker、Provider 与 Context |
| `apps/mcp-gateway`、`packages/policy/security/tool-contracts`、`mcp-servers` | S3 | 工具、安全和策略 |
| `web`、`packages/evaluation/observability/retrieval`、`evals` | S4 | 体验、评测和可观测性 |
| `apps/api`、`packages/domain/application`、`domain-packs` | S5 | Domain、Use Case 与 API |
| `packages/persistence`、`migrations`、`infra` | S6 | 数据、恢复与基础设施 |
| `scripts/integration`、`tests/integration` | S7 | 独立组合与证据复现 |
| 根契约、架构、验收、路线和团队文档 | S1 | 控制面与最终裁决 |

路径细节以根目录 [`AGENTS.md`](../../AGENTS.md) 为准。

## 7. 当前缺口与后续验收

| 能力 | 当前状态 | 计划验收 |
|---|---|---|
| Provider 与产品运行链 | M7 Adapter、产品组合、Web API/SSE 与 24 条知识执行器已合入；在线供应端未验证 | 后续里程碑补一键产品入口，并在明确授权后运行 DeepSeek V4 Flash Smoke |
| 身份、租户与 RLS | M8 本地 Keycloak、可信 SecurityContext、租户传播、RLS 与恢复组合已验收 | 后续只做本地产品整合；生产 IdP/HA 不在本路线 |
| 策略、DLP 与审计 | M9 本地 Rego、Capability、DLP、追加式审计和治理查询已通过组合验证 | 生产 Vault/KMS/SIEM/HA 不在本地路线；后续场景复用现有治理边界 |
| 知识检索 | M10 已完成本地导入、文档版本、ACL/RLS、混合检索、生命周期、稳定引用与诊断入口 | M14 收口面向员工的知识问答、反馈和转工单业务体验 |
| Context | 硬预算、摘要和 Handoff 过滤已有机制 | M11～M13 分别完成短期记忆、长期记忆和用户画像 |
| 业务场景 | 历史知识样例与新员工候选已有代码 | M14～M18 完成五条 Web 可操作业务链 |
| 120+36 | 156 条固定分母已运行；40 通过、116 因无执行器明确失败 | M11～M18 随能力增量注册执行器，M19 完成五链报告与 Judge 校准 |
| `make acceptance` | 可生成完整 Bundle 和 39 项 Hash 闭包；当前 Gate 为 fail | M19 产出可复现且满足发布门槛的产品报告 |
| 安全多模态 | 隔离与 Observation 契约已有设计项 | M20 完成隔离、扫描、脱敏、注入检测和只读 Agent |
| 全仓 Ruff | M6 收口时为零 Finding | 后续增量保持零新增 Finding |

Traceability 当前仍保持 `DESIGNED`，因为 Feature 提升需要其规定路径下的正式
Evidence Artifact，而不是只依赖分支测试结论。不得提前宣传性能或成功率数字。

## 8. 后续交付计划

M8、M9、M10 候选与 M9T 工程控制面已经完成验收。M11 短期记忆已激活；
M12～M20 尚未启动：

```text
M7 真实 Provider 与本地运行链
 → M8 本地身份与租户
 → M9 本地策略、密钥与 DLP
 → M10 本地知识平台
 → M11 短期记忆
 → M12 长期记忆
 → M13 用户画像
      ├→ M14 知识库问答 → M15 智能工单 ─┐
      └→ M16 新员工入职 → M17 权限变更 ─┤
                                           ↓
                                          M18 审批辅助
                                           ↓
                                          M19 五链集成与 120+36
                                           ↓
                                          M20 安全多模态
```

M7 的 WP-070～WP-073、M8 的 WP-080～WP-088、M9T 的 WP-090～WP-094 和
M9 的 WP-100～WP-109 已完成。
M10 使用 `CHAIN-M10-KNOWLEDGE-01` 和 WP-110～WP-120，所有工作包均已完成并合入。
M11 使用 `CHAIN-M11-SHORT-TERM-MEMORY-01` 和 WP-121～WP-129；控制面已激活，S3/WP-122
已就绪但尚未派发，用户明确唤醒后才取得写租约；其余角色等待精确线性 Head。
固定分母 Gate 继续保持失败，直到后续里程碑为其余业务与安全 Case 提供产品执行器。
M9 的工程控制面只记录开发范围和证据，不参与产品授权。

M8 启动前的 WP-037 工程契约已完成：S1～S7 作为领域主 Agent，默认使用 `DELTA`
热启动，并可在有效工作包内自主调用临时子 Agent。子任务使用最小 Context Capsule、
稳定 `TASK_DEDUP_KEY` 和单写者规则；相关 Blob 与证据未变化时复用结论，不重复读取
或复现。同类问题重复出现时转为共享机理与数据驱动回归，不继续堆叠样本补丁。

M7～M13 是平台主链。M13 后两条业务轨道可以使用互斥路径并行，之后统一进入
审批辅助、产品评测和多模态。真实 Jira/ServiceNow/CMDB/HR/IAM、企业
Vault/KMS/SIEM、生产高可用、跨地域部署、采购领域包和 LoRA 不在本路线范围。

详细交付项、退出条件、拆包和时间估计见
[`IMPLEMENTATION_PLAN.md`](./IMPLEMENTATION_PLAN.md)。

## 9. 协作与恢复

- 新链只注册覆盖目标所需的最小 Agent 集合，未选择会话不接收消息。
- 长期任务默认使用 Git Base→Target 的 `DELTA` Context，不全量重读未变化文档。
- 领域主 Agent 可自主调用临时子 Agent；子 Agent 不拥有 Git、跨会话唤醒或裁决权。
- 正常链只在完成、P0/P1、范围请求和用户门禁发送事件。
- S7 只在垂直候选汇合时运行门禁；S1/用户保留合并与发布裁决。
- 聊天中断不丢状态：以 Work Package、Git Head、Handoff/Proof Hash 为准恢复。

## 10. 文档清理说明

当前文档结构只保留一个现状入口和一个实施路线。已经完成且被主分支、Chain、
Handoff 和 Proof 覆盖的 M3～M6 加速规划不再保留独立副本，避免继续误导派发。
本文件、工作包索引和 Chain Authority 分别承担“项目现状、任务状态、历史证据”。

以下内容不是冗余，必须保留：ContractSet/Review Attestation、ADR、Migration、
已接受 Chain Authorization、Handoff、Proof、安全负例和原始方案历史输入。
