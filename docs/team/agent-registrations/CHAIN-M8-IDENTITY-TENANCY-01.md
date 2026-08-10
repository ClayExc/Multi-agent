# CHAIN-M8-IDENTITY-TENANCY-01 Agent 注册表

```text
REGISTRY_STATUS=ACTIVE
REGISTRY_MODE=minimum-capability-set
EXECUTION_MODE=PARALLEL_JOIN_ORDERED
MAX_ACTIVE_PRINCIPALS=2
MAX_ACTIVE_WRITERS=2
MAX_SUBAGENTS_PER_PRINCIPAL=2
COMMUNICATION=event-driven
SELECTED=identity-security-builder,identity-data-builder,identity-api-builder,identity-runtime-builder,identity-experience-builder,m8-identity-verifier
CURRENTLY_ACTIVE=identity-security-builder,identity-data-builder
NOT_YET_ACTIVATED=identity-api-builder,identity-runtime-builder,identity-experience-builder,m8-identity-verifier
```

M8 跨越六个路径 Owner，因此里程碑角色并集无法再缩小；调度仍只激活当前并行层的
一到两个主 Agent。未激活者不接收背景或普通进度。

| Agent ID | Role | 能力与写入范围 | 当前状态 | 退出条件 |
|---|---|---|---|---|
| identity-security-builder | S3-PLATFORM | OIDC/JWKS、ContextSource、Workload Auth、Gateway；`packages/security/**`、`apps/mcp-gateway/**`、`tests/platform/**` | ACTIVE | WP-082 clean Handoff |
| identity-data-builder | S6-DATA | Keycloak、Context Store、RLS、Migration；`infra/**`、`packages/persistence/**`、`migrations/**`、`tests/data/**` | ACTIVE | WP-081/WP-084 各自 clean Handoff |
| identity-api-builder | S5-CORE | API/BFF、Application、Workspace Lock；`apps/api/**`、`packages/application/**`、`tests/core/**`、共享依赖文件 | DEPENDENCY_WAIT | WP-083 clean Handoff |
| identity-runtime-builder | S2-RUNTIME | Worker/Graph/Context 恢复重验；S2 独占路径 | DEPENDENCY_WAIT | WP-085 clean Handoff |
| identity-experience-builder | S4-QUALITY | Web 与独立黑盒；S4 独占路径 | DEPENDENCY_WAIT | WP-086/WP-087 clean Handoff |
| m8-identity-verifier | S7-INTEGRATION | 组合、空环境、证据复算；S7 独占路径 | DEPENDENCY_WAIT | WP-088 PASS Handoff |

所有主 Agent 默认 `CONTEXT_MODE=DELTA`，使用 Attempt 内子 Agent而不注册新的长期 S 编号。
子 Agent 的有效权限为父角色、当前 WP 与子任务范围交集；不能提交、唤醒或裁决。
