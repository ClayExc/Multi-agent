# WP-031-a1 S4-QUALITY 交接

## 基本信息

- Work Package：WP-031
- Attempt ID：WP-031-a1
- Chain ID：CHAIN-M6-ACCEPTANCE-REMEDIATION-01
- Step ID：M6-REM-01-S4
- 责任会话：S4-QUALITY（临时 Agent `acceptance-remediator`）
- 接收会话：S1-ARCH
- 交接策略：`S1_GATE`
- 功能 ID：FP-EVAL-003、FP-EVAL-004、FP-OPS-002
- 基线提交：`3119d73e65e0dcad6144b4707103fff4908bf4bb`
- 分支/实现提交：`codex/s4/wp-031-acceptance-remediation` / `258046d6ec4eaa15675b4044f0be24d25a5398a5`
- ContractSet 摘要：`sha256:f3c2dd6eb7d398d9a0a0891110cbc913bb998ed72208ea179a644c97af655e56`
- 状态：完成

## 完成内容

- 建立显式 `CaseExecutionResult`、`CaseExecutor` 与 Registry 边界；Case 定义、预期字段或文件存在不再构成产品执行成功。
- 未注册执行器、执行异常、输入/输出摘要错配、断言集合错配、证据缺失及 Judge 未校准均失败关闭。
- Registry 拒绝空或 `none` 的执行器 ID/版本，并强制 Result 身份与被选中的注册执行器完全一致。
- 每个执行证据引用使用规范 POSIX 相对路径，限制在本轮 evidence root 内；逃逸、别名、重复引用、Artifact 名冲突及缺失全部拒绝。
- 所有真实执行证据以 `execution/<relative-ref>` 加入 Acceptance Manifest `artifact_hashes`，并可按文件复算。
- 六类测试结果进入统一 Gate；Aggregate、Manifest、REPORT 与进程退出码使用同一结论。
- 修复 `sha256:sha256:` 与错误 Fixture Manifest 路径；拒绝 `unknown` 或非法 Hash。
- Judge Case 在当前代理校准状态下明确失败，Judge 不得覆盖非功能、安全、授权、工具成功或终态门禁。
- 控制台失败明细限制为前 12 条，其余保存在 `failures.json`，减少重复日志噪音。

## 未完成与非目标

- 尚未为 156 个场景注册真实产品 Executor；最终复跑按设计得到 `0 PASS / 156 FAIL`，不得解释为产品成功率。
- 64 个 Judge Case 尚未完成人工双轮盲审与有效校准。
- 本包不修复 WP040 历史 Manifest/Report 固定 Hash 漂移，因此 Integration 仍有 3 个既存失败。
- 未修改公共契约、数据集、Runtime、API、Gateway、Persistence、Makefile 或 Traceability 状态。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/evaluation/execution.py` | 产品执行结果、身份、证据引用与 Hash 闭包边界 | S4-QUALITY |
| `packages/evaluation/reporting.py` | GateCheck、Hash 合法性及统一报告结论 | S4-QUALITY |
| `packages/evaluation/__init__.py` | 导出新增 Evaluation 边界 | S4-QUALITY |
| `scripts/acceptance/run_acceptance.py` | fail-closed 编排、测试 Gate、执行证据收集 | 本工作包授权 S4 |
| `scripts/acceptance/README.md` | 同步真实执行与证据闭包语义 | 本工作包授权 S4 |
| `tests/acceptance/evaluation/test_case_execution.py` | 执行、身份、证据、冲突、幂等和安全负例 | S4-QUALITY |
| `tests/acceptance/evaluation/test_acceptance_runner.py` | Runner 未执行、Judge、安全与退出码负例 | S4-QUALITY |
| `tests/acceptance/evaluation/test_reporting.py` | 测试失败、非法 Hash 与报告一致性负例 | S4-QUALITY |
| `tests/acceptance/evidence/WP-031-a1-HANDOFF.md` | 本交接证据 | S4-QUALITY（S1 扩展授权） |

## 契约、数据库与配置变化

- 契约版本：无变化；ContractSet 摘要保持 `f3c2dd6e...55e56`。
- Migration：无。
- 环境变量：无。
- 兼容性：`generate_acceptance_bundle` 的既有调用保持兼容；新增 GateCheck 和执行证据参数均有默认值。Acceptance Runner 的旧静态 PASS 行为被有意收紧为失败关闭。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| `uv run --all-packages --all-groups --locked python -B -m pytest tests/acceptance/evaluation -q` | PASS：132 passed | 当前分支控制台结果 |
| `uv run --all-packages --all-groups --locked ruff check scripts/acceptance packages/evaluation tests/acceptance/evaluation` | PASS | 当前分支控制台结果 |
| `uv run --all-packages --all-groups --locked mypy --strict --explicit-package-bases --follow-imports=skip packages/evaluation/execution.py packages/evaluation/reporting.py scripts/acceptance/run_acceptance.py` | PASS：3 source files | 当前分支控制台结果 |
| `uv run --all-packages --all-groups --locked python -B scripts/acceptance/run_acceptance.py --output <temp> --run-id wp031-a1-closure` | EXPECTED FAIL：exit 1；Manifest/Aggregate/REPORT 均 FAIL；0/156/0；64 个 Judge 未校准 | `C:\Users\Administrator\AppData\Local\Temp\flowpilot-wp031-a1-closure-a79dcc9409ab4c74af77d598dd16e414` |
| 同轮 Unit / Contract / E2E / Recovery / Security | PASS：161 / 17 / 230 / 40 / 17 | 同上 `test-results-summary.json` |
| 同轮 Integration | FAIL：105 passed、3 个 WP040 固定 Hash 既存失败 | 同上 `test-results/integration.xml` |

## 安全与失败路径

- 已验证负向路径：未注册执行器、空/`none` 身份、伪造执行器归因、输入摘要错配、输出证据 Hash 错配、证据缺失、路径逃逸、重复引用、Artifact 覆盖冲突、断言失败、测试套件失败、非法 Hash、Judge 未校准及 Judge 介入安全 Gate。
- 未验证风险：真实产品 Executor 尚未接入；其运行时资源清理、超时和外部依赖隔离需在后续类别工作包逐项验证。
- Secret/PII 检查：现有 Evidence 安全门禁保持启用；完整 Security 套件 17 passed；临时产物仅含合成数据。

## 已知问题

- 156 个 Case 对应 156 个 scenario tag，建议按 7 个功能类别和 6 个安全类别注册共享 Harness，而不是创建 156 个复制 Handler。
- Integration 的 `test_wp040_composition.py` 3 个失败来自当前 Contract/Workspace 变化后的历史固定 Manifest/Report Hash，责任归 S1/S7 后续重算，且现已被 Acceptance Gate 正确暴露。

## 学习候选

```text
LEARNING_CANDIDATE=结果引用不等于证据闭包
MATURITY=VERIFIED
TRIGGER=CaseExecutionResult 已包含 evidence_refs，但 Bundle Manifest 未 Hash 对应文件，导致结果看似可追踪却无法独立复算。
MECHANISM=跨层只传递证据路径而未在最终聚合边界枚举、规范化、去重并 Hash，引用文件可缺失、冲突、逃逸或被替换。
STRUCTURE=由 Acceptance 聚合器集中收集执行证据；使用规范相对路径和根目录约束，绑定注册执行器身份与输入/输出摘要，拒绝重复、别名、冲突和缺失，再将每个文件 1:1 写入 artifact_hashes。
EVIDENCE=提交 258046d；test_executor_evidence_is_hashed_into_manifest、身份伪造及证据冲突/缺失/逃逸负例；132 passed。
RESIDUAL_RISK=当前验证使用合成 ObservingExecutor，真实产品 Executor 的过程证据仍需按类别接入和独立复现。
TARGET=playbook section: 验收证据闭包与执行器归因
```

## 接收会话下一步

1. S1 复核 `258046d` 的执行证据 1:1 Hash、身份绑定和授权路径。
2. 将 156 个场景按 13 个类别分配后续 Executor/Harness 工作包；未接入前维持 0 PASS。
3. 由 S1/S7 在契约治理修复后重算 WP040 历史固定 Manifest/Report Hash。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M6-ACCEPTANCE-REMEDIATION-01
STEP_ID=M6-REM-01-S4
ATTEMPT_ID=WP-031-a1
NEW_HEAD=258046d6ec4eaa15675b4044f0be24d25a5398a5
BASE_COMMIT=3119d73e65e0dcad6144b4707103fff4908bf4bb
CONTRACT_CONTENT_DIGEST=sha256:f3c2dd6eb7d398d9a0a0891110cbc913bb998ed72208ea179a644c97af655e56
GATE=PASS
HANDOFF=tests/acceptance/evidence/WP-031-a1-HANDOFF.md
NEXT_ROLE=S1-ARCH
NEXT_ATTEMPT_ID=none
ESCALATE_TO_S1=yes
```

## 可回滚方式

- 回滚本 Attempt 在基线 `3119d73e...` 之后的四个提交；不需数据库、契约或外部资源回滚。
