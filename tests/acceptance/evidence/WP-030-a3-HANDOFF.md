# WP-030-a3 S4-QUALITY Studio Agent Server 黑盒交接

## 基本信息

- Work Package：WP-030
- Attempt ID：WP-030-a3
- Chain ID：CHAIN-M2-STUDIO-01
- Step ID：M2-STUDIO-03-S4
- 责任会话：S4-QUALITY
- 接收会话：S7-INTEGRATION
- 交接策略：CONSUMER_GATE
- 功能 ID：FP-OBS-001、FP-EVAL-003；同时黑盒复核上游
  FP-FLOW-001、FP-FLOW-004、FP-FLOW-005、FP-FLOW-006、FP-OPS-002
- 基线提交：`cf5102d1ff66d3fd04362d68f48a6aba9b32acfa`
- 实现提交：`14d0d560864ddc903355d6d132e0afbb03442652`
- 分支/最终提交：`codex/s4/wp-030-quality-bootstrap`；本文件所在提交，
  精确 SHA 由唤醒信封返回
- ContractSet 摘要：
  `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- 状态：完成，等待 S7 消费门禁

## 完成内容

- 核对当前任务标题、Project、Worktree、Branch 和 DEDUP_KEY；验证 S2
  Handoff SHA-256 为
  `e9542a5c95592679f2e4fac29fefcd36b97531c59b22fe99c876a6298c730ce3`，
  ContractSet 摘要、授权范围和线性祖先关系一致后，仅以 `--ff-only`
  精确到达 S2 Head
  `cf5102d1ff66d3fd04362d68f48a6aba9b32acfa`。
- 新增真实本地 Agent Server 黑盒生成器。生成器使用锁定解释器启动
  `langgraph dev --no-browser`，只从公开 SDK/API 读取 Assistant、Graph、
  Thread、Run、State 和 Checkpoint History；不导入 Worker Graph、
  `tests/runtime` 或 S2 私有 Fixture。
- 使用 S4 独立拓扑 Oracle 验证唯一稳定图 ID
  `flowpilot_it_service`、16 个 API 节点和 22 条展开边；生产者无法通过
  同时修改自身拓扑快照绕过 S4 门禁。
- 在同一真实 Thread 完成：
  - clarification Interrupt → Resume；
  - 并行 knowledge/service readonly → join → Handoff；
  - approval Interrupt → Resume；
  - 首次运行失败 → retry → `COMPLETED`。
- 验证最终路径、`checkpoint_sequence=4`、`run_generation=1`、
  `retry_count=1`、18 帧闭合安全投影、19 个 Checkpoint History 状态、
  连续 metadata step 和完整 parent checkpoint 链。
- 负向验证生产 Profile 编辑和未知 Scenario 在 `prepare` 前失败，
  Approval 拒绝保持 `FAILED` 且补偿为无副作用；Tenant、API Key、
  Provider Session、PII、Raw Context 和未来未知字段均不能进入结果或
  Debug Projection。
- 启动前移除生产凭据/Endpoint 并固定
  `FLOWPILOT_EXTERNAL_NETWORK=disabled`；运行前后复算 `apps`、
  `packages`、`domain-packs`、`migrations`、`infra` 文件指纹，证明本地
  Studio Smoke 未改变业务源码/事实源文件。
- 生成器在成功和失败路径都关闭完整服务器进程树，验证监听端口释放，
  精确删除自身生成的 `.langgraph_api`，并在存在旧运行目录时拒绝启动，
  避免覆盖未知本地状态。
- 证据保持 `release_gate=false`、`dataset_completion_claim=false`、
  `measured_quality_claim=false`；没有输出成功率、Token 改善或 120/36
  数据集完成声明。

## 未完成与非目标

- 未修改 Runtime、Graph、Worker、API、Gateway、Policy、Persistence、
  Makefile、公共契约、ADR、Workspace 或 Lock。
- 未启用 `studio-integration`，未连接生产 Provider、企业 MCP、数据库、
  RLS、Outbox、外部网络或真实凭据。
- 未使用浏览器、截图或人工点击作为权威证据。
- 未填充或宣称 120 条功能集、36 条安全/故障集完成。
- 未测量或报告任务成功率、Token、延迟或质量提升。
- `make acceptance` 仍未实现；本 Step 不构成发布级验收。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `artifacts/acceptance/generators/__init__.py` | 导出 Studio Agent Server 证据生成器 | S4-QUALITY |
| `artifacts/acceptance/generators/studio_agent_server.py` | 真实服务器启动、API 探针、门禁、证据和清理 | S4-QUALITY |
| `tests/acceptance/studio/expected_agent_server_topology.json` | S4 独立 API 拓扑 Oracle | S4-QUALITY |
| `tests/acceptance/studio/test_agent_server_blackbox.py` | 图、运行、恢复、安全、失败关闭和清理黑盒 | S4-QUALITY |
| `tests/acceptance/evidence/WP-030-a3-PROOF.json` | 命令、覆盖、残留和非发布声明的结构化 Proof | S4-QUALITY |
| `tests/acceptance/evidence/WP-030-a3-HANDOFF.md` | 本交接 | S4-QUALITY |

## 契约、数据库与配置变化

- 契约版本：无变化。
- ContractSet：
  `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`。
- Migration / RLS / 数据库：无变化。
- Workspace / Lock / Makefile / `langgraph.json`：无变化。
- 环境变量：无仓库配置变化；测试子进程固定 Studio Safe 值并清除生产
  凭据/Endpoint。
- 第三方生产依赖：无新增；只使用锁内 LangGraph CLI/API/SDK。
- 兼容性：测试只消费公开 Agent Server API，不扩展公共契约、枚举或对象。

## 验证

环境：Windows、锁定 CPython 3.12.11、uv 0.11.32、Pytest 9.1.1、
LangGraph CLI 0.4.31、LangGraph API 0.11.2、in-memory Runtime 0.31.2、
SDK 0.4.2、GNU Make 4.4.1。

| 命令 | 结果 | 证据 |
|---|---|---|
| `python -B -m pytest tests/acceptance/studio -q` | PASS：4 passed，含真实 Agent Server | `WP-030-a3-PROOF.json` |
| `python -B -m pytest tests/acceptance -q` | PASS：65 passed | 同上 |
| `make test` | PASS：213 passed | 同上 |
| `make test-security` | PASS：51 passed | 同上 |
| `make test-contract` | PASS：`CONTRACT_CONFORMANCE_OK`，含 43 个语义负例 | 同上 |
| `python -B scripts/acceptance/validate_offline.py` | PASS：2 Case、0 Findings | 同上 |
| 本 Attempt 文件 Ruff | PASS：All checks passed | 同上 |
| 证据生成器 Mypy `--strict` | PASS：3 source files | 同上 |
| `PYTHONUTF8=1` 下锁内 `langgraph --version` / `langgraph dev --help` | PASS：CLI 0.4.31 | 同上 |
| UTF-8/LF/BOM、JSON 重复键和高置信 Secret Scan | PASS：4 文件；Secret 0 | 同上 |
| Agent Server 进程、端口和 `.langgraph_api` 残留检查 | PASS：全部 0 | 同上 |
| `make studio-smoke` | ENV_BLOCKED：Windows 可用 GNU Make 通过 `/usr/bin/bash` 解析绝对 `UV` 路径时丢失盘符分隔；相同锁内命令直接运行 PASS | 同上 |
| 全 Acceptance 目录 Ruff 诊断 | INHERITED_FINDINGS：本 Attempt 之前 4 个测试文件有 I001；当前差异 Ruff PASS | 同上 |
| `make acceptance` | NOT_RUN：目标尚未实现且 Makefile 不在本 Step 写范围 | 同上 |

Proof：`tests/acceptance/evidence/WP-030-a3-PROOF.json`；精确 SHA-256
由最终提交后复算并写入 S7 唤醒信封。

Contract Conformance：

```text
CONTRACT_CONFORMANCE_OK schemas=20 cases=35 positive=18 negative=17 mutation_cases=19 mutation_positive=3 mutation_negative=16 semantic_cases=43 semantic_positive=0 semantic_negative=43 audit_chain_cases=5 audit_chain_positive=1 audit_chain_negative=4 manifest_cases=21 manifest_positive=1 manifest_negative=20 features=52
```

## 安全与失败路径

- 生产 Profile 编辑和未知 Scenario 均返回稳定 GraphError，`step_count=0`、
  `visited_nodes=[]`、`debug_projection=[]`，没有进入业务节点。
- Approval 拒绝终态为 `FAILED`，原因
  `STUDIO_APPROVAL_DENIED`，补偿状态为
  `not_required_no_side_effect`，最终 Tool Stage 为
  `no_authoritative_write`。
- Debug Projection 使用闭合字段集；所有帧均为 `studio-safe`、
  `fake_readonly`，Checkpoint 和 Run Generation 与历史对齐，合成 Secret/
  PII/Raw Context/未知状态不会进入结果或证据。
- 子进程不加载生产凭据/Endpoint，外部网络标志固定关闭；运行前后业务
  源文件指纹一致。
- 服务器完整进程树、监听端口和 `.langgraph_api` 均清零；生成器不删除
  启动前已存在的目录，而是立即失败。
- Proof 和生成证据为 UTF-8、LF、无 BOM；没有真实 Secret、PII、Prompt、
  隐藏思考过程、原始附件或动态 Thread/Run ID。

## 已知问题

- `make acceptance` 尚不存在，不能把本包写成发布验收。
- Windows GNU Make 的 `studio-smoke` 目标无法安全接收当前绝对 `UV`
  路径；锁内等价命令和更强的真实 Server Blackbox 均通过。Makefile
  属于共享路径，本 Attempt 未越权修改。
- 全 Acceptance 目录仍有 4 个继承的 Ruff I001 导入排序发现，位于
  WP-030-a1 文件且不在本 Attempt 差异；不影响运行门禁，建议 S4 后续
  机械清理。
- 根 `.gitignore` 仍未忽略官方 Server 生成的 `.langgraph_api`。本生成器
  将其作为隔离与清理门禁；共享文件修订需另行授权。
- `studio-integration` 可信端口尚未装配，当前显式选择继续失败关闭。
- Agent Server 本地组件的 Elastic-2.0 限制沿用 S5/S2 记录；本交付只用
  于本地开发和自动化验证，不授权产品分发、托管或生产部署。

## 学习候选

```text
LEARNING_CANDIDATE=本地 Agent Server 清理必须针对完整进程树而非监听进程
MATURITY=VERIFIED
TRIGGER=Windows 下 uv/console launcher、watch supervisor 和 in-memory worker 形成多层父子进程，监听 PID 不是唯一残留
MECHANISM=只终止启动器或监听进程可能留下 watcher/worker；只检查端口也不能证明进程和本地持久化目录全部消失
STRUCTURE=以启动 PID 为根关闭完整进程树，随后独立验证根进程退出、端口释放和 .langgraph_api 删除；启动前若目录已存在则拒绝覆盖
EVIDENCE=artifacts/acceptance/generators/studio_agent_server.py；tests/acceptance/studio/test_agent_server_blackbox.py
RESIDUAL_RISK=异常宿主若无法提供进程树终止能力，生成器必须失败而不能降级为仅关闭端口
TARGET=docs/architecture/ENGINEERING_PLAYBOOK.md local development server cleanup section
```

## 接收会话下一步

1. 核验本交接 NEW_HEAD、Handoff/Proof SHA、ContractSet、实现提交、
   `cf5102…` 到 NEW_HEAD 的路径范围与洁净 Worktree。
2. S7 分支只以 `--ff-only` 精确到达 S4 NEW_HEAD；禁止 rebase、reset、
   强制合并或复制文件绕过。
3. 按 `WP-040-a5` 在全新环境复算 Workspace/Lock、全仓/安全/
   Acceptance/Contract、独立拓扑、真实 Agent Server API 和无残留资源。
4. S7 完成后按链路唤醒 S1-ARCH final gate，并设置
   `USER_GATE_REQUIRED=yes`。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M2-STUDIO-01
STEP_ID=M2-STUDIO-03-S4
ATTEMPT_ID=WP-030-a3
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=cf5102d1ff66d3fd04362d68f48a6aba9b32acfa
CONTRACT_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
GATE=PASS
HANDOFF=tests/acceptance/evidence/WP-030-a3-HANDOFF.md
NEXT_ROLE=S7-INTEGRATION
NEXT_ATTEMPT_ID=WP-040-a5
ESCALATE_TO_S1=no
```

## 可回滚方式

- 实现提交与本 Handoff 提交可由链路 Owner 按逆序 `git revert`；禁止
  reset/rebase。
- 本 Attempt 没有数据库、Migration 或外部系统写入，无数据回滚。
