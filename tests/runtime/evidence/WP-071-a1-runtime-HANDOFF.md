# WP-071-a1-runtime S2-RUNTIME 产品组合交接

## 基本信息

- Work Package：WP-071
- Attempt ID：WP-071-a1-runtime
- Chain ID：CHAIN-M7-LOCAL-PRODUCT-01
- Step ID：M7-07-S2-RUNTIME-COMPOSITION
- 责任会话：S2-RUNTIME
- 下一责任会话：S2-RUNTIME（WP-072 Studio 安全投影）
- 交接策略：预授权链内连续执行
- 功能 ID：FP-FLOW-001、FP-FLOW-005、FP-OBS-001、FP-OPS-001
- 基线提交：`0c1a7a175a1c2cc6772a0d4f2536a9601bf495ef`
- 分支：`codex/s2/wp-070-provider-runtime-adapters`
- 最终提交：本文件所在提交；精确 SHA 由后续唤醒信封返回
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：PASS_HANDOFF

## 完成内容

- 消费 S5/S6 的正式 Application/Data 组合边界：创建现有
  `PostgresDataUnitOfWorkFactory`，调用
  `compose_application_unit_of_work_factories`，把 Command、Task Query、
  Task Event 三类收窄 UoW 分别注入 S5 `create_product_app`。
- API CREATE 只在 Tx-A 原子初始化完整 Task v0、version=-1 命令槽和
  StoredCommand；Tx-A 不发布业务事件。Worker Tx-B 通过同一持久化 UoW
  原子提交首 Checkpoint 与唯一 `task.created.v1` Outbox。
- 原始 Data UoW 继续供 Durable Worker、Checkpoint/Lease/Fencing 与
  `CoordinationRebuilder` 使用；Redis 仅保存可重建协调信号，不是事实源。
- 注入 S2 `RuntimeExecutionAdapter` 与调用方提供的可信
  `RequestSecurityPort`、`TaskInitializationConfig`、服务端
  `ThreadIdFactory`；浏览器 Tenant/Header 不参与可信主体或租户推导。
- 新增正式企业知识问答 LangGraph：
  `prepare -> resolve/clarify interrupt -> knowledge + service_read(skip) -> join
  -> context rebuild -> model -> artifact -> terminal`。VPN 仅保留为历史回归
  Fixture，不进入产品路由。
- 知识检索只消费 S3 `GatewayClientPort`，不直连 Knowledge MCP Adapter；请求、
  策略、租户、用途、分类、幂等键与结果回执逐项回绑，`UNKNOWN` 失败关闭，
  可重试故障按稳定状态恢复。
- 模型调用只消费 `AgentRuntimePort` 和逻辑模型 `flowpilot.primary.fast`；Tool、
  Handoff 和 Tool-call 引用全部为空，模型不能决定授权、租户、终态或业务工具
  成功。
- 问题与脱敏知识摘要只进入临时 `ContextEnvelope`；Graph Checkpoint、Outbox、
  Result Artifact 只保存最小引用、计数与受控答案，不保存请求正文、知识摘要、
  ACL、凭据、隐藏思维链或 Provider Session。
- 覆盖正常、澄清 Interrupt、重复 Command、Worker 重建/Provider 重试、错误租户
  来源和正式 PostgreSQL 组合根等路径。

## 未完成与非目标

- 未运行真实在线 Provider Smoke；它继续要求显式开关、隔离凭据和成本授权。
  本 Attempt 未读取真实密钥、未产生网络或付费 Provider 调用。
- 未修改公共 Contract、Migration、S3 安全边界、S5/S6 实现、共享依赖、
  `pyproject.toml`、`uv.lock`、`Makefile` 或根配置。
- WP-072 的 Studio 安全投影与可视化调试将在本链下一 Step 完成；本交接不把
  业务 Context 或答案正文暴露给 Studio。

## 修改文件

| 文件 | 变化 |
|---|---|
| `apps/worker/src/flowpilot_worker/composition.py` | 正式 API/Application/Data/Worker 产品组合根 |
| `apps/worker/src/flowpilot_worker/knowledge.py` | 企业知识问答 Graph 与 Durable Graph Factory |
| `apps/worker/src/flowpilot_worker/durable.py` | Checkpoint Adapter 注入 Task Event Publisher，建立 Worker Tx-B 原子边界 |
| `apps/worker/src/flowpilot_worker/__init__.py` | 导出正式产品组合与知识图接口 |
| `tests/runtime/integration/test_m7_product_runtime.py` | 产品链、恢复、重复、Interrupt、跨租户与 PostgreSQL 组合测试 |
| `tests/runtime/evidence/WP-071-a1-runtime-HANDOFF.md` | 本交接证据 |

## 契约、数据库与配置变化

- 公共契约：无修改；ContractSet 摘要保持不变。
- 数据库与 Migration：无修改；只消费 S6 已接受的 Port/Factory。
- 共享文件与依赖：无修改、无新增依赖。
- 配置：产品 Graph 失败关闭校验 Graph/Domain/Context/Policy/Tool Set Release、
  Provider、知识 Schema Pin 和预算；在线 Provider 默认关闭。

## 验证

| 命令 | 结果 |
|---|---|
| `uv build --package flowpilot-worker --wheel` | PASS；生成 `flowpilot_worker-0.1.0-py3-none-any.whl` |
| `.\\scripts\\quality.ps1 lint` | PASS；Ruff、strict Mypy 124 source files |
| `uv run --all-packages --all-groups --locked python -B -m pytest tests/runtime -q` | PASS；195 passed、1 explicit online skip |
| `.\\scripts\\quality.ps1 test-all` | PASS；846 passed、1 explicit online skip |
| `.\\scripts\\quality.ps1 test-security` | PASS；116 passed |
| `.\\scripts\\quality.ps1 audit` | PASS；0 known vulnerabilities；editable Workspace 包按入口定义跳过 |
| `git diff --check`、范围/直连/Secret 扫描 | PASS；仅 S2 授权路径，直连与高置信密钥 0 |

Contract Conformance：

```text
CONTRACT_CONFORMANCE_OK schemas=20 cases=35 positive=18 negative=17 mutation_cases=19 mutation_positive=3 mutation_negative=16 semantic_cases=43 semantic_positive=0 semantic_negative=43 audit_chain_cases=5 audit_chain_positive=1 audit_chain_negative=4 manifest_cases=21 manifest_positive=1 manifest_negative=20 review_attestation_cases=10 review_attestation_positive=2 review_attestation_negative=8 retired_review_attestation_cases=5 retired_review_attestation_positive=0 retired_review_attestation_negative=5 features=52
```

## 安全、失败与恢复证据

- 伪造浏览器租户在 Task、Queue、Gateway 和模型调用前失败关闭；跨租户成功读写
  数为 0。
- 缺少问题时先进入 LangGraph Interrupt，知识与模型调用数均为 0。
- 重复 Command 不重复分配 Thread、不重复入队；Provider 可重试失败后以新 Worker
  从 Checkpoint 恢复，知识逻辑执行仍为 1，`task.created.v1` 保持唯一。
- 错租户知识引用在模型与 Artifact 前失败关闭；Gateway 回执漂移、分类越级、
  `UNKNOWN`、不可信 source prefix 均由确定性校验拒绝。
- Checkpoint/Outbox 不含问题、知识摘要、Provider Session、ACL、凭据或隐藏思维链。

## 已知风险

- P2：真实在线 Provider Smoke 未运行；这是安全与成本策略，不阻断离线产品组合。
- P2：本地组合与确定性 Fake 不代表生产 OIDC、HA、TLS、备份或真实 Provider
  可用性；真实 OIDC 属于 M8。
- P3：Studio 当前仍只提供既有安全投影；WP-072 将把正式产品图拓扑、恢复状态和
  受控计数可视化，同时继续禁止正文、ACL、凭据与隐藏思维链。

## 学习候选

```text
LEARNING_CANDIDATE=none
```

## 下一步

1. 以本提交为 WP-072 精确基线，继续 `M7-08-S2-STUDIO-PROJECTION`，不重新加载
   未变化基线。
2. 将正式产品 Graph 暴露为稳定 Studio Graph ID，并提供拓扑、Interrupt、恢复、
   知识调用数、引用数和终态的安全投影；不得暴露问题/答案正文、知识摘要、ACL、
   凭据、Provider Session 或隐藏思维链。
3. 正常完成后把精确 Head 和 Handoff 交给 S4-QUALITY；P0/P1、契约/S3 边界、
   越权路径、门禁失败或未授权外部调用立即停链上报 S1。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M7-LOCAL-PRODUCT-01
STEP_ID=M7-07-S2-RUNTIME-COMPOSITION
ATTEMPT_ID=WP-071-a1-runtime
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=0c1a7a175a1c2cc6772a0d4f2536a9601bf495ef
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/runtime/evidence/WP-071-a1-runtime-HANDOFF.md
NEXT_ROLE=S2-RUNTIME
NEXT_ATTEMPT_ID=WP-072-a1-runtime
ESCALATE_TO_S1=no
```

## 可回滚方式

- Revert 本 Handoff 所在提交；禁止 reset、rebase 或 force-push。
