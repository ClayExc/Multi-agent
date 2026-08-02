# 离线可观测性边界

`SignalRouter` 为 `FP-OBS-001` 提供确定性的测试接缝：

- Trace 信号可以采样。
- Audit 和 SecurityEvent 信号必须保留。
- 每个信号都保留 tenant、trace、task 和 correlation 标识。
- Trace、Audit 和 SecurityEvent 分别写入不同目标。
- 被阻断的 Audit 事件与对应 SecurityEvent 必须双向关联。
- 含疑似密钥材料或被禁止的原始推理字段的 Payload，在成为证据前必须被拒绝。

本包不配置 OpenTelemetry SDK 或任何生产存储；相关集成需等待
WP-010/WP-011/WP-020/WP-021 交接。
