# M9 本地治理控制面

M9 把现有策略、安全扫描和信号草稿接成可运行的本地治理闭环。它处理四件事：用
版本化策略作出确定性授权决定，在工具调用前签发短时能力凭据，在所有模型和工具边界
执行 DLP，并把不可采样的 Audit/Security Event 写入可查询、可校验的事实存储。

这套能力只服务本地产品演示。它保留面向企业 OPA、Vault/KMS 和 SIEM 的 Port，不实现
任何企业 Connector，也不把本地密钥文件描述为生产密钥管理。

## 决策与状态归属

OPA 只执行 Rego，不拥有 Task、审批或工具执行状态。每次评估产生不可变
`PolicyDecision`，绑定策略版本、Bundle 摘要、可信 SecurityContext、动作摘要、资源、
用途、数据分级、风险和过期时间。LangGraph 仍是跨节点状态机，PostgreSQL 仍是业务与
审计事实源。

策略采用 deny-overrides。任何输入缺失、Bundle 不可信、版本不可用、OPA 超时或返回
未知 Obligation 时都失败关闭。缓存只保存已验证 Bundle 和短时决定；策略版本、主体、
资源、动作、Context Hash 或环境指纹变化后必须失效。

策略发布与回滚形成线性版本历史。运行中的审批继续绑定原策略版本；恢复执行时若该
版本已撤销、过期或动作绑定变化，旧审批失效，不能静默迁移到新版本。

## Capability 与 Secret

Capability Token 由可信 Gateway 边界签发，只授权一次确定的上游动作。Token 至少绑定：

- tenant、主体 Context Hash 与工作负载身份；
- 工具、操作、资源、`action_digest` 和策略决定；
- audience、purpose、数据分级、签发时间、过期时间和唯一标识。

Gateway 在调用上游前验证并消费 Capability。重放、错 audience、错资源、错租户、过期、
策略撤销和动作漂移均在账本占位与上游调用前停止。

开发用 Secret Provider 只在 Gateway 的上游调用栈内解析凭据引用。调用完成后立即丢弃
明文；Task、Command、Context、Checkpoint、Trace、Audit、Security Event、错误和缓存
只能保存凭据引用或安全摘要。环境变量或本地 Secret 文件只是演示适配器，不成为公共
契约，也不进入 Git。

## DLP 与注入检查

DLP 是确定性安全控制，不交给模型裁决。集中注册表保存凭据 family、敏感字段、数据
分级和 Prompt Injection 规则，输出稳定 Finding 代码和安全路径，不返回命中的原文。

检查点覆盖：

1. Prompt 与 Context 进入 Provider 前；
2. 模型结构化输出进入 Graph/应用前；
3. 工具参数进入 Gateway 前；
4. MCP/上游工具结果进入 Agent 或 Web 前；
5. Trace、Audit、Security Event、SSE 和错误投影生成前。

边界之间复用同一规则注册表，但可以使用不同动作：阻断、脱敏或隔离。授权、工具参数、
身份、审批和密钥一律阻断；面向用户的普通业务文本只有在规则允许且保留安全摘要时才
能脱敏继续。第三次出现等价绕过时停止增加局部正则，回到集中注册表和组合测试矩阵。

## Audit 与 Security Event

Trace 可以采样。Audit 和 Security Event 不采样，由可信 Store 分配 stream、sequence
和完整性链。两类记录绑定 tenant、task、run、trace、correlation、causation、主体、
策略版本、动作摘要和结果；阻断事件保持双向引用。

PostgreSQL 表采用强制 RLS、追加写约束和任务/租户范围内的连续序号。更新与删除默认
拒绝，完整性链断裂、重复序号、跨租户查询和不可信游标都失败关闭。查询 API 只返回
脱敏投影，并重新验证当前 SecurityContext、用途、权限和租户。

拒绝路径的顺序固定为：输入安全检查 → 身份与 Context 验证 → 策略评估 → 审批重验 →
Capability 签发/消费 → 账本占位 → 上游调用 → 回读。前五步任何失败都必须满足上游
调用数为 0、有效账本写入数为 0，同时留下不可采样的拒绝证据。

## 本地可观察入口

治理页面提供当前策略版本、最近发布/回滚、策略决定、Audit、Security Event、关联链和
稳定错误码。页面不显示 Rego 输入全文、Prompt、工具原始参数、原始模型输出或凭据。
策略管理动作先保留为本地 CLI；Web 只做受控查询，避免在 M9 同时引入新的管理写面。

## M9 完成边界

- 本地 OPA 使用已固定摘要的 Bundle，发布、回滚和缓存失效可复现。
- 敏感读写均可追溯到策略版本和确定性决定。
- Capability 重放、Secret/DLP 泄漏、Prompt Injection、恶意 MCP 内容和审批绕过成功数
  均为 0。
- Audit/Security Event 可按租户和任务查询，完整性篡改能够被检测。
- 固定 156 条 Case 不缩分母；只为真实接通的 M9 能力注册执行器。
- 不宣称生产 OPA、Vault/KMS、SIEM、HA 或企业网络接入。
