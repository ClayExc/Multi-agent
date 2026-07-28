# FlowPilot rc2 三会话实现基线复审指令

## 固定评审目标

```text
CONTRACT_SET_ID=flowpilot-m0-contracts-v1-rc2
VERSION=1.0.0-rc.2
REVIEWED_CONTENT_DIGEST=sha256:a8de1d2bd74d7bd507f766829c0e31e2d60f29d1904aabb502a47bcbd505f8ec
MODE=READ_ONLY
```

本轮评审用于确认该 `candidate` 能否成为实现基线，不等同于发布级 `frozen`。三会话必须审查同一摘要；任一内容哈希、Schema、Artifact 或 `freeze_requirements` 改变后，本轮结论失效。

共同规则：

1. 禁止修改文件，禁止 Git 操作，禁止创建分支或提交。
2. 依次阅读 `README.md`、`STRUCTURE.md`、`docs/acceptance/TRACEABILITY.md`、`docs/team/CODEX_SESSIONS.md`、本角色 Session Contract、WP-000、ContractSet、rc1 裁决、rc2 就绪报告及角色相关 ADR。
3. 核对 `contracts/contract-set.v1.json.content_digest` 与上方摘要完全一致。
4. 尽可能运行：

```text
python contracts/conformance/validate.py
```

若当前环境没有 `jsonschema>=4.23`，报告 `GATE=NOT_RUN:<原因>`，不得把未运行写成通过。S1 已验证的参考输出是：

```text
CONTRACT_CONFORMANCE_OK schemas=20 cases=35 positive=18 negative=17 mutation_cases=18 mutation_positive=3 mutation_negative=15 semantic_cases=36 semantic_positive=0 semantic_negative=36 audit_chain_cases=5 audit_chain_positive=1 audit_chain_negative=4 manifest_cases=20 manifest_positive=1 manifest_negative=19 features=52
```

5. 只返回以下结构；只有无阻断的 `VERDICT=ACCEPT` 才计入实现基线：

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
- <本角色可否按该摘要开始 WP-010/020/030>
```

## S2-RUNTIME 指令

复制到 S2 会话：

```text
SESSION_ROLE=S2-RUNTIME
WORK_PACKAGE=WP-000-RC2-S2-IMPLEMENTATION-BASELINE-REVIEW
MODE=READ_ONLY
REVIEWED_CONTENT_DIGEST=sha256:a8de1d2bd74d7bd507f766829c0e31e2d60f29d1904aabb502a47bcbd505f8ec

你是 FlowPilot 的 S2-RUNTIME。禁止修改文件、禁止 Git。严格按 AGENTS.md 阅读顺序，并额外阅读：
- docs/team/session-contracts/S2-RUNTIME.md
- docs/team/work-packages/WP-000-m0-contract-freeze.md
- docs/review/WP-000-RC1-DISPOSITION.md
- docs/review/WP-000-RC2-READINESS.md
- contracts/contract-set.v1.json
- contracts/README.md
- docs/architecture/AGENT_RUNTIME.md
- docs/architecture/CONTEXT_ENGINEERING.md
- docs/decisions/ADR-0001-orchestration-boundary.md
- docs/decisions/ADR-0003-task-command-event-protocol.md
- contracts/jsonschema/agent-run-request.v1.schema.json
- contracts/jsonschema/agent-run-result.v1.schema.json
- contracts/jsonschema/context-envelope.v1.schema.json
- contracts/jsonschema/task.v1.schema.json
- contracts/jsonschema/task-command.v1.schema.json
- contracts/jsonschema/task-event.v1.schema.json
- contracts/jsonschema/tool-result.v1.schema.json
- contracts/conformance/validate.py
- contracts/conformance/rc2-cases.json

重点复核：
1. Request/Context/SecurityContext 的 Task、Tenant、Agent、Purpose、Provider、分类 ceiling 与 Token 预算绑定是否可确定性实现。
2. Task 状态字段组合、创建命令预分配 task_id、command_digest 重算、Command 与 SecurityContext 的租户/主体/用途绑定、版本/同版本槽位和 Event sequence/task_version 语义。
3. Runtime 错误映射、Provider Session 与 Checkpoint 分离、Handoff 重新构建和 Tool Proposal 非权威边界。
4. ToolResult 的 request/policy/operation 回绑、写回读证据及 UNKNOWN/重试恢复语义。
5. 正例基线先通过、语义负例不会因基线已有错误而假通过。

按本文件共同格式返回；只有 ACCEPT 计入基线。
```

## S3-PLATFORM 指令

复制到 S3 会话：

```text
SESSION_ROLE=S3-PLATFORM
WORK_PACKAGE=WP-000-RC2-S3-IMPLEMENTATION-BASELINE-REVIEW
MODE=READ_ONLY
REVIEWED_CONTENT_DIGEST=sha256:a8de1d2bd74d7bd507f766829c0e31e2d60f29d1904aabb502a47bcbd505f8ec

你是 FlowPilot 的 S3-PLATFORM。禁止修改文件、禁止 Git。严格按 AGENTS.md 阅读顺序，并额外阅读：
- docs/team/session-contracts/S3-PLATFORM.md
- docs/team/work-packages/WP-000-m0-contract-freeze.md
- docs/review/WP-000-RC1-DISPOSITION.md
- docs/review/WP-000-RC2-READINESS.md
- contracts/contract-set.v1.json
- contracts/README.md
- docs/decisions/ADR-0002-safe-side-effects.md
- docs/decisions/ADR-0003-task-command-event-protocol.md
- docs/decisions/ADR-0004-reproducible-acceptance-and-freeze.md
- contracts/jsonschema/security-context-ref.v1.schema.json
- contracts/jsonschema/policy-decision.v1.schema.json
- contracts/jsonschema/approval.v1.schema.json
- contracts/jsonschema/planned-action.v1.schema.json
- contracts/jsonschema/tool-request.v1.schema.json
- contracts/jsonschema/tool-result.v1.schema.json
- contracts/jsonschema/task-event.v1.schema.json
- contracts/jsonschema/audit-event.v1.schema.json
- contracts/jsonschema/security-event.v1.schema.json
- contracts/conformance/validate.py
- contracts/conformance/rc2-cases.json

重点复核：
1. 用户主体、Agent 工作负载主体、Tenant、Purpose、SecurityContext 引用+哈希和 PolicyDecision 精确绑定。
2. 强类型 obligation、deny-overrides、单审批、approver != requester、摘要/Schema/策略/过期绑定。
3. ToolRequest/ToolResult 写路径、幂等、回读、权威未执行证明、UNKNOWN 对账和重复写防护。
4. TaskEvent 生产者与 run_id，Audit/Security 分流、双向关联和无明文敏感信息。
5. Audit RFC 8785 前像、可信 Stream/Tenant、事件哈希重算、序号连续、重复/缺口/跨流负例。

按本文件共同格式返回；只有 ACCEPT 计入基线。
```

## S4-QUALITY 指令

复制到 S4 会话：

```text
SESSION_ROLE=S4-QUALITY
WORK_PACKAGE=WP-000-RC2-S4-IMPLEMENTATION-BASELINE-REVIEW
MODE=READ_ONLY
REVIEWED_CONTENT_DIGEST=sha256:a8de1d2bd74d7bd507f766829c0e31e2d60f29d1904aabb502a47bcbd505f8ec

你是 FlowPilot 的 S4-QUALITY。禁止修改文件、禁止 Git。严格按 AGENTS.md 阅读顺序，并额外阅读：
- docs/team/session-contracts/S4-QUALITY.md
- docs/team/work-packages/WP-000-m0-contract-freeze.md
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
- contracts/jsonschema/evaluation-case.v1.schema.json
- contracts/jsonschema/evaluation-registry.v1.schema.json
- contracts/jsonschema/evaluation-dataset-manifest.v1.schema.json
- contracts/jsonschema/evaluation-fixture-manifest.v1.schema.json
- contracts/jsonschema/feature-traceability.v1.schema.json
- contracts/jsonschema/contract-set.v1.schema.json
- contracts/conformance/validate.py
- contracts/conformance/rc2-cases.json

重点复核：
1. EvaluationCase 对 Dataset/Fixture/Registry 的 ID、版本、哈希绑定以及 Case 内 Assertion/终态/工具集合一致性。
2. 120/36 配额、类别数量、all_declared_cases 分母以及 failed/skipped/quarantined 均计失败。
3. 安全类别必需确定性 Gate，Judge 只能 semantic_only，Frozen Judge 引用和 Prompt 哈希可解析。
4. Feature 的父 ID、独立验证角色、结构化 Evidence、文件存在与 SHA-256、VERIFIED/RELEASED 状态门禁。
5. ContractSet content_digest 与 Review Attestation 是否解决可变评审包络问题；candidate 实现基线与发布级 frozen 是否无循环依赖。
6. Audit 两事件正链和 tamper/gap/duplicate/cross-stream 负例，以及 UTF-8/LF/无 BOM/重复 JSON key 门禁。

按本文件共同格式返回；只有 ACCEPT 计入基线。
```
