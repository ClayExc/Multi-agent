# WP-084-a1 S7 Migration Baseline Verifier 交接

## 基本信息

- Chain：`CHAIN-M8-IDENTITY-TENANCY-01`
- Step：`M8-02C-S7-MIGRATION-VERIFIER`
- Attempt：`WP-084-a1-s7-verifier`
- Session / Agent：`S7-INTEGRATION` / `migration-baseline-verifier`
- Execution：`PARALLEL` with `M8-02A-S5-API`
- 风险：R2
- 输入 Head：`bbea6363a9e1b262087c1ef7d17dc207187293be`
- 实现 Head：`41a11fc66536178299d91ce8600ce46107f34f2d`
- 最终 Head：本文件所在提交；精确 SHA 由交接消息返回
- ContractSet：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- Feature：`FP-SEC-006`

## 消费者门禁与复用

- Worktree、branch、Head 与信封精确一致；开始时工作树 clean。
- ContractSet 内容摘要独立复算一致。
- 复用 S6 已交付的 Data、实库 Migration/RLS 证据；本步没有运行 Compose、
  Keycloak、全仓测试或 M8 Release，也没有重复判断 S6 的数据库实现。
- 未使用子 Agent；任务只涉及一个窄验证器和对应测试，不需要并行拆分。

## 完成内容

- 将 WP-040 固定迁移 Head 从 `0003_api_task_initialization` 更新为授权的
  `0004_security_context_rls_binding`。
- 固定 0004 up Hash：
  `f9bd159ae37f7c8eb8963e3b8ca5e938db22b83f0f304337989303ce6ed06121`。
- 固定 0004 down Hash：
  `5386c89dcdcdcc0aab8323f360c98f7770e2a161904f501f51c185ec04d1930b`。
- 因 0003.down 合法加入 0004 后继保护，更新其 Hash 为
  `fa6a349b1319c654345d8bb80a84e1ef78457b9ec9ba23a8c635123dc097dc3c`。
- 保留并逐文件固定 0001～0003 的其余历史 Hash；完整保护清单现为 8 个 up/down
  文件。
- 验证线性链 `0001 -> 0002 -> 0003 -> 0004`、0002/0003 predecessor-down
  successor guard，以及 0004 对任何后续未知迁移的 down guard。
- 更新确定性 Manifest / Report Hash，并增加缺失、内容篡改、额外非法迁移 Head
  和完整历史 Hash 清单负例。

## 修改路径

- `scripts/integration/verify_wp040.py`
- `tests/integration/test_wp040_composition.py`
- `tests/integration/evidence/WP-084-a1-S7-MIGRATION-HANDOFF.md`

未修改 `migrations/**`、S6 实现、公共 Contract、Workspace、Lock、Compose 或其他
Owner 路径。

## 验证结果

- 修复前精确复现：4 failed / 31 passed；四项均由旧 0003 Head/Hash 与确定性快照
  引起。
- 修复后受影响测试：`39 passed`。
- Candidate manifest：36 checks / 0 failed / PASS。
- Deterministic Manifest：
  `sha256:5056790c039f3a0070d3bec6a24c468f30ce754bf9bf5817cec355572de17aed`。
- Deterministic Report：
  `sha256:30caf939917ad72ed7293bf19d40b934d9f5e960d0ee133c488f9aaa61b90391`。
- Ruff：PASS。
- strict Mypy：PASS（2 个受影响文件）。
- Contract Digest：精确一致。
- `git diff --check`：PASS。

## 环境说明与非目标

- 当前输入的 `uv.lock` 对根 Workspace 元数据报告需更新，`uv --locked` 因此拒绝
  创建本 worktree 环境。本步无权修改共享锁文件，也未运行 `uv lock`。
- 测试使用主工作区已有锁定 Python 3.12 虚拟环境执行，并从当前 worktree 加载源
  文件；这不改变本 worktree 或依赖锁。该锁闭包问题由并行 S5 Workspace Owner
  收口，不阻塞本次纯 S7 verifier 结果。
- 本交接不是 M8 Release，不提升 Feature 状态，不批准合并。

## 风险与下一步

- BLOCKERS：none。
- ADVISORY：S5 必须在其并行步骤收口 `pyproject.toml` / `uv.lock` 后复核锁定环境；
  S7 未修改或豁免该门禁。
- S1 核对最终 Head、Handoff Hash、三条 S7 路径与 clean 后，可在 M8 汇合点组合本
  verifier 修复；不得把本交接当成 S6 实库或 M8 Release 证据。
- 按派发要求，本任务不唤醒其他角色。

```text
LEARNING_CANDIDATE=Migration verifier baselines must pin the full authorized up/down chain and every predecessor-down successor guard; adding a legal successor changes both the new migration hashes and the predecessor down hash.
```

## 机器摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M8-IDENTITY-TENANCY-01
STEP_ID=M8-02C-S7-MIGRATION-VERIFIER
ATTEMPT_ID=WP-084-a1-s7-verifier
SESSION_ROLE=S7-INTEGRATION
AGENT_ID=migration-baseline-verifier
INPUT_HEAD=bbea6363a9e1b262087c1ef7d17dc207187293be
IMPLEMENTATION_HEAD=41a11fc66536178299d91ce8600ce46107f34f2d
NEW_HEAD=<this-handoff-commit>
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/integration/evidence/WP-084-a1-S7-MIGRATION-HANDOFF.md
NEXT_ROLE=S1-ARCH
USER_INPUT_REQUIRED=none
```
