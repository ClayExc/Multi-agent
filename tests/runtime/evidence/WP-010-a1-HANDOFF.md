# WP-010-a1 S2-RUNTIME 交接

## 基本信息

- Work Package：WP-010
- Attempt：WP-010-a1
- 责任会话：S2-RUNTIME
- 接收会话：S1-ARCH、S4-QUALITY、S5-CORE；Checkpoint/Lease 端口后续由 S6-DATA 接入
- 功能 ID：FP-FLOW-001、FP-FLOW-002、FP-AGT-002、FP-CTX-001
- 分支：`codex/s2/wp-010-runtime-bootstrap`
- 基线提交：`93597a5023320d48875b292dc08106f03227a3fb`
- 实现提交：`ff858035d6e60afc91e89885c4bb04d858a8c152`
- 补充安全测试提交：`1b1e43d3fd30a05868e9bb281b2c3fda555f212d`
- 契约摘要：`sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- 状态：部分完成；S2 实现与直接测试完成，共享 Workspace 集成和跨角色验收待处理

## 完成内容

- 实现 S5 `ExecutionPort` 适配器，并按 `tenant_id + command_id` 提交到幂等执行队列。
- 建立真正的 LangGraph `StateGraph` 拓扑。Worker 只依赖
  `GraphExecutionPort`；确定性 Kernel 只提供节点逻辑，不暴露第二个生产执行器。
- 建立最小 Graph State、确定性状态迁移、并行 Reducer、Interrupt、图版本门禁、
  Checkpoint CAS 和 Lease/run-generation fencing 端口。
- 建立 Worker dequeue/lease/execute/ack/retry 骨架及内存 Queue、Checkpoint、Lease Fake。
- 建立 Provider 中立 `AgentRuntimePort`、v1 值对象、稳定错误、请求跨对象门禁和无网络
  `FakeAgentRuntime`。
- 建立 `ContextEnvelope` L0/L1/L2 构建、分类/用途/Provider/Token 门禁、确定性裁剪、
  Manifest 和 Handoff 重建。
- 建立 Provider 中立 Model Gateway 端口、确定性路由 Fake 和预算/分类拒绝。
- Checkpoint 只保存恢复所需的业务引用，不保存 Provider Session、凭据、原始附件或
  SDK 对象；Tool Proposal 仅保存非权威引用。
- 崩溃发生在 `run_agent` 检查点之后时，新租约复用同一 request/attempt，避免将进程
  崩溃误计为新的 Provider 尝试。

## 未完成与非目标

- 根 `pyproject.toml`、`uv.lock`、`Makefile` 未修改。Workspace 注册、锁定
  `langgraph>=1.2,<2` 和稳定测试入口已通过
  `WP-010-a1-DEPENDENCY_REQUEST.md` 请求 S5。
- PostgreSQL/Redis Checkpoint、Lease 和 durable queue adapter 属于后续 S6 集成；
  本包只定义端口、fencing 语义和确定性内存 Fake。
- OpenAI、Claude、真实 Model Gateway、MCP Gateway 和企业网络接入均为非目标。
- S3 ToolRequest/ToolResult adapter 及 S5 Task Event/SSE 投影尚无已接受的内部端口；
  本包不复制公共契约，仅保留 Tool Proposal 引用和稳定运行结果供后续适配。
- 尚未完成 S1/S4/S5 的跨角色审查，因此不得把 WP-010 标记为 VERIFIED。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `apps/worker/**` | ExecutionPort adapter、队列端口/Fake、Worker | S2-RUNTIME |
| `packages/agent-runtime/**` | Runtime Port、v1 模型、门禁、确定性 Fake | S2-RUNTIME |
| `packages/context/**` | ContextEnvelope、Builder、Handoff、Manifest | S2-RUNTIME |
| `packages/graph/**` | StateGraph、Kernel、State、Checkpoint/Lease、Reducer/Fake | S2-RUNTIME |
| `packages/model-gateway/**` | Model Gateway Port 与确定性 Fake | S2-RUNTIME |
| `tests/runtime/**` | 契约、正常、边界、失败、安全和恢复测试及证据 | S2-RUNTIME |

## 契约、数据库与配置变化

- 契约版本：未修改；消费 rc2 v1 契约和 S5 M0 `ExecutionPort`。
- Migration：无。
- 环境变量：无。
- 共享配置：无修改。
- 包内依赖声明：`packages/graph/pyproject.toml` 声明
  `langgraph>=1.2,<2`；共享锁与 Workspace 仍待 S5 处理。
- 兼容性：公共契约未复制或放宽；Root Workspace 在依赖请求落地前不能安装五个 S2 包。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| 直接运行 `tests/runtime` | PASS：36 passed | 正常、边界、失败、安全、恢复测试 |
| 直接运行 `tests/core tests/runtime tests/acceptance` | PASS：86 passed | S5/S2/S4 组合回归 |
| `python contracts/conformance/validate.py` 等价入口 | PASS：`CONTRACT_CONFORMANCE_OK`，20 schemas、35 baseline cases、43 semantic cases、52 features | 契约门禁终端输出 |
| Ruff 检查五个 S2 包与 `tests/runtime` | PASS：All checks passed | 静态检查终端输出 |
| Mypy `--strict` 检查五个 S2 包 | PASS：24 source files | 第三方 import 跟随关闭，S2 源文件严格检查 |
| `git diff --check` | PASS | 无 whitespace 错误 |
| Secret pattern scan | PASS：0 matches | S2 修改路径 |
| `make test` | FAIL：当前 Windows 环境找不到 `make` | 不冒充稳定命令通过 |
| `make test-contract` | FAIL：当前 Windows 环境找不到 `make` | 不冒充稳定命令通过 |

直接测试使用 Python 3.12.7。验证解释器已有 LangGraph 1.2.9；为执行冻结的契约和
静态门禁，仅把 `rfc8785==0.1.4`、Ruff 0.16.0、Mypy 1.20.2 安装到系统临时目录，
未写入仓库或共享锁文件。外部 pytest 插件报告
`asyncio_default_fixture_loop_scope` 未配置的弃用警告，不影响本包同步测试结果。

## 安全与失败路径

- 已验证负向路径：伪造租户安全上下文、Command digest/绑定错误、过期安全上下文、
  Context 分类和预算越界、越权工具提案、敏感字段进入 Context/Checkpoint、Provider
  无路由、无效 Provider 输出、预算耗尽、并行事实冲突、丢失/过期租约和图版本漂移。
- 已验证状态权威：模型输出的终态/节点字段不改变 Graph；Tool Proposal 不成为
  PlannedAction/Approval；Provider Session 只在 Runtime Result 中用于诊断。
- 已验证恢复：重复提交、可重试错误、Worker 崩溃后队列恢复、检查点后崩溃复用 attempt、
  Interrupt 恢复、旧 worker fencing。
- 未验证风险：真实 Provider、S3 Gateway、S6 durable adapter 和多进程数据库竞争；
  这些需要相应责任会话的集成与黑盒测试。
- Secret/PII 检查：Secret pattern 0 命中；Fixture 只使用虚构租户、主体和引用。

## 已知问题

- `WP-010-a1-DR-001` 仍为 `PENDING`。在 S5 合入 Workspace、锁文件和稳定测试入口前，
  `make test` 不能作为 WP-010 的验收通过项。
- Task Event/SSE 与 ToolRequest/ToolResult 的跨包 adapter 需要先由 S5/S3 提供显式
  内部端口；S2 不应自行复制 v1 Schema 对象。
- S6 持久化实现必须保证 Checkpoint CAS 与 Lease generation fencing 同一事务语义；
  内存 Fake 不能替代该集成证据。

## 接收会话下一步

1. S1 复核 LangGraph 唯一状态机、Graph 权威、Provider Session 分离和恢复语义。
2. S4 使用确定性 Fake 增加黑盒故障/状态权威审查，并复核 36 项 Runtime 测试覆盖。
3. S5 处理 `WP-010-a1-DR-001`，更新共享 Workspace/锁/稳定命令后运行
   `make bootstrap`、`make test`、`make test-contract`。
4. S5/S3 明确 Task Event 与 ToolRequest/ToolResult 内部适配端口；如需公共契约变化，
   由 S2 提 RFC，不直接修改 `contracts/**`。
5. S6 后续实现 durable Queue、Checkpoint 和 Lease 端口，并执行数据库竞争和恢复测试。

## 可回滚方式

- 按逆序 revert
  `1b1e43d3fd30a05868e9bb281b2c3fda555f212d` 和
  `ff858035d6e60afc91e89885c4bb04d858a8c152`。
- 交接提交只包含本文件，可独立 revert；禁止 reset/rebase 其他会话分支。
