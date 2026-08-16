# WP-115：安全 Knowledge MCP

- 状态：ACCEPTED_M10
- Attempt：WP-115-a1
- Owner：S3-PLATFORM
- 风险：R2
- Feature：FP-MCP-001/002、FP-SEC-003/005/006
- 依赖：WP-114
- 执行：ORDERED

将 Knowledge MCP 从内存样例迁移到 Retrieval Port。保持 `knowledge.search.v1` 与当前 Schema
Hash，不增加外部字段；查询前验证工作负载、SecurityContext、tenant、purpose、ACL、分级、
有效期和策略，结果返回前复验引用并执行 DLP/Prompt Injection 检查。

写入 `mcp-servers/knowledge/**`、必要的 `apps/mcp-gateway/**`、`packages/security/**`、
`tests/platform/**`。覆盖跨租户、错 purpose、过期 Context、恶意文档、引用篡改和未授权
元数据零泄漏。发现 Tool Schema 必须变化时停链 RFC。PASS 后唤醒 S5 WP-116。
