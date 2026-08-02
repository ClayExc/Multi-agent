# flowpilot-model-gateway

为不需要 Agent 循环的模型调用提供与 Provider 无关的路由接缝。M0 实现由确定性、
无网络的 Fake 与路由策略组成。LiteLLM 集成继续置于该 Port 之后，不属于
WP-010-a1 范围。

Gateway 不得放宽 Context 的 Provider Allowlist、数据分类上限或 Token/成本预算。
