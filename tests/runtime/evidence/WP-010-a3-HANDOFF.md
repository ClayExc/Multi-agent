# WP-010-a3 S2-RUNTIME VPN 产品图交接

## 基本信息

- Work Package：WP-010
- Attempt ID：WP-010-a3
- Chain ID：CHAIN-P1-VPN-READONLY-01
- Step ID：P1-VPN-03-S2
- DEDUP Key：
  `CHAIN-P1-VPN-READONLY-01/P1-VPN-03-S2/WP-010-a3/d360f0351520790c86b9c2cc9a7e8c08222a38f9`
- 责任会话：S2-RUNTIME
- 接收会话：S4-QUALITY
- 交接策略：CONSUMER_GATE
- 风险等级：R2
- 功能 ID：FP-FLOW-002、FP-FLOW-003、FP-AGT-001、FP-CTX-001、
  FP-MCP-001、FP-MCP-002、FP-SEC-003、FP-EVAL-003、FP-OPS-002
- 基线提交：`d360f0351520790c86b9c2cc9a7e8c08222a38f9`
- 实现提交：`d3f40bc9d1c1da9fd315fbee9057a22c60165371`
- 分支：`codex/s2/wp-010-runtime-bootstrap`
- 最终提交：本文件所在提交；精确 SHA 由唤醒信封返回
- ContractSet 摘要：
  `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- Knowledge Schema Pin：
  `sha256:b7679fde5be1187e8a36b4cd4dd95a95b63a50dc56532294174b0088f0e6600b`
- 状态：完成，等待 S4 消费门禁

## 完成内容

- 新增 `VpnReadOnlyGraph`，通过既有同源 graph factory 实现确定性
  `intake -> clarify/interrupt -> knowledge -> respond` 产品路径。
- 只消费 S5 `RequestObservationService` / `ResultArtifactService` 和 S3
  `GatewayClientPort`；Knowledge Tool 固定为新 Schema Pin，未导入或实例化
  `KnowledgeMcpAdapter`，没有数据库、上游 MCP、企业网络或 Provider 调用。
- 缺失 `environment` 时使用 LangGraph 动态 `interrupt()`；Gateway 与结果
  Artifact 调用均为 0。恢复时可跨 Worker/Graph 实例复用控制 Checkpoint；
  即使节点重进，Gateway 幂等键也使逻辑知识执行数保持 1。
- `service_read` 在并行槽位中固定为显式 skip，不产生旁路读取；Knowledge
  分支只接受绑定正确、`VERIFIED`、分类不越级且字段闭合的 ToolResult。
- 每次请求/结果阶段都重建 L0/L1/L2 `ContextEnvelope`。Graph State 只保留
  observation/result/source ref、调用数、引用数和恢复元数据；回答正文只经
  S5 Artifact Port 保存，Task 侧只得到不透明 `result_ref`。
- 零结果、Gateway/Artifact 故障、`UNKNOWN`/失败状态和结果绑定异常映射为
  稳定失败；Artifact 暂时不可用时跨 Worker 队列重试，不重复逻辑检索。
- Studio 安全投影新增逻辑知识调用数、引用数和 `service_read` skip；既有
  Interrupt/Resume、路由、终态、恢复和同源拓扑仍可通过本地 Agent Server
  查看，快照已更新。

## 未完成与非目标

- 未加入真实模型 Provider、真实企业 Knowledge MCP、Ticket/Asset 写工具、
  审批、数据库表、Migration、RLS、Redis 或外部网络。
- 未修改公共 ContractSet、Tool Schema、ADR、Traceability、根 Workspace、
  `pyproject.toml`、`uv.lock`、`Makefile` 或 `langgraph.json`。
- 本步骤不建立 20 Case Acceptance 数据集，不宣称 P1 已 VERIFIED/RELEASED；
  黑盒 Case、组合验证和最终裁决分别属于 S4、S7、S1。
- `make acceptance` 仍未实现，本步骤没有将手工检查替代为 Acceptance PASS。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `apps/worker/src/flowpilot_worker/vpn.py` | VPN 产品图、Gateway 请求、恢复与稳定错误映射 | S2 |
| `apps/worker/src/flowpilot_worker/__init__.py` | 导出 VPN 组合入口 | S2 |
| `apps/worker/src/flowpilot_worker/studio.py` | 安全知识/引用/skip 投影事实 | S2 |
| `apps/worker/README.md` | 产品组合与 Studio 可见性说明 | S2 |
| `packages/graph/src/flowpilot_graph/state.py` | 最小观察/引用/计数恢复状态与敏感键拒绝 | S2 |
| `packages/graph/src/flowpilot_graph/debug.py` | 默认拒绝的 Knowledge 调试投影 | S2 |
| `packages/graph/README.md` | 最小恢复状态说明 | S2 |
| `tests/runtime/integration/test_vpn_readonly_graph.py` | 完整、Interrupt、Worker 重启、重入、零结果、安全测试 | S2 |
| `tests/runtime/integration/test_studio_graph.py` | Studio Knowledge 可见性断言 | S2 |
| `tests/runtime/security/test_studio_security.py` | 安全投影泄漏负例 | S2 |
| `tests/runtime/unit/test_graph_state.py` | 原文、ACL、Payload 等 Checkpoint 拒绝负例 | S2 |
| `tests/runtime/snapshots/studio-safe.debug-projection.json` | 新安全投影快照 | S2 |

## 契约、数据库与配置变化

- 公共契约：无变化；ContractSet content digest 保持不变。
- 内部 Python 组合：新增 `VpnReadOnlyGraph`，固定消费既有 S5/S3 Port。
- Tool Schema：无变化；只固定消费 S3 已接受的新 Knowledge Pin。
- Migration / RLS / PostgreSQL / Redis：无变化。
- 环境变量 / `langgraph.json` / 生产配置：无变化。
- 依赖 / Workspace / Lock：无变化；没有新增第三方依赖或许可证面。
- 兼容性：既有 Runtime、Worker、Studio graph ID/factory/topology 保持不变；
  `GraphState.from_checkpoint` 对新增字段提供默认值。

## 验证

| 命令 / 门禁 | 结果 | 证据 |
|---|---|---|
| 消费 Head、Handoff Hash、ContractSet、Pin、祖先、范围、clean | PASS | 消费门禁后 ff-only 精确到 `d360f035...` |
| `make test` | 环境未运行 | 当前 PowerShell 无 `make.exe`，未宣称 PASS |
| Makefile `test` 的锁定底层命令 | PASS | 253 passed，含 Runtime 67 / VPN 5 |
| Makefile `test-contract` 的锁定底层命令 | PASS | 20 schemas / 35 cases / 43 semantic cases / 52 features |
| Makefile `test-security` 的锁定底层命令 | PASS | Platform security 68 passed |
| Ruff（S2 源码与 Runtime 测试） | PASS | All checks passed |
| Mypy `--strict`（S2 四个源码包） | PASS | 27 source files |
| `uv sync --all-packages --all-groups --locked` | PASS | 116 resolved / 113 checked |
| Studio CLI smoke 的锁定底层命令 | PASS | LangGraph CLI 0.4.31；`langgraph dev --help` PASS |
| `uv build --all-packages --wheel` | PASS | 14 wheels |
| `git diff --check` | PASS | 无 whitespace error |
| 变更路径高置信 Secret Scan | PASS | 0 matches |
| Contract / Shared / Lock / 越权路径差异 | PASS | 0 changes |

Contract Conformance：

```text
CONTRACT_CONFORMANCE_OK schemas=20 cases=35 positive=18 negative=17 mutation_cases=19 mutation_positive=3 mutation_negative=16 semantic_cases=43 semantic_positive=0 semantic_negative=43 audit_chain_cases=5 audit_chain_positive=1 audit_chain_negative=4 manifest_cases=21 manifest_positive=1 manifest_negative=20 features=52
```

## 安全与失败路径

- 已验证：完整 VPN 691 请求只产生 1 次逻辑 Gateway read、1 个引用和稳定
  `result_ref`；Artifact 内容不进入 Graph State 或 debug projection。
- 已验证：缺环境字段时动态 Interrupt，知识与 Artifact 调用均为 0；恢复后
  跨 Worker 实例完成，重复 Command 不增加调用或改变 `result_ref`。
- 已验证：Artifact 暂时不可用导致 `RETRY_PENDING`，节点重进时 Gateway
  调用记录可重放，但逻辑执行数仍为 1，Artifact 最终只保存一份。
- 已验证：零结果失败关闭，不伪造引用或结果；旧/漂移 Knowledge Pin 在 S2
  配置入口失败关闭。
- 已验证：原始请求、回答正文、ACL、完整工具 Payload、凭据、Provider
  Session 和隐藏思维链不能进入 Checkpoint/Studio 安全投影。
- Secret/PII：仅合成租户、请求、知识和攻击标记；高置信扫描 0 matches。

## 已知问题

- 当前 PowerShell 无 GNU Make；已按 Makefile 原样执行锁定底层命令。S4/S7
  若环境有 Make，应复跑稳定入口。
- 当前 Worker 队列仍是信号边界；真实耐久队列和远端 Knowledge 网络故障
  不属于本切片。恢复正确性依赖既有 Checkpoint/Lease 与 S3/S5 幂等 Port。
- `flowpilot-worker` 在本仓库按 all-packages Workspace 闭包运行；本链禁止
  `pyproject.toml` / Lock 变化，因此未扩大独立产品分发授权。

## 学习候选

```text
LEARNING_CANDIDATE=动态 Interrupt 控制 Checkpoint 与 Task 权威 Checkpoint 分离恢复
MATURITY=IMPLEMENTED
TRIGGER=Worker 在 Clarification 或 Knowledge 节点边界重启、控制 Checkpoint 可用或丢失
MECHANISM=把 LangGraph 控制游标当 Task 事实会混淆权威；只依赖进程内游标又无法跨 Worker 恢复
STRUCTURE=Task GraphState 保存最小权威状态；LangGraph Checkpointer 保存可恢复控制游标；控制游标丢失时从脱敏引用重建，外部 Port 以稳定幂等键收敛
EVIDENCE=d3f40bc9d1c1da9fd315fbee9057a22c60165371；tests/runtime/integration/test_vpn_readonly_graph.py
RESIDUAL_RISK=真实持久 LangGraph Checkpointer 与耐久队列仍需 S7/后续数据工作包组合验证
TARGET=docs/architecture/ENGINEERING_PLAYBOOK.md
```

## 接收会话下一步

1. S4 核验 NEW_HEAD、Handoff SHA、ContractSet、Knowledge Pin、线性父提交、
   授权范围和干净 Worktree，输出消费者结论后仅以 `--ff-only` 到达精确 Head。
2. 按 WP-030-a4 建立恰好 20 条固定 VPN 黑盒 Case，覆盖完整/缺字段、零结果、
   错租户/ACL、恶意查询、恢复、重复投递、引用完整性和安全投影。
3. 从公开/稳定边界验证逻辑知识调用数、`result_ref`、Task 终态和逐 Case 结果；
   Judge 不得覆盖安全、实际调用或引用断言。
4. 正常 PASS 后只唤醒 S7-INTEGRATION / WP-040-a6；P0/P1、契约/共享文件
   变化、越权路径或新门禁失败才停链上报 S1。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-P1-VPN-READONLY-01
STEP_ID=P1-VPN-03-S2
ATTEMPT_ID=WP-010-a3
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=d360f0351520790c86b9c2cc9a7e8c08222a38f9
INPUT_HEAD=d360f0351520790c86b9c2cc9a7e8c08222a38f9
IMPLEMENTATION_HEAD=d3f40bc9d1c1da9fd315fbee9057a22c60165371
CONTRACT_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
KNOWLEDGE_SCHEMA_PIN=sha256:b7679fde5be1187e8a36b4cd4dd95a95b63a50dc56532294174b0088f0e6600b
GATE=PASS
HANDOFF=tests/runtime/evidence/WP-010-a3-HANDOFF.md
NEXT_ROLE=S4-QUALITY
NEXT_ATTEMPT_ID=WP-030-a4
ESCALATE_TO_S1=no
```

## 可回滚方式

- 实现提交和 Handoff 提交可由 Chain Owner 按逆序 `git revert`；禁止
  reset/rebase。
- 本 Attempt 没有数据库、Migration、外部系统写入、Contract 或 Lock 变化，
  无数据、Schema Registry 或依赖回滚。
