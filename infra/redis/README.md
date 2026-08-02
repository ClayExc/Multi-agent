# Redis 协调边界

Redis 只包含租户范围内的调度提示、缓存条目和速率限制。它不保存具有权威性的
Task、Command、Approval、执行、Checkpoint、Outbox 或 Audit 状态。

本地容器禁用 AOF 和 RDB 持久化，以便默认演练数据丢失与重建行为。
