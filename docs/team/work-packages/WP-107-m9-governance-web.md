# WP-107：本地治理页面与可观察信号

## 元数据

- 状态：BLOCKED
- Owner：S4-QUALITY
- Attempt：WP-107-a1
- 风险：R2
- Feature：FP-UI-001、FP-OBS-002、FP-OBS-003
- 依赖：WP-106
- 执行：ORDERED
- 写入：`packages/observability/**`、`web/**`、`tests/experience/**`、`tests/acceptance/m9/**`、`tests/acceptance/m9/evidence/WP-107-a1-HANDOFF.md`

## 主写目标

提供中文治理页面，展示当前策略版本、策略决定、Audit、Security Event、关联链和稳定
错误；Trace/Audit/Security 明确分流，页面只消费安全查询投影。

## 验收

- 登录、租户隔离、分页/过滤、关联跳转、空状态、撤销会话和 SSE/刷新竞态可用。
- 页面、DOM、浏览器日志和网络响应中的 Token、Secret、Prompt、原始参数/结果为 0。
- Audit/Security 不采样；查询失败不会降级为未授权数据或 Trace 替代品。
- Experience/黑盒测试、Ruff、strict Mypy、Secret Scan 和可访问性检查通过。

## 非目标

Web 不发布/回滚策略，不直接读取数据库或 OPA。完成后热继续 WP-108。
