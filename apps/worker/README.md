# flowpilot-worker

WP-010 Runtime 基线的最小 Worker 装配。

`RuntimeExecutionAdapter` 通过向执行队列写入租户隔离且命令幂等的信封，实现
S5 定义的 `ExecutionPort`。`RuntimeWorker` 获取带 fencing 的租约、推进状态图、
在安全节点边界保存 Checkpoint，并且仅依据稳定的 Graph/Runtime 语义确认或重新入队
该信封。

`VpnReadOnlyGraph` 是 P1 产品切片中确定性
`intake -> clarify/interrupt -> knowledge -> respond` 路径的组合实现。它只解析
S5 提供的脱敏请求观测，仅通过 S3 的 `GatewayClientPort` 调用
`knowledge.search.v1`，通过不透明的结果 Artifact Port 保存回答内容，并且只持久化
观测、结果和引用元数据。并行的 `service_read` 分支在当前切片中被明确跳过。

`PersistenceLeaseAdapter` 和 `PersistenceCheckpointAdapter` 将 Graph Port 桥接到
S6 persistence v2。它们解析可信 Task Thread，绑定 tenant/task/thread 与
run generation，在有效租约 fence 下执行 Checkpoint CAS，并将持久化故障映射为
稳定的 Graph 错误。

队列是信号边界，不是业务事实源。内存队列仅作为确定性测试 Fixture。持久化的
Checkpoint 与租约语义由 S6 `DataUnitOfWork` 提供；持久化队列信号适配器仍属于
后续集成范围。

本地检查状态图时，`flowpilot_worker.studio` 会把 `LangGraphRuntime` 使用的同一
Graph Factory 绑定到确定性的合成节点。`studio-safe` 配置不执行任何业务写入或
外部网络访问；一旦检测到生产凭据、端点或配置，会以失败关闭方式拒绝启动。其状态
只输出默认拒绝的调试投影，可用于观察路由、Interrupt、Handoff、重试、预算、
Checkpoint 推进、逻辑知识调用次数、引用次数，以及确定性的 service-read 跳过状态。
