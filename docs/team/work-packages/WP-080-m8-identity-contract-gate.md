# WP-080：M8 身份与租户契约门禁

## 元数据

- 状态：DONE
- Attempt：WP-080-a1
- Owner：S1-ARCH
- Reviewer：S2、S3、S5、S6 在首次消费时验证
- 风险：R2
- Feature：FP-SEC-001、FP-SEC-002、FP-SEC-007、FP-OPS-001、FP-EVAL-002
- Chain：CHAIN-M8-IDENTITY-TENANCY-01
- 子 Agent：只读，最多 2 个，主 Agent 已复核

## 目标

冻结本地 OIDC、用户/工作负载双主体、SecurityContext 生命周期、租户传播和 RLS 绑定
边界，为 M8 各 Owner 提供不依赖聊天记录的共同输入。

## 输出

- [`ADR-0005`](../../decisions/ADR-0005-local-identity-and-tenant-boundary.md)
- [`IDENTITY_TENANCY.md`](../../architecture/IDENTITY_TENANCY.md)
- 现有 `SecurityContextRef v1` 保持不变；Contract digest 不变。

## 非目标

不实现 Keycloak、JWT Adapter、API 会话、Worker、Gateway、RLS 或 Web；不启动 M9。

## 验收

- 用户 Token 不透传 MCP，原始 Token 不进入 State/Trace/Checkpoint。
- tenant 只从可信 Claim 派生，浏览器、模型和 Graph State 不能覆盖。
- Worker 恢复、Gateway 调用和数据库事务均重新验证。
- 无公共 Schema 变化；相关文档链接和 Contract Conformance 通过。
