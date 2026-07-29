# WP-012：LangGraph Studio 非黑箱开发入口

## 元数据

- 状态：`READY_AFTER_WP040_ACCEPTANCE`
- 责任会话：S2-RUNTIME
- 评审会话：S1-ARCH、S4-QUALITY；开发依赖变化时增加 S5-CORE
- 功能 ID：FP-FLOW-001、FP-FLOW-004、FP-FLOW-005、FP-FLOW-006、FP-OBS-001、FP-OPS-002
- 依赖工作包：WP-010、WP-011、WP-021、WP-040
- 调度：`ORDERED`；S1 接受 WP-040 后派发，依赖锁变化由 S5 先交付

## 目标

- 使用与 Worker 相同的 graph factory 提供 LangGraph Studio 本地入口。
- 可视化路由、Interrupt、Handoff、Checkpoint、重试、预算和安全状态投影。
- 建立“可调试但不改变业务事实源、不泄露敏感数据”的开发边界。

## 允许修改路径

- `apps/worker/**`
- `packages/graph/**`
- `packages/agent-runtime/**`
- `packages/context/**`
- `tests/runtime/**`
- `langgraph.json`：本工作包显式授权 S2 为单一写入者

`pyproject.toml`、`uv.lock` 和 `Makefile` 不在本包范围；如需新增 LangGraph CLI 或开发 Extra，由 S5 创建共享依赖子包并先行交接。

## 输入与输出

| 类型 | 内容 |
|---|---|
| 输入 | WP-040 已接受产品树、GraphState、Checkpoint/Lease Port、Application/Runtime Port |
| 输出 | `langgraph.json`、稳定 graph factory/entrypoint、安全 `debug_projection`、拓扑快照和 Studio Smoke 证据 |

## 必须测试

- 正常：Studio 加载 `flowpilot_it_service`，合成任务经过路由、Interrupt 和恢复。
- 边界：空 Context、预算边界、无 Provider Session、checkpoint sequence 边界。
- 失败：入口分叉、未知节点、旧 `run_generation`、过期 Lease、恢复错位。
- 安全：生产 Profile 状态编辑、Secret/PII 字段、越权工具、Gateway 绕过全部失败关闭。
- 恢复：节点重进不重复副作用，Studio checkpoint 与 FlowPilot checkpoint 显式对齐。

## 完成定义

- 满足 [`LANGGRAPH_STUDIO.md`](../../architecture/LANGGRAPH_STUDIO.md) 的全部验收项。
- 图拓扑和安全投影可由自动化测试复现，不能只提交截图。
- Studio Thread 不参与 Task 终态、审批、租户和业务恢复判断。
- S4 完成黑盒复核，S1 完成事实源与节点语义复核。
