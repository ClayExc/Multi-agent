# FlowPilot Security

M9 在既有身份与凭据识别内核上增加三个进程内安全边界：

- `CapabilityHandle` 是短时、单次使用的 opaque handle，绑定 tenant、SecurityContext
  Hash、工作负载、工具、资源摘要、动作摘要、策略版本、执行 ID、用途、audience、
  classification、scope 和 `invoke/readback/reconcile` 使用类型。权威 Broker 必须原子
  `consume`，Gateway 不能用布尔标记模拟防重放。
- `SecretProviderPort` 只接受 Registry 固定的 `secret_ref` 和已经验证的 Capability。
  `SecretLease` 不可序列化，`repr/str` 永久脱敏，并在异步调用栈退出时覆盖内存缓冲。
  `DevelopmentSecretProvider` 仅用于本地演示，不宣称生产 Vault/KMS。
- `PROMPT_INJECTION_RULES` 与现有 `CREDENTIAL_FAMILIES` 共同形成集中内容安全注册表。
  Finding 只携带 rule/family ID、安全路径和 surface；不保存或渲染命中原文。

本包验证公共 `SecurityContextRef` 是否与当前可信的服务端身份记录匹配，
并验证已认证的工作负载主体是否与声明的 Agent 一致。

本包绝不接受模型输出中的租户、角色、audience 或凭据声明。Capability 凭据
使用不透明、绑定 audience 的短期 handle 表示；本包不会返回原始 token，
生命周期、Audit、Security 和调试投影中也禁止出现原始 token。

M11 增加 `ContentSurface.WORKING_MEMORY` 与 `assert_working_memory_safe`。同一入口用于
Turn 构造、Snapshot/Manifest 写入前、重放、Context 输出以及错误/日志投影，统一执行
凭据 family、禁止字段、隐藏推理、原始异常回显、循环和最大嵌套深度检查。Finding 和
异常只包含稳定 rule/family ID 与安全路径；调用方不得把被拒绝的 key/value 或原异常拼入
日志。该表面只验证内容安全，不拥有 Context、Memory、Persistence 或业务状态。

WORKING_MEMORY 输入先经一次安全读取复制为内建 `dict/tuple/scalar` 快照；凭据和内容规则
只扫描该快照，不会再次访问调用方 Mapping/Sequence。循环只按当前祖先路径判定，因此真实
回边失败关闭，而同一合法子对象被多个字段引用不会被误判。隐藏推理与权威状态字段使用受限
family 分词策略，拒绝 `analysis/thinking/role/approval/security_context/scope/capability`
等字段及其前后缀变体，但不把任意未知字段当作本包的 Schema allowlist；具体 Turn、Snapshot
与 Manifest 未知字段及 classification ceiling 仍由 Context 模型边界验证。
