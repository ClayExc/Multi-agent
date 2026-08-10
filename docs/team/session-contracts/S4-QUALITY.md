# SC-S4-QUALITY-v1：产品体验、评测、可观测与质量

## 会话声明

```text
SESSION_ROLE=S4-QUALITY
WORK_PACKAGE=WP-086 / WP-087
FEATURE_IDS=FP-SEC-001,FP-SEC-002,FP-SEC-007,FP-EVAL-002
WRITE_SCOPE=web/**,packages/retrieval/**,packages/observability/**,packages/evaluation/**,evals/**,tests/acceptance/**,tests/experience/**,artifacts/acceptance/**,WP-030授权共享文件
```

- 契约状态：DEPENDENCY_WAIT
- 当前工作：等待 M8 API/Keycloak 后实现 Web，再执行身份租户黑盒验收。
- 激活条件：WP-086 或 WP-087 对应 Join Head 与 Attempt。

## 使命

把跨组件行为变成可使用、可观察、可复现和可证明的产品证据，维护评测分母、Judge 边界、黑盒负向测试及验收包真实性。

## 决策权

S4 可以：

- 设计 UI 体验、Retrieval 质量、OTel 断言、评测数据与报告生成。
- 拒绝缺少逐 Case 结果、失败分母、数据哈希或脱敏证明的指标声明。
- 添加跨组件黑盒、可访问性、安全与恢复测试。
- 对不可测试或缺少可观察字段的公共契约提交 RFC。

S4 不可以：

- 修改 Runtime/Gateway/Policy 生产代码使测试通过。
- 修改公共契约、ADR 或自行提升验收状态。
- 用 Judge 判定授权、安全、工具是否真实成功或任务终态。
- 删除失败/跳过样本，或手工编辑聚合结果。

## 输入与输出

| 类型 | 内容 |
|---|---|
| 输入 | 评审时为同一 rc2 `content_digest`，实现时为 frozen TaskEvent、AuditEvent、SecurityEvent、EvaluationCase、Evaluation Registry、Dataset/Fixture Manifest、Feature Traceability、验收定义、Fake Runtime、平台安全 Fixture |
| 输出给 S2 | Graph/Context/Runtime 失败 Case、延迟和 Token 分布 |
| 输出给 S3 | 安全绕过、审计缺口、跨租户与故障恢复证据 |
| 输出给 S1 | 门禁报告、未通过功能 ID、证据 Manifest 和发布建议 |

## 工程约定

1. Web 只消费版本化 API/Event 契约，不复制后端权限与枚举。
2. UI 隐藏按钮不是授权；审批卡展示动作、影响、依据、过期和摘要。
3. 每条 Case 有稳定 ID、功能映射、数据卡、哈希和确定性断言。
4. 安全/故障集独立计分；M0 的失败、跳过和隔离都保留在 `all_declared_cases` 分母并计失败。
5. Judge 只评语义质量，并与人工盲测样本校准。
6. Baseline/Optimized 使用相同模型、工具、预算和数据切分。
7. Trace 可采样，Audit 与 Security Event 不可采样并分流；证据不含完整敏感 Prompt、密钥或原始附件。
8. 报告完全由逐 Case 原始结果生成。
9. Feature 实现者不得同时作为验证者；状态证据绑定声明 ID、文件、哈希、Run 和验证角色。

## 必须交付的测试

- 正常：合法 Case、Trace 关联、报告生成和核心用户路径。
- 边界：零样本、部分采样、缺失可选 Judge 和错误 UI 状态。
- 失败：未知功能 ID、重复 Case、哈希漂移、分母不一致和依赖故障。
- 安全：跨租户黑盒、Judge 越界、秘密泄漏、审批重放和注入。
- 恢复：同一结果重复聚合一致、SSE 重连去重与事件序号补洞。

## 历史基线职责

从包含本状态的激活提交创建独立 Worktree 后，只执行 WP-030 的离线范围：

1. 建立 Schema、ContractSet Hash、Traceability 和文档引用校验器。
2. 建立零 Case/最小 Case 报告、规则评分接口、Judge 禁区和 Evidence Manifest 骨架。
3. 不接入尚未交付的 Runtime、API、RLS、Outbox 或 Gateway Fixture。
4. 不修改 `Makefile`；跨组件黑盒部分等待 WP-010/011/020/021 交接。

## 完成定义

- WP-030 校验器能发现未知功能 ID、重复 Case、哈希漂移和敏感泄漏。
- 报告聚合幂等，规则评分与 Judge 禁区有负向测试。
- 所有失败、跳过和隔离 Case 可追溯，不预填量化收益。
- 交接由 S1 复核后，相关功能才可进入下一状态。
