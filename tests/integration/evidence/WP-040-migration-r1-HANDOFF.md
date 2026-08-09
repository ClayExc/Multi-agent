# WP-040-migration-r1 S7 Migration Verifier 交接

## 基本信息

- Chain：`CHAIN-M7-LOCAL-PRODUCT-01`
- Step：`M7-06V-S7-MIGRATION-VERIFIER`
- Attempt：`WP-040-migration-r1`
- Agent：`migration-verifier`
- 责任会话：`S7-INTEGRATION`
- 接收会话：`S6-DATA`
- 风险：R2 / P1 范围内单次修复
- 输入 Head：`89bc610a493d20a1714a14cf3c2625d43d155f92`
- S7 实现 Head：`fd699f54acf0033ab9ee5da06eed9744c84dc87a`
- ContractSet：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 最终 Head：本文件所在提交；精确值由唤醒信封提供

## 消费门禁

- 独立复算 S6 Handoff 原始字节 SHA-256 为
  `sha256:567ac7613af5290c6d784a6a445ad0f47aa4ef038838dae293d0ed800f3414cf`。
- 独立复算 ContractSet 内容摘要与信封一致。
- S7 原 Head 是输入 Head 祖先，工作树 clean；只用 `git merge --ff-only`
  精确到达输入 Head，未 merge commit、rebase、reset 或 push。
- S6 候选范围与线性历史符合交接；未修改 S6 Migration、RLS、Port、事务或产品代码。

## 完成内容

- WP-040 迁移清单从 `0001 -> 0002` 更新为授权的
  `0001 -> 0002 -> 0003_api_task_initialization` 单一线性 Head。
- 固定 `0002.down` 新内容 Hash，并固定 `0003` up/down Hash。
- 验证 `0003` 明确依赖 `0002`、携带当前 ContractSet 摘要，且
  `0002.down` 明确要求先回滚 `0003`。
- 迁移报告新增完整线性链和实际后继保护检测结果；多 Head、Hash 漂移、依赖或
  down-guard 缺失仍失败关闭。
- 更新确定性产物 Hash；候选与 S1-final 的分支、祖先、产品树、ContractSet、
  输入 Heads、Lock 与 Migration 保护未取消。

## 修改文件

- `scripts/integration/verify_wp040.py`
- `tests/integration/test_wp040_composition.py`
- `tests/integration/evidence/WP-040-migration-r1-HANDOFF.md`

## 验证结果

- 原 3 个失败：PASS；`tests/integration/test_wp040_composition.py` 为
  `35 passed`。
- 全量 `tests/integration`：`63 passed`。
- Ruff：PASS。
- strict Mypy：PASS（2 个本次影响文件）。
- `git diff --check`：PASS。
- Deterministic manifest：
  `sha256:a731ae741e5d22a158485671672156e105cf5704c10e98ae6dfa664b46f33cbf`。
- Deterministic report：
  `sha256:1b1bca696a21251be8ddf2608bca65103b000f5618e4cdfd7e5d35e748e8448c`。

## 未完成、风险与下一步

- BLOCKERS：none。
- 本步不批准 M7 合并或发布，不替代 S6 Data 与全仓门禁。
- S6 应只以 `--ff-only` 精确消费本交接最终 Head，复跑原 3 个失败、Data 与
  全仓门禁；全部 PASS 后才可唤醒 S2。
- `LEARNING_CANDIDATE=固定迁移验证器应钉住完整授权链、每个文件 Hash 与 predecessor-down successor guard，不能只钉当前单一 Head。`

## 机器可读摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M7-LOCAL-PRODUCT-01
STEP_ID=M7-06V-S7-MIGRATION-VERIFIER
ATTEMPT_ID=WP-040-migration-r1
AGENT_ID=migration-verifier
INPUT_HEAD=89bc610a493d20a1714a14cf3c2625d43d155f92
IMPLEMENTATION_HEAD=fd699f54acf0033ab9ee5da06eed9744c84dc87a
NEW_HEAD=<this-handoff-commit>
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/integration/evidence/WP-040-migration-r1-HANDOFF.md
NEXT_ROLE=S6-DATA
NEXT_ATTEMPT_ID=WP-071-a1-data-r1
NEXT_AGENT_ID=data-composer
USER_GATE_REQUIRED=no
ESCALATE_TO_S1=no
```
