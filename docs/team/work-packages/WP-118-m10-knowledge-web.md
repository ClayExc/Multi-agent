# WP-118：知识管理与检索诊断 Web

- 状态：BLOCKED
- Attempt：WP-118-a1
- Owner：S4-QUALITY
- 风险：R2
- Feature：FP-UI-001、FP-SEC-003
- 依赖：WP-117
- 执行：ORDERED

实现中文知识列表、版本、导入/更新/撤销、索引状态、检索诊断和引用回查页面。页面使用
Cookie-only 身份和服务端 tenant，不展示未授权元数据、正文、向量、Secret 或隐藏思维链。

写入 `web/**`、`tests/experience/**`、`tests/acceptance/m10/**`。覆盖会话失效、错租户、并发
更新、SSE 重放、无证据、错误恢复和可访问性。PASS 后热继续 WP-119。
