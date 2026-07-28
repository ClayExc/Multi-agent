# 原始架构评审报告

## 1. 评审对象

- 文件：`企业智能工单与流程协同平台项目方案（企业级优化版）.md`
- 规模：2,353 行
- 仓库现状：无 README、无代码、无依赖清单、无接口契约、无自动化测试
- 评审结论：**设计方向正确，但尚不能作为可实施、可验收的企业级工程基线。**

## 2. 值得保留的设计

1. 以 LangGraph 作为跨业务流程的唯一状态机。
2. 将 Agents SDK 限制在有边界的专业 Agent 节点。
3. 不把 MCP 协议本身当作企业安全边界。
4. 知识、数据、执行、策略 Agent 权限分离。
5. 读写分离，高风险写操作进入人工审批。
6. Checkpoint、Interrupt、幂等、回读验证和转人工构成恢复闭环。
7. OIDC、租户隔离、RBAC + ABAC、DLP、密钥与审计从设计早期进入。
8. Trace、Audit Log、Security Event 分流。
9. 多模态附件先隔离解析和脱敏，再进入模型。
10. 量化指标必须由测试产生，不预先声称结果。

## 3. 阻止落地的主要问题

| 编号 | 问题 | 风险 | 改造决定 |
|---|---|---|---|
| R-01 | 95 KB 总稿混合产品、架构、接口、路线、简历话术 | 实施事实源不清，容易相互矛盾 | 拆为 README、结构、架构、Context、验收、ADR 和路线 |
| R-02 | 目录以 `backend/app` 技术分层为主 | 领域规则、Provider、框架和基础设施容易互相引用 | 改为 `apps + packages + contracts + domain-packs` |
| R-03 | MCP Gateway 放在后端内部模块 | 无法形成独立凭据、网络和故障边界 | 作为独立部署进程，所有上游 MCP 访问集中在此 |
| R-04 | FastAPI 直接驱动长图的边界不清 | 请求超时、重启丢任务、并发恢复 | API 接收命令，Worker 持续执行；队列只是信号，PG 为事实源 |
| R-05 | 缺少任务写入、Checkpoint、审计之间的事务边界 | 状态已成功但事件未投递，或重复执行 | PostgreSQL 执行账本 + Transactional Outbox + 回读验证 |
| R-06 | 审批只有 `approval_id`，未绑定动作内容 | 参数修改、策略变化或重放后仍可能执行 | 对规范化动作计算 `action_digest`，审批与其强绑定 |
| R-07 | 未明确 LangGraph Interrupt 会从节点开头重跑 | Interrupt 前副作用可能重复 | Interrupt 节点前零副作用；副作用单独节点且幂等 |
| R-08 | “单一状态源”表述过宽 | Checkpoint、业务记录、缓存职责混淆 | 按数据类别定义权威源；PG 同库不同模型，不把 Cache 当事实源 |
| R-09 | Context Engineering 只有原则，缺少输入契约 | 无法证明 Token 降幅和 Handoff 隔离 | 引入 `ContextEnvelope`、层级预算、裁剪日志和对照评测 |
| R-10 | LiteLLM 与双 Agents SDK 调用路径重叠 | 路由、Session、Trace 与计费重复 | 区分 `AgentRuntimePort` 与 `ModelGatewayPort` |
| R-11 | LLM-as-Judge 与规则评分边界不足 | Judge 可能误判安全和状态正确性 | 安全/工具/状态用确定性断言，Judge 只评语义质量 |
| R-12 | 评测数量为范围，缺少固定清单与证据格式 | 可挑选样本或只报告平均值 | 固定 120 功能 + 36 安全/故障，使用版本化 Manifest |
| R-13 | LoRA 数字可能被误读为已完成 | 简历真实性与复现风险 | 800 条样本、0.86/0.91 均标为待验证；先通过数据卡和基线 |
| R-14 | 没有架构依赖自动测试 | 模块边界会随实现腐化 | 增加导入规则和跨进程契约测试 |
| R-15 | 控制面能力超出个人项目首版 | 实施周期失控 | 首版配置文件 + 审批发布；治理 UI 后置 |

## 4. 官方能力边界校准

- OpenAI Agents SDK 提供有界 Agent loop、agents-as-tools、Handoff、Session、可恢复审批和 Trace；它不自动提供 FlowPilot 的跨租户业务授权、数据库 RLS 或不可篡改审计。
- OpenAI 的 MCP 指南支持 `allowed_tools` 和调用审批，并明确提醒只连接可信 Server、审查发送数据和处理 Prompt Injection；FlowPilot 因此仍需要自己的 MCP Gateway。
- LangGraph Checkpoint 适合线程级短期状态、Interrupt 与故障恢复；长期用户事实、业务记录和审计分别进入专用 Store/业务表/审计存储。
- LangGraph Interrupt 恢复会从包含 `interrupt()` 的节点开头重新执行，因此副作用不能放在 Interrupt 前。
- 当前 MCP 授权规范要求资源指示和 Token audience 校验，明确禁止 Token passthrough；Gateway 必须执行面向目标 MCP Server 的令牌交换。

参考：

- [OpenAI Agents SDK](https://developers.openai.com/api/docs/guides/agents)
- [OpenAI MCP and Connectors](https://developers.openai.com/api/docs/guides/tools-connectors-mcp)
- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [MCP Authorization 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)
- [MCP Security Best Practices](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices)

## 5. 企业级与个人项目的平衡

企业级不是服务数量，而是边界、证据和恢复行为。核心版只保留以下真实可做、可演示的部署单元：

- API
- Task Worker
- MCP Gateway
- Web
- 四个模拟 MCP Server
- PostgreSQL、Redis、Keycloak、OPA、OpenTelemetry Collector

Vault、WORM、SIEM、真实 ServiceNow/Jira、Kubernetes、多区域容灾和 LoRA 训练平台作为生产映射或可选扩展，不得在未实现时进入核心完成定义。

## 6. 评审验收结论

原始总稿通过“方向评审”，未通过“实施验收”。完成以下事项后才进入实现：

- README 明确状态和真实性边界。
- 结构规范明确部署单元和依赖方向。
- 架构文档定义状态所有权、事务和失败语义。
- Context 文档定义分层输入与测量方法。
- 验收文档为每个功能分配稳定 ID、测试和证据。
- ADR 固化编排边界与有副作用动作协议。

上述文档已作为本轮架构基线建立。下一阶段从最小 VPN 垂直切片开始实现。
