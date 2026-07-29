# FlowPilot 七会话执行契约

## 契约作用

会话契约把角色说明转换为可验收的工作边界。每个顶层 Codex 会话只能绑定一个 `SESSION_ROLE`，并执行对应契约：

| 会话 | 契约 | 当前工作包 | 当前激活状态 |
|---|---|---|---|
| S1-ARCH | [SC-S1-ARCH-v1](./S1-ARCH.md) | [WP-000](../work-packages/WP-000-m0-contract-freeze.md) | ACTIVE |
| S2-RUNTIME | [SC-S2-RUNTIME-v2](./S2-RUNTIME.md) | [WP-010/WP-012](../work-packages/WP-012-langgraph-studio-observability.md) | WP010_ACCEPTED / WP012_READY |
| S3-PLATFORM | [SC-S3-PLATFORM-v2](./S3-PLATFORM.md) | [WP-020](../work-packages/WP-020-platform-bootstrap.md) | READY_ON_BASELINE_SYNC |
| S4-QUALITY | [SC-S4-QUALITY-v1](./S4-QUALITY.md) | [WP-030](../work-packages/WP-030-quality-bootstrap.md) | ACTIVE_ON_COMMIT（离线范围） |
| S5-CORE | [SC-S5-CORE-v1](./S5-CORE.md) | [WP-011](../work-packages/WP-011-core-bootstrap.md) | ACCEPTED_M0 |
| S6-DATA | [SC-S6-DATA-v1](./S6-DATA.md) | [WP-021](../work-packages/WP-021-data-bootstrap.md) | ACCEPTED_M0 |
| S7-INTEGRATION | [SC-S7-INTEGRATION-v1](./S7-INTEGRATION.md) | [WP-040](../work-packages/WP-040-integration-verification.md) | ACCEPTED / IDLE |

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

当前 Git 仓库、远端和七个独立 Worktree 已建立。摘要 `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc` 的实现基线仍有效；WP-010/011/021 已通过 S7 原子组合和 S1 final gate。S3/WP-020 与 S2/WP-012 必须从新的最终主基线启动新 Attempt，旧工作树状态不能自动视为写授权。

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
