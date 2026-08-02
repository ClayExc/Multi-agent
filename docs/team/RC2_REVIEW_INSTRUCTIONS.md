# FlowPilot rc2 五会话实现基线复审指令

> 历史入口：本文件固定复现 `0a82…` 轮次。当前复审目标已迁移到
> [`RC2_DELTA_REVIEW_1CAD07BD.md`](./RC2_DELTA_REVIEW_1CAD07BD.md)，不得复用本文件的旧摘要。

> 状态：摘要 `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc` 的五角色复审已经完成。本文件保留为复现入口；被摘要覆盖的内容变化后必须生成新摘要并重新执行。

## 固定评审目标

```text
CONTRACT_SET_ID=flowpilot-m0-contracts-v1-rc2
VERSION=1.0.0-rc.2
REVIEWED_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
MODE=READ_ONLY
```

本轮只确认 `candidate` 能否成为实现基线，不等同于发布级 `frozen`。S2、S3、S4、S5、S6 必须审查同一摘要；任一内容哈希、Schema、Artifact、`required_reviewers` 或 `freeze_requirements` 改变后，全部结论失效。

相对上一轮 `babf…4d94`，本轮变更固定为：

- 将 Approval 官方正例的 `tool_schema_hash` 对齐 PlannedAction Tool Schema Hash。
- Approval 与 ToolRequest 语义门禁强制绑定 Tool Schema Hash。
- Approval、PlannedAction、PolicyDecision 的 `policy_version` 与 `expires_at` 必须一致。
- 新增七个 Schema 合法的跨对象语义负例，语义负例由 36 个增至 43 个。
- `contracts/README.md` 的评审者说明由三条修正为 S2～S6 五条。

上一摘要的 S2/S4/S5/S6 `ACCEPT` 与 S3 `REJECT` 均只作为历史处置记录，不能迁移；五角色必须对本摘要重新返回结论。历史证据见 `docs/review/WP-000-RC2-REVIEW-BABF5689.md`。

## 共同规则

1. 禁止修改文件、禁止 Git 操作、禁止创建分支或提交。
2. 按 `AGENTS.md` 的顺序阅读，并额外阅读 `WORKFLOW.md`、本角色 Session Contract、对应 Work Package、WP-000、ContractSet、rc1 裁决与 rc2 就绪报告。
3. 核对 `contracts/contract-set.v1.json.content_digest` 与指令摘要完全一致。
4. 尽可能运行：

```text
python contracts/conformance/validate.py
```

若环境缺少 `jsonschema>=4.23`，报告 `GATE=NOT_RUN:<原因>`，不得写成通过。S1 已验证的参考输出为：

```text
CONTRACT_CONFORMANCE_OK schemas=20 cases=35 positive=18 negative=17 mutation_cases=19 mutation_positive=3 mutation_negative=16 semantic_cases=43 semantic_positive=0 semantic_negative=43 audit_chain_cases=5 audit_chain_positive=1 audit_chain_negative=4 manifest_cases=21 manifest_positive=1 manifest_negative=20 features=52
```

5. 只返回：

```text
SESSION_ROLE=<role>
VERDICT=ACCEPT|ACCEPT_WITH_RFC|REJECT
REVIEWED_CONTENT_DIGEST=sha256:...
GATE=PASS|FAIL|NOT_RUN:<reason>
BLOCKERS:
- <none 或 finding>
ADVISORIES:
- <none 或 finding>
IMPLEMENTABILITY:
- <本角色能否按该摘要启动指定工作包>
```

只有无阻断的 `VERDICT=ACCEPT` 才计入实现基线。返回结论后停止，不得开始开发；开发必须等待 S1 的激活提交、独立 Worktree 和 `MODE=IMPLEMENTATION` 指令。

## S2-RUNTIME

复制以下完整内容到 S2：

```text
SESSION_ROLE=S2-RUNTIME
WORK_PACKAGE=WP-000-RC2-S2-IMPLEMENTATION-BASELINE-REVIEW
TARGET_WORK_PACKAGE=WP-010
MODE=READ_ONLY
REVIEWED_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc

你是 FlowPilot 的 S2-RUNTIME。当前只做只读实现性复审，禁止修改文件、禁止 Git、禁止提前开发。

严格按 AGENTS.md 阅读顺序，并额外阅读：
- WORKFLOW.md
- docs/team/session-contracts/S2-RUNTIME.md
- docs/team/work-packages/WP-000-m0-contract-freeze.md
- docs/team/work-packages/WP-010-runtime-bootstrap.md
- docs/review/WP-000-RC1-DISPOSITION.md
- docs/review/WP-000-RC2-READINESS.md
- contracts/contract-set.v1.json
- contracts/README.md
- docs/architecture/AGENT_RUNTIME.md
- docs/architecture/CONTEXT_ENGINEERING.md
- docs/decisions/ADR-0001-orchestration-boundary.md
- docs/decisions/ADR-0003-task-command-event-protocol.md
- contracts/conformance/validate.py
- contracts/conformance/rc2-cases.json

重点复核 Request/Context/SecurityContext 绑定、Task/Command/Event 语义、Checkpoint/Interrupt/恢复、Handoff 重建、Provider Session 隔离、Tool Proposal 非权威边界，以及 WP-010 与 S5 Application Port、S6 Persistence Port 的接口是否可确定性实现。

核对 content_digest，尽可能运行 python contracts/conformance/validate.py，然后严格按 docs/team/RC2_REVIEW_INSTRUCTIONS.md 的共同返回格式输出。只有 ACCEPT 计入基线；输出后停止。
```

## S3-PLATFORM

复制以下完整内容到 S3：

```text
SESSION_ROLE=S3-PLATFORM
WORK_PACKAGE=WP-000-RC2-S3-IMPLEMENTATION-BASELINE-REVIEW
TARGET_WORK_PACKAGE=WP-020
MODE=READ_ONLY
REVIEWED_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc

你是 FlowPilot 的 S3-PLATFORM。当前只做只读实现性复审，禁止修改文件、禁止 Git、禁止提前开发。

严格按 AGENTS.md 阅读顺序，并额外阅读：
- WORKFLOW.md
- docs/team/session-contracts/S3-PLATFORM.md
- docs/team/work-packages/WP-000-m0-contract-freeze.md
- docs/team/work-packages/WP-020-platform-bootstrap.md
- docs/review/WP-000-RC1-DISPOSITION.md
- docs/review/WP-000-RC2-READINESS.md
- contracts/contract-set.v1.json
- contracts/README.md
- docs/decisions/ADR-0002-safe-side-effects.md
- docs/decisions/ADR-0003-task-command-event-protocol.md
- docs/decisions/ADR-0004-reproducible-acceptance-and-freeze.md
- contracts/conformance/validate.py
- contracts/conformance/rc2-cases.json

重点复核 SecurityContext 与 PolicyDecision 精确绑定、RBAC+ABAC deny-overrides、审批摘要/Schema/策略/过期绑定、MCP Gateway 单一工具边界、写幂等/回读/UNKNOWN 对账、Audit/Security 分流，以及 WP-020 与 S6 执行账本 Port 的接口是否可确定性实现。

核对 content_digest，尽可能运行 python contracts/conformance/validate.py，然后严格按 docs/team/RC2_REVIEW_INSTRUCTIONS.md 的共同返回格式输出。只有 ACCEPT 计入基线；输出后停止。
```

## S4-QUALITY

复制以下完整内容到 S4：

```text
SESSION_ROLE=S4-QUALITY
WORK_PACKAGE=WP-000-RC2-S4-IMPLEMENTATION-BASELINE-REVIEW
TARGET_WORK_PACKAGE=WP-030
MODE=READ_ONLY
REVIEWED_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc

你是 FlowPilot 的 S4-QUALITY。当前只做只读实现性复审，禁止修改文件、禁止 Git、禁止提前开发。

严格按 AGENTS.md 阅读顺序，并额外阅读：
- WORKFLOW.md
- docs/team/session-contracts/S4-QUALITY.md
- docs/team/work-packages/WP-000-m0-contract-freeze.md
- docs/team/work-packages/WP-030-quality-bootstrap.md
- docs/review/WP-000-RC1-DISPOSITION.md
- docs/review/WP-000-RC2-READINESS.md
- contracts/contract-set.v1.json
- contracts/README.md
- docs/acceptance/ACCEPTANCE.md
- docs/acceptance/TRACEABILITY.md
- docs/acceptance/traceability.v1.json
- docs/decisions/ADR-0004-reproducible-acceptance-and-freeze.md
- contracts/registries/evaluation-registry.v1.json
- contracts/registries/evaluation-dataset-manifest.v1.json
- contracts/registries/evaluation-fixture-manifest.v1.json
- contracts/conformance/validate.py
- contracts/conformance/rc2-cases.json

重点复核 120/36 固定分母、确定性安全 Gate 与 Judge 边界、Feature/Evidence 独立验证、ContractSet 五评审者门禁、Audit 链负例，以及 S2/S3/S5/S6 的黑盒行为能否由 WP-030 独立验证。

核对 content_digest，尽可能运行 python contracts/conformance/validate.py，然后严格按 docs/team/RC2_REVIEW_INSTRUCTIONS.md 的共同返回格式输出。只有 ACCEPT 计入基线；输出后停止。
```

## S5-CORE

复制以下完整内容到 S5：

```text
SESSION_ROLE=S5-CORE
WORK_PACKAGE=WP-000-RC2-S5-IMPLEMENTATION-BASELINE-REVIEW
TARGET_WORK_PACKAGE=WP-011
MODE=READ_ONLY
REVIEWED_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc

你是 FlowPilot 的 S5-CORE。当前只做只读实现性复审，禁止修改文件、禁止 Git、禁止提前开发。

严格按 AGENTS.md 阅读顺序，并额外阅读：
- WORKFLOW.md
- docs/team/session-contracts/S5-CORE.md
- docs/team/work-packages/WP-000-m0-contract-freeze.md
- docs/team/work-packages/WP-011-core-bootstrap.md
- docs/review/WP-000-RC1-DISPOSITION.md
- docs/review/WP-000-RC2-READINESS.md
- contracts/contract-set.v1.json
- contracts/README.md
- docs/decisions/ADR-0001-orchestration-boundary.md
- docs/decisions/ADR-0003-task-command-event-protocol.md
- contracts/jsonschema/task.v1.schema.json
- contracts/jsonschema/task-command.v1.schema.json
- contracts/jsonschema/task-event.v1.schema.json
- contracts/jsonschema/planned-action.v1.schema.json
- contracts/jsonschema/approval.v1.schema.json
- contracts/jsonschema/security-context-ref.v1.schema.json
- contracts/conformance/validate.py
- contracts/conformance/rc2-cases.json

重点复核纯 Domain 不依赖框架、Task 状态不变量、Command Intake 的版本/去重/摘要/SecurityContext 绑定、Approval action_digest、稳定 API 错误，以及 WP-011 向 S2 暴露 Execution Port、向 S6 暴露 Repository/UoW Port 是否足够且不复制公共契约。

核对 content_digest，尽可能运行 python contracts/conformance/validate.py，然后严格按 docs/team/RC2_REVIEW_INSTRUCTIONS.md 的共同返回格式输出。只有 ACCEPT 计入基线；输出后停止。
```

## S6-DATA

复制以下完整内容到 S6：

```text
SESSION_ROLE=S6-DATA
WORK_PACKAGE=WP-000-RC2-S6-IMPLEMENTATION-BASELINE-REVIEW
TARGET_WORK_PACKAGE=WP-021
MODE=READ_ONLY
REVIEWED_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc

你是 FlowPilot 的 S6-DATA。当前只做只读实现性复审，禁止修改文件、禁止 Git、禁止提前开发。

严格按 AGENTS.md 阅读顺序，并额外阅读：
- WORKFLOW.md
- docs/team/session-contracts/S6-DATA.md
- docs/team/work-packages/WP-000-m0-contract-freeze.md
- docs/team/work-packages/WP-021-data-bootstrap.md
- docs/review/WP-000-RC1-DISPOSITION.md
- docs/review/WP-000-RC2-READINESS.md
- contracts/contract-set.v1.json
- contracts/README.md
- docs/decisions/ADR-0002-safe-side-effects.md
- docs/decisions/ADR-0003-task-command-event-protocol.md
- docs/decisions/ADR-0004-reproducible-acceptance-and-freeze.md
- contracts/jsonschema/task.v1.schema.json
- contracts/jsonschema/task-command.v1.schema.json
- contracts/jsonschema/task-event.v1.schema.json
- contracts/jsonschema/tool-request.v1.schema.json
- contracts/jsonschema/tool-result.v1.schema.json
- contracts/jsonschema/audit-event.v1.schema.json
- contracts/conformance/validate.py
- contracts/conformance/rc2-cases.json

重点复核 PostgreSQL 业务事实源、tenant_id/RLS fail-closed、Task/Approval/Inbox/Outbox/执行账本事务边界、事件任务内有序与可去重补洞、Redis 可丢失恢复、UNKNOWN 对账，以及 WP-021 对 S5 Repository Port、S2 Checkpoint/Lease、S3 Ledger Port 的实现边界是否充分。

核对 content_digest，尽可能运行 python contracts/conformance/validate.py，然后严格按 docs/team/RC2_REVIEW_INSTRUCTIONS.md 的共同返回格式输出。只有 ACCEPT 计入基线；输出后停止。
```
