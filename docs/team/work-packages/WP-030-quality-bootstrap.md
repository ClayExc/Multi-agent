# WP-030：Quality、评测与证据基线

## 元数据

- 状态：IN_PROGRESS（`WP-030-a1` 离线范围 `ACCEPTED_AND_MERGED`；跨组件范围等待依赖）
- 责任会话：S4-QUALITY
- 评审会话：S1-ARCH、S2-RUNTIME、S3-PLATFORM、S5-CORE、S6-DATA
- 功能 ID：FP-OBS-001、FP-EVAL-001、FP-EVAL-002、FP-EVAL-003、FP-OPS-002
- 依赖工作包：五角色同摘要 ACCEPT 与 Attestation 已完成；从实现基线激活提交创建独立 Worktree；跨组件部分依赖 WP-010/WP-011/WP-020/WP-021
- 目标分支：`codex/s4/wp-030-quality-bootstrap`
- S1 评审：[`WP-030-A1-S1-REVIEW.md`](../../review/WP-030-A1-S1-REVIEW.md)
- 离线基线合并提交：`5cfa78b7e8d9cc1393dac4ae515ac6a9340fdf5f`

## 目标

- 建立公共 Schema、功能追踪和验收证据的自动校验骨架。
- 建立离线可重复的 EvaluationCase Fixture、规则评分边界和证据 Manifest 生成器。
- 约束 OpenTelemetry 关联字段与 Trace/Audit/Security Event 分离的测试入口。

## 非目标

- 在 M0 填满 120 + 36 数据集或声称成功率提升。
- 使用 LLM-as-Judge 判定授权、安全或工具执行是否成功。
- 修改 Runtime、Gateway、Policy、Persistence 生产代码。
- 在本工作包并行修改 `Makefile`。

## 允许修改路径

- `packages/observability/**`
- `packages/evaluation/**`
- `evals/**`
- `tests/acceptance/**`
- `tests/experience/**`
- `artifacts/acceptance/**` 的生成器与结构
- `scripts/acceptance/**`

共享 `Makefile` 由 WP-011 单写；接入 `make acceptance` 需在 WP-011 合并后另开工作包。

## 输入契约

| 契约 | 版本 | 提供者 |
|---|---|---|
| `contract-set.v1.json` | `1.0.0-rc.2` reviewed implementation baseline | S1-ARCH |
| EvaluationCase / Evaluation Registry | v1 | S1-ARCH |
| TaskEvent / AuditEvent / SecurityEvent | v1 | S1-ARCH |
| `traceability.v1.json` 与验收定义 | rc2 当前基线 | S1-ARCH |
| Fake Runtime Fixture | WP-010 | S2 |
| 安全/数据 Fixture | WP-020 | S3 |
| API/Domain Fixture | WP-011 | S5 |
| RLS/Outbox/恢复 Fixture | WP-021 | S6 |

## 输出契约

| 契约 | 版本 | 消费者 |
|---|---|---|
| 契约与追踪校验器 | M0 | S1、S2、S3 |
| EvaluationCase Fixture 与规则评分接口 | M0 | S2、S3 |
| Acceptance Manifest 草案 | v1 | S1 |
| OTel 关联字段测试 Fixture | M0 | S2、S3 |

## 架构与安全约束

- Judge 不参与安全、授权、状态或工具成功判定。
- 失败、跳过和隔离样本必须保留并进入分母说明。
- 证据只含摘要、哈希、引用和脱敏诊断，不复制密钥、完整 Prompt 或原始附件。
- Trace 可采样，Audit 不可采样；测试必须区分两者。
- 报告从逐 Case 结果生成，不允许手工回填 24%、90% 或 0.91。

## 实施内容

1. 建立 JSON Schema、契约集哈希和文档链接校验器。
2. 建立最小功能与安全/故障 EvaluationCase Fixture，而非预填完整数据集。
3. 建立确定性规则评分接口及 Judge 禁区测试。
4. 建立 Acceptance Manifest 生成器和空结果报告。
5. 建立 Trace Correlation 属性与信号分流测试 Fixture。
6. 在 WP-010/WP-011/WP-020/WP-021 交付后接入 Fake Runtime、API、RLS、Outbox 和安全黑盒测试。

## 必须测试

- 正常路径：合法 Case、Manifest 和契约集通过校验。
- 边界条件：零 Case 报告、可选 Judge 维度和采样 Trace。
- 失败路径：未知功能 ID、哈希漂移、重复 Case ID、非法状态被拒绝。
- 安全负向：Judge 结果不能覆盖安全断言；证据 Secret Scan 为 0。
- 恢复/幂等：同一原始结果重复聚合产生相同 Manifest 和汇总。

## 验收命令

```bash
# WP-030 先提供可直接运行的离线命令。
# make acceptance 在后续共享文件工作包接入，当前尚未实现。
```

## 证据

- Schema/链接/追踪校验报告
- Fixture 与评分器测试结果
- Acceptance Manifest 示例
- 按 `docs/team/HANDOFF_TEMPLATE.md` 创建的交接

## 完成定义

- 校验器能检测哈希漂移、未知功能 ID、重复 Case 和证据泄漏。
- 规则评分与 Judge 边界有自动化负向测试。
- 与 WP-010/WP-011/WP-020/WP-021 的公共对象仅通过已评审实现基线契约交换。
- S1、S2、S3 完成跨角色审查。
