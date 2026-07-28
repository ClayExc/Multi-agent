# WP-011-H1 S1 验收记录

## 结论

- 日期：2026-07-29
- 评审角色：S1-ARCH
- Attempt：`WP-011-a1`
- 分支：`codex/s5/wp-011-core-bootstrap`
- 基线：`b5caaf2448c2860cfa67d8c5a39b9cda62eca809`
- 评审提交：`ce5600c77da9b0dc2a2062bebd5d7098b439bef0`、`1ac0f9377872ea5ab7f4c32b8fb1d52497394edb`
- ContractSet：`sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- 裁决：`CHANGES_REQUESTED`

WP-011-H1 暂不接受，不能据此解锁 WP-010 或 WP-021。主体结构、路径所有权和已有测试有效；阻断项修复后沿用原分支和 Attempt 复审。

## 已复核内容

- 改动只涉及 S5 独占目录以及 WP-011 指定的 `pyproject.toml`、`uv.lock`、`Makefile`。
- Domain 未依赖 FastAPI、LangGraph、SQLAlchemy、Redis、MCP 或 Provider SDK。
- Command Intake 的摘要/安全绑定、逻辑去重、版本槽和恢复顺序与交接说明一致。
- `ExecutionPort`、Repository、Command Inbox 和 Unit of Work 的责任边界可供 S2/S6 实现。
- S1 独立运行 `tests/core`：`21 passed`。
- S1 独立运行 Contract Conformance：PASS，包含 43 个语义负例。

## 阻断项

### S1-WP011-H1-001：Approval 过期时间未参与跨对象绑定

`Approval.assert_action_binding()` 比较了租户、任务、请求人、Action ID、Action Digest、Tool Schema Hash 和策略版本，但没有比较 `Approval.expires_at` 与 `PlannedAction.expires_at`。

S1 构造了 Action 在 `08:15Z` 过期、Approval 在 `08:30Z` 过期的对象。两者其他绑定完全一致，当前方法未抛出异常并正常返回。

这违反：

- ADR-0002 第 2 条：审批必须绑定过期时间。
- Contract Conformance 的 `approval.expires_at_mismatch.semantic_invalid`。
- 工具安全门禁：审批必须未过期并绑定当前动作。

`action_digest` 包含 PlannedAction 的过期时间，只能证明 Approval 保存的 Digest 指向该 Action，不能证明 Approval 自己单独保存的 `expires_at` 与 Action 相同。

必须处置：

1. 在确定性跨对象绑定中比较两者的规范化 UTC 时间。
2. 增加单字段错配负例，断言稳定的 `APPROVAL_BINDING_MISMATCH`。
3. 重跑 Core、Contract、Ruff、Mypy 和 wheel 构建。
4. 更新 Handoff 与 Proof，提交新的复审 HEAD。

## Advisory

- S5 Worktree 当前存在 `.idea` 已跟踪文件变化和未跟踪模块文件。它们不在交付提交中，但复审前工作区必须恢复为干净；不得把 IDE 私有状态混入修复提交。
- H1 仍不是完整 WP-011。修复并接受 H1 后，只解锁 S2/S6 的 Port 实现，不提升 API 或 Domain Pack 的功能状态。

## 复审入口

S5 提交修复后提供：

```text
SESSION_ROLE=S5-CORE
WORK_PACKAGE=WP-011
ATTEMPT_ID=WP-011-a1
MODE=REMEDIATION_HANDOFF
NEW_HEAD=<commit>
FIXED=S1-WP011-H1-001
```
