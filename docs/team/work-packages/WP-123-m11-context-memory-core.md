# WP-123：短期记忆与摘要核心

- 状态：BLOCKED
- Attempt：WP-123-a1
- Owner：S2-RUNTIME
- 风险：R2
- Feature：FP-CTX-001～004、FP-SEC-003
- 依赖：WP-122
- 执行：ORDERED

在 `packages/context` 实现 Conversation Turn、Working Memory Snapshot、Context Manifest、
Summary Candidate/Store Port、事实等级验证、确定性合并、版本/Hash/CAS 请求和硬 Token 预算。
复用公共 ContextEnvelope v1，不复制公共 Schema。

覆盖 claimed/verified/inferred 越级、矛盾、重复/乱序消息、预算边界、摘要失败回退、敏感内容、
Handoff 过滤和序列化负例。写入 `packages/context/**`、`tests/runtime/**`。PASS 后交接 S6。
