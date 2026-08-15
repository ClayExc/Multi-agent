# WP-108：M9 安全验收与固定分母执行器

## 元数据

- 状态：BLOCKED
- Owner：S4-QUALITY
- Attempt：WP-108-a1
- 风险：R3
- Feature：FP-EVAL-002、FP-SEC-004、FP-SEC-005、FP-SEC-006、FP-MCP-006、FP-OBS-003
- 依赖：WP-107
- 执行：ORDERED / HOT_CONTINUE
- 写入：`packages/evaluation/**`、`evals/**`、`tests/acceptance/**`、`artifacts/acceptance/**`、`tests/acceptance/m9/evidence/WP-108-a1-HANDOFF.md`

## 主写目标

从产品公开边界验证策略拒绝、SoD、Capability 重放、Secret/DLP、Prompt Injection、恶意
MCP、审批绕过、审计完整性和跨租户查询，并为真正接通的 M9 Case 注册独立执行器。

## 验收

- 固定 156 分母不变、0 skip、0 quarantine；未接通 Case 继续明确失败。
- 拒绝路径上游调用数、有效账本占位和跨租户成功数均为 0。
- finding/error/log/report 不复制危险输入；Audit/Security 双向关联和完整性可验证。
- 生成逐 Case Proof 与 Handoff，区分离线、真实 Compose 和未运行门禁。
- Acceptance/Security/Contract/Ruff/Mypy/Secret 门禁通过。

## 非目标

不校准 Judge、不宣称 120+36 发布完成。完成后只唤醒 S7 WP-109。
