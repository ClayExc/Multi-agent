# FlowPilot Knowledge MCP 测试实现

`knowledge.search.v1` 是一个确定性、只读的 MCP 测试实现，用于验证 Gateway
边界。其 P1 Schema Pin 由 `KNOWLEDGE_SCHEMA_PIN` 固定；旧版 M0 Pin 会以关闭
方式失败（fail closed）。

在检查任何摘要是否匹配之前，适配器会根据以下条件过滤可信元数据：

- 用户主体的 ACL 成员关系和已认证的工作负载主体；
- 租户、Purpose 以及 `knowledge.search` capability Scope；
- 数据分类上限，以及文档的生效和过期时间。

封闭输出仅包含 `source_ref`、文档版本、章节、脱敏摘要、内容哈希和分类。
内部 ACL 绝不会进入结果。该测试实现没有写 API、生产凭据、网络依赖或
持久事实存储。
