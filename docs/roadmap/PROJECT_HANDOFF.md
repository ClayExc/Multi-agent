# FlowPilot 项目交接总览

## 1. 当前结论

```text
SNAPSHOT=FLOW_LITE_TRIPLE_MERGED
STATUS=MERGED_FLOW_LITE_TRIPLE
S7_HEAD=0b1d6ba3aa31536d9170027f0981c0e626b71f35
MERGED_CANDIDATE_HEAD=613118c
CONTRACT_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
RELEASED=false
FROZEN=false
```

FlowPilot 已完成企业 Agent 平台的公共契约、领域与应用骨架、安全 MCP 平台、
PostgreSQL/RLS/Inbox/Outbox/Lease/Checkpoint、LangGraph Studio 非黑箱入口、VPN
确定性只读闭环，以及 P2 持久化恢复候选。真实 Provider、安全工单写入、Web、
第二业务场景和 120+36 冻结评测尚未完成。

本文件是“现在做到哪里、如何运行、还缺什么、下一步怎么走”的主入口。详细
设计仍由 ADR/架构文档负责，历史过程仍由 Chain/Handoff/Proof 负责。

## 2. 已完成并进入主分支的能力

| 增量 | 能力 | 可宣称边界 |
|---|---|---|
| M0 | 14 包 Python Workspace、Domain/Application/API/Runtime/Persistence 骨架 | 工程与端口基线，不等于完整业务产品 |
| M1 Platform | MCP Gateway、Policy、Security、审批绑定、账本与回读骨架 | 安全平台切片，不等于真实企业工具已接入 |
| M2 Studio | Worker 同源 LangGraph、Interrupt/Resume、Handoff、重试与安全投影 | 可视化调试入口，不连接生产凭据或事实源 |
| P1 | VPN 信息补全、知识检索、租户/ACL 过滤、引用回答与稳定结果引用 | 确定性只读闭环，不包含工单写入 |

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

当前 `make acceptance` 尚未实现。Windows 没有 `make.exe` 时，应执行 Makefile
对应的锁定底层命令并如实标记入口 `NOT_RUN/NOT_IMPLEMENTED`，不能伪装通过。

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

## 7. 尚未完成

| 能力 | 当前状态 | 下一验收 |
|---|---|---|
| Outbox→SSE | **已合入 master**（flow-lite g1，2026-08-01） | S4/S7 独立复核后 FP-DATA-003 升 VERIFIED |
| VPN 安全工单写入 | **已合入 master**（flow-lite g2，2026-08-01） | S4 黑盒复核后 FP-MCP/APR 系列升 VERIFIED；真实 Ticket MCP 接入 |
| 评测候选语料 | **已合入 master**（flow-lite g3，69 条候选登记） | 120+36 冻结前转正式 Case 集 |
| 真实 OpenAI/Claude Provider | 未实现 | 至少一个真实 Adapter；确定性验收不依赖其在线 |
| Multi-Agent/Context 优化 | 设计与骨架 | 受限 Handoff、预算、消融与真实 Token 报告 |
| Web 产品面 | 未实现 | Task/Timeline/补全/审批/证据面板 |
| 新员工复合申请 | 未实现 | `AC-E2E-002`、多动作、重启和部分失败 |
| 120+36 | Registry/Runner 骨架 | 固定 Case、数据卡、Hash、失败保留和 Judge 校准 |
| `make acceptance` | 未实现 | 一条命令生成机器 Manifest 与人类报告 |
| 全仓 Ruff | 29 个继承 finding | 对应 Owner 分批清零，不阻断 P2 |
| 多模态与 LoRA | 未开始 | 不进入当前核心交付窗口 |

Traceability 当前仍保持 `DESIGNED`，因为 Feature 提升需要其规定路径下的正式
Evidence Artifact，而不是只依赖分支测试结论。不得提前宣传性能或成功率数字。

## 8. 后续交付计划

P2 用户合并后，建议目标窗口为 15～25 个有效工作日：

```text
P2 final
  -> g2 SSE
  -> g3 安全写入
  -> M4 Provider / Multi-Agent / Context
  -> M5 Web + 新员工复合申请
  -> M6 120+36 freeze
```

并行轨道：

- `evaluation-curator`：M3～M5 分批构建 48+21、40+12、32+3 条候选，M6
  冻结为 120+36。
- `experience-builder`：API/SSE 契约稳定后实现 Web 外壳，M5 接第二场景。
- `connector-preview`：只做 Vendor-neutral Port、Sandbox Adapter、Schema 和
  契约测试，不连接生产系统或凭据。

完整计划见
[`ACCELERATED_DELIVERY_PLAN.md`](./ACCELERATED_DELIVERY_PLAN.md)。
`g2/g3` 仍需要各自用户门禁，本文件不构成自动批准。

## 9. 协作与恢复

- 新链只注册覆盖目标所需的最小 Agent 集合，未选择会话不接收消息。
- 长期任务默认使用 Git Base→Target 的 `DELTA` Context，不全量重读未变化文档。
- 正常链只在完成、P0/P1、范围请求和用户门禁发送事件。
- S7 只在垂直候选汇合时运行门禁；S1/用户保留合并与发布裁决。
- 聊天中断不丢状态：以 Work Package、Git Head、Handoff/Proof Hash 为准恢复。

## 10. 文档清理说明

本次收口删除了强制上下文中重复的逐提交历史、过时的固定 S8/S9/S10 扩容
建议和已完成基线的冗长启动说明，改由本文件、工作包索引和 Chain Authority
分别承担“当前状态、任务状态、历史证据”。

以下内容不是冗余，必须保留：ContractSet/Review Attestation、ADR、Migration、
已接受 Chain Authorization、Handoff、Proof、安全负例和原始方案历史输入。
