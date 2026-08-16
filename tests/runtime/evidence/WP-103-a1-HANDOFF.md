# WP-103-a1 S2-RUNTIME 模型边界 DLP 交接

## 基本信息

- Work Package：WP-103
- Attempt ID：WP-103-a1
- Chain ID：CHAIN-M9-GOVERNANCE-01
- Step ID：M9-03-S2-RUNTIME-DLP
- 责任会话：S2-RUNTIME
- 接收会话：S5-CORE
- 交接策略：CONSUMER_GATE
- 功能 ID：FP-SEC-005、FP-SEC-006、FP-OPS-003
- 基线提交：`6669b4371b494cd17c77a2c1fa7984696017e6ae`
- 分支：`codex/s2/wp-103-m9-runtime-dlp`
- 最终提交：本文件所在提交；精确 SHA 由交接响应返回
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：PASS_HANDOFF

## 完成内容

- Context Builder 在完整 Provider Context、Conversation Summary、Handoff 来源与重建
  Bundle 边界调用 S3 `assert_content_safe`；危险内容只返回稳定、无原值的 Context 错误。
- Agent Runtime 的 Fake、Sandbox、OpenAI Agents SDK 与 Claude Agent SDK Adapter 在
  Provider 调用前扫描 Context，在接受 structured output、公开摘要和 Tool Proposal
  arguments/resources 前重新扫描；阻断结果不携带输出、Provider Session 或危险原值。
- Model Gateway 在记录逻辑调用及调用 Provider 前扫描输入，在构造 ModelResult 前扫描
  Provider 输出与 Tool Proposal；LiteLLM 与确定性 Sandbox Provider 同时执行边界检查，
  输入拒绝时真实/模拟 Transport 调用均为 0。
- Worker 对自定义 Agent Runtime 返回与 Knowledge ToolResult 再做防御性扫描，确保绕过
  Adapter 的实现不能把危险内容写入 Artifact、Checkpoint、Outbox 或 Graph 终态。
- 仅复用 S3 `ContentSurface`、`assert_content_safe`、`SecurityErrorCode` 与集中规则；没有
  复制 Credential、Prompt-Injection 注册表、正则或危险样本保留逻辑。
- 新增正常回归、Secret/Prompt-Injection 阻断、Summary/Handoff、两种 SDK、公开摘要、
  Model Gateway 输入/输出/Tool Resource、Worker Artifact/Checkpoint 以及 Interrupt/Resume
  重投测试。重复 Command 在队列幂等层被丢弃，模型调用保持恰好 1 次。
- 同步迁移 Runtime 恢复测试的 WP-102 Capability Fixture：完整绑定
  context/tool/resource/policy/execution/use/token hash，并对 invoke/readback 分别原子
  consume；没有添加 legacy 或可选字段降级。

## 未完成与非目标

- 未修改 S3 内容规则、Policy、MCP Gateway、公共 Contract、应用 API、数据库、Web、
  Migration、Compose 或生产 Provider 配置。
- 在线 Provider Smoke 保持显式关闭；真实凭据读取、外部网络与付费调用均为 0。
- 未修改 `pyproject.toml`、`uv.lock` 或 `Makefile`。`flowpilot-security` 已在锁定 Workspace
  中可用且本轮未新增外部依赖；S5 WP-104 按其授权继续完成 Workspace/Lock/Wheel 闭包。

## 修改文件

| 文件/目录 | 变化 | 所有者 |
|---|---|---|
| `packages/context/**` | Context、Summary、Handoff 集中内容安全门禁与稳定错误 | S2-RUNTIME |
| `packages/agent-runtime/**` | 请求、输出、公开摘要和 Tool Proposal DLP；Adapter 错误映射 | S2-RUNTIME |
| `packages/model-gateway/**` | Provider 输入/输出/Tool Proposal 门禁与稳定 Gateway 错误 | S2-RUNTIME |
| `apps/worker/**` | RuntimeResult 与 Knowledge ToolResult 写入前防御性复核 | S2-RUNTIME |
| `tests/runtime/**` | M9 DLP、Worker 恢复、既有错误码和 WP-102 Capability Fixture 回归 | S2-RUNTIME |
| `tests/runtime/evidence/WP-103-a1-HANDOFF.md` | 本交接证据 | S2-RUNTIME |

## 契约、数据库与配置变化

- 契约版本、Schema 与 ContractSet：无变化；Conformance PASS。
- Migration、PostgreSQL/Redis、Checkpoint Schema：无变化。
- 环境变量、Provider 配置、Workspace 依赖和锁：无变化。
- 内部兼容性：新增 `MODEL_CONTENT_BLOCKED` / `CONTENT_BLOCKED` 内部错误映射；公共 JSON
  Contract 未变化。凭据型模型内容从旧的通用 invalid/scope 失败提升为稳定 guardrail 阻断。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| `PYTHONPATH=. uv run --all-packages --all-groups --locked python -B -m pytest tests/runtime -q` | PASS | 278 passed，1 个显式 online Provider skip |
| `uv run ... ruff check apps/worker/src packages/context/src packages/agent-runtime/src packages/model-gateway/src tests/runtime` | PASS | All checks passed |
| `uv run ... mypy --strict apps/worker/src packages/context/src packages/agent-runtime/src packages/model-gateway/src` | PASS | 33 source files，0 issues |
| `uv run ... python -B contracts/conformance/validate.py` | PASS | 20 schemas / 35 cases / 43 semantic cases / 52 features |
| `uv run ... pytest tests/experience/test_secret_scan.py -q` | PASS | 2 passed |
| `git diff --check` | PASS | 无 whitespace error |

## 安全与失败路径

- Provider 输入 Secret/Prompt Injection：在 Gateway/SDK Transport 调用前拒绝，调用数 0。
- Provider 输出、公开摘要和 Tool Proposal resource：调用后、业务结果前拒绝；结果、错误、
  Trace 投影中危险原值为 0。
- Worker 自定义 Runtime 输出：Artifact 调用为 0，Checkpoint/Outbox/Graph Outcome 不含
  Secret 或危险文本。
- Interrupt/Resume 后危险输出：终态失败；相同 Command 重投不生成新 Checkpoint，模型
  调用保持 1 次。
- Provider 不可用、预算、路由与既有 Session 边界回归保持通过；在线 Smoke 未启用。
- Secret/PII：仅使用运行时拼接的合成凭据；Secret Scan PASS，真实 Token/PII/隐藏思维链
  读取、记录和持久化均为 0。

## 已知问题

- P2：直接运行 `uv run pytest tests/runtime` 时，两个既有测试要求仓库根位于模块搜索
  路径；最终门禁使用 `PYTHONPATH=.` 后 278/1 全量通过，未修改共享测试入口。
- P2：本步骤不做独立 Wheel 安装闭包；S5 WP-104 已获授权执行 Workspace/Lock/Wheel
  收口。没有新增第三方依赖或锁变化。

## 已知事实与避免重复

- `KNOWN_FACTS`：WP-101/WP-102 的集中 DLP、Capability 与 Secret Provider 已通过生产者
  和共享 Security 门禁；本步骤只消费公开安全 Port。
- `DO_NOT_RECHECK`：未重跑 OPA、MCP Gateway、S3 424 条平台测试、数据库、Web、Compose
  或在线 Provider。
- `FAILURE_SIGNATURES`：`RUNTIME_ROOT_IMPORT_PATH`——未设置仓库根模块路径时两个既有
  Runtime 测试收集失败；显式 `PYTHONPATH=.` 后全套通过。
- `REUSED_DECISIONS`：WP-101/WP-102 Handoff、S3 集中 `ContentSurface` 映射、M7 Provider
  Session 边界、M8 当前身份与 P2 Durable Recovery。
- `DUPLICATE_WORK_AVOIDED`：复用 2 份 S3 Handoff、1 份生产者 Handoff、1 份 S4 Fixture
  Handoff 和既有 Runtime/Provider/恢复测试；未重新审计无关目录。

## 学习候选

```text
LEARNING_CANDIDATE=Content safety must run at value-object consumers, not constructors
MATURITY=VERIFIED
TRIGGER=Wire dataclass 构造期拒绝使调用边界的零 Transport 断言不可观测，并抢先改变既有错误语义
MECHANISM=值对象保持可构造；Provider/Gateway/Runtime 在实际消费和持久化前使用同一集中注册表失败关闭
STRUCTURE=central scanner -> boundary-specific stable error -> no raw value -> call/write count assertion
EVIDENCE=WP-103 Runtime 278 passed；输入拒绝 Transport=0，输出拒绝 Artifact/Checkpoint=0
RESIDUAL_RISK=新增消费者必须显式接入集中扫描，不能依赖对象构造副作用
TARGET=ENGINEERING_PLAYBOOK model-boundary safety candidate
```

## 子 Agent 使用摘要

```text
SUBAGENTS_USED=0
SUBAGENT_MODES=none
SUBAGENT_TASKS=none
SUBAGENT_WRITERS=0
PARENT_REPRODUCED_RESULTS=yes
REUSED_DECISIONS=WP-101,WP-102,M7-provider,M8-identity,P2-recovery
DUPLICATE_WORK_AVOIDED=4
```

## 接收会话下一步

1. S5 核对精确 `NEW_HEAD`、本 Handoff SHA256、ContractSet、基线祖先、授权路径与 clean
   状态，只用 `--ff-only` 消费本提交。
2. 执行 WP-104 治理查询 Port/API，并按其单一写入授权完成 Workspace/Lock/Wheel 收口；
   不复制 S3 内容规则，也不得把危险 Rego/Prompt/参数/结果写入 API 投影。
3. 正常 PASS 后按链唤醒 S6 WP-105；只有 P0/P1、契约、安全边界或越权变化回到 S1。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M9-GOVERNANCE-01
STEP_ID=M9-03-S2-RUNTIME-DLP
ATTEMPT_ID=WP-103-a1
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=6669b4371b494cd17c77a2c1fa7984696017e6ae
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/runtime/evidence/WP-103-a1-HANDOFF.md
NEXT_ROLE=S5-CORE
NEXT_ATTEMPT_ID=WP-104-a1
ESCALATE_TO_S1=no
SUBAGENTS_USED=0
```

## 可回滚方式

- 仅按正常 Git 流程 revert 本 Attempt 提交；禁止 reset、rebase 或 force-push。
