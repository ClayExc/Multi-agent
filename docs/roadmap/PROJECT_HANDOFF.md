# FlowPilot 项目交接总览

## 1. 当前结论

```text
SNAPSHOT=M6_FREEZE_COMPLETE
STATUS=MERGED_M6_FREEZE_COMPLETE
S7_HEAD=0b1d6ba3aa31536d9170027f0981c0e626b71f35
MERGED_CANDIDATE_HEAD=1b021a9
CONTRACT_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
RELEASED=false
FROZEN=false
```

FlowPilot 已将 M0～M6 工程候选合入主分支：公共契约与 14 包 Python Workspace、
安全 MCP 平台、PostgreSQL/RLS/Inbox/Outbox/Lease/Checkpoint、LangGraph Studio、
VPN 只读与安全写入、Context/Handoff、新员工复合申请、Fixture Web，以及 120 条
功能任务和 36 条安全/故障任务的版本化语料与 Hash 冻结。

整体仍不是发布版本。真实 Provider、Web/API/Worker/数据平面的完整产品装配、真实
企业 Connector 和 156 条任务的产品执行器尚未完成；Judge 校准仍是
`placeholder_proxy`。`make acceptance` 已实现，但缺少产品执行器时会保留全部失败
并返回非零状态。这里的 `M6_FREEZE_COMPLETE` 只表示 M6 语料与工具链候选已收口，
不表示 `RELEASED` 或整体 `FROZEN`。

本文件是“现在做到哪里、如何运行、还缺什么、下一步怎么走”的主入口。详细
设计仍由 ADR/架构文档负责，历史过程仍由 Chain/Handoff/Proof 负责。

## 2. 已完成并进入主分支的能力

| 增量 | 能力 | 可宣称边界 |
|---|---|---|
| M0 | 14 包 Python Workspace、Domain/Application/API/Runtime/Persistence 骨架 | 工程与端口基线，不等于完整业务产品 |
| M1 Platform | MCP Gateway、Policy、Security、审批绑定、账本与回读骨架 | 安全平台切片，不等于真实企业工具已接入 |
| M2 Studio | Worker 同源 LangGraph、Interrupt/Resume、Handoff、重试与安全投影 | 可视化调试入口，不连接生产凭据或事实源 |
| P1 | VPN 信息补全、知识检索、租户/ACL 过滤、引用回答与稳定结果引用 | 确定性只读闭环，不包含工单写入 |
| M3 | Outbox→SSE、VPN 安全写入、审批绑定、幂等和回读 | 合成工具与安全闭环，不等于真实企业工单已接入 |
| M4 | Sandbox Provider、Context 硬预算、受限 Handoff 与多 Agent 节点 | 零凭据、零网络候选；真实模型尚未接入 |
| M5 | Fixture Web 与新员工设备/权限复合申请 | 产品交互和第二场景代码已合入，尚未接成真实本地产品 |
| M6 | 120+36 语料、Hash 冻结、Judge 校准工具、`make acceptance` 与 Ruff 收口 | 产品执行器缺失，Judge 仍为占位校准，不能报告成功率 |

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

当前 `make acceptance` 已实现。它会在缺少产品执行器时按设计生成失败证据并返回
非零状态。Windows 没有 `make.exe` 时，应运行
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

| 能力 | 当前状态 | 下一验收 |
|---|---|---|
| Outbox→SSE | 发布与重连代码已合入 | M7 接入真实 API/Worker 运行链并完成产品级复核 |
| VPN 安全工单写入 | 审批、账本、幂等和回读候选已合入 | M8 接入 Ticket Connector 并完成黑盒安全验收 |
| Provider Adapter | Sandbox Adapter 已合入，零凭据、零网络 | M7 接入首个真实 Provider |
| Context 预算与受限 Handoff | 机制、硬预算和过滤测试已合入 | M7/M10 生成真实 Token 与消融报告 |
| 真实模型 Provider | 未实现 | M7 接入 LiteLLM + DeepSeek V4 Flash；确定性验收不依赖在线模型 |
| Multi-Agent/Context 量化 | 机制和测试已合入 | M7/M10 运行真实 Token、预算与消融报告 |
| Web 产品面 | Fixture Web、审批卡、时间线与 SSE 交互已合入 | M7 接通 FastAPI、Worker、LangGraph 与数据平面 |
| 新员工复合申请 | 澄清、并行读取、双动作和部分失败测试已合入 | M9 完成真实 API/Web 连续操作与恢复验收 |
| 120+36 | 三个数据集共 156 条 Case，M6 Hash 冻结文件已合入 | M10 注册产品执行器；Contract Registry 仍不得提前提升为发布状态 |
| `make acceptance` | 编排器、六类测试收集、失败保留、Bundle/REPORT 已实现 | M10 用真实产品执行器完成 156 条固定分母运行 |
| Judge 校准 | 盲测工具和绑定校验已实现，当前基线为 `placeholder_proxy` | M10 完成双轮人工校准和 Promotion Gate |
| 全仓 Ruff | **已清零**（M6-3，All checks passed） | 后续增量继续维持零新增 Finding |
| 多模态与 LoRA | 未开始 | 不进入当前核心交付窗口 |

Traceability 当前仍保持 `DESIGNED`，因为 Feature 提升需要其规定路径下的正式
Evidence Artifact，而不是只依赖分支测试结论。不得提前宣传性能或成功率数字。

## 8. 后续交付计划

当前执行窗口改为 M7～M10：

```text
M7  LiteLLM + DeepSeek V4 Flash，并接通本地产品只读链路
 -> M8  VPN 审批与安全工单写入
 -> M9  新员工设备/权限复合申请
 -> M10 120+36 产品执行、Judge 校准与发布候选门禁
```

M7 先解决“模块很多但用户无法连续操作”的问题；M8、M9 分别收口两条业务
链路；M10 才运行正式产品执行器并产生可对外使用的指标。真实企业 Connector
可以预先完成 Vendor-neutral Port、Schema 和 Sandbox/Preview，但首个窗口不要求
写满所有厂商适配器。安全多模态与路由 LoRA 顺延为 M11、M12。

详细退出条件见 [`IMPLEMENTATION_PLAN.md`](./IMPLEMENTATION_PLAN.md)。M3～M6 的
并行建设记录继续保留在
[`ACCELERATED_DELIVERY_PLAN.md`](./ACCELERATED_DELIVERY_PLAN.md)，不再作为当前
派发计划。

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
