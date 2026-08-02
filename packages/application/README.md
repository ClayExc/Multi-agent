# flowpilot-application

本包提供 Application 用例、经过校验的声明式 Domain Pack 加载，以及带版本的内部端口。
S2 实现 `ExecutionPort`；S6 实现 `TaskRepositoryPort`、`TaskQueryPort`、
`CommandInboxPort` 和 `UnitOfWork`。

适配器必须把 Provider、队列和数据库故障映射为本包定义的稳定错误，且不得暴露原始异常文本。

## 端口语义

- `ExecutionPort.submit` 以租户和 `command_id` 保证幂等。重复提交返回
  `disposition=duplicate` 的回执，不会启动第二条工作流。
- `UnitOfWork` 原子保存命令、租户范围内的幂等映射，以及
  `(tenant_id, task_id, expected_task_version)` 预留。
- Intake 在打开 Unit of Work 前校验命令摘要与安全绑定。事务内依次检查幂等性、
  `command_id`、Task 版本，最后检查版本槽预留。
- Runtime 只在已接受命令提交后派发。派发失败时，重放同一命令会重试幂等的
  Execution Port；一旦回执持久化，后续派发将被抑制。
- `TaskQueryPort` 的每次查询都必须限定在 `(tenant_id, task_id)`，不得返回其他租户
  或其他 Task 的投影。
- `TaskQueryService` 为每次查询打开只读 Unit of Work，使租户绑定、事务清理和连接
  生命周期仍由适配器负责。
- `RequestReferenceResolverPort` 接收租户、Task、消息和安全上下文的绑定，只返回
  与摘要绑定且已脱敏的观察结果。Application 服务根据 Domain Pack 重新计算必需字段，
  并拒绝租户、用途、分类、引用或摘要不匹配的结果。
- `ResultArtifactPort.put` 按 `(tenant_id, idempotency_key)` 原子去重。相同摘要的重放
  返回原始 `result_ref`，不同摘要则产生冲突。回执绝不暴露结果内容，因此公共 Task
  投影只携带 `result_ref`。
- `flowpilot.reference-ports.p1.v1` 是内部 Python 端口版本，不会扩宽公共
  `TaskCommand` 或 Task JSON Schema。
- Domain Pack 是纯数据目录。加载过程限制文件大小、要求字段精确匹配、校验路径包含关系，
  并使用拒绝别名的安全 YAML 加载器；不会从 Pack 导入任何模块。v2 manifest 还会校验
  合成请求观察、知识样本，以及每个用例的引用预期。

## 依赖记录

| 依赖 | 用途 | 许可证 | 替代方案 | 攻击面与控制 |
| --- | --- | --- | --- | --- |
| PyYAML | 解析声明式 Domain Pack YAML | MIT | 仅使用 JSON 的 Pack，或自定义解析器 | 通过文件大小限制、精确 Schema、`SafeLoader` 和拒绝别名，约束解析器资源与对象构造风险 |
| types-PyYAML（开发依赖） | 为 PyYAML 提供严格 Mypy 覆盖 | Apache-2.0 | 本地协议桩 | 仅在构建时使用，不包含在生产 wheel 中 |
