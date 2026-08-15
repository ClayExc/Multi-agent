# WP-083：M8 API/BFF OIDC 入口

## 元数据

- 状态：ACCEPTED_M8
- Attempt：WP-083-a1
- Owner：S5-CORE
- Reviewer：S3-PLATFORM、S4-QUALITY
- 风险：R2
- Feature：FP-SEC-001、FP-SEC-007
- 依赖：WP-081、WP-082 Join
- 执行：与 WP-084 `PARALLEL`
- 子 Agent：`read-only/bounded-write`，最多 2 个；同一 Worktree 单写者

## 目标与输出

API/BFF 提供登录发起、回调、刷新、登出和会话失效；浏览器只持有不透明 Cookie。
生产组合实现 `RequestSecurityPort`，Command、Task、SSE 只使用受信 Identity 和
SecurityContextRef，不接受 Header/正文自报 tenant、role、purpose 或 classification。

## 允许路径

`apps/api/**`、`packages/application/**`、`tests/core/**`、`pyproject.toml`、`uv.lock`、
`Makefile`。根依赖锁只在本包由 S5 收口。

## 必须测试

登录/刷新/登出、state/nonce/PKCE/replay、错 audience、过期/撤销、Cookie 安全属性、
正文和 Header 伪造、SSE 重连认证、稳定 401/403、零 Token 泄漏。

## 非目标

Web 页面、JWT 内核、Graph、Gateway、RLS、生产 IdP。
