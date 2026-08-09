# FlowPilot 七会话执行契约

## 契约作用

会话契约把角色说明转换为可验收的工作边界。每个顶层 Codex 会话只能绑定一个 `SESSION_ROLE`，并执行对应契约：

| 会话 | 契约 | 当前工作包 | 当前激活状态 |
|---|---|---|---|
| S1-ARCH | [SC-S1-ARCH-v1](./S1-ARCH.md) | 无；M7 候选已合入 | IDLE |
| S2-RUNTIME | [SC-S2-RUNTIME-v2](./S2-RUNTIME.md) | 无；WP-070/071/072 已完成 | IDLE |
| S3-PLATFORM | [SC-S3-PLATFORM-v2](./S3-PLATFORM.md) | 无 | IDLE |
| S4-QUALITY | [SC-S4-QUALITY-v1](./S4-QUALITY.md) | 无；WP-072/073 已完成 | IDLE |
| S5-CORE | [SC-S5-CORE-v1](./S5-CORE.md) | 无；WP-070/071 与安全返修已完成 | IDLE |
| S6-DATA | [SC-S6-DATA-v1](./S6-DATA.md) | 无；WP-071 已完成 | IDLE |
| S7-INTEGRATION | [SC-S7-INTEGRATION-v1](./S7-INTEGRATION.md) | 无；WP-073 组合复现已完成 | IDLE |

## 约束优先级

1. 用户对当前工作的明确要求。
2. 根目录 `AGENTS.md` 与架构不变量。
3. 本目录中的对应会话契约。
4. 当前工作包。
5. 会话自己的实现偏好。

低层规则不得放宽高层安全边界。发现冲突时停止相关写入，由 S1 记录并裁决；非 S1 会话通过 RFC 请求变更。

## 激活状态

- `ACTIVE`：允许在所有权与工作包范围内写入。
- `REVIEW_ONLY`：只读检查契约、架构和工作包，在会话中返回审查结论；不得写仓库。
- `BLOCKED`：存在外部前置条件，除记录阻塞信息外不能推进。
- `HANDOFF`：实现结束，等待跨角色审查或集成。

当前只保留主 Worktree，没有活动开发 Agent。ContractSet 候选摘要为
`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`；
M0～M7 与 P2 已进入主分支，M8 尚未激活。任何角色必须按 Agent Registry
从新的主基线取得 Attempt 和写入范围，历史分支或会话状态不能自动视为写授权。

本摘要的五角色只读复审已经完成；[rc2 五会话复审指令](../RC2_REVIEW_INSTRUCTIONS.md) 现作为历史复现入口。若被摘要覆盖的内容发生变化，全部 Review 自动失效并重新进入 `REVIEW_ONLY`。

## 每次会话必须声明

```text
SESSION_ROLE=<S1-ARCH|S2-RUNTIME|S3-PLATFORM|S4-QUALITY|S5-CORE|S6-DATA|S7-INTEGRATION>
WORK_PACKAGE=<WP-ID>
FEATURE_IDS=<FP-ID,...>
WRITE_SCOPE=<允许路径>
EXECUTION_MODE=<PARALLEL|READ_ONLY_PARALLEL|ORDERED>
```

缺失以上声明时，只允许只读分析。

## 统一输出

每次完成一个工作包必须输出：

- 完成与未完成内容。
- 修改文件与契约/数据库变化。
- 实际运行命令及退出结果。
- 正常、边界、失败、安全和恢复测试结果。
- 已知风险和证据路径。
- 下一接收会话及其明确动作。

仓库交接使用 `docs/team/HANDOFF_TEMPLATE.md`。聊天中的“已完成”不能替代交接与证据。
