# WP-011：Core、API 与 Python Workspace 基线

## 元数据

- 状态：READY_ON_ACTIVATION_COMMIT
- 责任会话：S5-CORE
- 评审会话：S1-ARCH、S2-RUNTIME、S4-QUALITY
- 功能 ID：FP-FLOW-007、FP-FLOW-008、FP-FLOW-009、FP-APR-001
- 依赖工作包：五角色同摘要 ACCEPT 与 Attestation 已完成；从实现基线激活提交创建独立 Worktree
- 目标分支：`codex/s5/wp-011-core-bootstrap`

## 目标

- 建立可安装、可测试的 Python 3.12+ Workspace。
- 建立纯 Domain、Application Port、FastAPI Command Intake 与 IT Service Domain Pack 骨架。
- 为 S2/S3/S4/S6 提供公共依赖、稳定测试命令和契约适配基线。

## 非目标

- LangGraph、Worker、Provider Adapter 或 Context 构建。
- MCP Gateway、PolicyDecision、Repository、Migration 或真实基础设施。
- 完整 IT 服务业务闭环。
- 修改公共契约或验收状态。

## 允许修改路径

- `apps/api/**`
- `packages/domain/**`
- `packages/application/**`
- `domain-packs/it-service/**`
- `tests/core/**`
- `pyproject.toml`
- `uv.lock`
- `Makefile`

本工作包是 M0 中 `pyproject.toml`、`uv.lock`、`Makefile` 的唯一写入者。

## 输入契约

| 契约 | 版本 | 提供者 |
|---|---|---|
| `contract-set.v1.json` | reviewed implementation baseline | S1-ARCH |
| Task / Command / Event、Approval、SecurityContextRef | v1 | S1-ARCH |
| Runtime Execution Port 约束 | M0 internal | S2-RUNTIME |
| Repository/Unit-of-Work Port 约束 | M0 internal | S6-DATA |

## 输出契约

| 契约 | 版本 | 消费者 |
|---|---|---|
| Python Workspace 与稳定测试命令 | M0 | S1/S2/S3/S4/S6 |
| Domain/Application Port | M0 internal | S2/S6 |
| API Command/Event 适配层与 OpenAPI | v1 skeleton | S4 |
| 纯领域与 API Fixture | M0 | S4 |

## 架构与安全约束

- Domain 不依赖任何 Web、Graph、ORM、Redis、MCP 或 Provider 框架。
- API 只提交 `TaskCommand`；不得直接改变任务状态或生成权威 Event。
- Command 摘要、安全上下文、租户、主体、用途、幂等和版本必须在 Intake 确定性校验。
- Application 只依赖 Port；具体 Runtime 和 Persistence Adapter 由 S2/S6 提供。
- 新生产依赖必须记录许可证、用途、替代方案和攻击面。

## 实施内容

1. 创建 Workspace、依赖组、格式、类型、测试配置与锁文件。
2. 创建纯领域 Task/Command/Approval 值对象和状态转换。
3. 创建 Application Use Case、Runtime/Persistence Port 和稳定错误。
4. 创建 FastAPI 健康检查、Command Intake 和只读 Task API 骨架。
5. 创建 IT Service Domain Pack 注册边界。
6. 提供 `make bootstrap`、`make test`、`make test-contract` 基础命令。
7. 添加领域依赖、命令冲突、重放、安全绑定和 API 契约测试。

## 必须测试

- 正常：Command Intake → Application Use Case → Runtime/Persistence Fake。
- 边界：空附件、最大版本、合法等待状态和最小 Domain Pack。
- 失败：摘要错误、版本冲突、非法状态和外部错误映射。
- 安全：Tenant/Subject/Purpose 错配、领域框架依赖和授权对象伪造被拒绝。
- 恢复/幂等：相同 Command 重放，同键不同摘要冲突。

## 验收命令

```bash
make bootstrap
make test
make test-contract
```

## 完成定义

- 空 Python 环境可重复安装和运行基础命令。
- Domain 依赖、API 契约、Command 安全和幂等测试通过。
- S2/S3/S4/S6 可在不修改公共 Workspace 的情况下接入。
- S1/S2/S4 完成跨角色审查。
