# WP-117 / S2-RUNTIME Handoff

## 基本信息

- Work Package：WP-117
- Attempt ID：WP-117-a1
- Chain ID：CHAIN-M10-KNOWLEDGE-01
- Step ID：M10-07-S2-RUNTIME-CITATIONS
- 责任会话：S2-RUNTIME（knowledge-runtime-consumer）
- 接收会话：S4-QUALITY（knowledge-quality-builder）
- 交接策略：CONSUMER_GATE
- 功能 ID：FP-FLOW-003、FP-CTX-001、FP-MCP-001
- 基线提交：`244439c2c07f94a86f2f58427500004c5d6e370d`
- 产品提交：`c813492f12fa53134af62c579a8fb7552059ecfa`
- 分支：`codex/s2/wp-117-m10-knowledge-runtime`
- ContractSet 摘要：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：完成；等待 S4 消费门禁

## 完成内容

- 保持 LangGraph 为唯一跨节点持久化状态机，知识读取继续只经既有 `GatewayClientPort` 和固定 `knowledge.search.v1` Schema Pin；未增加第二编排器、数据库直连或工具旁路。
- 将一次知识搜索绑定为稳定 `knowledge_result_digest`。首次读取、Handoff、模型调用前、模型返回后、Retry 和 Worker 重启均重新取得 Gateway 权威结果并比较完整候选指纹；同 Request/Idempotency Key 的多次物理核验仍计为一个逻辑 Tool Call。
- 收紧 ToolResult：只接受 `records/returned_count`，限制返回数，逐条校验租户、规范 Knowledge URI、版本、Section、Hash、Classification、脱敏摘要和聚合 Classification；任一部分损坏即整体失败关闭。
- LangGraph Checkpoint 在模型选择引用前只保存候选集合摘要，不保存完整候选列表。终态仅保存被模型实际引用的 `source_ref/version/section/hash/classification/redacted_summary`，并与 `reference_refs` 一致；原始正文、Provider Session 和凭据不进入持久化状态。
- 空结果稳定终止为 `RUNTIME_KNOWLEDGE_NO_RESULT`，模型与 Artifact 调用均为 0；这是当前公共 Artifact 必须含 Citation 条件下的确定性“不知道/需要更多信息”语义，不伪造企业事实或引用。
- 增加正常选择、空证据、恶意摘要、跨租户、旧版本、Handoff 漂移、模型后漂移、Interrupt/Resume、Provider Retry、Worker 重启与无重复逻辑调用回归。

## 未完成与非目标

- 未实现 Web 呈现或固定分母执行器；由 WP-118/WP-119 完成。
- 未修改公共 Contract、`knowledge.search.v1` Schema Pin、Workspace/Lock、Migration、API、Retrieval 或 MCP Gateway。
- 未执行在线 Provider、真实凭据、付费调用、Compose、Keycloak、PostgreSQL/RLS 或全仓产品测试；这些不属于工程选择器为本差异选择的门禁，且 WP-116 对未变化基线已有可复用证据。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `apps/worker/src/flowpilot_worker/knowledge.py` | Gateway 引用重验、候选摘要绑定、严格结果/URI 校验、无证据失败关闭 | S2 |
| `packages/graph/src/flowpilot_graph/state.py` | 增加候选结果摘要和终态最小 Citation Binding Checkpoint 字段 | S2 |
| `tests/runtime/integration/test_m7_product_runtime.py` | M10 规范引用 Fixture 与端到端安全/恢复/漂移测试 | S2 |
| `tests/runtime/unit/test_graph_state.py` | Citation Binding Checkpoint 往返和危险字段负例 | S2 |
| `tests/runtime/evidence/WP-117-a1-HANDOFF.md` | 本交接证据 | S2 |

## 契约、数据库与配置变化

- 契约版本：无变化；ContractSet Digest 保持不变。
- Tool Schema：无变化；`knowledge.search.v1` Pin 保持 `sha256:b7679fde5be1187e8a36b4cd4dd95a95b63a50dc56532294174b0088f0e6600b`。
- Migration / 数据库：无变化。
- 环境变量 / 依赖 / Lock：无变化。
- 兼容性：新增 GraphState 字段均有空默认值，旧 Checkpoint 可读取；既有 `reference_refs` 投影保留。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| `flowpilot-eng tests select ...` | PASS | TARGETED；`tests/runtime`；plan `a6e17366eaadc387b38f8d14040c8641b43b25822792574c11cd298b89f48e7f`；selection complete |
| `uv run ... pytest tests/runtime -q` | PASS | 288 passed，1 个显式 online Provider skip |
| Makefile `test-security` 底层 pytest 命令 | PASS | 273 passed |
| `python -B contracts/conformance/validate.py` | PASS | 20 schemas / 35 cases / 43 semantic cases / 52 features |
| Makefile Ruff 底层命令 | PASS | All checks passed |
| Makefile strict Mypy 底层命令 | PASS | 170 source files |
| `git diff --check` | PASS | 无 whitespace error |
| `make test-security` / `make lint` | ENV_BLOCKED | Windows 主机无 `make.exe`；已按当前 Makefile 原样执行底层命令，不宣称 Make 入口通过 |

## 安全与失败路径

- 已验证负向路径：空结果、跨租户引用、URI/版本不一致、超分类/分类漂移、Handoff 漂移、模型返回后漂移、Secret/Prompt-Injection 摘要、模型越权字段、错误 workload audience、撤销身份、Retry/重启引用漂移。
- 写 Artifact 前最后一次引用重验；漂移时 Artifact、终态和危险摘要写入数均为 0。
- 完整候选列表只存在于单次内存 Context 构建边界，Checkpoint/Outbox/LangGraph State 仅保留候选摘要 Hash 与最终被选中的安全引用。
- Secret/PII 检查：共享 Security 273 passed；Runtime 凭据扫描与危险 Sentinel 持久化断言通过。
- 未验证风险：S4 应以真实 Agent Server/Web 黑盒复算“空证据”呈现和旧引用漂移；Runtime 依赖 Gateway 每次 `execute` 返回当前安全权威结果，ACL 本身不进入 Worker 或 Checkpoint。

## 已知问题

- 本机缺少 `make.exe`；稳定目标包装命令为 `ENV_BLOCKED`，其底层锁定命令均已通过。
- 无 P0/P1、公共契约变化、路径越权或未授权调用。

## 已知事实与避免重复

- `KNOWN_FACTS`：WP-116 Handoff Hash `sha256:261e69c979f6948e27e65848bd2fea8542f102e4e2505dfa50cd83cd337b0a06` 已在消费者门禁核验；其全仓/Workspace/Lock 结果未变化。
- `DO_NOT_RECHECK`：WP-116 管理 API、Workspace Lock、Retrieval/MCP 生产实现、Compose/RLS、固定 156 Acceptance 基线。
- `FAILURE_SIGNATURES`：`RUNTIME_KNOWLEDGE_NO_RESULT`、`RUNTIME_KNOWLEDGE_RESULT_INVALID`、`RUNTIME_KNOWLEDGE_REFERENCE_DRIFT`。
- `REUSED_DECISIONS`：Gateway 是唯一业务工具边界；公共 Tool Schema 不暴露内部 ACL 或 `content_ref`，Runtime 使用 `source_ref` 作为稳定公开内容引用。
- `DUPLICATE_WORK_AVOIDED`：复用 WP-116 完整门禁和既有 M7/M8/M9 恢复、安全 Fixture；未重跑无关 Compose、Keycloak、RLS、API 与全仓验收。

## 学习候选

```text
LEARNING_CANDIDATE=候选摘要绑定与选择后引用持久化
MATURITY=VERIFIED
TRIGGER=恢复/Handoff 既要重验完整候选结果，又禁止把完整候选列表写入 Checkpoint
MECHANISM=Checkpoint 保存规范化候选集合 Hash；每个权威边界用同一幂等 Tool Request 重取并比较；模型选择后只持久化实际 Citation 的安全绑定
STRUCTURE=query_result_digest + Gateway authoritative revalidation + selected citation_bindings
EVIDENCE=c813492f12fa53134af62c579a8fb7552059ecfa；Runtime 288 passed；Security 273 passed
RESIDUAL_RISK=上层必须把无证据稳定错误映射为明确的不知道/需要更多信息，不得补造答案
TARGET=docs/architecture/CONTEXT_ENGINEERING.md
```

## 子 Agent 使用摘要

```text
SUBAGENTS_USED=2
SUBAGENT_MODES=READ_ONLY_PARALLEL
SUBAGENT_TASKS=wp117_runtime_review,wp117_test_review
SUBAGENT_WRITERS=0
PARENT_REPRODUCED_RESULTS=yes
REUSED_DECISIONS=WP-116 Handoff、现有 Gateway Fake 幂等语义、M7/M8/M9 Runtime 恢复与安全测试
DUPLICATE_WORK_AVOIDED=4
```

## 接收会话下一步

1. 核验包含本 Handoff 的精确 S2 Evidence Head、Handoff SHA256、ContractSet、范围和 clean；只用 `--ff-only` 消费。
2. WP-118 以 Web/真实 Agent Server 黑盒验证空证据呈现、引用显示、错租户、漂移、Interrupt/Resume 和 SSE/Trace 不泄漏；不得修改 Runtime 的安全绑定或公共 Contract。
3. 正常通过后按原链热继续 WP-119；P0/P1、契约变化、旧引用静默重定向或原始正文泄漏时停链回 S1。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M10-KNOWLEDGE-01
STEP_ID=M10-07-S2-RUNTIME-CITATIONS
ATTEMPT_ID=WP-117-a1
NEW_HEAD=c813492f12fa53134af62c579a8fb7552059ecfa
BASE_COMMIT=244439c2c07f94a86f2f58427500004c5d6e370d
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/runtime/evidence/WP-117-a1-HANDOFF.md
NEXT_ROLE=S4-QUALITY
NEXT_ATTEMPT_ID=WP-118-a1
ESCALATE_TO_S1=no
SUBAGENTS_USED=2
```

`NEW_HEAD` 是完成产品实现与门禁的精确提交；包含本 Handoff 的最终 Evidence Head 和文件 Hash 由外部唤醒信封精确指定。

## 可回滚方式

- 仅由 S1 通过新增反向提交线性回滚产品提交；禁止 reset/rebase/force-push。
- 不得通过关闭 Gateway 重验、删除安全负例、恢复非规范 Citation URI、持久化完整候选列表或让模型生成无证据答案来“回滚”。
