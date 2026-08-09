# WP-072-a1-runtime S2-RUNTIME Studio 安全投影交接

## 基本信息

- Work Package：WP-072
- Attempt ID：WP-072-a1-runtime
- Chain ID：CHAIN-M7-LOCAL-PRODUCT-01
- Step ID：M7-08-S2-STUDIO-PROJECTION
- 责任会话：S2-RUNTIME
- 接收会话：S4-QUALITY
- 交接策略：CONSUMER_GATE
- 功能 ID：FP-FLOW-002、FP-FLOW-004、FP-OBS-001、FP-OBS-002
- 基线提交：`3c27f1a57c63782a2062aad7793811bae15cb7cf`
- 分支：`codex/s2/wp-070-provider-runtime-adapters`
- 最终提交：本文件所在提交；精确 SHA 由唤醒信封返回
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：PASS_HANDOFF

## 完成内容

- 保持根 `langgraph.json` 的稳定 Graph ID `flowpilot_it_service` 与
  `flowpilot_worker/studio.py:graph` 入口不变；本地 LangGraph Agent Server 可直接
  装载并显示正式产品同源拓扑。
- 将 Studio 默认场景切换为 `knowledge_demo`，绑定正式
  `flowpilot.enterprise-knowledge.m7.v1` / `knowledge_question`；VPN 与旧
  `full_demo` 只保留为显式历史回归，不参与默认产品路由。
- 新增 `product_debug_projection`，在 default-deny 基线之上只增加：稳定 Graph/
  Intent/Actor、5 阶段进度、模型调用数、引用/产物计数和恢复标志。
- 五阶段固定为 Intake、Interrupt、Knowledge、Model、Terminal；在
  Clarification Interrupt 尚未恢复时即可看到 `2/5`，恢复后进度单调到 `5/5`，
  避免重启或恢复后只看到文件变化而不知道 Graph 正处于哪一阶段。
- 默认演示执行：Clarification -> 并行 knowledge/service-read(skip) -> join ->
  Context/Tool Scope rebuild -> 模型可重试 -> terminal；知识调用数保持 1，模型
  调用数与重试一致，引用/Artifact 只显示计数。
- 增加 Provider timeout 与 Checkpoint recovery failure 场景，分别投影稳定
  `PROVIDER_TIMEOUT` 与 `GRAPH_CHECKPOINT_UNAVAILABLE`，终态均失败关闭且无
  Artifact。
- 保留原 `full_demo` 的 18 帧、双 Interrupt、恢复、Handoff、Retry、Topology
  与摘要快照不变，避免破坏既有 Studio 黑盒回归。
- 真实 Agent Server 首次验证发现文件路径装载没有 package 上下文；已将
  Studio 对产品常量的导入改为绝对包导入，并以真实 Server 4 项黑盒测试复现
  闭环。

## 安全边界

- Studio 仍固定 `studio-safe`、127.0.0.1、本地 in-memory Runtime、外部网络
  disabled、远程 Trace disabled；不读取 `.env`、生产凭据、数据库、Redis、
  MCP Gateway Token 或 Provider Key，不启用 Tunnel。
- 投影不包含请求/答案正文、知识摘要、Citation 内容、ACL、Tenant、审批、
  SecurityContext、Provider Session、Checkpoint 内容、凭据或隐藏思维链。
- Actor、Phase、Intent 与错误码必须匹配稳定字符集；未知字段继续 default-deny，
  Task 引用继续散列为不透明 `task://sha256/...`。
- Studio 是本地调试投影，不是业务事实源、授权入口或权威 Task 状态存储。

## 修改文件

| 文件 | 变化 |
|---|---|
| `packages/graph/src/flowpilot_graph/debug.py` | 新增产品 5 阶段安全调试投影 |
| `packages/graph/src/flowpilot_graph/__init__.py` | 导出 `product_debug_projection` |
| `apps/worker/src/flowpilot_worker/studio.py` | 默认正式知识产品 Demo、阶段/Actor/恢复/失败投影 |
| `tests/runtime/integration/test_studio_graph.py` | 产品进度、Interrupt、恢复、超时与恢复失败测试 |
| `tests/runtime/security/test_studio_security.py` | 正文、知识、Session、Tenant 与权威字段零泄漏测试 |
| `tests/runtime/evidence/WP-072-a1-runtime-HANDOFF.md` | 本交接证据 |

## 契约、数据库与配置变化

- 公共 Contract、ContractSet、数据库和 Migration：无修改。
- `langgraph.json`、`pyproject.toml`、`uv.lock`、`Makefile`、`.env*`：无修改。
- 新依赖：无；继续消费 S5 锁定的 LangGraph CLI/API/in-memory Runtime。
- 公网、生产凭据、远程 Trace 与付费 Provider 调用：0。

## 验证

| 命令 | 结果 |
|---|---|
| WP-072 定向 Studio/安全测试 | PASS；23 passed |
| 真实 `tests/acceptance/studio` Agent Server 黑盒 | PASS；4 passed，Graph 注册/拓扑/真实线程/Checkpoint/安全/清理均通过 |
| `langgraph --version`、`langgraph dev --help` | PASS；CLI 0.4.31；本机无 `make.exe`，按 Makefile 原命令执行 |
| `.\\scripts\\quality.ps1 lint` | PASS；Ruff、strict Mypy 124 source files |
| `uv run --all-packages --all-groups --locked python -B -m pytest tests/runtime -q` | PASS；199 passed、1 explicit online skip |
| `.\\scripts\\quality.ps1 test-all` | PASS；850 passed、1 explicit online skip |
| `.\\scripts\\quality.ps1 test-security` | PASS；117 passed |
| `.\\scripts\\quality.ps1 audit` | PASS；0 known vulnerabilities；editable Workspace 包按入口定义跳过 |
| `git diff --check`、范围与高置信 Secret 扫描 | PASS；仅 S2 授权路径，Secret 0 |

Contract Conformance：

```text
CONTRACT_CONFORMANCE_OK schemas=20 cases=35 positive=18 negative=17 mutation_cases=19 mutation_positive=3 mutation_negative=16 semantic_cases=43 semantic_positive=0 semantic_negative=43 audit_chain_cases=5 audit_chain_positive=1 audit_chain_negative=4 manifest_cases=21 manifest_positive=1 manifest_negative=20 review_attestation_cases=10 review_attestation_positive=2 review_attestation_negative=8 retired_review_attestation_cases=5 retired_review_attestation_positive=0 retired_review_attestation_negative=5 features=52
```

## 已知风险

- P2：本机未安装 `make.exe`；`studio-smoke` 的两条 Makefile 原命令均已直接
  PASS，不安装系统工具。S4/S7 有 Make 的环境应复跑稳定入口。
- P2：锁定的 `langgraph-api==0.11.2` 启动时提示已进入 Critical support，当前
  Audit 为 0 known vulnerabilities；升级到 0.12.x 需要 S5 依赖工作包重新锁定与
  Conformance，不在本 Step 越权处理。
- P2：真实在线 Provider Smoke 继续显式关闭；本地 Studio 只证明产品拓扑、
  Interrupt、恢复和安全投影，不代表生产 HA、OIDC 或 Provider 可用性。

## 学习候选

```text
LEARNING_CANDIDATE=LangGraph 文件入口必须兼容无 package 上下文装载
MATURITY=VERIFIED
TRIGGER=普通 pytest 包导入通过，但真实 langgraph dev 按 studio.py 文件路径装载时相对导入失败
MECHANISM=GraphSpec 使用 importlib 按文件执行，模块没有 __package__，相对导入无法解析
STRUCTURE=Studio 文件入口对 Workspace 包使用绝对导入；真实 Agent Server Smoke 必须进入锁定门禁
EVIDENCE=tests/acceptance/studio/test_agent_server_blackbox.py；WP-072-a1-runtime 提交
RESIDUAL_RISK=未来 Studio 入口新增相对导入时仍可能只在真实 Server 暴露
TARGET=ENGINEERING_PLAYBOOK LangGraph Studio 装载边界候选
```

## 接收会话下一步

1. 核验 S2 `NEW_HEAD`、本文件 SHA256、ContractSet、线性祖先、分支、授权路径
   与 clean，只用 `--ff-only` 到达精确 Head。
2. 执行 `M7-09-S4-WEB-STUDIO` / `WP-072-a1`：Web/SSE 只消费 API/Task 投影，
   显示节点、5 阶段进度、引用计数、Interrupt、恢复与稳定错误，不复制业务事实。
3. 验证刷新/断线重连/重复事件/序列缺口/多次 Interrupt；浏览器不得伪造
   Tenant、主体、Purpose、授权或审批，页面/Trace 不得包含敏感值。
4. P0/P1、契约/S3 边界、越权路径、门禁失败或未授权外部调用立即停链上报 S1；
   正常完成按预授权链继续下一消费者。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M7-LOCAL-PRODUCT-01
STEP_ID=M7-08-S2-STUDIO-PROJECTION
ATTEMPT_ID=WP-072-a1-runtime
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=3c27f1a57c63782a2062aad7793811bae15cb7cf
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/runtime/evidence/WP-072-a1-runtime-HANDOFF.md
NEXT_ROLE=S4-QUALITY
NEXT_ATTEMPT_ID=WP-072-a1
ESCALATE_TO_S1=no
```

## 可回滚方式

- Revert 本 Handoff 所在提交；禁止 reset、rebase 或 force-push。
