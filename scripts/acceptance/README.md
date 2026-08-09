# WP-030 离线命令

校验已激活的 rc2 仓库输入和两个最小合成 Case：

```text
python scripts/acceptance/validate_offline.py
```

根据显式 metadata、已声明 Case ID 和 Case 结果生成确定性验收包：

```text
python scripts/acceptance/generate_bundle.py \
  --metadata <metadata.json> \
  --declared-cases <declared-case-ids.json> \
  --results <case-results.json> \
  --output <artifacts/acceptance/run-id>
```

生成器不会自行发现或删除 Case。缺失任何已声明结果都会失败；零 Case 输入会生成
`empty` 报告，其门禁失败且不提供成功率。

## M6-1 验收编排器

`make acceptance` 通过单条命令运行完整的 M6 验证闭环
（`scripts/acceptance/run_acceptance.py`）：

1. 收集 156 条候选（A 69 + B 52 + C 35 = 120 条功能 + 36 条安全/故障），
   按类型（suite x category）枚举，并根据 Evaluation Registry 校验各项配额。
   类型缺失或多余时立即中止，并保留 `collection-errors.json` 作为证据。
2. 对每条候选执行预检，再分派给显式注册的产品 executor。executor 缺失、
   结果绑定不完整、执行证据缺失，或所需 Judge 未完成校准时均按 fail-closed
   处理。Case 定义及 expected 字段绝不视为观测结果。结构化账本
   `eval/execution-results.jsonl` 和 `eval/verdicts.json` 记录全部 156 条候选。
3. 运行六类测试套件（unit/contract/integration/e2e/recovery/security），结果写入
   `test-results/*.xml`；任何套件没有可用目标目录时，都会中止并生成同一份
   `collection-errors.json` 证据。
4. 组装验收包（`manifest.json` + `REPORT.md` + `eval/`），其中
   `manifest.artifact_hashes` 与所有产物保持 1:1 覆盖。每个 executor 证据引用
   都会规范化到 `execution/` 下；路径逃逸、重复、冲突或缺失都会被拒绝，合法引用
   则纳入该哈希映射。

M7 当前只为 24 条企业知识问答 Case 注册真实产品执行器。其余 132 条虽然尚未
实现，仍留在固定分母并以 `EXECUTOR_NOT_REGISTERED` 失败；因此本步骤不会把部分
产品覆盖误报为 M7 RELEASE。

使用方式：

```text
make acceptance
python scripts/acceptance/run_acceptance.py [--run-id run-20260802-120000]
```
