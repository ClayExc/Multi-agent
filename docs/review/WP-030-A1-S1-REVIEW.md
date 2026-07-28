# WP-030-a1 S1 验收记录

## 结论

- 日期：2026-07-29
- 评审角色：S1-ARCH
- Attempt：`WP-030-a1`
- 分支：`codex/s4/wp-030-quality-bootstrap`
- 基线：`b5caaf2448c2860cfa67d8c5a39b9cda62eca809`
- 评审提交：`04a0e6da504aaad4cd25ada40f5c3b1b3c0e8578`、`a343d090adf5db5144be2a2162a937227a129512`
- ContractSet：`sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- 裁决：`CHANGES_REQUESTED`

WP-030-a1 离线骨架暂不合入主分支。已有校验器、固定分母、Judge 边界、Evidence 和信号分流设计可以保留；修复失败状态提升问题后沿用原分支和 Attempt 复审。

## 已复核内容

- 改动只涉及 WP-030 允许路径，未修改公共契约和共享 `Makefile`。
- 两个最小 Fixture 没有冒充 120/36 冻结数据集。
- Judge 被限制在 `semantic_only`，不能覆盖确定性断言。
- Audit/Security 不可采样，信号分流和 Secret 检查有负向测试。
- S1 独立运行 Acceptance 测试：`26 passed`。
- S1 独立运行离线 Gate：`case_count=2`、`findings=0`、PASS。
- S1 独立运行 Contract Conformance：PASS。

## 阻断项

### S1-WP030-A1-001：明确失败的执行状态可被提升为 passed

`DeterministicScorer.score()` 只保留 `skipped` 和 `quarantined`，没有保留 `execution_status=failed`。当执行已经失败而断言映射全部为 `True` 时，当前实现返回 `CaseStatus.PASSED`。

S1 最小复现输出：

```text
RESULT=passed
```

这会让执行失败 Case 进入成功分子，违反：

- ADR-0004 的固定分母与失败保留规则。
- WP-030“失败、跳过和隔离样本必须保留”的约束。
- 验收报告不得用聚合逻辑美化结果的真实性边界。

必须处置：

1. 只有 `execution_status=passed` 时，才允许根据确定性断言计算通过。
2. `failed`、`skipped`、`quarantined` 都必须保留原状态；Judge 分数不得改变它们。
3. 增加 `failed + 全断言通过 + Judge 高分` 的负向测试。
4. 重跑 Acceptance、离线 Gate、Contract Conformance 和证据生成。
5. 更新 Handoff 与 Proof，提交新的复审 HEAD。

## Advisory

- 参考环境的 `pytest-asyncio` 配置弃用警告不阻断本 Attempt；公共 Workspace 接入后应以锁定依赖重跑。
- 当前仍只接受离线骨架，不代表 120/36 数据集、跨组件黑盒验收或 `make acceptance` 已完成。

## 复审入口

S4 提交修复后提供：

```text
SESSION_ROLE=S4-QUALITY
WORK_PACKAGE=WP-030
ATTEMPT_ID=WP-030-a1
MODE=REMEDIATION_HANDOFF
NEW_HEAD=<commit>
FIXED=S1-WP030-A1-001
```
