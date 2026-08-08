# WP-070：M7 Provider 与 Agents SDK Runtime Adapter

## 元数据

- 状态：READY_NOT_ACTIVATED
- Attempt ID：待激活
- 风险等级：R2
- 责任角色：S2-RUNTIME
- 评审角色：S1-ARCH、S4-QUALITY
- 功能 ID：FP-AGT-002、FP-AGT-003、FP-OPS-003、FP-SEC-006
- 依赖工作包：WP-036
- 执行模式：ORDERED
- Chain ID：待激活
- 下一角色：WP-071

## 目标

- 在 Model Gateway 后实现 LiteLLM Provider，首个在线模型使用 DeepSeek V4 Flash。
- 保留并实现 OpenAI/Claude Agents SDK 的统一 Runtime Adapter 边界；SDK 只在单个
  LangGraph 节点内运行，不成为第二套业务状态机。
- 统一请求、结果、错误、预算、计量、Session 引用与安全日志。

## 非目标

- 不装配 Web/API/Worker 全链，不调用业务写工具。
- 不允许 Provider Session 代替 LangGraph Checkpoint。
- 不把在线 Smoke 纳入离线确定性测试。

## 允许修改路径

- S2：`packages/model-gateway/**`、`packages/agent-runtime/**`、`tests/runtime/**`。
- S5 收口步骤：相关包 `pyproject.toml`、根 `uv.lock`；只负责依赖闭包。
- 不修改公共 Contract；需要变更时先提交 RFC。

## 输入与输出

| 类型 | 内容 |
|---|---|
| 输入 | ProviderWire、AgentRuntimePort、ContextEnvelope、稳定错误码 |
| 输出 | LiteLLM Adapter、OpenAI/Claude SDK Adapter、Conformance 报告、在线 Smoke 入口 |

## 必须测试

- 正常：三个 Adapter 均通过统一 Port Conformance；LiteLLM 在线 Smoke 可单独启用。
- 边界：预算、超时、空响应、结构化输出与单节点单 Provider。
- 失败：限流、网络、无效模型响应和缺少密钥映射为稳定错误码。
- 安全：凭据不进入 Prompt、Trace、Checkpoint、SDK Session 或返回对象。
- 恢复：Session 引用失效后可重新建立，不改变业务 Checkpoint。

## 解锁条件

- 用户再次批准 M7 启动；分配精确 Base、Attempt、写入范围和 Agent Registry。
- 模型标识、LiteLLM 路由名和 SDK 版本在实现时通过官方文档与锁文件固定。
