# WP-086：M8 Web 登录体验

## 元数据

- 状态：BLOCKED
- Attempt：WP-086-a1
- Owner：S4-QUALITY
- Reviewer：S5-CORE、S1-ARCH
- 风险：R2
- Feature：FP-SEC-001、FP-EVAL-002
- 依赖：WP-081、WP-083
- 执行：与 WP-085 `PARALLEL`
- 子 Agent：`read-only/bounded-write`，最多 2 个；同一 Worktree 单写者

## 目标与输出

提供中文登录、登出、会话状态、过期/刷新失败和重新认证体验；页面不再提供可成为
权威输入的 tenant/role 字段，浏览器不解析 Token 决定权限。

## 允许路径

`web/**`、`tests/experience/**`、`tests/acceptance/**`。

## 必须测试

登录/登出/过期/撤销/刷新失败、SSE 重连、错误可访问性、跨租户 UI 路径、Cookie 与
DOM/日志中零 Token。独立黑盒与 S5 白盒测试使用不同观察边界。

## 非目标

前端授权、JWT 内核、RLS、最终固定分母报告。
