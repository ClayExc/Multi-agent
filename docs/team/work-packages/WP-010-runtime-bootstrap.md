# WP-010：Runtime 与 Python Workspace 基线

## 元数据

- 状态：BLOCKED
- 责任会话：S2-RUNTIME
- 评审会话：S1-ARCH、S4-QUALITY
- 功能 ID：FP-FLOW-001、FP-FLOW-002、FP-FLOW-009、FP-AGT-002、FP-CTX-001
- 依赖工作包：S2/S3/S4 对同一 WP-000 `content_digest` 全部 ACCEPT、Git 基线提交
- 目标分支：`codex/s2-runtime/wp-010-runtime-bootstrap`

## 目标

- 建立可安装、可测试的 Python 3.12+ workspace。
- 建立 Domain、Application、API、Worker、Fake Runtime 与 Context 的最小端口和契约适配骨架。
- 用架构依赖测试阻止领域层依赖框架和 Provider SDK。

## 非目标

- 完整 VPN 业务闭环或 Multi-Agent 图。
- 真实 Provider 账户调用。
- 直连 PostgreSQL、Redis、OPA、MCP 或企业网络。
- 修改公共契约或实现最终授权。

## 允许修改路径

- `apps/api/**`
- `apps/worker/**`
- `packages/domain/**`
- `packages/application/**`
- `packages/graph/**`
- `packages/agent-runtime/**`
- `packages/model-gateway/**`
- `packages/context/**`
- `domain-packs/it-service/**`
- `tests/runtime/**`
- `pyproject.toml`
- `uv.lock`
- `Makefile`

本工作包是 M0 中 `pyproject.toml`、`uv.lock`、`Makefile` 的唯一写入者。

## 输入契约

| 契约 | 版本 | 提供者 |
|---|---|---|
| `contract-set.v1.json` | `1.0.0-rc.2` reviewed implementation baseline | S1-ARCH |
| Task / Command / Event | v1 | S1-ARCH |
| ContextEnvelope / AgentRunRequest / AgentRunResult | v1 | S1-ARCH |
| ToolRequest / ToolResult | v1 | S1-ARCH |
| Agent Runtime Port 与 Conformance Cases | rc2 当前版本 | S1-ARCH |

## 输出契约

| 契约 | 版本 | 消费者 |
|---|---|---|
| Python workspace 与稳定测试命令 | M0 | S3、S4、S1 |
| Domain/Application Port | M0 internal | S3 |
| Fake Runtime Conformance Fixture | M0 | S4 |
| API Command/Event 适配层 | v1 skeleton | S4 |

## 架构与安全约束

- `packages/domain` 不依赖 FastAPI、LangGraph、SQLAlchemy、Redis、MCP 或 Provider SDK。
- API 只提交 `TaskCommand`；内部节点名不进入公共接口。
- Graph State 不存 Provider Session、Token、原始附件或 SDK 对象。
- Fake Runtime 必须确定性且不依赖网络。
- 所有跨进程对象严格消费冻结 Schema；契约不足时提交 RFC。

## 实施内容

1. 创建 workspace、基础依赖组、格式/类型/测试配置与锁文件。
2. 创建最小 API、Worker 入口和健康检查，不接真实基础设施。
3. 定义纯领域 Task/Command 值对象和 Application Port。
4. 创建 Fake Runtime 与最小 ContextEnvelope 构建器。
5. 创建稳定错误码和契约转换边界。
6. 添加领域依赖、命令冲突、重复命令与 Fake Runtime 测试。
7. 提供 `make bootstrap`、`make test`、`make test-contract` 基础命令；未覆盖项必须失败或明确标记，不得假通过。

## 必须测试

- 正常路径：创建命令进入可运行投影，Fake Runtime 返回确定性结果。
- 边界条件：空可选上下文、最大允许版本值和合法等待状态。
- 失败路径：过期 `expected_task_version`、未知命令类型和 Runtime 结构错误。
- 安全负向：领域层依赖扫描；模型输出不能构造 SecurityContext/PolicyDecision。
- 恢复/幂等：同一命令重复提交只产生一个逻辑处理结果。

## 验收命令

```bash
make bootstrap
make test
make test-contract
```

## 证据

- `tests/runtime/**` 测试结果
- 依赖边界报告
- Runtime Conformance 报告
- 按 `docs/team/HANDOFF_TEMPLATE.md` 创建的交接

## 完成定义

- 所有验收命令在空 Python 环境按文档可重复运行。
- 正常、边界、失败、负向和幂等测试均存在且通过。
- 未复制或放宽公共 Schema。
- S1/S4 完成跨角色审查；相关功能只能按证据更新状态。
