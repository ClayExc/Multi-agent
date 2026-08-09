# WP-072-a1-runtime-r1 S2-RUNTIME Latest Checkpoint 绑定交接

## 基本信息

- Work Package：WP-072
- Attempt ID：WP-072-a1-runtime-r1
- Chain ID：CHAIN-M7-LOCAL-PRODUCT-01
- Step ID：M7-SEC-04-S2-LATEST-CHECKPOINT-BINDING
- 责任会话：S2-RUNTIME
- 接收会话：S4-QUALITY
- 交接策略：CONSUMER_GATE
- 功能 ID：FP-FLOW-002、FP-FLOW-004
- 基线/输入提交：`35c1865f130beee6d8a57b1a981bf8cf5b67db5c`
- 分支：`codex/s2/wp-070-provider-runtime-adapters`
- 最终提交：本文件所在提交；精确 SHA 由唤醒信封返回
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：PASS_HANDOFF

## 完成内容

- Studio Resume 在执行图之前使用相同 `thread_id` 与 `checkpoint_ns` 查询权威最新
  Checkpoint；查询配置主动移除客户端 `checkpoint_id`，不允许客户端把历史
  Checkpoint 选为状态权威。
- 客户端未提供 `checkpoint_id` 时按最新 Checkpoint 正常恢复；显式提供时必须与
  权威最新 `checkpoint_id` 精确相等，否则稳定返回
  `GRAPH_STUDIO_STATE_EDIT_FORBIDDEN`，安全消息固定为
  `Studio resume must target the latest checkpoint`。
- 校验通过后，实际图执行同样使用去掉客户端 `checkpoint_id` 的 latest 配置，避免
  把已校验的 ID 继续作为分叉执行指针；原有纯 Resume、当前 Interrupt
  kind/payload、`update`/`goto`/`graph` 和 update-state 系列门禁全部保留。
- 原图、`copy()`、同步 `stream`、异步 `astream`/`ainvoke` 路径及真实本地 Agent
  Server 使用同一守卫。历史 clarification/approval Resume 在挂起态和终态均于执行前
  失败关闭。
- 拒绝历史重放前后，latest values、next/Interrupt、checkpoint sequence、history
  count 与 Checkpointer writes 完全不变；不会产生新 Checkpoint、终态或 Artifact。
- 正常无 ID 恢复与显式 latest ID 恢复均保持可用。

## 未完成与非目标

- 不重做已由 S4 接受的 WP-074 凭据注册表，也不修改 S5 TaskEvent/SSE。
- 不修改 S4 Web/Studio 体验路径、S5/S6 数据路径、公共 Contract、依赖或共享文件。
- 未执行真实 Provider、外部网络或付费调用；显式在线 Provider smoke 保持关闭。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `apps/worker/src/flowpilot_worker/studio.py` | latest Checkpoint 查询、显式 ID 精确绑定、latest 执行配置 | S2-RUNTIME |
| `tests/runtime/security/test_studio_security.py` | clarification/approval 历史重放、latest/no-ID 正例、原图/copy/stream 不变性 | S2-RUNTIME |
| `tests/runtime/integration/test_studio_agent_server_authority.py` | 真实 Agent Server 历史挂起态与终态重放负例 | S2-RUNTIME |
| `tests/runtime/evidence/WP-072-a1-LATEST-CHECKPOINT-HANDOFF.md` | 本交接证据 | S2-RUNTIME |

## 契约、数据库与配置变化

- 公共 Contract、ContractSet、Schema：无变化；Conformance PASS。
- Migration、PostgreSQL、Redis、Checkpoint 数据结构：无变化。
- `langgraph.json`、`pyproject.toml`、`uv.lock`、`Makefile`、环境变量：无变化。
- 兼容性：无 `checkpoint_id` 与精确 latest ID 的合法 Resume 保持；历史 ID 从可分叉
  执行收窄为执行前拒绝。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| Studio 定向安全/图/真实 Server | PASS；70 passed | 原图/copy、同步/异步入口、两类历史 Checkpoint、终态零变化 |
| `uv run --all-packages --all-groups --locked python -B -m pytest tests/runtime -q` | PASS；246 passed、1 explicit online skip | 包含真实 Agent Server authority；付费 Smoke 未启用 |
| `.\scripts\quality.ps1 lint` | PASS | Ruff；strict Mypy 126 source files |
| `.\scripts\quality.ps1 test-contract` | PASS | 20 schemas / 35 cases / 43 semantic cases / 52 features |
| `.\scripts\quality.ps1 test-security` | PASS；163 passed | 含 Runtime 负例与全仓高置信 Secret 扫描 |
| `.\scripts\quality.ps1 audit` | PASS | 0 known vulnerabilities；editable Workspace 包按入口定义跳过 |
| `git diff --check`、授权路径与运行目录检查 | PASS | 仅 S2 WRITE_SCOPE；`.langgraph_api` 不存在 |

## 安全与恢复证据

- 历史 clarification Checkpoint 在当前 approval Interrupt 重放：拒绝，history/writes/state
  变化均为 0。
- 历史 approval Checkpoint 在 terminal 后重放：拒绝，history/writes/state 变化均为 0。
- 显式 latest approval Checkpoint：正常完成；未提供 ID：正常进入下一 Interrupt。
- 当前 Interrupt kind/payload 校验、纯 Resume 结构门禁、update/goto/graph 禁止与四类
  update-state 禁止继续通过。
- 真实 Server 返回稳定 `GraphError` 安全消息；拒绝不会进入业务节点或产生 Artifact。

## 已知风险

- P2：当前边界对单线程/Agent Server 同 Thread 串行运行提供确定性 latest 绑定，并在
  校验后移除客户端 Checkpoint 分叉指针。读取 latest 与实际执行仍不是跨进程原子 CAS；
  若未来允许同 Thread 并发 Run，必须在调度/持久化层增加运行串行化或 CAS，并复跑竞争
  黑盒。本 Attempt 不修改公共 Checkpoint Contract，因此不宣称分布式并发原子性。
- P3：在线 Provider smoke 需要显式授权，本轮保持 skip；与本地 Studio authority 结论
  无关。

## 学习候选

```text
LEARNING_CANDIDATE=校验调用者选择的 Checkpoint 不等于绑定权威 latest Checkpoint
MATURITY=VERIFIED
TRIGGER=历史 snapshot.config 携带 checkpoint_id 再次 Resume，LangGraph 从历史点创建分叉并增加 history
MECHANISM=Ingress 使用调用者原始 config 读取状态，因此把历史 checkpoint_id 同时当成校验来源和执行指针
STRUCTURE=按 thread_id/checkpoint_ns 去掉 checkpoint_id 查询权威 latest；显式 ID 与 latest 精确比较；通过后仍以无客户端 ID 的 latest 配置执行
EVIDENCE=tests/runtime/security/test_studio_security.py；tests/runtime/integration/test_studio_agent_server_authority.py；WP-072-a1-runtime-r1 提交
RESIDUAL_RISK=跨进程同 Thread 并发需要调度串行化或持久化 CAS
TARGET=ENGINEERING_PLAYBOOK LangGraph Checkpoint/Resume 权威绑定候选
```

## 接收会话下一步

1. 核验 S2 `NEW_HEAD`、本文件 SHA256、ContractSet、线性祖先、分支、授权路径与
   clean，只用 `--ff-only` 到达精确 Head。
2. 独立复算 terminal 历史 approval replay 的 history、writes 与 state 变化全部为 0，
   并复算历史 clarification replay 与 latest/no-ID 正例。
3. 通过后恢复原 `WP-072-a1` Web/Studio 工作；不要放宽当前纯 Resume、Interrupt kind
   或 update-state 门禁。
4. 若要求跨进程同 Thread 并发原子绑定，停止当前局部返修并向 S1 提交调度/CAS RFC。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M7-LOCAL-PRODUCT-01
STEP_ID=M7-SEC-04-S2-LATEST-CHECKPOINT-BINDING
ATTEMPT_ID=WP-072-a1-runtime-r1
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=35c1865f130beee6d8a57b1a981bf8cf5b67db5c
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/runtime/evidence/WP-072-a1-LATEST-CHECKPOINT-HANDOFF.md
NEXT_ROLE=S4-QUALITY
NEXT_ATTEMPT_ID=WP-072-a1
ESCALATE_TO_S1=no
```

## 可回滚方式

- Revert 本 Handoff 所在提交；禁止 reset、rebase 或 force-push。
