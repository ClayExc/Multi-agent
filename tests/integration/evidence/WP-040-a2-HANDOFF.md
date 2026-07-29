# WP-040-a2 S7-INTEGRATION 最终阶段验证修复交接

## 基本信息

- Work Package：WP-040
- Attempt ID：WP-040-a2
- 执行模式：ORDERED
- 模式：IMPLEMENTATION_REMEDIATION
- 风险等级：R1
- 责任会话：S7-INTEGRATION
- 接收会话：S1-ARCH
- 功能 ID：FP-OPS-002、FP-FLOW-001、FP-DATA-001、FP-SEC-004
- 基线：`4314766c0cfb57c3332a5fc0b0c27395e93cf879`
- S1 最终测试 Head：
  `9b166f8cbc6a85fc036458c5d88caf1ec10feacf`
- S1 最终测试 Tree：`6c93a0d208e54e65045d4501cb771a0ab7075f01`
- ContractSet：
  `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- 最终 S7 Head：本文件所在提交；精确 SHA 由交接消息返回
- 结论：PASS，交回 S1 复算

## 问题与修复

WP-040-a1 verifier 把 S7 候选阶段的分支和增量范围直接用于 S1 最终
合并阶段，导致合法的 S1 原子合并仅在以下两项产生假失败：

- `git.branch`
- `git.s7_delta_scope`

本 Attempt 新增两个显式阶段：

### `S7_CANDIDATE`

- 仍为 CLI 和 Python API 默认值。
- 分支必须是 `codex/s7/wp-040-integration-verification`。
- 只验证
  `56c90b1355213357415778bda43fc3acf96aa8ed..4314766c0cfb57c3332a5fc0b0c27395e93cf879`
  为 S7 独占路径。
- 输出内容保持 WP-040-a1 字节级兼容，原 Manifest/Report Hash 不变。

### `S1_FINAL`

- 待验 Head 必须包含 S7 Head
  `4314766c0cfb57c3332a5fc0b0c27395e93cf879`。
- 分支必须为 `codex/s1/*` 或 `master`；不接受任意分支或简单取消分支
  校验。
- `S7_HEAD..final_head` 只接受：
  - S1 独占路径；
  - 本工作包明确允许的共享 `.gitignore`；
  - 被最终 `.gitignore` 覆盖的 `.idea/**` 删除。
- `.idea/**` 例外严格限制为 `D`；新增、修改、复制或重命名仍失败关闭。
- 对 S7 候选与 Final 逐项比较受保护产品 Tree、Contracts Tree、
  `uv.lock` Blob 和 Migration Tree。
- 三个输入 Heads 必须仍为 Final Head 的祖先。

`S1_FINAL` 可通过：

```powershell
python scripts/integration/verify_wp040.py `
  --phase S1_FINAL `
  --target-head 9b166f8cbc6a85fc036458c5d88caf1ec10feacf `
  --output-dir artifacts/integration/runs/WP-040-a2-final
```

## 最终增量复算

`4314766..9b166f8` 的路径增量为：

- S1 独占：`AGENTS.md`、`README.md`、`WORKFLOW.md`、`docs/review/**`、
  `docs/team/**`。
- 明确允许的共享文件：`.gitignore`。
- 删除且被 `.gitignore` 覆盖：六个 `.idea/**` 文件。

受保护内容全部相同：

| 身份 | S7 Candidate | S1 Final |
|---|---|---|
| Contracts Tree | `3b67857c6aacce574080089ce1d8b763dd766a77` | `3b67857c6aacce574080089ce1d8b763dd766a77` |
| `uv.lock` Blob | `41d1de70751b6a8d5ac5d31c94749697b8a1a41b` | `41d1de70751b6a8d5ac5d31c94749697b8a1a41b` |
| Migration Tree | `162f2b65c41d1f7bad571e7d95c723206f6b86c9` | `162f2b65c41d1f7bad571e7d95c723206f6b86c9` |

- `uv.lock` SHA-256：
  `eb0f7ef676b42d81bd60d47de02b202197cc6d300ae8d4715814c3ebf3da70f8`
- `0002_checkpoint_sequence_cas.sql` SHA-256：
  `e5ca8fca2de8e913caedd488821356e441b2adc5ae72a20d015fe4df5b403112`
- S2/S5/S6 精确 Heads 均为 S1 Final Head 的祖先。
- Apps、Packages、Domain Pack、Infra、Migration、Core/Runtime/Data
  测试树和根 Workspace 文件均未被 S1 增量改写。

## 新增负例

1. 合法 `codex/s1/*` 原子合并：PASS。
2. S1 Final 增量修改非 S1 的产品路径：FAIL。
3. S7 Candidate 增量越出 S7 独占路径：FAIL。
4. S1 分支身份不匹配：FAIL。
5. `.idea/**` 修改而非删除：FAIL。

## FAST Gate

按派发要求未重复 Wheel、全量 143 测试、Compose、漏洞扫描或 Fresh
Install；RELEASE 证据继续引用 WP-040-a1。

| 命令 | 结果 |
|---|---|
| 默认 `S7_CANDIDATE` verifier | PASS：36/36 |
| `S1_FINAL --target-head 9b166f8...` verifier | PASS：42/42 |
| `pytest -q -p no:cacheprovider tests/integration` | PASS：14 passed |
| Ruff：`scripts/integration tests/integration` | PASS |
| Mypy `--strict scripts/integration/verify_wp040.py` | PASS：1 source file |
| `git diff --check` | PASS |
| S1 Final Worktree 只读洁净度 | PASS：0 changes |

候选阶段兼容证据：

```text
WP040_COMPOSITION_PASS checks=36 failed=0
MANIFEST_SHA256=sha256:1e9140e267470a0b4404a34b07254569875c3d8c582517599cc328ba8b5dddb1
REPORT_SHA256=sha256:533a2540a2d41264fe38bbc84c92ae5fa9bd5f3e1292b57598139e470c4e143c
```

最终阶段证据：

```text
WP040_S1_FINAL_PASS checks=42 failed=0
MANIFEST_SHA256=sha256:de0472abb4e07957a9ce70bc6a730852f2ea7fefa7494a292b450b271b6e69f6
REPORT_SHA256=sha256:8648d273b15a130d1dd234fba9dda6672ac5a67aaf87372e5eb6a0fff002ec5a
```

生成的 Manifest/Report 位于被忽略的
`artifacts/integration/runs/WP-040-a2-*`，不提交运行结果。

## 修改文件

| 文件 | 变化 |
|---|---|
| `scripts/integration/verify_wp040.py` | 增加阶段、Final 分支/祖先/范围/不变性验证 |
| `tests/integration/test_wp040_composition.py` | 增加阶段兼容、合法 Final 和越权负例 |
| `tests/integration/evidence/WP-040-a2-HANDOFF.md` | 本交接 |

没有修改 S1 Final Worktree、产品代码、Contract、Migration、Workspace、
共享文件或其他会话分支；没有执行 merge、rebase、reset 或 push。

## 下一步

1. S1 在 Final Worktree 使用 `--phase S1_FINAL` 和精确测试 Head 复跑
   FAST Gate。
2. S1 复算新 Final Manifest/Report Hash。
3. 原发布级产品、Wheel、Compose、漏洞与 152 tests 证据继续绑定
   WP-040-a1 和 S1 最终门禁，不由本修复重复声明。
4. S1 保留正式验收、合并和发布裁决。

## 机器可读摘要

```text
OUTCOME=PASS_HANDOFF
SESSION_ROLE=S7-INTEGRATION
WORK_PACKAGE=WP-040
ATTEMPT_ID=WP-040-a2
BASE_COMMIT=4314766c0cfb57c3332a5fc0b0c27395e93cf879
NEW_HEAD=<this-handoff-commit; exact-sha-in-final-message>
S1_FINAL_TEST_HEAD=9b166f8cbc6a85fc036458c5d88caf1ec10feacf
S7_CANDIDATE_GATE=PASS:36/36
S1_FINAL_GATE=PASS:42/42
INTEGRATION_TESTS=PASS:14
CANDIDATE_MANIFEST_SHA256=sha256:1e9140e267470a0b4404a34b07254569875c3d8c582517599cc328ba8b5dddb1
CANDIDATE_REPORT_SHA256=sha256:533a2540a2d41264fe38bbc84c92ae5fa9bd5f3e1292b57598139e470c4e143c
FINAL_MANIFEST_SHA256=sha256:de0472abb4e07957a9ce70bc6a730852f2ea7fefa7494a292b450b271b6e69f6
FINAL_REPORT_SHA256=sha256:8648d273b15a130d1dd234fba9dda6672ac5a67aaf87372e5eb6a0fff002ec5a
HANDOFF=tests/integration/evidence/WP-040-a2-HANDOFF.md
NEXT_ROLE=S1-ARCH
```
