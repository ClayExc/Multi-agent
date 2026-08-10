# WP-037：主 Agent 与子 Agent 工程契约

## 元数据

- 状态：DONE
- Attempt ID：WP-037-a1
- 风险等级：R1
- 责任会话：S1-ARCH
- 评审会话：S2～S7 在 M8 首次消费时验证可执行性
- 功能 ID：FP-OPS-002
- 依赖工作包：WP-036、M7 final
- 执行模式：ORDERED
- Chain ID：无
- Step ID：无
- 交接策略：S1_GATE
- 下一角色：无；M8 尚未激活
- 目标分支：`master`

## 目标

- 保留长期会话的 DELTA 热启动。
- 明确 S1～S7 作为领域主 Agent 自主调用临时子 Agent 的权限、上下文、并发、Git
  和交接规则。
- 让 M8 后续工作优先使用主 Agent 内部分派，减少新增长期会话和跨会话 Token。

## 非目标

- 不启动 M8，不创建 M8 分支或 Worktree。
- 不修改公共 ContractSet、产品代码、Migration、依赖和发布状态。
- 不允许子 Agent 绕过路径 Owner、工作包、风险门禁或用户批准。

## 允许修改路径

- `AGENTS.md`
- `README.md`
- `docs/team/**`

## 输入契约

| 契约 | 版本 | 提供者 |
|---|---|---|
| Context Bootstrap | v1 | S1-ARCH |
| Agent Registry | v1 | S1-ARCH |
| Work Package / Handoff | 当前模板 | S1-ARCH |

## 输出契约

| 契约 | 版本 | 消费者 |
|---|---|---|
| Principal/Subagent Protocol | `flowpilot.principal-subagent.v1` | S1～S7 |

## 架构与安全约束

- 子 Agent 权限是父角色、工作包与子任务范围的交集。
- 同一 Worktree 只有一个写入者。
- 子 Agent 没有 Git、跨会话唤醒、契约和发布裁决权。
- 正式证据必须由领域主 Agent 复现并提交。

## 必须测试

- 所有新增相对链接可解析。
- 旧模板仍可使用，新增字段不会改变公共 ContractSet。
- 文档明确覆盖只读并行、单写者、越权、上下文缺失和结果冲突。
- M7 状态、M8 未激活状态不发生回退。

## 完成定义

- 主协议、根工程约定、热启动、注册、工作包、交接和唤醒文档引用一致。
- Git 差异仅包含 S1 文档路径并通过格式与链接检查。
