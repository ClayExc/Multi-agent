# WP-011-H1 S1 验收记录

## 结论

- 日期：2026-07-29
- 评审角色：S1-ARCH
- Attempt：`WP-011-a1`
- 分支：`codex/s5/wp-011-core-bootstrap`
- 基线：`b5caaf2448c2860cfa67d8c5a39b9cda62eca809`
- 评审提交：`ce5600c77da9b0dc2a2062bebd5d7098b439bef0`、`1ac0f9377872ea5ab7f4c32b8fb1d52497394edb`
- 修复提交：`c4e33590caa23d60b8a10342b80502b60517018b`
- 修复交接：`3ab002774539b6e5557d1d7268feceed54a587a4`
- 合并提交：`5959820d9740f162fc3fdb0e74372bb6d0cbcc7a`
- ContractSet：`sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- 裁决：`ACCEPTED_AND_MERGED`

WP-011-H1 已接受并合入主分支。它解锁 WP-010 与 WP-021 的 Port 实现；完整 WP-011 仍需继续交付 API 与 IT Service Domain Pack。

## 复审结果

- `Approval.expires_at` 与 `PlannedAction.expires_at` 在 UTC 规范化后确定性比较。
- 单字段过期时间错配稳定返回 `APPROVAL_BINDING_MISMATCH`。
- 同一时刻使用不同时区偏移的合法表示仍可通过。
- S1 独立运行 Core：`22 passed`。
- S1 独立运行 Contract Conformance：PASS。
- 合入 S4 离线基线后的联合测试：`50 passed`。
- S5 Worktree 在交接时干净，`.idea` 噪音未进入提交。

## 已复核内容

- 改动只涉及 S5 独占目录以及 WP-011 指定的 `pyproject.toml`、`uv.lock`、`Makefile`。
- Domain 未依赖 FastAPI、LangGraph、SQLAlchemy、Redis、MCP 或 Provider SDK。
- Command Intake 的摘要/安全绑定、逻辑去重、版本槽和恢复顺序与交接说明一致。
- `ExecutionPort`、Repository、Command Inbox 和 Unit of Work 的责任边界可供 S2/S6 实现。
- S1 独立运行 `tests/core`：`21 passed`。
- S1 独立运行 Contract Conformance：PASS，包含 43 个语义负例。

## 已关闭的阻断项

### S1-WP011-H1-001：Approval 过期时间未参与跨对象绑定

`Approval.assert_action_binding()` 比较了租户、任务、请求人、Action ID、Action Digest、Tool Schema Hash 和策略版本，但没有比较 `Approval.expires_at` 与 `PlannedAction.expires_at`。

S1 构造了 Action 在 `08:15Z` 过期、Approval 在 `08:30Z` 过期的对象。两者其他绑定完全一致，当前方法未抛出异常并正常返回。

这违反：

- ADR-0002 第 2 条：审批必须绑定过期时间。
- Contract Conformance 的 `approval.expires_at_mismatch.semantic_invalid`。
- 工具安全门禁：审批必须未过期并绑定当前动作。

`action_digest` 包含 PlannedAction 的过期时间，只能证明 Approval 保存的 Digest 指向该 Action，不能证明 Approval 自己单独保存的 `expires_at` 与 Action 相同。

处置要求（已完成）：

1. 在确定性跨对象绑定中比较两者的规范化 UTC 时间。
2. 增加单字段错配负例，断言稳定的 `APPROVAL_BINDING_MISMATCH`。
3. 重跑 Core、Contract、Ruff、Mypy 和 wheel 构建。
4. 更新 Handoff 与 Proof，提交新的复审 HEAD。

## Advisory

- S5 Worktree 当前存在 `.idea` 已跟踪文件变化和未跟踪模块文件。它们不在交付提交中，但复审前工作区必须恢复为干净；不得把 IDE 私有状态混入修复提交。
- H1 仍不是完整 WP-011。修复并接受 H1 后，只解锁 S2/S6 的 Port 实现，不提升 API 或 Domain Pack 的功能状态。

## 后续范围

- H1 接受不提升 API、Domain Pack 或完整 FP 功能状态。
- S5 后续实现使用新的 Attempt，继续留在 WP-011 与原独立 Worktree。
- S2 必须实现 tenant + command_id 幂等的 `ExecutionPort`。
- S6 必须原子实现 Repository、Command Inbox、版本槽和 Unit of Work。
