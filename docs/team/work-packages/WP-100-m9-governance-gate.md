# WP-100：M9 本地治理门禁

## 元数据

- 状态：DONE
- Attempt：WP-100-a1
- Owner：S1-ARCH
- Reviewer：S3、S2、S5、S6、S4、S7
- 风险：R1
- Feature：FP-SEC-004/005/006、FP-MCP-006、FP-OBS-002/003
- 依赖：WP-094
- 执行：ORDERED

## 目标

固定 M9 策略、Capability、Secret、DLP、Audit/Security Event 的状态归属、信任边界、
最小 Agent 注册和工作包顺序。不修改公共 ContractSet 或产品代码。

## 输出与完成定义

- [`LOCAL_GOVERNANCE_CONTROL_PLANE.md`](../../architecture/LOCAL_GOVERNANCE_CONTROL_PLANE.md)
- `CHAIN-M9-GOVERNANCE-01`、WP-101～WP-109 和对应 Agent Registry。
- M9T Context Capsule 记录读取范围、范围扩展和已复用 WP-094 证据。
- M9 与 M9T 状态不混淆；`RELEASED=false`、`FROZEN=false` 保持不变。
