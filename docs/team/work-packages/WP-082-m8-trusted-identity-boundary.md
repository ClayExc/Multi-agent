# WP-082：M8 可信身份边界

## 元数据

- 状态：ACCEPTED_M8
- Attempt：WP-082-a1
- Owner：S3-PLATFORM
- Reviewer：S4-QUALITY、S1-ARCH
- 风险：R2；P0/P1 立即停链
- Feature：FP-SEC-001、FP-SEC-007
- 依赖：WP-080
- 执行：与 WP-081 `PARALLEL`，路径互斥
- 子 Agent：`read-only/bounded-write`，最多 2 个；同一 Worktree 单写者

## 目标与输出

- OIDC/JWKS 验证 Port 与 Adapter：算法白名单、签名、issuer、audience/azp、时间和 nonce。
- 允许 Claim 到服务端 `TrustedSecurityContext` 的确定性映射与可撤销 ContextSource Port。
- 用户与 Worker/Gateway 双主体入口；用户 Token 不能作为 MCP 工作负载 Token。
- Gateway 在策略/账本/上游前重验 audience、tenant、purpose、tool、时效与上下文 ref/hash。

## 允许路径

`packages/security/**`、`apps/mcp-gateway/**`、`tests/platform/**`。包级依赖声明可修改，
根 `uv.lock` 由后续 S5 单独收口。公共 Contract 不变；不足时先 RFC。

## 复用与禁止重复

复用 `SecurityVerifier`、`AuthenticatedWorkload`、集中凭据扫描器和 Gateway 现有授权顺序。
不重造 `SecurityContextRef`，不复制第二套敏感字段扫描。白盒子任务、Fixture 子任务与
独立负向复核回答不同问题。

## 必须测试

- 正常用户/工作负载 Token 与 JWKS 轮换边界。
- 错签名/算法/issuer/audience/azp、过期/未生效、nonce 重放、未知 tenant/role。
- 浏览器/模型 Claim 覆盖、用户 Token 直达 MCP、撤销 Context 和日志泄漏均失败关闭。

## 非目标

API 登录会话、Keycloak 配置、RLS、M9 Rego/DLP/Capability、真实外部 IdP。
