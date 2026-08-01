# WP-P2：持久化恢复闭环

## 元数据

- 状态：REVIEW（S7 RELEASE PASS，等待 S1 final 与用户门禁）
- Flow Lite Goal：`g1`（用户于 `2026-08-01T09:19:07Z` 批准）
- 风险等级：R2
- 责任会话：S6-DATA、S2-RUNTIME
- 评审会话：S7-INTEGRATION、S1-ARCH
- 功能 ID：FP-FLOW-005、FP-DATA-001、FP-DATA-002、FP-DATA-003、FP-SEC-002
- 依赖工作包：已合并的 P1 候选、WP-010、WP-021、WP-040
- 执行模式：ORDERED
- Chain ID：`CHAIN-P2-DURABLE-RUNTIME-01`
- 交接策略：CONSUMER_GATE，最终 S1/用户门禁
- 注册表：[`CHAIN-P2-DURABLE-RUNTIME-01`](../agent-registrations/CHAIN-P2-DURABLE-RUNTIME-01.md)

## 目标

让 VPN 任务在 Worker 进程重启或 Redis 状态丢失后，以 PostgreSQL 中的 Task、
Checkpoint、Lease/Fencing 与 Outbox 为权威精确续跑；已完成分支不得重复执行，
Task 投影、Checkpoint 和事件必须能够对账。

## 非目标

- SSE 产品接口、Ticket 写入、审批、真实 Provider 或新业务场景。
- 新 Migration、公共契约、新生产依赖、Workspace/Lock 或 Compose 结构变化。
- 为拆文件而重构 `vpn.py`；仅允许为恢复接线和可测试性所需的最小调整。
- 实现 `make acceptance` 或把相关 Feature 提前标为 `VERIFIED`。

## 允许修改路径

- S6：`packages/persistence/**`、`tests/data/**`
- S2：`apps/worker/**`、`packages/graph/**`、`tests/runtime/**`
- S7：`scripts/integration/**`、`tests/integration/**`

每个范围只在对应 Step 生效。`contracts/**`、`migrations/**`、`infra/**`、共享
Workspace 文件及其他角色路径均不在授权内。

## 输入与输出

| Step | 输入 | 输出 |
|---|---|---|
| S6 / WP-021-a3 | 当前主分支；现有 Checkpoint CAS、Lease、Outbox、RLS | Runtime 可直接消费的类型化恢复边界与数据恢复证据 |
| S2 / WP-010-a4 | 精确 S6 Head 与 Handoff | PostgreSQL Checkpoint/Lease 接线、重启与 Redis 丢失恢复证据 |
| S7 / WP-040-a7 | 精确 S2 Head 与两份 Handoff | RELEASE 组合复现、Proof 与 S1 final 输入 |

## 架构与安全约束

1. PostgreSQL 是 Task、Checkpoint 和 Outbox 的事实源；Redis 只承载可重建信号。
2. Worker 通过类型化 Port 消费持久化能力，不直连业务数据库或绕过应用边界。
3. `run_generation` 与 Lease/Fencing 必须拒绝旧 Worker；Checkpoint CAS 必须拒绝
   旧序列写入。
4. 恢复不得重复已完成分支、业务工具调用或逻辑事件；稳定结果引用不漂移。
5. RLS 跨租户 Checkpoint/Task 成功读取数必须为 0。
6. `studio-safe` 可继续使用内存 Checkpointer；生产 Worker/恢复入口不能把
   `InMemorySaver` 当作默认持久化实现。

## 必须测试

- 正常：运行至持久化点，创建新 Worker 实例后从 PostgreSQL 续跑至 `COMPLETED`。
- 边界：Checkpoint 序列、租约过期、`run_generation` 递增和重复恢复命令。
- 失败：节点失败、旧 Worker 写入、Checkpoint CAS 冲突和 Redis 信号丢失。
- 安全：跨租户读取为 0，伪造租户/租约/Generation 失败关闭。
- 恢复/幂等：Redis 清空后由 Outbox 重建信号，已完成分支执行次数保持不变。

## 验收命令

```powershell
uv run --frozen python -m pytest -q
uv run --frozen python contracts/conformance/validate.py
python scripts/integration/verify_wp040.py --repo .
```

S7 按 `INTEGRATION_GATES.md` 执行 RELEASE，包含隔离 Compose、RLS、Redis 丢失
恢复、清理验证和安全扫描。不存在的 `make acceptance` 仍必须报告为未实现。

## 完成定义

- S6、S2、S7 按精确线性 Head 完成交接且路径无越权。
- 重启、Redis 丢失、旧 Worker fencing、Checkpoint CAS 与跨租户负例可复现。
- S7 证明已完成分支重复执行数为 0，并向 S1 提交 Handoff/Proof。
- S1 独立 final gate 通过后停在用户合并门禁；不得自动启动 g2 或 g3。
