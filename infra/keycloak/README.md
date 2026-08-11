# M8 本地 Keycloak Fixture

`flowpilot-local-realm.json` 由 Keycloak 26.1.4 在本地 Compose 首次启动时导入。
Realm 已存在时，Keycloak 会跳过启动导入，因此容器重启不会重建用户、Client 或会话。

Fixture 提供：

- `flowpilot-web`：confidential Authorization Code + PKCE（S256），只允许单一 BFF
  回调和 Origin；Client Secret 与 Refresh Token 只由服务端 BFF 边界持有；
- `flowpilot-api`：只作为 API audience，不允许交互登录或服务账号；
- `flowpilot-worker`、`flowpilot-gateway`：只允许 Client Credentials，并使用不同
  Secret、audience 和 `workload_kind`；
- `tenant-a`、`tenant-b` 各有普通用户和审批用户。Token 同时携带固定
  `tenant_id` 和唯一 `/tenants/<tenant>/<role>` Group 路径，后续可信映射必须核对
  两者一致；角色只是策略输入，不代表最终授权。

Realm JSON 中的密码、Client Secret、回调地址和 Origin 都是环境占位符。Compose
要求调用方显式提供这些值；示例值只在 `.env.example` 中使用明显的本地 `change-me`
占位符。不要提交实际 `.env`，也不要把 Token、Cookie、授权码或 Secret 写入测试输出。

本配置使用 `start-dev` 和内置本地存储，仅用于 M8 本地演示。Keycloak 只暴露在
`127.0.0.1`；现代浏览器把回环地址视为可信本地来源，可以回传 Keycloak 的 Secure
认证 Cookie。不得把该 Realm 暴露到本机之外。它不是生产 IdP、HA、TLS 终止、备份
或外部企业身份配置。
