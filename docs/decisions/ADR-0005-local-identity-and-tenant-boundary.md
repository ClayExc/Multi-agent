# ADR-0005：本地身份与租户信任边界

## 状态

Accepted for M8 implementation。

## 背景

FlowPilot 已有 `SecurityContextRef`、用户与 Agent 双主体校验、API 请求安全端口和
PostgreSQL 强制 RLS，但尚未把真实 OIDC 身份、工作负载身份和数据库租户绑定成一条
可运行链。浏览器 Header、请求正文、Graph State 或模型输出都不能成为可信身份来源。

## 决策

1. 本地身份源固定为 Keycloak；Web 登录使用 Authorization Code + PKCE，由 API/BFF
   持有服务端会话。浏览器不保存 Refresh Token，也不解析 Token 形成授权结论。
2. 用户、Worker 和 MCP Gateway 使用不同 Client、audience 与凭据。用户 Token 不得
   透传 Worker、MCP Gateway 或上游工具；服务间入口把验证结果转换为受信工作负载身份。
3. API 只接受允许算法，并校验签名、issuer、audience、authorized party、时间和
   nonce/state。tenant、subject、role/scope、认证强度和数据等级只从允许声明及服务端
   映射产生；purpose 由服务端用例决定，不能由浏览器或模型提升。
4. 现有 `SecurityContextRef v1` 继续作为跨进程引用，不增加 Bearer Token、Cookie 或
   完整 Claim。服务端保存可撤销的上下文记录；每次延迟执行、恢复和敏感工具调用都按
   ref/hash、有效期和 active 状态重新解析。
5. API、Worker 和 Gateway 传播的是用户上下文引用与独立工作负载身份。Graph、Context、
   Checkpoint、Trace、Audit、事件和错误不得保存原始 Token。
6. PostgreSQL 事务只能消费受信上下文派生的 tenant binding；每次事务重新设置并在归还
   连接前清除。预存高权限角色、缺少 tenant、连接池残留和恢复时陈旧 tenant 一律失败关闭。
7. 本地演示提供两个租户、普通用户、审批用户和独立服务 Client。配置可重复导入，演示
   密码只能来自本地环境，不进入 Git、日志或证据。
8. API/BFF 的服务端一次性会话存储是 state、nonce 与 PKCE verifier 的权威来源；
   OIDC 验证器只接收该可信存储给出的 expected nonce 并执行比较/消费。浏览器提交的
   nonce 不能直接成为 expected nonce。
9. MCP Gateway 的外部生产入口接收瞬时工作负载 Bearer，并在入口内部完成验证后才
   构造调用对象。接受 `AuthenticatedWorkload` 的核心服务仅属于进程内已认证边界，
   不得被 HTTP/MCP Transport 直接挂载。
10. 工作负载注册精确绑定 issuer、authorized party 和 subject。`attested` 默认拒绝，
    只有完整验证证据存在时才能为真；摘要统一采用严格的 64 位小写 SHA-256。
11. `context_hash` 覆盖不可变授权快照，包括 tenant/subject、issuer/authorized party、
    roles/scopes、认证信息、purpose、数据上限、issued/expires 与源 Token Hash。`active`
    是独立可撤销状态，不进入不可变快照，但每次解析都必须同时检查。

## 兼容性

本决策不修改公共 JSON Schema。M8 复用 `SecurityContextRef v1`、`AuthenticatedWorkload`
和既有 RLS；新增内容是内部 Port、生产 Adapter、配置与黑盒证据。若实现发现公共字段
不足，必须暂停并单独走 Contract Major/RFC，不能在内部对象中复制更宽松版本。

## 验收

- 所有产品入口必须经过可信 OIDC 身份，错签名、issuer、audience、nonce、过期或撤销均拒绝。
- 用户身份与工作负载身份可区分，用户 Token 到达 MCP 的成功数为 0。
- API→Graph→MCP→RLS 保持同一 tenant/context 绑定，跨租户成功读写均为 0。
- Worker 重启、Interrupt/Resume、连接池复用和会话失效后仍重新验证，不沿用陈旧授权。
- 原始 Token 在 State、Checkpoint、Trace、事件、日志、错误和 Evidence 中出现次数为 0。

## 关联功能

- `FP-SEC-001`
- `FP-SEC-002`
- `FP-SEC-007`
- `FP-OPS-001`
- `FP-EVAL-002`
