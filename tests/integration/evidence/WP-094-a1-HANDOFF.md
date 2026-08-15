# WP-094-a1-r1 S7-INTEGRATION Handoff

## OUTCOME

`PASS_HANDOFF`。P1 提交后复现缺陷已修复。在精确输入
`80eba3066bc7dfe3ed91985343881b89d280ac17` 上完成
M9T 工程控制面组合验证，可交给 S1 独立复算。本结论不提升 FP-OPS-002 状态，不批准
Release，也不启动原 M9 产品链。

## EVIDENCE

- S1 在 clean committed Head `10a0702` 发现验证器错误要求当前 Head 必须等于 S4
  `INPUT_HEAD`，导致验证器自身提交后无法公开复现。返修后 `INPUT_HEAD` 仍是固定被验输入；
  当前候选必须以它为祖先，且 `INPUT_HEAD..candidate` 只能包含 WP-094 四个授权 S7 路径。
  规则不嵌入新提交 SHA，因此没有自引用。
- clean committed candidate 形态下，S1 给出的公开 CLI 与 pytest 复现命令均 PASS；新增
  合法候选、非祖先、越权产品后继、输入保护树漂移回归，共 `7 passed`。

- 消费者门禁：专用分支/Worktree clean，当前 Head 是输入祖先；仅用 `--ff-only` 到达
  精确输入。Handoff、Proof、Contract digest 全部匹配派发值。
- 独立解析原始 28 条 Case：28 个唯一 ID、28 PASS、0 FAIL、0 skip；Proof 内部摘要
  `66a06074e062bc421797030bbdff44556f80761175fb98444b63369e57730cdd` 复算一致。
- Mutation Matrix 固定 12 类，非失败关闭 Case 均选择非空命令；漏选数 0。未知跟踪路径
  保持 `ENG_UNKNOWN_PATH`。
- 初始读取复算为 6/88 files、307/67820 bytes、45 basis points（0.45%），小于 20%。
- Cache 9 类和 Report 3 类失败关闭声明均从逐 Case 原始记录复算，不从汇总数字反推。
- 在空的干净临时 Git clone 中，公开 CLI 的 Repository Map、Context Capsule、Test Plan
  各执行两次，三个输出均逐字节一致。
- Contract、Migration、apps 保护树未变化；`packages/**` 产品差异只包含授权新增的
  `packages/engineering-control/**`。Workspace 与 `uv.lock` 都完整包含该包。

## GATES

- P1 定向公开 CLI：PASS；P1 定向 pytest：7 passed。
- Ruff、strict Mypy、diff-check、Secret Scan：P1 受影响范围 PASS。
- 下列 WP-094-a1 结果按派发复用，未重复执行：

- `tests/core/engineering_control`：56 passed。
- S4 黑盒 Acceptance：6 passed；S7 Integration + Secret：5 passed。
- Contract Conformance：PASS（20 schemas / 35 cases / 43 semantic / 52 features）。
- Ruff：PASS。
- strict Mypy：13 个生产源文件、4 个 Acceptance 源文件、2 个 S7 源文件分别 PASS。
- `uv lock --check`：PASS；`pip-audit`：0 known vulnerabilities。
- Secret Scan：0 findings；`git diff --check`：PASS。

首次把 Core 与 Acceptance 测试目录放入同一个 pytest 收集命令时，因两个顶层
`engineering_control` 测试包同名发生 collection collision；按仓库稳定入口分开运行后
分别全绿。首次把继承的 Core Fixture 测试也纳入 strict Mypy 聚合根时暴露既有 Fixture
类型错误；生产、Acceptance 与 S7 的声明严格类型根分别全绿。这两个失败均保留在 Proof
diagnostics 中，未冒充通过，也未修改 Owner 文件掩盖问题。

## SCOPE / RISKS / NEXT ACTION

变更仅位于 WP-094 授权的 `scripts/integration/**`、`tests/integration/**`。没有修改产品、
Contract、Migration、Workspace、Lock 或共享配置。未运行 Compose、在线 Provider、真实
Migration、破坏性恢复或全仓测试；这些不是本 WP 的声明门禁，亦未复用 Cache 冒充。

`BLOCKERS=none`。S1 应独立复算 Head、Proof、保护树及命令结果后作最终裁决。
`LEARNING_CANDIDATE=none`。本 Attempt 未使用子 Agent。

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M9T-ENGINEERING-CONTROL-01
STEP_ID=M9T-04-S7-INTEGRATION
ATTEMPT_ID=WP-094-a1-r1
SESSION_ROLE=S7-INTEGRATION
BASE_COMMIT=10a07024951d017b868303a9410f0e3caeaf0d2c
NEW_HEAD=<this-handoff-commit>
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
HANDOFF=tests/integration/evidence/WP-094-a1-HANDOFF.md
PROOF=tests/integration/evidence/WP-094-a1-PROOF.json
GATE=PASS
NEXT_ROLE=S1-ARCH
USER_GATE_REQUIRED=yes
```
