# WP-040-a3 S7-INTEGRATION 主分支回归边界修复交接

## 基本信息

- Work Package：WP-040
- Attempt ID：WP-040-a3
- 执行模式：ORDERED
- 模式：IMPLEMENTATION_REMEDIATION
- 风险等级：R1
- 责任会话：S7-INTEGRATION
- 接收会话：S1-ARCH
- 功能 ID：FP-OPS-002、FP-FLOW-001、FP-DATA-001、FP-SEC-004
- 基线：`a2f7f39592229b81000ec43e15327da7fd564c2c`
- 固定 S1 Final 测试 Head：
  `9b166f8cbc6a85fc036458c5d88caf1ec10feacf`
- 当前只读 S1 Final Head：
  `7564351c17cea034acd4c1be6d5eca83b642ac27`
- ContractSet：
  `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- 最终 S7 Head：本文件所在提交；精确 SHA 由交接消息返回
- 结论：PASS，交回 S1

## P1 根因

a2 已把 `S7_CANDIDATE` 与 `S1_FINAL` 分开，但仍有两个主分支边界：

1. `test_candidate_is_exact_and_dependency_complete()` 默认从当前 ROOT
   构造 Candidate Manifest，Candidate 的 `git.branch` 仍读取当前
   checkout。测试合入 `master` 或 `codex/s1/*` 后会把合法主分支误判为
   Candidate 身份失败。
2. `S1_FINAL` 从固定 S7 Candidate Head 计算到最终 Head。S1 合入经审查的
   a2/a3 verifier、test 和 evidence 后，这些 S7 独占路径会被旧范围规则
   误判为 S1 越权。

## 最小修复

### Candidate 纯复算与 checkout 门禁拆分

- Python API 的默认 Candidate 构造只重建固定 Candidate 身份、36 项检查
  和历史 Hash，不读取当前 checkout 分支。
- CLI 始终传入 `enforce_checkout_identity=True`：
  - S7 Candidate 分支：PASS。
  - `master` / `codex/s1/*`：仍在 `git.branch` 失败关闭。
- 因此仓库测试可在 S7、S1 或 main checkout 上复算同一候选身份；CLI 的
  操作身份门禁没有取消。

### Final 控制增量

`S1_FINAL` 允许的非产品控制增量现在是：

- S1 独占路径；
- 明确授权的共享 `.gitignore`；
- S7 独占 `scripts/integration/**`、`tests/integration/**` 和
  `artifacts/integration/**`；
- 被最终 `.gitignore` 覆盖的 `.idea/**` 删除，且只允许删除。

以下保护保持不变：

- Final 分支必须为 `codex/s1/*` 或 `master`。
- 固定 S7 Candidate Head 必须是 Final Head 的祖先。
- Apps、Packages、Domain Pack、Infra、Core/Runtime/Data tests、根
  Workspace 等受保护对象必须逐项相同。
- Contracts Tree、`uv.lock` Blob、Migration Tree 必须完全相同。
- S2/S5/S6 输入 Heads 必须仍为 Final Head 的祖先。
- S1 或 S7 之外的路径，以及任何产品路径修改，仍失败关闭。

Verifier 不嵌入 a3 自身 SHA；S7 工具通过 Final 增量路径所有权和 S7
Review 证明，避免递归的“提交中包含自身 SHA”问题。

## 回归测试

新增或加强：

1. Candidate 默认纯复算固定报告
   `branch=codex/s7/wp-040-integration-verification`，不依赖 checkout。
2. Candidate checkout 身份函数只接受 S7 Candidate 分支。
3. Final 接受经审查的 S7 verifier/test/evidence 路径。
4. S1 修改 `packages/domain/**` 仍失败。
5. 非 S1/S7 的 `tests/acceptance/**` 仍失败。
6. `.idea/**` 修改仍失败，只允许已忽略文件删除。
7. 固定合法 S1 Final Head 的全量 42 项静态门禁继续通过。

只读实测：

- 在 S1 Final Worktree 运行显式 Candidate CLI：
  `WP040_COMPOSITION_FAIL checks=36 failed=1`，退出码 1，符合身份门禁。
- 对同一 S1 Final Worktree 当前 Head 运行 `S1_FINAL`：
  `WP040_S1_FINAL_PASS checks=42 failed=0`，退出码 0。
- S1 Final Worktree 始终洁净且未被 S7 修改。

## FAST Gate

按派发要求未运行完整产品测试、Wheel、Fresh Install、Compose 或漏洞扫描。

| 命令 | 结果 |
|---|---|
| S7 Candidate CLI | PASS：36/36 |
| 固定 `9b166f8...` S1 Final verifier | PASS：42/42 |
| 当前 `7564351...` S1 Final verifier | PASS：42/42 |
| S1 checkout 上 Candidate CLI | EXPECTED FAIL：仅 `git.branch` |
| `pytest -q -p no:cacheprovider tests/integration` | PASS：16 passed |
| Ruff：`scripts/integration tests/integration` | PASS |
| Mypy `--strict scripts/integration/verify_wp040.py` | PASS：1 source file |
| `git diff --check` | PASS |
| S1 Final Worktree 洁净度 | PASS：0 changes |

Candidate 历史证据保持字节级一致：

```text
WP040_COMPOSITION_PASS checks=36 failed=0
MANIFEST_SHA256=sha256:1e9140e267470a0b4404a34b07254569875c3d8c582517599cc328ba8b5dddb1
REPORT_SHA256=sha256:533a2540a2d41264fe38bbc84c92ae5fa9bd5f3e1292b57598139e470c4e143c
```

固定 S1 Final 测试 Head 的 a2 证据也保持一致：

```text
WP040_S1_FINAL_PASS checks=42 failed=0
MANIFEST_SHA256=sha256:de0472abb4e07957a9ce70bc6a730852f2ea7fefa7494a292b450b271b6e69f6
REPORT_SHA256=sha256:8648d273b15a130d1dd234fba9dda6672ac5a67aaf87372e5eb6a0fff002ec5a
```

合入 a3 后的最终 Manifest/Report 由 S1 对新 Final Head 重新生成；它们会
包含新 Final Head 和经审查的 S7 控制增量，不在提交中预填自身 SHA。

## 修改文件

| 文件 | 变化 |
|---|---|
| `scripts/integration/verify_wp040.py` | 分离 Candidate 纯复算/CLI 身份；允许 Final 的 S7 控制路径 |
| `tests/integration/test_wp040_composition.py` | 增加 main checkout 与 S7 控制增量回归 |
| `tests/integration/evidence/WP-040-a3-HANDOFF.md` | 本交接 |

没有修改 S1 Final Worktree、产品、Contract、Migration、Workspace 或其他
会话分支；没有执行 merge、rebase、reset 或 push。

## S1 下一步

1. 将 a3 Head 合入 S1 Final 测试分支。
2. 在该 S1/main checkout 运行 `tests/integration`，预期全部 PASS。
3. 对新的 Final Head 运行 `--phase S1_FINAL`，预期产品、Contract、输入
   Heads、锁和 Migration 不变性全部 PASS。
4. S1 保留正式验收、合并和发布裁决。

## 机器可读摘要

```text
OUTCOME=PASS_HANDOFF
SESSION_ROLE=S7-INTEGRATION
WORK_PACKAGE=WP-040
ATTEMPT_ID=WP-040-a3
BASE_COMMIT=a2f7f39592229b81000ec43e15327da7fd564c2c
NEW_HEAD=<this-handoff-commit; exact-sha-in-final-message>
S7_CANDIDATE_GATE=PASS:36/36
S1_FINAL_GATE=PASS:42/42
INTEGRATION_TESTS=PASS:16
CANDIDATE_MANIFEST_SHA256=sha256:1e9140e267470a0b4404a34b07254569875c3d8c582517599cc328ba8b5dddb1
CANDIDATE_REPORT_SHA256=sha256:533a2540a2d41264fe38bbc84c92ae5fa9bd5f3e1292b57598139e470c4e143c
FIXED_FINAL_MANIFEST_SHA256=sha256:de0472abb4e07957a9ce70bc6a730852f2ea7fefa7494a292b450b271b6e69f6
FIXED_FINAL_REPORT_SHA256=sha256:8648d273b15a130d1dd234fba9dda6672ac5a67aaf87372e5eb6a0fff002ec5a
HANDOFF=tests/integration/evidence/WP-040-a3-HANDOFF.md
NEXT_ROLE=S1-ARCH
```
