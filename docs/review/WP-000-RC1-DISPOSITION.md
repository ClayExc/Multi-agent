# WP-000 rc1 评审裁决

## 1. 结论

- 裁决角色：`S1-ARCH`
- 评审目标：`flowpilot-m0-contracts-v1-rc1`
- 最终结论：`REJECTED`
- 后继候选：`flowpilot-m0-contracts-v1-rc2`
- 功能状态：全部保持 `DESIGNED`

S2、S3、S4 均对 rc1 返回 `REJECT`。所有阻塞项成立，rc1 从未进入 `frozen`，不得被实现会话或简历声明当作稳定边界。

原始会话：

- S2-RUNTIME：`019fa697-7be1-7811-8afe-5d8763bbfd9f`
- S3-PLATFORM：`019fa698-9217-71b1-bb1d-114f3d453935`
- S4-QUALITY：`019fa699-6ed3-79f3-a2c4-6daea933f4ff`

## 2. S2-RUNTIME 裁决

| Finding | 裁决 | rc2 处理 |
|---|---|---|
| S2-CR-001 缺少冻结的 Agent Runtime Port | 接受，阻塞 | 新增 `AGENT_RUNTIME.md`、`AgentRunRequest v1`、`AgentRunResult v1` 和 Conformance 要求 |
| S2-CR-002 Task 状态与 waiting/result/error/time 可矛盾 | 接受，阻塞 | 使用条件 Schema 封闭等待态、完成态和失败态字段组合 |
| S2-CR-003 Task 暴露内部 `current_node` | 接受，阻塞 | 从外部 Task Schema 删除；内部图节点不属于公共协议 |
| S2-CR-004 Command 幂等、版本检查和同版本并发顺序不明 | 接受，阻塞 | 增加 `command_digest`，ADR-0003 固定去重优先级和同版本唯一槽位 |
| S2-CR-005 ToolResult 状态组合可矛盾 | 接受，阻塞 | 封闭 `verified/failed_retryable/failed_final/unknown`，未知结果只能对账 |
| S2-CR-006 Context 可缺失或重复基础层 | 接受，阻塞 | 强制且仅允许一个 L0、L1、L2，并限制所有层最多一个 |

## 3. S3-PLATFORM 裁决

| Finding | 裁决 | rc2 处理 |
|---|---|---|
| S3-CR-001 obligation 参数无约束 | 接受，阻塞 | 改为按名称判别的强类型对象；未知、重复、畸形和不可执行项 fail-closed |
| S3-CR-002 多审批策略与单 Approval 矛盾 | 接受，阻塞 | M0 明确只支持 `minimum_approvers=1`；会签/或签留给 v2 显式契约 |
| S3-CR-003 ToolResult 可把不确定结果标为可重试 | 接受，阻塞 | `unknown.retryable=false` 且必须带对账计划；重试需证明未执行 |
| S3-CR-004 任意生产者可伪造 Task 终态 | 接受，阻塞 | TaskEvent 加生产者矩阵；Worker 拥有生命周期事实，模型 JSON 不具权威性 |
| S3-CR-005 Audit 无稳定拒绝、安全和数据等级证据 | 接受，阻塞 | AuditEvent 增加原因、策略、分类、链完整性；新增独立 SecurityEvent |

## 4. S4-QUALITY 裁决

| Finding | 裁决 | rc2 处理 |
|---|---|---|
| S4-CR-001 EvaluationCase 无功能 ID | 接受，阻塞 | 增加非空、去重 `feature_ids` |
| S4-CR-002 无机器可读 Feature→Test→Evidence | 接受，阻塞 | 新增 `feature-traceability.v1` Schema 和唯一事实源 `traceability.v1.json` |
| S4-CR-003 缺独立 SecurityEvent | 接受，阻塞 | 新增安全事件 Schema；Trace/Audit/Security 分流且后两者不可采样 |
| S4-CR-004 Assertion/Judge 和终态为自由字符串 | 接受，阻塞 | 结构化引用、限制终态并新增 Evaluation Registry；Judge 仅限语义维度 |

## 5. 兼容性裁决

rc2 对 rc1 增加必填字段、收紧枚举并改变部分字段结构，技术上属于 breaking change。由于 rc1 仅是未冻结候选、仓库无实现消费者，允许继续使用 v1 文件名并提升预发布版本到 `1.0.0-rc.2`。一旦 v1 标记为 `frozen`，同类变化必须发布新的 Major 契约。

## 6. rc2 冻结门禁

rc2 只有在以下条件同时满足后才能由 S1 改为 `frozen`：

1. 清单列出的全部 Schema（当前 rc2 为 20 个）通过 Draft 2020-12 编译和 `$ref` 解析。
2. 官方正反例、Registry、Traceability 和跨文件 ID 校验通过。
3. 清单列出的 SHA-256 与仓库字节完全一致。
4. S2、S3、S4 必须针对 rc2 的同一稳定 `content_digest` 重新审查并返回 `ACCEPT`；rc1 的结论不能沿用。
5. 任一新阻塞项先由 S1 裁决，未关闭前保持 `candidate`。
6. `make test-contract` 尚未接入时必须明确报告“未实现”，不能把一次性底层命令包装成完整工程验收。

## 7. rc2 定向复审范围

- S2-RUNTIME：Runtime Port、Task 状态、Command 顺序、Context 层、ToolResult 和实现可生成性。
- S3-PLATFORM：双主体授权、obligation、单审批、Gateway 请求/结果、生产者权限、Audit/Security。
- S4-QUALITY：EvaluationCase、Registry、Traceability、事件关联、哈希链、确定性门禁和 Judge 边界。
