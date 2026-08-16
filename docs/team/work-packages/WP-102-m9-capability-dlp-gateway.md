# WP-102：Capability、Secret 与 Gateway DLP

## 元数据

- 状态：ACCEPTED_M9
- Owner：S3-PLATFORM
- Attempt：WP-102-a1
- 风险：R3
- Feature：FP-MCP-006、FP-SEC-005、FP-SEC-006、FP-SEC-007
- 依赖：WP-101
- 执行：ORDERED / HOT_CONTINUE
- 写入：`packages/security/**`、`apps/mcp-gateway/**`、`packages/tool-contracts/**`、`tests/platform/**`、`tests/platform/evidence/WP-102-a1-HANDOFF.md`

## 主写目标

实现目标资源绑定的短时 Capability、开发 Secret Provider Port、集中 DLP/Prompt
Injection 注册表，并把工具参数、MCP 内容、工具结果和信号投影接入 Gateway 强制边界。

## 验收

- Capability 绑定 tenant/context/workload/tool/resource/action/policy/audience/TTL，重放为 0。
- Secret 只在上游调用栈内解析；任何公共对象、日志、错误或事件中的明文命中为 0。
- Prompt Injection、恶意 MCP 内容、敏感参数/结果在账本占位和上游调用前失败关闭。
- 所有拒绝都有稳定码和关联 Audit/Security Draft，不复制危险原文。
- Platform/Security 定向测试、Ruff、strict Mypy、Contract、Secret Scan 通过。

## 非目标

不修改 Model Gateway、数据库、Compose 或 Web。完成后唤醒 S2 WP-103。
