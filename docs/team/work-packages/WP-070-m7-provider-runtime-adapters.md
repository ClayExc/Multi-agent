# WP-070：M7 Provider 与 Agents SDK Runtime Adapter

## 元数据

- 状态：MERGED_M7_CANDIDATE
- Attempt ID：WP-070-a1 / WP-070-a2 / WP-070-q1
- 风险等级：R2
- 责任角色：S2-RUNTIME
- 评审角色：S1-ARCH、S4-QUALITY
- 功能 ID：FP-AGT-002、FP-AGT-003、FP-OPS-003、FP-SEC-006
- 依赖工作包：WP-036
- 执行模式：ORDERED
- Chain ID：CHAIN-M7-LOCAL-PRODUCT-01
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
- S4 复核步骤：`tests/acceptance/provider_runtime/**`；只添加黑盒负向与证据。
- 不修改公共 Contract；需要变更时先提交 RFC。

## 输入与输出

| 类型 | 内容 |
|---|---|
| 输入 | ProviderWire、AgentRuntimePort、ContextEnvelope、稳定错误码 |
| 输出 | LiteLLM Adapter、OpenAI/Claude SDK Adapter、Conformance 报告、在线 Smoke 入口 |

## Provider 标识与版本规则

- 产品逻辑名固定为 `flowpilot.primary.fast`，业务代码不得依赖供应商模型名。
- DeepSeek 官方 API 模型 ID 固定为 `deepseek-v4-flash`；LiteLLM Provider 路由名由
  Adapter 配置映射，不能写入 Task、Checkpoint 或公共契约。
- LiteLLM、`openai-agents` 与 `claude-agent-sdk` 的精确版本由 S5 在锁文件步骤固定。
- 在线 Smoke 必须显式启用并检查密钥；离线 Conformance 使用 Fake Transport，不能
  因没有外部凭据而跳过错误、预算、Session 和脱敏测试。

## 必须测试

- 正常：三个 Adapter 均通过统一 Port Conformance；LiteLLM 在线 Smoke 可单独启用。
- 边界：预算、超时、空响应、结构化输出与单节点单 Provider。
- 失败：限流、网络、无效模型响应和缺少密钥映射为稳定错误码。
- 安全：凭据不进入 Prompt、Trace、Checkpoint、SDK Session 或返回对象。
- 恢复：Session 引用失效后可重新建立，不改变业务 Checkpoint。

## 解锁条件

- 用户已批准 M7 启动；精确 Base、Attempt、写入范围和 Agent Registry 由
  `CHAIN-M7-LOCAL-PRODUCT-01` 提供。
- S2 只在收到激活提交和独立 Worktree 后进入实现。
