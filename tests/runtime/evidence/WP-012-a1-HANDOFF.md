# WP-012-a1 S2-RUNTIME 交接

## 基本信息

- Work Package：WP-012
- Attempt ID：WP-012-a1
- Chain ID：CHAIN-M2-STUDIO-01
- Step ID：M2-STUDIO-02-S2
- 责任会话：S2-RUNTIME
- 接收会话：S4-QUALITY
- 交接策略：CONSUMER_GATE
- 功能 ID：FP-FLOW-001、FP-FLOW-004、FP-FLOW-005、FP-FLOW-006、
  FP-OBS-001、FP-OPS-002
- 基线提交：`c6b250e3b3a5b7df93b60857b5ee438027ee2ff3`
- 实现提交：`de5e41b7ecc9732fccde3fe1b068f1f1fba11115`
- 分支：`codex/s2/wp-010-runtime-bootstrap`
- 最终提交：本文件所在提交；精确 SHA 由唤醒信封返回
- ContractSet 摘要：
  `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- 状态：完成，等待 S4 独立黑盒验收

## 完成内容

- 消费者门禁核验了任务标题、项目、Worktree、Branch、DEDUP_KEY、S5
  Handoff Hash、ContractSet、共享锁摘要、线性祖先关系和洁净状态；随后只用
  `--ff-only` 精确到达 S5 输入 Head，并输出
  `CONSUMER_VERDICT=ACCEPT`。
- 根 `langgraph.json` 暴露唯一稳定图 ID
  `flowpilot_it_service`，默认固定 `studio-safe`、关闭远程 Trace 和外部
  网络，不读取 `.env`，不启用 Tunnel，并为 Windows 子进程固定 UTF-8
  模式。
- `LangGraphRuntime` 与 Studio 装配都消费同一个
  `build_flowpilot_it_service_graph`；工厂 ID、图 ID 和拓扑摘要不一致会以
  `GRAPH_FACTORY_DIVERGED` 失败关闭。
- 稳定拓扑覆盖 Context 构建、确定性路由、clarification Interrupt、
  并行只读、join、Handoff、approval Interrupt、Agent 调用、retry、
  compensation 和终止。
- `studio-safe` 使用纯合成状态、Fake readonly 工具语义和无外部 I/O
  节点；Interrupt 之前没有业务副作用，Studio Thread 不充当 Task、
  Checkpoint、Lease、Approval 或终态事实源。
- 每个节点生成 default-deny `debug_projection`，展示节点、路由、预算、
  重试、Interrupt、Handoff、Context 层、checkpoint sequence、
  `run_generation` 和脱敏 Task 引用；未知字段、权威对象、原始 Context、
  Provider Session、Secret 和 PII 默认不可见。
- 提交拓扑快照和完整 18 帧投影摘要快照。测试将快照与实际编译节点/边及
  每帧完整内容摘要绑定，故意分叉工厂时失败。
- 真实本地 Agent Server Smoke 通过：API 注册
  `flowpilot_it_service`；合成运行先后停在 clarification 与 approval
  Interrupt，恢复后完成 Handoff、一次 retry，最终
  `COMPLETED/SYNTHETIC_SUCCESS`，`checkpoint_sequence=4`、
  `run_generation=1`、安全投影 18 帧。

## 未完成与非目标

- `studio-integration` 已注册为显式 Profile，但在可信 Application、
  MCP Gateway、测试 Realm 和一次性凭据端口尚未装配时稳定拒绝；不会由
  缺失配置自动升级，也没有调试直通路径。
- Studio 不接入生产 Provider、企业网络、业务数据库、真实凭据、真实 PII
  或生产 Trace；这些不是本 Attempt 的目标。
- `pyproject.toml`、`uv.lock`、`Makefile`、`.gitignore`、公共 Contract、
  ADR、Migration 和数据事实源均未修改。
- S4 仍需从 Agent Server API 独立完成黑盒可见性、安全投影和恢复验收；
  S7 仍需从全新环境复算启动、关闭和无残留资源。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `langgraph.json` | 稳定图入口与 Studio-safe 环境 | S2-RUNTIME（WP-012 显式授权） |
| `apps/worker/src/flowpilot_worker/studio.py` | 合成 Studio adapter、Interrupt、恢复和投影装配 | S2-RUNTIME |
| `apps/worker/README.md` | Studio-safe 使用边界 | S2-RUNTIME |
| `packages/graph/src/flowpilot_graph/factory.py` | Worker/Studio 共用图工厂和拓扑摘要 | S2-RUNTIME |
| `packages/graph/src/flowpilot_graph/debug.py` | default-deny 调试投影与 Profile 门禁 | S2-RUNTIME |
| `packages/graph/src/flowpilot_graph/langgraph_runtime.py` | Worker 切换到同源图工厂 | S2-RUNTIME |
| `packages/graph/src/flowpilot_graph/errors.py` | 稳定 Studio/投影/工厂错误码 | S2-RUNTIME |
| `packages/graph/src/flowpilot_graph/__init__.py` | 导出图工厂和调试 API | S2-RUNTIME |
| `packages/graph/README.md` | 同源图与投影边界 | S2-RUNTIME |
| `tests/runtime/integration/test_studio_graph.py` | 配置、拓扑、分叉、Interrupt/Resume、恢复与失败测试 | S2-RUNTIME |
| `tests/runtime/security/test_studio_security.py` | Profile、外网、Secret/PII、未知字段与状态编辑负例 | S2-RUNTIME |
| `tests/runtime/snapshots/flowpilot_it_service.topology.json` | 稳定拓扑快照 | S2-RUNTIME |
| `tests/runtime/snapshots/studio-safe.debug-projection.json` | 18 帧安全投影摘要快照 | S2-RUNTIME |

## 契约、数据库与配置变化

- 契约版本：无修改；继续消费冻结的 rc2 v1 ContractSet。
- Migration：无。
- 数据库：无。
- 环境变量：`langgraph.json` 为本地 Agent Server 固定
  `FLOWPILOT_STUDIO_PROFILE=studio-safe`、
  `FLOWPILOT_EXTERNAL_NETWORK=disabled`、
  `LANGSMITH_TRACING=false`、`PYTHONDONTWRITEBYTECODE=1` 和
  `PYTHONUTF8=1`。
- 兼容性：Worker 的 ExecutionPort、Checkpoint/Lease 端口和权威状态
  语义不变；现有 Runtime 测试全部通过。

## 验证

验证解释器为 Python 3.12.11，锁内 LangGraph CLI 为 0.4.31，
LangGraph API 为 0.11.2，in-memory Runtime 为 0.31.2。

| 命令 | 结果 | 证据 |
|---|---|---|
| `uv sync --all-packages --all-groups --locked` | PASS | 116 个锁定包、14 个 Workspace 包装配成功 |
| `python -B -m pytest -q` | PASS：213 passed | 全部产品测试 |
| `python -B -m pytest -q tests/runtime` | PASS：62 passed | 正常、边界、失败、安全、恢复 |
| `python -B -m pytest -q tests/platform tests/runtime/security` | PASS：68 passed | Platform 与 Runtime 安全负例 |
| `python -B contracts/conformance/validate.py` | PASS | 20 schemas、35 cases、43 semantic cases、52 features |
| `ruff check` 全部 S2 包和 `tests/runtime` | PASS | All checks passed |
| `mypy --strict` 全部 S2 源码 | PASS：28 source files | no issues found |
| `langgraph --version`、`langgraph dev --help` | PASS | CLI 0.4.31 可用 |
| 真实 `langgraph dev --config langgraph.json --host 127.0.0.1 --port 2024 --no-browser` + SDK/API 探针 | PASS | 图注册、两次 Interrupt/Resume、Handoff、retry、终态和投影断言 |
| `git diff --check` 与候选范围审计 | PASS | 仅授权 S2 路径和 `langgraph.json` |
| 高置信 Secret Scan | PASS：0 matches | 本 Attempt 修改路径 |
| Agent Server 关闭与残留检查 | PASS | 精确进程集合已关闭，`.langgraph_api` 已清理 |
| `make test` / `make studio-smoke` | ENV_BLOCKED | Windows Host 未安装 `make`；已执行其锁内等价命令和更强真实 Server Smoke |

Contract Conformance 完整结果：

```text
CONTRACT_CONFORMANCE_OK schemas=20 cases=35 positive=18 negative=17 mutation_cases=19 mutation_positive=3 mutation_negative=16 semantic_cases=43 semantic_positive=0 semantic_negative=43 audit_chain_cases=5 audit_chain_positive=1 audit_chain_negative=4 manifest_cases=21 manifest_positive=1 manifest_negative=20 features=52
```

真实 Agent Server 关键结果：

```json
{
  "checkpoint_sequence": 4,
  "context_rebuilt": true,
  "debug_frame_count": 18,
  "first_interrupt": "clarification",
  "handoff_count": 1,
  "retry_count": 1,
  "second_interrupt": "approval",
  "state_next": [],
  "status": "COMPLETED",
  "terminal_reason": "SYNTHETIC_SUCCESS",
  "tool_scope_rebuilt": true
}
```

## 安全与失败路径

- 已验证负向路径：生产/Integration Profile、父进程中的生产凭据或数据库
  Endpoint、显式启用外部网络、生产 Profile 状态编辑、Task/Tenant/
  Lease/Tool 权威字段注入、未知状态字段、Provider Session、原始 Context、
  PII、预算耗尽、运行失败、入口分叉和并行 reducer 冲突。
- 已验证恢复：动态 clarification/approval Interrupt、相同 Thread 两次
  Resume、节点重进、retry、checkpoint sequence、`run_generation`、
  Handoff 后 Context/工具范围重建；原 WP-010 套件继续覆盖过期 Lease、
  stale generation、CAS 重放和 Worker 重启。
- Secret/PII 检查：高置信源码 Secret Scan 为 0；安全测试使用显式合成
  sentinel，并断言它们不进入投影或最终状态。
- Studio 所有 Tool 阶段均为 `fake_readonly` / `proposal_only` /
  `result_verified` / `no_authoritative_write`，不产生权威写入。

## 已知问题

- P2：官方 in-memory Agent Server 会在当前目录创建可再生的
  `.langgraph_api/` 本地状态，根 `.gitignore` 尚未忽略它。本轮 Smoke
  已精确清理并验证无残留；`.gitignore` 是共享文件，S2 未越权修改。
  S4/S7 启动后必须清理并验证；后续由 S1 指派共享文件 Owner 处理忽略项。
- P2：`studio-integration` 的可信端口尚未装配，当前显式选择会稳定拒绝。
  这避免默认升级或 Gateway 绕过；如后续启用，必须由独立工作包提供测试
  Realm、沙箱工具和一次性凭据。
- S5 已记录本地 Agent Server 组件的 Elastic-2.0 限制；本交付只授权
  本地开发和自动化验证，不授权产品分发、托管或生产部署。

## 学习候选

```text
LEARNING_CANDIDATE=LangGraph 并行分支的 LastValue 通道写冲突
MATURITY=VERIFIED
TRIGGER=同一 superstep 的 knowledge_read 与 service_read 同时写共享标量状态时触发 INVALID_CONCURRENT_GRAPH_UPDATE
MECHANISM=未声明 reducer 的 LastValue 通道每个 superstep 只接受一个更新；并行分支写相同字段即使值相同也不安全
STRUCTURE=并行分支只写各自完成字段；visited/debug 使用确定性 Annotated reducer；共享 current_node/tool_stage 由 join 节点统一写入
EVIDENCE=de5e41b7ecc9732fccde3fe1b068f1f1fba11115；tests/runtime/integration/test_studio_graph.py；真实 Agent Server full_demo
RESIDUAL_RISK=新增并行分支时仍需逐字段分类并由拓扑/恢复测试覆盖
TARGET=docs/architecture/ENGINEERING_PLAYBOOK.md 4.4
```

## 接收会话下一步

1. 核验唤醒信封中的 S2 NEW_HEAD、本文件 SHA、ContractSet、线性父提交、
   分支/Worktree、允许路径和洁净状态。
2. 只用 `--ff-only` 精确到达 S2 NEW_HEAD；不能 rebase、reset、强制合并
   或跨分支复制。
3. 从本地 Agent Server API 黑盒复算图 ID、拓扑、两次
   Interrupt/Resume、checkpoint 对齐、安全投影、Profile/状态编辑拒绝和
   无业务事实源写入。
4. 生成 S4 接受证据后按链授权直接唤醒 S7-INTEGRATION；只有 P0/P1、
   契约/路径/Head/门禁异常才上报 S1。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M2-STUDIO-01
STEP_ID=M2-STUDIO-02-S2
ATTEMPT_ID=WP-012-a1
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=c6b250e3b3a5b7df93b60857b5ee438027ee2ff3
CONTRACT_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
GATE=PASS
HANDOFF=tests/runtime/evidence/WP-012-a1-HANDOFF.md
NEXT_ROLE=S4-QUALITY
NEXT_ATTEMPT_ID=WP-030-a3
ESCALATE_TO_S1=no
```

## 可回滚方式

- 按逆序 revert 本 Handoff 提交和实现提交
  `de5e41b7ecc9732fccde3fe1b068f1f1fba11115`；禁止 reset、rebase 或
  force-push。
