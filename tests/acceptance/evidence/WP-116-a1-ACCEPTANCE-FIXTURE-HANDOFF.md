# WP-116-a1 Acceptance Fixture Handoff

## 基本信息

- Chain / Step：`CHAIN-M10-KNOWLEDGE-01` / `M10-06C-S4-ACCEPTANCE-FIXTURE-MIGRATION`
- Work Package / Attempt：`WP-116-R2` / `WP-116-a1-acceptance-fixture`
- Owner / 返回：`S4-QUALITY` / `S1-ARCH`
- 执行：`ORDERED / IMPLEMENTATION`，风险 `R2`
- Base：`75902004e339d05eeca3a9e6a376427fa12f0fad`
- Feature：`FP-KNOW-010`、`FP-SEC-001`
- ContractSet：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 结果：`PASS_HANDOFF`

## 消费者门禁

- 消费前 S4 Head 为 `7422e8f831f5488f6fb1e25ef2f4b7011e5c116f`，工作树 clean，
  且是 Base 的祖先；ContractSet digest 匹配。
- 只执行 `git merge --ff-only 75902004e339d05eeca3a9e6a376427fa12f0fad`，随后精确到达
  Base；未 rebase/reset 或复制文件绕过线性门禁。
- 复用 S1 对 29 个旧消费者失败的定向归因；未重跑 Owner 产品测试、全仓、Compose、
  Migration 或 Release。

## 完成内容

- Provider Runtime 的 credential-shaped LiteLLM wire 输入/输出期望从旧
  `INVALID_OUTPUT` 迁移到集中 DLP 的稳定 `CONTENT_BLOCKED`；保留 Transport 未调用、
  Structured Output 为空以及 Secret 不进入 `repr`/错误的断言。嵌套 `session_ref` 等结构错误
  仍保持 `INVALID_OUTPUT`，未混淆 DLP 与 Schema 错误。
- VPN Knowledge Fixture 不再预造缺字段 Capability。每次真实 `GatewayCall` 到达 Probe 后，
  从可信 SecurityContext 与 PlannedAction 绑定 `context_hash`、`tool_name`、
  `resource_digest`、`action_digest`、`policy_version`、固定 execution、`INVOKE` use 和
  use/action/execution 派生的 `token_id_hash`。
- VPN Ticket Fixture 对同一真实 Tool Action 分别生成 `INVOKE` 与 `READBACK` Capability；
  READBACK 只在 Invoke 成功后生成，两个 Token Hash 按 use 隔离。ToolResult 与 Capability
  使用同一 execution ID。
- 两个 Probe 都在实际调用前执行强绑定自检，逐字段对照 SecurityContext、Tool、Resource、
  Action、Policy、Execution、Use 和 Token Hash。原 tenant/ACL/workload/purpose/classification
  安全负例、重复投递、UNKNOWN、readback、恢复及幂等断言均保持并通过。
- 未把任何 Capability 字段设为 optional，未恢复 legacy Handle，未修改 Capability Issuer、
  consume/replay 机制、产品 Adapter 或公共 Contract。

## 变更路径

- `tests/acceptance/provider_runtime/test_provider_runtime_blackbox.py`
- `tests/acceptance/vpn/blackbox.py`
- `tests/acceptance/vpn/test_vpn_write_closed_loop.py`
- `tests/acceptance/evidence/WP-116-a1-ACCEPTANCE-FIXTURE-HANDOFF.md`

没有产品代码、公共 Contract、根共享文件、Dataset、固定分母或其他角色测试变化。

## 验证

| 检查 | 结果 |
|---|---|
| Provider Runtime 目标文件 | PASS：`31 passed`；原 1 failure 闭合 |
| `pytest --import-mode=importlib tests/acceptance/vpn -q` | PASS：`31 passed`；原 28 failures 闭合 |
| Ruff：provider_runtime + VPN | PASS |
| 变更路径 `flowpilot_security.scan_secret_material` | PASS：`0 findings` |
| 输出泄漏 | PASS：Provider/VPN 定向断言中 Secret、私有投影、错误和 `repr` 泄漏均为 0 |
| `git diff --check` | PASS |

实际共闭合 S1 定向复现的 `29/29` 个旧 Fixture failures。未运行全仓测试。

## 风险与下一步

- 本 Attempt 只迁移 S4 消费端 Fixture，不声称重新验证 S5/S3/S6 产品内部实现。
- `BLOCKERS=none`；无新增 P0/P1，无 Contract、Dataset 或 Feature 状态变化。
- 按指令不唤醒 S5/S7；提交后只返回 S1。
- `SUBAGENTS_USED=0`；`LEARNING_CANDIDATE=none`。

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M10-KNOWLEDGE-01
STEP_ID=M10-06C-S4-ACCEPTANCE-FIXTURE-MIGRATION
ATTEMPT_ID=WP-116-a1-acceptance-fixture
INPUT_HEAD=75902004e339d05eeca3a9e6a376427fa12f0fad
NEW_HEAD=<this-handoff-commit>
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/acceptance/evidence/WP-116-a1-ACCEPTANCE-FIXTURE-HANDOFF.md
NEXT_ROLE=S1-ARCH
ESCALATE_TO_S1=no
SUBAGENTS_USED=0
USER_INPUT_REQUIRED=none
```
