# CHAIN-M9-GOVERNANCE-01 Agent 注册表

```text
REGISTRY_STATUS=ACTIVE
REGISTRY_MODE=minimum-capability-set
EXECUTION_MODE=ORDERED
MAX_ACTIVE_PRINCIPALS=1
MAX_ACTIVE_WRITERS=1
MAX_SUBAGENTS_PER_PRINCIPAL=2
COMMUNICATION=event-driven
SELECTED=policy-security-builder,runtime-dlp-consumer,governance-api-builder,audit-data-builder,governance-quality-builder,governance-integration-verifier
CURRENTLY_ACTIVE=policy-security-builder
NOT_YET_ACTIVATED=runtime-dlp-consumer,governance-api-builder,audit-data-builder,governance-quality-builder,governance-integration-verifier
UNSELECTED=none
```

| Agent ID | Role | 主写目标 | 当前状态 | 退出条件 |
|---|---|---|---|---|
| policy-security-builder | S3-PLATFORM | Rego/OPA、Capability、Secret、DLP、Gateway | ACTIVE | WP-101/102 clean Handoff |
| runtime-dlp-consumer | S2-RUNTIME | Prompt/Context/模型输出安全边界 | DEPENDENCY_WAIT | WP-103 clean Handoff |
| governance-api-builder | S5-CORE | 治理查询 Port、API、Workspace | DEPENDENCY_WAIT | WP-104 clean Handoff |
| audit-data-builder | S6-DATA | 审计事实存储、Migration、OPA/Secret Infra | DEPENDENCY_WAIT | WP-105/106 clean Handoff |
| governance-quality-builder | S4-QUALITY | Web、黑盒、安全执行器与证据 | DEPENDENCY_WAIT | WP-107/108 clean Handoff |
| governance-integration-verifier | S7-INTEGRATION | 本地组合、保护树和最终复算 | DEPENDENCY_WAIT | WP-109 PASS Handoff |

六个角色均有必要的独占路径，但不会同时运行。一个角色的 Handoff 只唤醒表中下一角色；
完成、P0/P1、权限请求和用户门禁之外不发送跨任务消息。
