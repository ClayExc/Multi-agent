# 离线评测边界

本包实现 WP-030 的离线质量边界，不依赖 Runtime、Gateway、API、RLS、
Outbox、Provider 或模型。

公开职责：

- 校验 ContractSet 内容及哈希绑定、Schema 引用、Traceability、Registry、
  Dataset、Fixture 和最小 EvaluationCase 输入；
- 使用 `all_declared_cases` 聚合所有已声明 Case，并将 `failed`、`skipped`
  和 `quarantined` 均计为失败；
- Judge 输出仅限语义质量判断，且确定性断言的优先级高于 Judge；
- 生成确定性且经过密钥扫描的验收包骨架；
- 仅为已声明的独立验证者创建结构化 Feature 证据。

在仓库根目录运行不依赖外部组件的离线门禁：

```text
python scripts/acceptance/validate_offline.py
```

`evals/fixtures/` 下的两个 JSON 文件是合成骨架 Fixture，不属于候选 Dataset
Manifest，也不表示 120 条功能用例或 36 条安全/故障用例已经完成。

## M6 incremental-A 候选语料集（目标 e1）

`incremental_a.py` 负责整理并校验 incremental-A 候选语料集：48 条功能候选
（knowledge_qa_citation 24、clarification 16、ticket_write_verification 8）
以及 21 条安全/故障候选（tenant_isolation 6、rbac_abac_sod 6、
prompt_injection_malicious_mcp 6、approval_replay_tamper_duplicate_write 3），
产物位于 `evals/datasets/m6-incremental-a/`。

每条候选都是完整的 EvaluationCase v1 实例，并绑定 Feature
（FP-EVAL-001/002）、已发布的 tenant/principal Fixture、Registry 规则断言、
`evals/fixtures/` 下的离线数据源 Fixture，以及安全分类（`security-class:` /
`gate:` 标签）。全部 69 条候选均通过
`OfflineRepositoryValidator.validate_evaluation_cases`；生成过程确定且完全离线
（参见 `dataset-card.yaml` 的重建章节）。

## M6 incremental-B 候选语料集（目标 B1）

`incremental_b.py` 负责整理并校验 incremental-B 候选语料集：40 条功能候选
（business_read 16、ticket_write_verification 8、approval_recovery 8、
long_context_handoff 8）以及 12 条安全/故障候选
（approval_replay_tamper_duplicate_write 3、dependency_failure_unknown 6、
secret_dlp_audit 3），产物位于 `evals/datasets/m6-incremental-b/`。
它沿用 incremental A 的 EvaluationCase v1 绑定规则，并加入已发布的长上下文/
Handoff 断言（`assert.context.within_budget.v1`、
`assert.handoff.fields_allowed.v1`）以及 UNKNOWN 对账断言
（`assert.event.sequence_complete.v1`）；dependency-failure 与
secret/DLP/audit 分类的新离线故障配置位于 `evals/fixtures/fault-profiles/`。
全部 52 条候选均通过 `OfflineRepositoryValidator.validate_evaluation_cases`
（0 findings）。与 incremental A 累计：88 条功能候选 + 33 条安全候选 =
121 条候选。
