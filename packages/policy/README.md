# FlowPilot Policy

本包解析公共 `PolicyDecision v1` 的精确结构，并应用其中封闭、强类型的
obligation。PEP 采用默认拒绝策略：

- 未知、重复、格式错误、互相冲突、已过期或不受支持的 obligation 均以关闭
  方式失败（fail closed）；
- 主体引用及哈希、已认证的 Agent 主体、租户、任务、动作摘要、工具操作、
  策略版本和过期时间均会被绑定；
- `deny` 始终覆盖其他任何信号；
- 在 Gateway 校验匹配的已批准记录前，`require_approval` 始终具有权威性。

策略决策通过可信来源 Port 加载。`ResolvedPolicyDecision` 携带已存储的
RFC 8785 输入原像，因此可以重新计算声明的 `input_hash`，而不是将任意 JSON
中的该字段直接视为可信值。
