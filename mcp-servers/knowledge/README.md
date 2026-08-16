# FlowPilot Knowledge MCP

`knowledge.search.v1` 是确定性的只读 MCP 边界。公共输入/输出 Schema 与
`KNOWLEDGE_SCHEMA_PIN` 保持不变；旧 Pin 和运行时 Schema 漂移均失败关闭。

M10 生产装配使用 `RetrievalKnowledgeMcpAdapter`。它只能由 Gateway 的
`TrustedContextToolAdapter` 路径调用，先精确绑定 SecurityContext、Capability、tenant、
purpose、ACL、action classification ceiling、audience、scope 和有效期，再调用
`HybridRetrievalEngine`。Action ceiling 作为强制字段在候选形成前传入，不能从模型参数
构造，也不能通过伪造降级 SecurityContext 传递。

Retrieval 只在候选、精确版本、Hash、classification 和授权复验后读取 bounded
`content_excerpt`。Knowledge MCP 随后执行集中 Secret/DLP/Prompt-Injection 检查，并只
映射公共 Schema 允许的 `source_ref`、精确版本、Section、`redacted_summary`、内容 Hash
和分类；内部 `content_ref`、ACL、分数和诊断不外泄。

旧 `KnowledgeMcpAdapter`/`KnowledgeRecord` 仅为 M7～M9 已冻结的离线 Fixture 保留，
不得用于 M10 生产组合。排序、阈值、去重和引用验证只由 `flowpilot-retrieval` 提供，
本包不复制第二套排序逻辑，也不直连数据库或正文存储。
