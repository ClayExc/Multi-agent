# CHAIN-M9T-ENGINEERING-CONTROL-01 Agent 注册表

```text
REGISTRY_STATUS=ACTIVE
REGISTRY_MODE=minimum-capability-set
EXECUTION_MODE=ORDERED
MAX_ACTIVE_PRINCIPALS=1
MAX_ACTIVE_WRITERS=1
MAX_SUBAGENTS_PER_PRINCIPAL=2
COMMUNICATION=event-driven
SELECTED=engineering-control-builder,engineering-quality-verifier,engineering-integration-verifier
CURRENTLY_ACTIVE=engineering-control-builder
NOT_YET_ACTIVATED=engineering-quality-verifier,engineering-integration-verifier
UNSELECTED=S2-RUNTIME,S3-PLATFORM,S6-DATA
```

| Agent ID | Role | 能力与写入范围 | 当前状态 | 退出条件 |
|---|---|---|---|---|
| engineering-control-builder | S5-CORE | Workspace 包、仓库地图、Capsule、测试选择、缓存、CLI | ACTIVE | WP-091 与 WP-092 clean Handoff |
| engineering-quality-verifier | S4-QUALITY | 黑盒、变异矩阵、效率与安全证据 | DEPENDENCY_WAIT | WP-093 PASS Handoff |
| engineering-integration-verifier | S7-INTEGRATION | 组合复算、保护树、最终证据 | DEPENDENCY_WAIT | WP-094 PASS Handoff |

S5 可以在两个工作包内调用最多两个只读子 Agent，分别审查 Git/Workspace 映射和测试/
缓存安全；只有 S5 主 Agent 写入、复跑测试、提交和交接。S4、S7 遵循同一规则。
