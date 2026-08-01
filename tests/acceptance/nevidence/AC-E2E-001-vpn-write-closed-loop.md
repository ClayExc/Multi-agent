# AC-E2E-001 验收记录 — VPN 工单写路径垂直闭环（g3）

- 目标: `g3 VPN 安全 Ticket 写入闭环（审批→Gateway 写→Ledger，AC-E2E-001）`
- Worktree: `E:\workspace\Multi-agent\.flow\wt\g2`（branch `flow-lite/g2`）
- 日期: 2026-08-01
- 实现角色: S3-PLATFORM（Gateway 写路径/Policy/模拟 Ticket MCP/Ledger 审计断言）
  + S5-CORE（领域审批接线、应用审批用例、API 审批决策入口）
  + S2-RUNTIME（受限子任务：apps/worker 写节点模块接线，S1 已预授权）
- 独立验证: S4-QUALITY 黑盒负向测试已按 AGENTS.md §12 编写于 `tests/platform/`；
  S1 门禁审查与 TRACEABILITY 状态提升待 S1/S4 执行（docs/acceptance 为 S1 独占路径，本包未修改）
- 测试命令: `uv run --frozen python -m pytest -q` → **285 passed**
  补充命令: `uv run --frozen python -m pytest tests/acceptance/vpn tests/acceptance/observability -q` → **36 passed**

## 1. AC-E2E-001 确定性断言逐条对照（写闭环部分，步骤 6–8）

| 断言（ACCEPTANCE.md §5） | 证据测试 | 结果 |
|---|---|---|
| 意图、必填字段和缺失字段符合领域包 | `tests/acceptance/vpn/test_vpn_readonly_candidate.py`（20 条固定 Case，`assert.intent.matches.v1`）；写升级观察契约见 `test_vpn_write_closed_loop.py::_resolved_observation`（intent `vpn_escalation`，字段 `symptom_code/platform/environment/tried_steps`，缺失字段为空） | PASS |
| Trace 中两个只读分支时间区间有重叠 | 既有 readonly 验收 Case（`test_vpn_readonly_candidate.py`，并行分支由 LangGraph 拓扑保证） | PASS（既有） |
| 过期 SOP 未进入最终证据 | `test_vpn_readonly_candidate.py`（`expired_knowledge_record` Case，`assert.citation.valid.v1`） | PASS（既有） |
| 工单参数包含用户已尝试步骤 | `test_vpn_write_closed_loop.py::test_ac_e2e_001_write_closed_loop_approve_write_verify_audit`：`write_call.request.planned_action.arguments["summary"] == TRIED_STEPS` | PASS |
| 相同执行命令重放十次，上游仅一个工单 | `test_vpn_write_closed_loop.py::test_ac_e2e_001_replayed_command_creates_one_ticket_only`（`logical_ticket_count == 1`）；Gateway 级：`tests/platform/integration/test_write_idempotency.py::test_same_write_command_replayed_ten_times_creates_one_resource`（FP-MCP-003） | PASS |
| `ToolExecution` 达到 `VERIFIED` | `test_vpn_write_closed_loop.py` 主用例（probe 回读 `VerificationMethod.READ_BACK`）；`tests/platform/integration/test_write_idempotency.py::test_approved_write_reaches_verified_with_complete_audit_correlation`（FP-MCP-004：ledger VERIFIED、outbox 1、审计 1） | PASS |
| 最终回答包含真实工单 ID | `test_vpn_write_closed_loop.py` 主用例：`artifact.content` 含 `ticket_id`，citations source_ref 为 `ticket://tenant-a/<id>` | PASS |
| 审计可关联任务、策略、动作摘要、执行和结果 | `tests/platform/integration/test_write_idempotency.py` 主用例：audit 断言 `task_id / policy_decision_id / action_digest / approval_id / tool_execution_id / result` 六字段 | PASS |

## 2. tests/platform 黑盒负向全绿（20 个新用例）

| 文件（SHA-256） | 覆盖 |
|---|---|
| `tests/platform/integration/test_write_idempotency.py` `f027cf634e92758a798985c1486b4636e84e29c3c0efddc52029970b1f9eb553` | FP-MCP-003 十次重放/一个资源；FP-MCP-004 回读 VERIFIED + 审计关联；重放不重复上游调用；回读不匹配永报 UNKNOWN |
| `tests/platform/recovery/test_unknown_outcome.py` `b3d1a63ae9d3acf60f880739fbbfc0f113834bd6edd34990829400da12e31869` | FP-MCP-005 超时已执行→UNKNOWN→对账 VERIFIED 0 重复；未执行→CONFIRMED_NOT_EXECUTED→单次重试；UNKNOWN 不盲重试；reconcile 仅限写 |
| `tests/platform/security/test_separation_of_duties.py` `361dadf90d8ddb96ba2a3d920a99277b1b735c6920cbf78f4489fc5863292033` | FP-APR-001 参数篡改/策略篡改阻断；FP-APR-002 审批人无当前角色阻断（含 audit/security 对）；审批跨主体/跨动作重放阻断；FP-SEC-007 错 audience 阻断；跨租户写 0（不变量 12）；审批不可附着于不要求审批的策略 |
| `tests/platform/recovery/test_reauthorize_resume.py` `b16e8cad8ec81a0148352354ec00ac8aac32c0b26ad5e44fba7111ed599d10b1` | FP-APR-003 角色撤销→执行拒绝+审计保留；REVOKED 记录无效；过期审批拒绝；重新授权后恢复写路径 |

## 3. Trace/Audit/Security Event 分流断言

`tests/acceptance/observability/test_signal_separation.py`
`a4e8596344dd3afa13bd25d150d44e49da64db51229728729d5c49d3c6606486`（既有，FP-OBS-002）
— Trace/Audit/Security 路由到不同目标；拒绝路径的 audit/security 配对链接断言见
`tests/platform/security/test_separation_of_duties.py`（`security.audit_event_id == audit.event_id`）。

## 4. FP 状态提升证据（哈希绑定，待 S1/S4 复核提升）

| FP ID | 目标代码（SHA-256） | 目标测试（SHA-256） |
|---|---|---|
| FP-MCP-003 写动作幂等重放 | `apps/mcp-gateway/src/flowpilot_mcp_gateway/gateway.py`（既有）+ `mcp-servers/ticket/src/flowpilot_mcp_ticket/server.py` `f0be0e77f606027daa5e7558eb27ed0a4ec2e21675d54a8d7d31096eb26f4054` | `tests/platform/integration/test_write_idempotency.py` `f027cf634e92758a798985c1486b4636e84e29c3c0efddc52029970b1f9eb553` |
| FP-MCP-004 工具结果回读验证 | 同上 + `apps/worker/src/flowpilot_worker/vpn_write.py` `55842b074039a470c7c3c70e4d6708069ccfba953926445402db977bae143c8d` | 同上 |
| FP-MCP-005 UNKNOWN 先对账再重试 | `apps/mcp-gateway/src/flowpilot_mcp_gateway/gateway.py`（既有 reconcile 路径） | `tests/platform/recovery/test_unknown_outcome.py` `b3d1a63ae9d3acf60f880739fbbfc0f113834bd6edd34990829400da12e31869` |
| FP-APR-001 审批绑定 action_digest | `packages/application/src/flowpilot_application/approvals.py` `3133dca2bd65b4b732c820f1c5669c42067c58d0244e6a381ee88710cb329cb5` + `apps/worker/src/flowpilot_worker/vpn_write.py` | `tests/platform/security/test_separation_of_duties.py` `361dadf90d8ddb96ba2a3d920a99277b1b735c6920cbf78f4489fc5863292033` |
| FP-APR-002 申请人与审批人职责分离 | `packages/application/src/flowpilot_application/approvals.py` + `apps/api/src/flowpilot_api/app.py` `c783bb8129a00a4ff5c4dc580b4c6dde065d494f21b3bc98570926d9bd03fde3` | 同上 |
| FP-APR-003 权限撤销使旧审批失效 | `apps/worker/src/flowpilot_worker/vpn_write.py` + `packages/application/src/flowpilot_application/approvals.py`（revoke） | `tests/platform/recovery/test_reauthorize_resume.py` `b16e8cad8ec81a0148352354ec00ac8aac32c0b26ad5e44fba7111ed599d10b1` |

## 5. 安全扫描

- Secret Scan（api_key/secret/password/bearer/token/私钥/AWS/SK- 模式扫描新代码与测试）：**0 findings**
  （仅有 `LeaseToken`/`token_budget`/ContextVar token 等标识符误报，无凭据字面量）
- 无真实凭据、无生产网络、无外部写入：全部为内存模拟 Ticket MCP（`mcp-servers/ticket`）与短时
  CapabilityHandle（TTL 5 分钟、audience 绑定、scope 最小化）。

## 6. 已知风险与移交

- `tests/acceptance/studio/test_agent_server_blackbox.py` 4 个错误为环境预存问题
  （LangGraph Studio Agent Server 30s 未就绪），与本次改动无关（stash 后同样失败），不属于本包回归。
- 写升级领域包（`domain-packs/it-service` 新增 `vpn_escalation` intent 与写 Case 数据集）需要 S1 分配
  新 FP ID，本次以测试内固定契约代替，未改领域包文件。
- 新写 Case（evals 数据集）按目标「新增写 Case 由 S1 分配 FP ID」保留给 S1/S4 后续包。
- TRACEABILITY 状态提升（DESIGNED→VERIFIED）需 S4 独立复核 + S1 门禁后执行；本包不修改
  `docs/acceptance/**`（S1 独占路径）。
