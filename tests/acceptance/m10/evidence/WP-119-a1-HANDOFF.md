# WP-119-a1 M10 固定分母验收阻断交接

## 基本信息

- Chain：`CHAIN-M10-KNOWLEDGE-01`
- Step：`M10-09-S4-KNOWLEDGE-ACCEPTANCE`
- Work Package / Attempt：`WP-119` / `WP-119-a1`
- Owner：`S4-QUALITY`
- 基线：`99b1e741492cafebf04a8b11190946345df35c92`
- ContractSet：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：`BLOCKED_HANDOFF`；未唤醒 S7，未声明 M10、Feature、RELEASED 或 FROZEN

## 已完成

- 新增独立 `flowpilot.m10.knowledge-security` v1.0.0 executor，仅按完整 canonical digest 精确匹配 `m6a.safe.pi.003 / injection_in_knowledge_doc`。
- 产品观察边界为真实 `HybridRetrievalEngine -> RetrievalKnowledgeMcpAdapter -> McpGateway -> Audit/Security Event`，不是期望值回显或通用安全 Fake。
- 独立黑盒覆盖跨租户候选、过期 Context、低相关阈值、恶意文档、引用漂移、删除/重建和确定性排序。跨租户成功数、过期候选读取数、危险内容投影数均为 0。
- Judge 为空；终态、Secret 暴露、写入数和 Audit 完整性全部由确定性观察判定。
- 官方唯一 Runner 增加第四个 executor；固定 Case、分母、skip/quarantine、唯一匹配与未注册失败语义未改变。
- 机械迁移 M7 S4-owned 产品 Fixture 到当前 exact citation 语义：每个合成文档作为一次导入绑定 persistence version 1，并把 `#section` 与输出分类上界写入实际 ToolResult。M7/M8 identity、version、Case digest 与断言结果保持不变。

## 官方固定分母实测

- 唯一入口：`python scripts/acceptance/run_acceptance.py --output artifacts/acceptance/wp-119-a1 --run-id WP-119-a1`。
- 156 条：40 PASS / 116 explicit FAIL / 0 skipped / 0 quarantined。
- Executor：M7=24、M8=6、M9=9、M10=1；所有 Case 最多匹配一个 executor。
- M10 Case：`m6a.safe.pi.003`，input digest `sha256:5147290294443ca3f9f445ab1f312c0cc97a87801dfe4daae22a48ad2d570934`。
- Manifest Gate 按预期保持 `fail`，因为 116 条尚未实现；没有缩分母或宣称 Release。
- Proof：`tests/acceptance/m10/evidence/WP-119-a1-PROOF.json`。

## 门禁

| 门禁 | 结果 |
|---|---|
| M10 + M7/M8/M9 executor 定向回归 | PASS：91 passed |
| Ruff + `git diff --check` | PASS |
| Mypy strict（M7） | PASS：1 source file |
| Mypy strict / explicit package bases（M10 executor + probe） | PASS：2 source files |
| Secret Scan | PASS：2 passed |
| Contract Conformance | PASS：20 schemas / 35 cases / 43 semantic negatives / 52 features |
| 官方 Runner contract/e2e/recovery/security | PASS |
| 官方 Runner unit | FAIL：1/575 |
| 官方 Runner integration | FAIL：1 个 S7-owned 旧注册表断言 |

## 阻断

### S4-WP119-A1-001（P1，需范围扩权）

`tests.experience.test_identity_shell::test_live_command_error_does_not_expose_upstream_message` 在官方 `tests/core tests/runtime/unit tests/experience` 顺序下两次得到 503，预期为安全映射后的 409。该测试单例与完整 `tests/experience`（103 passed）独立通过，说明是顺序/共享状态相关问题，不得以独立重试覆盖官方原始失败。修复需要 `tests/experience/**`（可能还需 `web/**`）精确扩权，当前 WP-119 不授权。

### S7-WP119-A1-001（P1，S7 Owner）

`tests.integration.m9.test_wp109_composition::test_wp109_recomputes_unique_official_registry` 仍精确锁定 M7/M8/M9 三 executor，新增 M10 后稳定报告 `product executor registry identity drifted`。`tests/integration/**` 属 S7，S4 不越权修改。S1 需决定由 S7 在 WP-120 更新组合 oracle，或先建立独立修复 Step。

## 修改路径

- `packages/evaluation/m10_knowledge.py`
- `packages/evaluation/m7_product.py`（仅当前 citation/output-classification Fixture 迁移）
- `tests/acceptance/m10/knowledge_acceptance_probe.py`
- `tests/acceptance/m10/test_knowledge_acceptance_executor.py`
- `tests/acceptance/evaluation/test_m8_identity_executor.py`
- `scripts/acceptance/run_acceptance.py`
- 本 Handoff 与 Proof

公共 Contract、Dataset/Case、Migration、RLS、Lock、Makefile 与根共享配置均无变化。真实 PostgreSQL/RLS 复用 WP-113，Runtime 重验证复用 WP-117，Web 投影复用 WP-118；本 Attempt 未重跑 Compose、实库或在线 Provider。

## 子 Agent 与学习候选

```text
SUBAGENTS_USED=0
LEARNING_CANDIDATE=fixed-case support requires an exact product observation, while successor-owned registry oracles must be updated at the composition step
MATURITY=CANDIDATE
```

## 下一动作

1. S1 裁决 `S4-WP119-A1-001` 的精确修复范围，并分派 `S7-WP119-A1-001`。
2. 修复后复跑失败的 unit/integration 门禁和官方 Runner；不得以单例重试冒充组合通过。
3. 只有六类门禁闭合且 Head clean 后，才生成 `PASS_HANDOFF` 并唤醒 S7 WP-120。

```text
OUTCOME=BLOCKED_HANDOFF
CHAIN_ID=CHAIN-M10-KNOWLEDGE-01
STEP_ID=M10-09-S4-KNOWLEDGE-ACCEPTANCE
WORK_PACKAGE=WP-119
ATTEMPT_ID=WP-119-a1
BASE_COMMIT=99b1e741492cafebf04a8b11190946345df35c92
NEW_HEAD=<checkpoint-commit>
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
FIXED_DENOMINATOR=156
COMPLETED=40
EXPLICIT_FAILED=116
SKIPPED=0
QUARANTINED=0
RELEASE_CLAIMED=false
BLOCKERS=S4-WP119-A1-001,S7-WP119-A1-001
NEXT_ROLE=S1-ARCH
```
