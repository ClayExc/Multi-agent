# CHAIN-M10-KNOWLEDGE-01 Agent 注册表

```text
REGISTRY_STATUS=ACTIVE
REGISTRY_MODE=minimum-capability-set
EXECUTION_MODE=ORDERED
MAX_ACTIVE_PRINCIPALS=1
MAX_ACTIVE_WRITERS=1
MAX_SUBAGENTS_PER_PRINCIPAL=2
COMMUNICATION=event-driven
SELECTED=knowledge-core-builder,knowledge-data-builder,retrieval-builder,knowledge-security-builder,knowledge-runtime-consumer,knowledge-quality-builder,knowledge-integration-verifier
CURRENTLY_ACTIVE=knowledge-core-builder
NOT_YET_ACTIVATED=knowledge-data-builder,retrieval-builder,knowledge-security-builder,knowledge-runtime-consumer,knowledge-quality-builder,knowledge-integration-verifier
UNSELECTED=none
```

| Agent ID | Role | 主写目标 | 当前状态 | 退出条件 |
|---|---|---|---|---|
| knowledge-core-builder | S5-CORE | 文档领域、应用 Port、API 与 Workspace | ACTIVE_WP111 | WP-111/116 clean Handoff |
| knowledge-data-builder | S6-DATA | 文档事实、RLS、pgvector、索引生命周期 | DEPENDENCY_WAIT | WP-112/113 clean Handoff |
| retrieval-builder | S4-QUALITY | 混合检索、重排、引用复验 | DEPENDENCY_WAIT | WP-114 clean Handoff |
| knowledge-security-builder | S3-PLATFORM | Knowledge MCP、Gateway 与输入安全 | DEPENDENCY_WAIT | WP-115 clean Handoff |
| knowledge-runtime-consumer | S2-RUNTIME | Graph 查询、稳定引用与无证据行为 | DEPENDENCY_WAIT | WP-117 clean Handoff |
| knowledge-quality-builder | S4-QUALITY | Web、固定分母执行器与验收证据 | DEPENDENCY_WAIT | WP-118/119 clean Handoff |
| knowledge-integration-verifier | S7-INTEGRATION | 本地组合、保护树和最终复算 | DEPENDENCY_WAIT | WP-120 PASS Handoff |

注册表描述责任，不要求七个会话常驻。只有 `CURRENTLY_ACTIVE` 的领域主 Agent 获得写租约；
同一角色相邻工作包使用热继续，不重新读取未变化的仓库内容。
