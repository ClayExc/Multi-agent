# SC-S5-CORE-v1：领域、应用与 API 核心

## 会话声明

```text
SESSION_ROLE=S5-CORE
WORK_PACKAGE=NONE
FEATURE_IDS=NONE
WRITE_SCOPE=apps/api/**,packages/domain/**,packages/application/**,domain-packs/it-service/**,tests/core/**,WP-011授权共享文件
```

- 契约状态：IDLE
- 当前工作：无；下一候选为 [WP-071](../work-packages/WP-071-m7-local-product-composition.md)
- 激活条件：WP-070 通过，Agent Registry 分配 Base、Attempt、范围与退出条件。

## 使命

建立不依赖框架的领域核心、版本化应用用例与 API Command Intake，并提供全仓可安装、可测试的 Python Workspace。S5 负责把外部请求转换为公共 `TaskCommand`，通过端口调用 S2 Runtime，而不拥有 LangGraph、授权或持久化实现。

## 决策权

S5 可以：

- 设计纯 Python Domain 值对象、状态转换和 Application Port。
- 决定 FastAPI 路由、稳定 API 错误映射和 Command Intake 细节。
- 管理公共 Python Workspace、依赖组、锁文件和基础测试命令。
- 在契约不足时向 S1 提交 RFC。

S5 不可以：

- 修改 LangGraph、Worker、Provider Adapter 或 Context 策略。
- 实现 PolicyDecision、MCP Gateway、RLS、Repository 或迁移。
- 让 API 直接 PATCH Task 状态或生成权威 TaskEvent。
- 复制、放宽或扩展 `contracts/**` 的公共对象。

## 输入与输出

| 类型 | 内容 |
|---|---|
| 输入 | Task/Command/Event、Approval、SecurityContextRef、ADR-0001/0003、S2 Execution Port 约束与 WP-011 |
| 输出给 S2 | 版本化 Application Port、已校验 TaskCommand、领域状态转换约束 |
| 输出给 S6 | Repository/Unit-of-Work Port、Task Projection 与 Command Inbox 事务需求 |
| 输出给 S4 | OpenAPI、稳定错误码、API Fixture 与纯领域 Fake |
| 输出给 S1 | API/领域契约缺口、依赖变化、RFC 与交接证据 |

## 工程约定

1. `packages/domain` 不依赖 FastAPI、LangGraph、SQLAlchemy、Redis、MCP 或 Provider SDK。
2. API 只接受版本化 Command；`task_id` 预分配、摘要重算、安全上下文绑定和版本检查均可确定性测试。
3. Application 只依赖 Port，不依赖 S2/S3/S6 的具体 Adapter。
4. 领域时间使用带时区 UTC，标识不可猜测；状态转换拒绝非法组合。
5. `pyproject.toml`、`uv.lock`、`Makefile` 在 M0 只由 S5 单写；其他会话通过依赖请求交接。
6. 新依赖必须记录用途、许可证、替代方案和攻击面。

## 必须交付的测试

- 正常：API Command → Application Use Case → S2 Execution Port Fake。
- 边界：创建命令空可选附件、最大版本、合法等待状态。
- 失败：摘要错误、过期版本、非法状态转换和稳定错误映射。
- 安全：伪造租户/主体/用途、领域框架依赖和模型构造授权对象被拒绝。
- 恢复/幂等：相同 Command 重放得到同一逻辑结果，同键不同摘要冲突。

## 历史基线职责

从包含本状态的激活提交创建独立 Worktree 后执行 WP-011：

1. 建立 Python Workspace、公共依赖组和稳定测试命令。
2. 建立纯 Domain、Application Port、Command Intake 和 API 骨架。
3. 优先交付 `WP-011-H1`：Python Workspace、Application Execution Port 与 Repository/UoW Port。
4. H1 由 S1 接受后，S2/WP-010 与 S6/WP-021 才可进入实现。

## 完成定义

- WP-011 验收命令在空 Python 环境可重复运行。
- 领域依赖门禁、API 契约、Command 安全负例和幂等测试齐备。
- 公共依赖和命令入口可供 S2/S3/S4/S6 使用。
- 交接由 S1/S2/S4 复核后，相关功能才可更新状态。
