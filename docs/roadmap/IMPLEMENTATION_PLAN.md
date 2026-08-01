# FlowPilot 实施路线

## 1. 实施策略

按“垂直切片”推进：每个里程碑同时包含领域规则、API、Graph、工具、数据、测试和证据。禁止先铺满所有 Agent、页面和基础设施，最后才验证闭环。

P2 完成后采用三条提前并行轨道：评测数据在 M3～M5 按固定类别逐步建设，
Web 外壳在 API/SSE 契约稳定后并行，企业系统只预建 Vendor-neutral Port、Sandbox
Adapter 与契约测试。详细路径、配额和汇合门禁见
[`ACCELERATED_DELIVERY_PLAN.md`](./ACCELERATED_DELIVERY_PLAN.md)。该计划不自动
批准 `g2/g3`，也不改变当前 P2 链。

> 编号说明：本路线中的 M0～M8 是产品里程碑；历史
> `CHAIN-M1-PLATFORM-01`、`CHAIN-M2-STUDIO-01` 是工程集成增量，二者不
> 表示产品 M1/M2 已完成。自 VPN 切片起，链 ID 使用 `P1` 等产品前缀避免
> 混淆。P1 已合并；当前激活链为
> [`CHAIN-P2-DURABLE-RUNTIME-01`](../team/chain-authorizations/CHAIN-P2-DURABLE-RUNTIME-01.md)，
> 只注册 S6 数据恢复、S2 持久化 Runtime 与 S7 独立验证三个能力。

核心路径：

```text
确定性 Fake Runtime
  → VPN 单 Agent 闭环
  → 持久化 LangGraph
  → 安全 MCP 写入
  → 审批与恢复
  → Multi-Agent + Context
  → 第二复合场景
  → 120 + 36 评测
  → 可选多模态
  → 可选 LoRA
```

## 2. M0：仓库与契约基线

交付：

- Python workspace、锁文件、Makefile 和质量工具。
- `api`、`worker`、`mcp-gateway` 最小入口。
- Task、Command、Event、Tool、Approval、Audit JSON Schema。
- PostgreSQL 初始迁移和 RLS 测试框架。
- Docker Compose 的 PostgreSQL、Redis、Keycloak、OPA、OTel。
- Fake Runtime 和内存/模拟工具。

退出条件：

- `make bootstrap/test/test-contract` 可运行。
- 架构依赖测试阻止 `domain -> FastAPI/LangGraph/SDK`。
- Compose 健康检查通过。
- 追踪矩阵 M0 相关项可更新为 VERIFIED。

## 3. M1：VPN 确定性单 Agent 基线

当前状态：`MERGED_P1_READONLY`。第一条有序链已经交付只读知识闭环；Ticket 写入、
审批、真实 Provider、Web 和通用向量检索仍按后续里程碑推进。

交付：

- Intake、Clarify、Knowledge、Respond。
- 带 ACL 元数据的 VPN 知识样本。
- 模拟 Ticket/Asset/Knowledge MCP。
- 单 Agent 基线 Runner。
- 最初 20 条功能 Case。

退出条件：

- 缺失字段追问可恢复。
- 所有知识结论有有效引用。
- 无工具旁路。
- 基线报告包含逐 Case 结果，不要求预设成功率。

## 4. M2：持久化图与可靠运行

当前状态：`S7_RELEASE_PASS_AWAITING_S1_FINAL_AND_USER_GATE`。Flow Lite `g1`
已完成 S6→S2→S7 注册链；PostgreSQL Checkpoint、Lease/Fencing、Outbox/Redis
信号重建和 Worker 重启恢复已由 S7 在真实 PostgreSQL/Redis 中复现。SSE 属于
后续未批准目标，不进入本链。

交付：

- PostgreSQL Checkpointer。
- Task Worker、运行租约、Command Inbox、Transactional Outbox。
- 并行知识/服务状态查询。
- SSE 任务事件。
- 重启、Redis 丢失、节点失败和循环测试。

退出条件：

- 进程重启后恢复。
- 已完成并行分支不被重复执行。
- Redis 清空后由 Outbox 重建运行信号。
- 状态投影可从 Checkpoint/事件对账。

## 5. M3：MCP Gateway 与安全写入

交付：

- Tool Registry、Schema Pinning 和信任分级。
- OPA/Rego RBAC + ABAC。
- `PlannedAction/action_digest`。
- 审批、职责分离和恢复再授权。
- 执行账本、幂等、`UNKNOWN` 对账、回读验证。
- Token Exchange/开发环境短时凭据模拟。
- Audit/Security Event。

退出条件：

- VPN 工单闭环 AC-E2E-001 通过。
- 参数篡改、审批重放、重复写和错 audience 被阻断。
- 写请求超时但上游成功时不重复创建。
- Secret Scan 为 0。

## 6. M4：Multi-Agent 与 Context Engineering

交付：

- Knowledge、Data、Action Planner、Verifier 受限 Agent。
- OpenAI 或 Claude 的第一个真实 Runtime Adapter。
- 第二 Provider 先实现契约适配测试，可后续接真实账户。
- `ContextEnvelope`、摘要、预算、Handoff Filter。
- 单 Agent/Multi-Agent 和 Context 消融 Runner。

退出条件：

- Agent 工具权限矩阵通过。
- Handoff 禁止字段泄漏为 0。
- 50 轮对话保持硬预算。
- 报告真实 Token 分布和质量变化，不预填 24%。

## 7. M5：新员工复合申请与产品面

交付：

- 新员工领域规则和多个关联动作。
- 员工工作台、审批卡、任务时间线、证据面板。
- 设备/库存/权限查询的并行分支。
- 审批后多个动作的独立执行与汇总。
- OTel Trace 和治理查询。

退出条件：

- AC-E2E-002 通过。
- Worker 重启和权限撤销路径通过。
- UI 显示动作影响、依据、摘要和执行结果。
- Trace、Audit、Security Event 正确分流。

## 8. M6：评测与核心发布

120+36 不再等到 M6 才开始编写：M3、M4、M5 分别形成 48+21、40+12、
32+3 条增量候选，M6 负责最终配额校验、Hash 冻结、Judge 校准和可复现报告。

交付：

- 固定 120 条功能集。
- 固定 36 条安全/故障集。
- 规则评分、Judge Rubric 和校准。
- 三次公平单 Agent/Multi-Agent 对比。
- `make acceptance` 证据包。
- 5 分钟业务演示与 3 分钟安全演示。

退出条件：

- 核心 P0 全部 VERIFIED。
- 无未解释的 skipped Case。
- Judge 校准满足预注册策略。
- Compose 空卷启动。
- README 状态和量化数据由报告自动/受控更新。

## 9. M7：安全多模态（可选）

交付：

- 隔离区、MIME/文件头检查、恶意文件扫描。
- OCR、日志解析、页/区域引用。
- PII/凭据/二维码遮罩。
- 只读 Multimodal Observation Agent。
- 12 条独立安全多模态用例。

退出条件：

- 原件不能绕过安全管道进入模型。
- 恶意文件和隐藏指令被阻断或隔离。
- 多模态 Agent 没有写工具。

## 10. M8：路由 LoRA（可选）

交付：

- 800 条版本化路由样本和数据卡。
- 冻结基线、训练、验证、测试与安全集。
- Adapter Registry、灰度、回滚。
- 低置信度回退。

退出条件：

- 满足预注册 Promotion Policy。
- 宏平均与逐类指标、延迟、资源完整报告。
- 适配器不参与授权、审批或工具执行。

## 11. 风险控制

| 风险 | 触发信号 | 控制 |
|---|---|---|
| 技术栈过多 | M1 前需要配置十多个生产组件 | 使用 Fake/开发模式，真实组件后置 |
| 双 SDK 重复状态 | 节点同时保存两套 Session | 一个节点一个 Runtime，业务状态只在图 |
| 微服务化过早 | 跨服务事务阻塞核心闭环 | 模块化单体 + 三个进程 |
| 安全停留在 Prompt | 测试只能观察模型是否“听话” | MCP Gateway/PDP/RLS 确定性强制 |
| 指标造假 | 手工挑选或删除失败样本 | 固定数据集哈希、逐 Case 报告 |
| LoRA 过早 | 尚无稳定标签就训练 | 核心发布后再进入 M8 |
| 多模态扩大攻击面 | 原件直接送模型 | 隔离、扫描、Observation-only |

## 12. 每个里程碑的统一完成定义

- 代码通过格式、类型、单元和架构依赖测试。
- 新接口有版本化契约和契约测试。
- 新数据表有迁移、RLS 和回滚说明。
- 新工具有风险级别、Schema、策略、幂等和回读定义。
- 新功能 ID 更新追踪矩阵。
- 新失败模式有自动化测试。
- 新可观察行为出现在 Trace/Audit/Security Event 中。
- 文档不声称尚未获得的数字。
