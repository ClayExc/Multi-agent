# FlowPilot 需求追踪矩阵

## 1. 使用规则

- `traceability.v1.json` 是功能、测试与证据映射的唯一机器事实源；Runner 和门禁不得解析本 Markdown。
- 本文件是面向人的投影视图。实现阶段由 S4-QUALITY 提供生成器，并以 `--check` 校验它与机器清单无差异。
- 该表是 README 技术声明的可读索引；发生冲突时以 `traceability.v1.json` 为准。
- `目标代码` 和 `目标测试` 是实施路径，不代表文件当前已存在。
- 当前无实现代码，因此所有条目均为 `DESIGNED`。
- 条目达到 `VERIFIED` 时必须填写结构化 `valid_evidence_refs`，绑定声明的 `evidence_id/test_id`、实际相对路径、SHA-256、验收 `run_id`、时间与验证角色。
- 功能需求、测试和证据同时变更；禁止只改状态。
- 验收清单只引用稳定的 `feature_id`、`test_id`、`evidence_id` 和精确文件哈希，不复制这些定义。
- `test_id` 与 `evidence_id` 必须包含父 Feature 段；实现责任人与验证责任人必须不同。
- 任意字符串、缺失文件、哈希漂移、跨 Feature 引用或错误验证角色都不能把状态提升到 `VERIFIED/RELEASED`。

## 2. 核心追踪矩阵

| ID | 级别 | 可观察能力 | 目标代码 | 目标测试 | 必需证据 | 当前状态 |
|---|---|---|---|---|---|---|
| FP-FLOW-001 | P0 | LangGraph 是唯一业务状态机 | `packages/graph` | `tests/runtime/e2e/test_state_authority.py` | 状态转换与写入路径断言 | DESIGNED |
| FP-FLOW-002 | P0 | 缺失字段触发追问并续跑 | `packages/graph/nodes` | `tests/runtime/e2e/test_clarification.py` | WAITING_USER 前后事件 | DESIGNED |
| FP-FLOW-003 | P0 | 知识/数据只读分支并行汇总 | `packages/graph` | `tests/runtime/e2e/test_parallel_reads.py` | Trace 时间区间重叠 | DESIGNED |
| FP-FLOW-004 | P0 | 审批 Interrupt 与恢复 | `packages/graph` | `tests/runtime/recovery/test_approval_resume.py` | Checkpoint + 两个 Run | DESIGNED |
| FP-FLOW-005 | P0 | 服务重启从持久化 Checkpoint 恢复 | `apps/worker` | `tests/runtime/recovery/test_worker_restart.py` | 重启日志与节点计数 | DESIGNED |
| FP-FLOW-006 | P0 | 死循环、步骤和成本预算终止 | `packages/graph` | `tests/runtime/e2e/test_budget_limits.py` | escalation 事件 | DESIGNED |
| FP-FLOW-007 | P0 | 可恢复失败重试、业务失败不盲重试 | `packages/application` | `tests/core/application/test_retry_matrix.py` | 每类错误调用次数 | DESIGNED |
| FP-FLOW-008 | P1 | 显式补偿动作 | `packages/application` | `tests/core/application/test_compensation.py` | 原动作与补偿审计 | DESIGNED |
| FP-FLOW-009 | P0 | 命令使用版本检查与逻辑去重，不能直接篡改任务状态 | `packages/application` | `tests/core/contract/test_command_concurrency.py` | 冲突与重复命令断言 | DESIGNED |
| FP-AGT-001 | P0 | 知识/数据/规划 Agent 职责与工具隔离 | `packages/agent-runtime` | `tests/runtime/integration/test_agent_tool_scope.py` | 每 Agent 工具清单 | DESIGNED |
| FP-AGT-002 | P0 | OpenAI/Claude Runtime 遵循统一端口 | `packages/agent-runtime` | `tests/runtime/contract/test_runtime_port.py` | Conformance 报告 | DESIGNED |
| FP-AGT-003 | P0 | 一个节点只使用一个 Provider | `packages/graph` | `tests/runtime/integration/test_provider_selection.py` | Trace Provider 断言 | DESIGNED |
| FP-AGT-004 | P1 | Handoff 不跨审批/执行边界 | `packages/agent-runtime` | `tests/runtime/integration/test_handoff_boundary.py` | Handoff 路径与拒绝事件 | DESIGNED |
| FP-CTX-001 | P0 | 每次模型调用使用 ContextEnvelope | `packages/context` | `tests/runtime/contract/test_context_envelope.py` | Context Manifest | DESIGNED |
| FP-CTX-002 | P0 | 分层摘要区分声称、验证与推断 | `packages/context` | `tests/runtime/unit/test_summary_contract.py` | 摘要 Schema 结果 | DESIGNED |
| FP-CTX-003 | P0 | Handoff 字段与工具重新过滤 | `packages/context` | `tests/runtime/integration/test_handoff_filter.py` | Handoff Manifest | DESIGNED |
| FP-CTX-004 | P0 | 长对话硬 Token 预算 | `packages/context` | `tests/runtime/e2e/test_long_context_budget.py` | 逐层 Token 报告 | DESIGNED |
| FP-CTX-005 | P1 | Baseline/Optimized Context 消融 | `packages/evaluation` | `evals/runners/context_ablation.py` | `context-ablation.json` | DESIGNED |
| FP-MCP-001 | P0 | 所有业务工具只经 MCP Gateway | `apps/mcp-gateway` | `tests/platform/security/test_no_tool_bypass.py` | 网络策略与调用图 | DESIGNED |
| FP-MCP-002 | P0 | Tool Schema 固定与变更降级 | `apps/mcp-gateway` | `tests/platform/contract/test_schema_pinning.py` | Schema diff 事件 | DESIGNED |
| FP-MCP-003 | P0 | 写动作幂等重放 | `packages/tool-contracts` | `tests/platform/integration/test_write_idempotency.py` | 10 次请求/1 个资源 | DESIGNED |
| FP-MCP-004 | P0 | 工具结果回读验证 | `apps/mcp-gateway` | `tests/platform/integration/test_readback_verification.py` | ToolExecution VERIFIED | DESIGNED |
| FP-MCP-005 | P0 | `UNKNOWN` 结果先对账再重试 | `apps/mcp-gateway` | `tests/platform/recovery/test_unknown_outcome.py` | 0 次重复写 | DESIGNED |
| FP-MCP-006 | P0 | 目标资源绑定的短时凭据 | `apps/mcp-gateway` | `tests/platform/security/test_capability_token.py` | audience/scope/TTL 断言 | DESIGNED |
| FP-APR-001 | P0 | 审批绑定 `action_digest` | `packages/domain` | `tests/core/unit/test_approval_digest.py` | 篡改拒绝事件 | DESIGNED |
| FP-APR-002 | P0 | 申请人与审批人职责分离 | `packages/policy` | `tests/platform/security/test_separation_of_duties.py` | PDP decision | DESIGNED |
| FP-APR-003 | P0 | 权限撤销使旧审批失效 | `packages/policy` | `tests/platform/recovery/test_reauthorize_resume.py` | 恢复拒绝审计 | DESIGNED |
| FP-SEC-001 | P0 | OIDC SecurityContext 不能由模型伪造 | `packages/security` | `tests/platform/security/test_security_context.py` | 签名/引用拒绝 | DESIGNED |
| FP-SEC-002 | P0 | PostgreSQL RLS 隔离租户 | `packages/persistence` | `tests/data/security/test_rls.py` | 跨租户成功数 0 | DESIGNED |
| FP-SEC-003 | P0 | 检索前 ACL 与租户过滤 | `packages/retrieval` | `tests/acceptance/security/test_retrieval_acl.py` | 候选集合断言 | DESIGNED |
| FP-SEC-004 | P0 | RBAC + ABAC deny-overrides | `packages/policy` | `tests/platform/security/test_policy_matrix.py` | 表驱动结果 | DESIGNED |
| FP-SEC-005 | P0 | Prompt Injection 不导致越权动作 | `packages/security` | `tests/platform/security/test_prompt_injection.py` | 未授权成功数 0 | DESIGNED |
| FP-SEC-006 | P0 | Prompt/Trace/Checkpoint/日志无明文密钥 | `packages/security` | `tests/platform/security/test_secret_leakage.py` | Secret Scan 结果 0 | DESIGNED |
| FP-SEC-007 | P0 | Token 不透传且校验 audience | `apps/mcp-gateway` | `tests/platform/security/test_token_audience.py` | 错 audience 拒绝 | DESIGNED |
| FP-SEC-008 | P1 | 附件隔离、扫描、脱敏 | `packages/security` | `tests/platform/security/test_attachment_pipeline.py` | Quarantine/Observation | DESIGNED |
| FP-DATA-001 | P0 | 任务、审批、账本、Outbox 有事务边界 | `packages/persistence` | `tests/data/integration/test_transaction_boundaries.py` | 故障点一致性报告 | DESIGNED |
| FP-DATA-002 | P0 | Redis 丢失不丢业务事实 | `apps/worker` | `tests/runtime/recovery/test_redis_loss.py` | Outbox 重投证据 | DESIGNED |
| FP-DATA-003 | P0 | Outbox 事件至少一次、任务内有序且消费者可去重补洞 | `packages/persistence` | `tests/data/integration/test_outbox_sequence.py` | 重投、乱序与序号缺口报告 | DESIGNED |
| FP-OBS-001 | P0 | OTel 贯通 API/Graph/Agent/MCP | `packages/observability` | `tests/acceptance/observability/test_trace_correlation.py` | Trace Assertions | DESIGNED |
| FP-OBS-002 | P0 | Trace、Audit、Security Event 分流 | `packages/observability` | `tests/acceptance/observability/test_signal_separation.py` | 三类存储断言 | DESIGNED |
| FP-OBS-003 | P0 | Audit 不采样、追加写且查询受控 | `packages/observability` | `tests/acceptance/security/test_audit_integrity.py` | 篡改拒绝/哈希链 | DESIGNED |
| FP-EVAL-001 | P0 | 固定 120 条功能任务 | `evals/datasets/functional` | `tests/acceptance/evaluation/test_dataset_manifest.py` | 数据集卡与哈希 | DESIGNED |
| FP-EVAL-002 | P0 | 固定 36 条安全/故障任务 | `evals/datasets/safety-fault` | `tests/acceptance/evaluation/test_dataset_manifest.py` | 数据集卡与哈希 | DESIGNED |
| FP-EVAL-003 | P0 | 规则评分与 Judge 分离 | `packages/evaluation` | `tests/acceptance/evaluation/test_scorer_boundaries.py` | 评分维度映射 | DESIGNED |
| FP-EVAL-004 | P1 | Judge 有盲测人工校准 | `packages/evaluation` | `evals/runners/calibrate_judge.py` | calibration.json | DESIGNED |
| FP-EVAL-005 | P1 | 单 Agent/Multi-Agent 公平对比 | `packages/evaluation` | `evals/runners/ablation.py` | baseline 报告 | DESIGNED |
| FP-ML-001 | P2 | 800 条路由样本具备数据卡 | `evals/datasets/routing-lora` | `tests/acceptance/evaluation/test_lora_dataset.py` | 哈希/切分/去重 | DESIGNED |
| FP-ML-002 | P2 | LoRA 可灰度与回滚且不参与授权 | `packages/model-gateway` | `tests/acceptance/security/test_lora_boundary.py` | Promotion/rollback 报告 | DESIGNED |
| FP-MM-001 | P2 | 多模态只消费安全 Observation | `packages/security` | `tests/platform/security/test_multimodal_observation.py` | 原件不可达断言 | DESIGNED |
| FP-OPS-001 | P0 | Docker Compose 空环境可启动 | `infra/compose` | `tests/data/e2e/test_compose_smoke.py` | 健康检查报告 | DESIGNED |
| FP-OPS-002 | P0 | 一条命令生成完整验收包 | `scripts` / `Makefile` | `tests/acceptance/evaluation/test_acceptance_manifest.py` | manifest + REPORT | DESIGNED |
| FP-OPS-003 | P1 | Provider/MCP/策略故障降级 | `apps/worker` | `tests/acceptance/chaos/test_dependency_failures.py` | Chaos 报告 | DESIGNED |

## 3. 简历声明映射

| 声明主题 | 必须 VERIFIED 的功能 |
|---|---|
| Multi-Agent 编排 | FP-FLOW-001～007、FP-FLOW-009、FP-AGT-001～004 |
| Checkpoint/Interrupt 与重试补偿 | FP-FLOW-004、005、007、008、FP-DATA-002 |
| Context Engineering / Token 优化 | FP-CTX-001～005 |
| MCP Tool Calling / 企业安全 | FP-MCP-001～006、FP-APR-001～003、FP-SEC-001～007 |
| 多模态 Agent | FP-SEC-008、FP-MM-001 |
| LLM-as-Judge | FP-EVAL-001～005 |
| 120 + 36 测试集 | FP-EVAL-001、FP-EVAL-002、FP-OPS-002 |
| 800 条 LoRA / Macro-F1 | FP-ML-001、FP-ML-002 |
| OpenTelemetry 可观测 | FP-OBS-001～003 |
| 企业级可部署 | FP-FLOW-009、FP-DATA-001～003、FP-OPS-001～003 |

某一行未全部 `VERIFIED` 时，简历只能使用“设计”或删除该声明。
