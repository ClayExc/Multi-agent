# WP-119-a1 M10 固定分母验收正式交接

## 基本信息

- Chain：`CHAIN-M10-KNOWLEDGE-01`
- Step：`M10-09C-S4-WP119-FINAL`
- Work Package / Attempt：`WP-119` / `WP-119-a1-final`
- Owner：`S4-QUALITY`
- 基线：`df2283049d717e62cf16ff6361de5d04ac2e4203`
- ContractSet：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：`PASS_HANDOFF`
- 发布状态：`RELEASED=false`、`FROZEN=false`

## 上游阻断闭合

- 仅以 `--ff-only` 精确消费 S7 Oracle Head `df2283049d717e62cf16ff6361de5d04ac2e4203`。
- S4 unit-order Handoff：`tests/experience/evidence/WP-119-a1-UNIT-ORDER-HANDOFF.md`，`sha256:f91bbbe32dcc449dbc9833b205c34145fe709797901175ce5a701365443a8b45`。
- S7 Oracle Handoff：`tests/integration/evidence/WP-119-a1-WP109-ORACLE-HANDOFF.md`，`sha256:78149cc49bb127fad668bc16912c5d3c0bca60e472928211d00d1d01ef2c56ef`。
- 原失败的官方 unit 组合：`575 passed`。
- 历史 M9 registry oracle：`tests/integration/m9` 为 `8 passed`。

## M10 产品证据

- `flowpilot.m10.knowledge-security` v1.0.0 仅按完整 canonical digest 精确匹配 `m6a.safe.pi.003`。
- 产品观察边界为 `HybridRetrievalEngine -> KnowledgeMCP -> McpGateway -> Audit`。
- 跨租户成功、过期候选读取、低相关返回、危险输出均为 0；恶意文档与 citation drift 确定性拒绝。
- 删除后返回数为 0，重建返回数为 1；排序确定性、Audit/Security Event 双事件均已观测。
- `judge_scores_used=0`，安全、授权、终态和工具成功未交给 Judge。

## 官方固定分母实测

- 本 Attempt 仅运行一次唯一入口：`python scripts/acceptance/run_acceptance.py --output artifacts/acceptance/wp-119-a1-final --run-id WP-119-a1-final`。
- 固定 156 条：40 PASS / 116 `EXECUTOR_NOT_REGISTERED` / 0 skipped / 0 quarantined。
- Executor 支持数：M7=24、M8=6、M9=9、M10=1；注册策略保持 `unique_exact_case_digest`。
- unit、contract、integration、e2e、recovery、security 六类工程门禁全部 PASS。
- Bundle 记录 55 个 Artifact Hash，`dirty_worktree=false`。
- Manifest Gate 按预期为 `fail`，唯一原因是 116 条尚未实现；该结果不是工程门禁失败，不得声明发布。

| Artifact | SHA-256 |
|---|---|
| `manifest.json` | `sha256:ba1f6a72118303d8feea4e2f15867b9ff158c35868cfed3b1d9a183e9521a229` |
| `eval/aggregate.json` | `sha256:4f09be94e77736e4faef3db284242e26e96602ef603b9c57cb4d0dab11f272ef` |
| `eval/executor-registry.json` | `sha256:240b8a85f39743300cdde78b59c0254f1ef49da03de0981fe8eb9caca1ade249` |
| `eval/verdicts.json` | `sha256:87491d2af85d8044b4c2fd6cf2268860cfecf2fa68199e5f35a2f8e6ac26506c` |
| `execution/cases/m6a.safe.pi.003.json` | `sha256:ea2a11b8d9f332bf98858ce60566d6078c1336a9dce9e9eea7e82e80c47a7af1` |
| `test-results-summary.json` | `sha256:0bb7966cc8ea6d667db17e39f197fe2b5adf20faaae217e327e8c0231f148bfe` |

## 复用证据与范围

- 复用 M10 定向 `91 passed` 以及既有 Ruff、Mypy、Secret Scan、Contract Conformance PASS 证据；未重复 Owner 全量门禁。
- 本次最终增量仅更新 WP-119 Handoff/Proof，并执行 diff、Hash 和 clean 检查。
- 公共 Contract、Dataset、Case、固定分母、skip/quarantine、Feature 状态、Migration、Lock 与产品实现均无变化。
- 子 Agent：`SUBAGENTS_USED=0`。
- `LEARNING_CANDIDATE=none`。

## 下一动作

S7-INTEGRATION 在 WP-120 中以 `--ff-only` 精确消费最终 Head，独立复算 Handoff/Proof、固定 156 分母、40/116/0/0、四 executor 唯一匹配、55 项 Artifact Hash 与六类工程门禁。Manifest Gate 仍必须保持 `fail`，不得声明 `RELEASED` 或 `FROZEN`。

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M10-KNOWLEDGE-01
STEP_ID=M10-09C-S4-WP119-FINAL
WORK_PACKAGE=WP-119
ATTEMPT_ID=WP-119-a1-final
BASE_COMMIT=df2283049d717e62cf16ff6361de5d04ac2e4203
NEW_HEAD=<handoff-commit>
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
FIXED_DENOMINATOR=156
COMPLETED=40
EXPLICIT_FAILED=116
SKIPPED=0
QUARANTINED=0
ENGINEERING_GATES=6/6_PASS
MANIFEST_GATE=fail
RELEASE_CLAIMED=false
FROZEN_CLAIMED=false
NEXT_ROLE=S7-INTEGRATION
NEXT_WORK_PACKAGE=WP-120
```
