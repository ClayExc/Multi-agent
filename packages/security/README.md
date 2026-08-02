# FlowPilot Security

本包验证公共 `SecurityContextRef` 是否与当前可信的服务端身份记录匹配，
并验证已认证的工作负载主体是否与声明的 Agent 一致。

本包绝不接受模型输出中的租户、角色、audience 或凭据声明。Capability 凭据
使用不透明、绑定 audience 的短期 handle 表示；本包不会返回原始 token，
生命周期、Audit、Security 和调试投影中也禁止出现原始 token。
