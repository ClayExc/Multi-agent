# WP-071：M7 本地产品运行链装配

## 元数据

- 状态：BLOCKED_BY_WP-070
- Attempt ID：待激活
- 风险等级：R2
- 责任角色：S5-CORE（组合入口）
- 参与角色：S6-DATA、S2-RUNTIME
- 评审角色：S1-ARCH、S4-QUALITY
- 功能 ID：FP-FLOW-001、FP-FLOW-005、FP-OBS-001、FP-OPS-001
- 依赖工作包：WP-070
- 执行模式：ORDERED

## 目标

接通 Web/API 之前的权威后端链：FastAPI → Command Intake → Worker → LangGraph →
PostgreSQL/Redis → 只读 MCP，并统一 task/run/thread/checkpoint/trace/event 标识。

## 允许修改路径

- S5：`apps/api/**`、`packages/application/**`、`tests/core/**`。
- S6：`packages/persistence/**`、`infra/**`、`.env.example`、`tests/data/**`。
- S2：`apps/worker/**`、`packages/graph/**`、`tests/runtime/**`。
- 共享 Python 依赖和锁文件最终只由 S5 收口。

## 非目标

- 不实现 OIDC、OPA、长期记忆、企业 Connector 或业务写动作。
- 浏览器提交的 tenant/header 不得升级为可信 SecurityContext。

## 必须测试

- 正常：中文只读 VPN 请求形成 Task、模型调用、知识引用与终态事件。
- 边界：并行只读、SSE 重连、Checkpoint 序列和硬预算。
- 失败：Provider/MCP/PostgreSQL/Redis 故障可定位且失败关闭。
- 安全：跨租户读取为 0，Worker 不直连外部业务网络。
- 恢复：Worker 重启、旧 generation fencing、Redis 清空和事件重投。

## 解锁条件

- WP-070 Adapter 与锁文件闭包通过；本地 Compose 可创建隔离测试资源。
