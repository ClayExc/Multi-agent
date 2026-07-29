# WP-011 H1 S5-CORE 交接

## 基本信息

- Work Package：WP-011 / WP-011-H1
- Attempt：WP-011-a1
- 风险等级：R2
- 责任会话：S5-CORE
- 接收会话：S1-ARCH；后续消费者 S2-RUNTIME、S6-DATA
- 功能 ID：FP-FLOW-007、FP-FLOW-008、FP-FLOW-009、FP-APR-001
- 分支：`codex/s5/wp-011-core-bootstrap`
- 基线提交：`b5caaf2448c2860cfa67d8c5a39b9cda62eca809`
- Control Plane 提交：`4322d1778583df71bc861817547b9c0b2ead0ccb`
- H1 实现提交：`ce5600c77da9b0dc2a2062bebd5d7098b439bef0`
- H1 修复提交：`c4e33590caa23d60b8a10342b80502b60517018b`
- ContractSet 摘要：`sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- 状态：`S1-WP011-H1-001` 已修复；等待 S1 复审

## S1 修复记录

- 阻断项：`S1-WP011-H1-001`
- 失败机理：Approval 单独保存的 `expires_at` 未与其绑定的
  PlannedAction 过期时间进行跨对象比较。
- 修复：`Approval.assert_action_binding()` 分别将 Approval 与
  PlannedAction 的 `expires_at` 规范化为 UTC，再进行确定性相等比较。
- 独立负例：只延后 Approval 的 `expires_at`，其余 Tenant、Task、
  Requester、Action ID、Action Digest、Tool Schema Hash 和 Policy Version
  保持一致；结果稳定返回 `APPROVAL_BINDING_MISMATCH`。
- 等价时区正例：Approval 使用 `+02:00` 表示与 PlannedAction 相同的时刻，
  规范化后绑定通过。

## 完成内容

- 建立 Python 3.12+ uv workspace、锁文件、开发依赖组和
  `bootstrap`、`test`、`test-contract` Make 目标。
- 建立不依赖 Web、Graph、ORM、Redis、MCP 或 Provider SDK 的纯
  Domain 包。
- 按公共 v1 契约实现 Task、TaskCommand、SecurityContextRef、
  PlannedAction 和 Approval 的不可变值对象、严格字段边界和稳定领域错误。
- 使用 RFC 8785 + SHA-256 重算 Command/PlannedAction 摘要，并确定性校验
  Tenant、Subject、Purpose、工具 Schema、策略版本、规范化过期时间和职责
  分离绑定。
- 实现 Application Command Intake，以及 S2 消费的 `ExecutionPort` 和
  S6 消费的 Repository、Command Inbox、Unit-of-Work Port。
- 固定 Intake 顺序为：摘要/安全绑定 → 幂等键 → command_id → 任务版本 →
  版本槽位；已接受但未成功分发的命令可通过同命令重放恢复。
- 提供 tenant-scoped、事务回滚可见的最小内存 Fake 和幂等 Execution Fake。
- 添加正常、边界、失败、安全、恢复/幂等测试，并以 JSON Schema 再校验
  Domain 对外投影。

## 未完成与非目标

- 遵照派单在 H1 停止，没有创建 FastAPI Command Intake、只读 Task API 或
  OpenAPI 骨架。
- 没有创建 IT Service Domain Pack 注册边界。
- 没有实现 LangGraph、Worker、真实 Runtime Adapter、数据库 Repository、
  Migration、MCP、Policy 或其他基础设施。
- 没有修改公共契约、架构/验收文档、其他角色目录，也没有合并主分支。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `pyproject.toml`、`uv.lock`、`Makefile` | Workspace、锁文件和稳定命令 | S5-CORE（WP-011 共享文件写入者） |
| `packages/domain/**` | 纯领域值、状态约束、摘要与安全绑定 | S5-CORE |
| `packages/application/**` | Use Case、Ports、稳定错误和最小 Fake | S5-CORE |
| `tests/core/**` | H1 测试与本交接证据 | S5-CORE |

## 契约、数据库与配置变化

- 契约版本：无变化；消费 reviewed ContractSet v1。
- Migration：无。
- 环境变量：无。
- 新生产依赖：`rfc8785==0.1.4`，Apache Software License；用途、替代方案和
  攻击面记录在 `packages/domain/README.md`。
- 兼容性：Python `>=3.12`；内部 Port 版本
  `flowpilot.application-ports.m0.v1`。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| `make bootstrap` | PASS | Python 3.12.11；Resolved 21 / Audited 20 packages |
| `make test` | PASS | 22 collected，22 passed in 0.64s |
| `make test-contract` | PASS | `CONTRACT_CONFORMANCE_OK`：20 schemas、35 cases、19 mutation cases、43 semantic cases、5 audit-chain cases、21 manifest cases、52 features |
| `ruff check --no-cache packages/domain packages/application tests/core` | PASS | `All checks passed!` |
| `mypy packages/domain/src packages/application/src` | PASS | 15 source files，0 issues |
| `uv build packages/domain --wheel`、`uv build packages/application --wheel` | PASS | 两个 wheel 构建成功且均包含 `py.typed` |

验收机原先未安装全局 `make` 和 `uv`。本次使用工作树外的临时 GNU Make
4.4.1 与 uv 0.8.24 执行上述 Make 目标，虚拟环境和缓存也位于工作树外。

## 安全与失败路径

- 已验证负向路径：错误摘要、同幂等键不同摘要、陈旧版本、版本槽位冲突、
  非法状态转换、无效 Execution Receipt、Runtime 失败恢复、跨租户 Task
  绑定、Tenant/Purpose 错配、审批人等于请求者、Approval 过期时间单字段
  错配、动作参数篡改、授权字段注入和非字符串引用。
- Domain 框架依赖由 AST 测试阻断；测试覆盖的禁止根包括 FastAPI、
  LangGraph、SQLAlchemy、Redis、MCP 和 Provider SDK。
- 外部异常只映射为稳定错误码和安全消息；测试确认原始异常中的敏感文本
  不进入 `safe_message`。
- Secret/PII 检查：未加入 Secret、访问令牌、真实 PII、生产 Prompt/Trace
  或原始附件。

## 已知问题

- Port 是 M0 internal baseline，需 S1/S2/S6 做可实现性复核后才能视为跨角色
  接口接受。
- 内存 Fake 只验证端口语义，不模拟真实数据库并发、隔离级别、进程崩溃或
  消息基础设施；这些属于 S6/WP-021 和 S2/WP-010。
- Command 先持久化再调用 Execution Port。真实 S2 Adapter 必须按 Tenant +
  command_id 幂等，真实 S6 Adapter 必须原子持久化幂等映射和版本槽位。
- H1 不是完整 WP-011，不应据此将 API 或 Domain Pack 标为 IMPLEMENTED。

## 接收会话下一步

1. S1-ARCH 复核修复提交 `c4e33590caa23d60b8a10342b80502b60517018b`
   的 UTC 过期时间绑定、单字段负例和本 HANDOFF 对应的 NEW_HEAD。
2. S2-RUNTIME 验证并实现 `ExecutionPort.submit` 的 tenant + command_id
   幂等语义，返回绑定 Command/Tenant/Task 的 Receipt。
3. S6-DATA 验证并实现 Task Repository、Command Inbox 和 Unit of Work，
   原子保证幂等映射与版本槽位唯一性。
4. S1 验收 H1 后，再决定是否激活 WP-011 后续 API 与 Domain Pack 工作。

## 可回滚方式

- H1 为单一实现提交，可在未合并前丢弃分支，或在合并后执行
  `git revert ce5600c77da9b0dc2a2062bebd5d7098b439bef0`。
- 修复可独立执行
  `git revert c4e33590caa23d60b8a10342b80502b60517018b`。
- 本包没有数据库、契约或环境变量变化，不需要数据回滚。
