# WP-031：M6 验收可信度修复

## 元数据

- 状态：READY
- Attempt ID：WP-031-a1
- 风险等级：R2
- 责任会话：S4-QUALITY
- 评审会话：S1-ARCH
- 功能 ID：FP-EVAL-003、FP-EVAL-004、FP-OPS-002
- 依赖工作包：M6 增量 A/B/C 已合入 master
- 执行模式：ORDERED
- Chain ID：CHAIN-M6-ACCEPTANCE-REMEDIATION-01
- Step ID：M6-REM-01-S4
- 交接策略：S1_GATE
- 下一角色：S1-ARCH
- 目标分支：`codex/s4/wp-031-acceptance-remediation`

## 目标

- 消除“Case 未执行却判 PASS”和“测试失败但报告 PASS”的假阳性。
- 让每个 Case 的状态来自可追踪执行结果；没有执行器时必须失败关闭。
- 修复验收包中的 Hash、Fixture、测试状态和退出码一致性。

## 非目标

- 不修改公共 Schema、ContractSet、Runtime、Gateway、API 或持久化生产代码。
- 不用预期字段、Case 文件存在或 Judge 代理结果替代产品执行。
- 不宣称人工 Judge 校准、发布冻结或 120+36 成功率完成。

## 允许修改路径

- `scripts/acceptance/**`
- `packages/evaluation/**`
- `tests/acceptance/evaluation/**`
- `artifacts/acceptance/**` 的生成器与结构；运行产物不提交

## 输入契约

| 契约 | 版本 | 提供者 |
|---|---|---|
| EvaluationCase / Registry / Dataset / Fixture | rc2 candidate | S1-ARCH |
| Feature Traceability | v1 candidate | S1-ARCH |
| 产品场景执行端口与现有测试 Harness | current master | S2/S3/S5/S6 |

## 输出契约

| 契约 | 版本 | 消费者 |
|---|---|---|
| CaseExecutionResult | WP-031 v1 | Acceptance Aggregator |
| Acceptance Manifest / REPORT | WP-031 v1 | S1/S7 |

## 架构与安全约束

- 逐 Case 结果必须绑定 Case ID、执行器、输入/输出摘要、实际断言结果和证据引用。
- 未注册执行器、执行异常、缺失证据、Judge 未校准、测试失败均不得报告 PASS。
- Judge 只评语义质量，不能判定授权、安全、工具成功或任务终态。
- 报告、Manifest 与进程退出码必须对同一 Gate 结论一致。
- 证据不得包含密钥、隐藏思维链、生产 PII 或原始敏感 Prompt。

## 实施内容

1. 建立显式 Case Executor/Result 边界，替换静态文件存在即通过逻辑。
2. 首先实现 fail-closed：未被真实执行的 Case 计失败并保留原因。
3. 接入可确定性运行的现有产品场景；每个已支持类别至少有一次真实执行。
4. 将六类测试状态纳入 Manifest/REPORT Gate，而非只影响退出码。
5. 修复双 `sha256:`、错误 Fixture Manifest 路径和 `unknown` 仍通过的问题。
6. 增加故意失败、未执行、测试失败、Hash 错误和重复执行的回归测试。

## 必须测试

- 正常路径：真实执行的 Case 产生可复算 PASS 证据。
- 边界条件：Judge 为空但无语义 Rubric；支持与未支持类别混合。
- 失败路径：未注册执行器、产品断言失败、任一测试套件失败时整体 Gate=FAIL。
- 安全负向：安全 Case 不得由 Judge 或期望字段直接判 PASS。
- 恢复/幂等：同一输入重复执行结果一致，失败证据不被覆盖或丢失。

## 验收命令

```powershell
uv run --all-packages --all-groups --locked python -B -m pytest tests/acceptance/evaluation -q
uv run --all-packages --all-groups --locked python -B scripts/acceptance/run_acceptance.py --output <temp-dir> --run-id wp031-a1
uv run --all-packages --all-groups --locked ruff check scripts/acceptance packages/evaluation tests/acceptance/evaluation
```

## 证据

- `tests/acceptance/evidence/WP-031-a1-HANDOFF.md`
- 临时验收包中的 Manifest、REPORT、逐 Case Result 与 JUnit；不提交生成结果。

## 完成定义

- 无产品执行证据的 Case 成功数为 0。
- 任一测试失败时 Manifest、REPORT 和进程退出码全部失败。
- Hash 为单一合法 `sha256:<64hex>`，Fixture 引用可复算且不得为 unknown。
- 责任范围测试与 Ruff 通过，工作树干净，并交回 S1 复核。
