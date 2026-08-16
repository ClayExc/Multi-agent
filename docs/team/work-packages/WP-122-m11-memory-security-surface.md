# WP-122：短期记忆内容安全表面

- 状态：ACTIVE
- Attempt：WP-122-a1
- Owner：S3-PLATFORM
- 风险：R2
- Feature：FP-CTX-002/003、FP-SEC-003/005
- 依赖：WP-121
- 执行：ORDERED

在集中内容安全注册表增加专用 `WORKING_MEMORY` 表面，覆盖 Turn、Snapshot、Manifest、重放、
错误与日志。拒绝凭据 family、隐藏推理、禁止字段名、超限嵌套和原始异常回显；合法业务 ID、
引用和中文文本不得被误报。写入 `packages/security/**`、`tests/platform/**`。

必须覆盖构造/持久化前/重放/Context 输出的同一矩阵；不得把安全对象、Token 或原文记录在
异常与证据中。PASS 后交接 S2 WP-123。
