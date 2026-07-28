# FlowPilot 四会话执行契约

## 契约作用

会话契约把角色说明转换为可验收的工作边界。每个顶层 Codex 会话只能绑定一个 `SESSION_ROLE`，并执行对应契约：

| 会话 | 契约 | 当前工作包 | 当前激活状态 |
|---|---|---|---|
| S1-ARCH | [SC-S1-ARCH-v1](./S1-ARCH.md) | [WP-000](../work-packages/WP-000-m0-contract-freeze.md) | ACTIVE |
| S2-RUNTIME | [SC-S2-RUNTIME-v1](./S2-RUNTIME.md) | [WP-010](../work-packages/WP-010-runtime-bootstrap.md) | REVIEW_ONLY |
| S3-PLATFORM | [SC-S3-PLATFORM-v1](./S3-PLATFORM.md) | [WP-020](../work-packages/WP-020-platform-bootstrap.md) | REVIEW_ONLY |
| S4-QUALITY | [SC-S4-QUALITY-v1](./S4-QUALITY.md) | [WP-030](../work-packages/WP-030-quality-bootstrap.md) | REVIEW_ONLY |

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

当前尚无 Git 基线和独立 Worktree。为避免四会话同时修改同一目录，只有 S1 处于 `ACTIVE`。用户完成 Git 基线后，S1 按工作包索引把 S2、S3、S4 切换为 `ACTIVE`。

Git 基线前可以立即启动另外三个顶层会话进行只读审查。它们使用 [rc2 三会话复审指令](../RC2_REVIEW_INSTRUCTIONS.md) 绑定同一 `content_digest`，并按 [契约审查模板](../CONTRACT_REVIEW_TEMPLATE.md) 返回结论；由 S1 统一落盘，避免并行写同一目录。

## 每次会话必须声明

```text
SESSION_ROLE=<S1-ARCH|S2-RUNTIME|S3-PLATFORM|S4-QUALITY>
WORK_PACKAGE=<WP-ID>
FEATURE_IDS=<FP-ID,...>
WRITE_SCOPE=<允许路径>
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
