# WP-109：M9 本地治理组合验证

## 元数据

- 状态：ACCEPTED_M9
- Owner：S7-INTEGRATION
- Attempt：WP-109-a1
- 风险：R3
- Feature：FP-SEC-004/005/006、FP-MCP-006、FP-OBS-002/003、FP-OPS-001
- 依赖：WP-108
- 执行：ORDERED / FINAL_GATE
- 写入：`scripts/integration/**`、`tests/integration/m9/**`、`tests/integration/evidence/WP-109-a1-HANDOFF.md`、`tests/integration/evidence/WP-109-a1-PROOF.json`、`artifacts/integration/**`

## 主写目标

在空本地环境组合 Keycloak、API、Worker、Gateway、OPA、PostgreSQL、Redis 和 Web，独立
复算策略、Capability、DLP、审计、固定分母与保护树证据。

## 验收

- 真实本地敏感读写绑定策略版本；发布/回滚/OPA 重启后结果符合版本历史。
- Capability 重放、Prompt Injection、恶意 MCP、Secret 泄漏、审批绕过、跨租户查询、
  拒绝后账本/上游调用成功数均为 0。
- Audit/Security 追加、查询、RLS、完整性篡改与 Redis 丢失恢复通过。
- 固定 156 结果与 WP-108 一致，不使用 Cache 代替 Compose、Secret、Migration 或安全门禁。
- Contract/Lock/Migration/Policy Bundle/Product trees、供应链和 cleanup 可复算。
- 验证器必须能从提交后的 clean candidate Head 公开运行，不能绑定一个只在提交前存在的
  工作树状态。

## 非目标

S7 不修改产品代码、不批准自身结果、不启动 M10。PASS 后显式唤醒 S1 并停在用户门禁。
