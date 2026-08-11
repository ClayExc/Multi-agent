# WP-084-a1 S6-DATA 正式交接

## 基本信息

- Chain：`CHAIN-M8-IDENTITY-TENANCY-01`
- Step：`M8-02D-S6-FINAL`
- Attempt：`WP-084-a1-r1`
- Session：`S6-DATA` / `identity-data-builder`
- Execution：`ORDERED`
- Feature：`FP-SEC-002`
- 输入 Head：`36710c21b07d4145565af0cbc83c73846ea6b63b`
- S6 实现提交：`bbea6363a9e1b262087c1ef7d17dc207187293be`
- 最终 Head：本文件所在提交；精确 SHA 由交接消息返回
- ContractSet：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：`PASS_HANDOFF`

## 完成内容

- 提供 PostgreSQL 可撤销 SecurityContext Source/Adapter，完整可信快照只使用 Security
  公共完整性算法验证，支持插入式幂等保存、解析与不可复活撤销。
- 提供 context-bound Data UoW，在同一事务绑定 tenant、context ref/hash 与 subject；
  缺失、伪造、错租户、撤销、过期或不安全数据库角色均失败关闭。
- commit、rollback、异常及连接归还路径确定性清理事务绑定，禁止事务结束后继续复用仓库。
- 新增线性迁移 `0004_security_context_rls_binding`：强制 RLS、最小权限、运行角色
  `NOSUPERUSER/NOBYPASSRLS` 纠正与复验、SecurityContext 不可变撤销及安全 down/replay guard。
- Compose 空卷初始化包含 `0001 -> 0004`；Redis 仍为可重建协调层，PostgreSQL 为事实源。

## 修改范围

- `packages/persistence/**`
- `migrations/**`
- `infra/**`
- `tests/data/**`

未修改公共 Contract、S2/S3/S4/S5/S7 独占路径或根锁；S5 与 S7 的 Join 提交由
`INPUT_HEAD` 精确 ff-only 消费。

## 验证与复用证据

| 检查 | 结果 |
|---|---|
| S6 checkpoint Data suite | PASS：`101 passed` |
| S6 checkpoint 真实 PostgreSQL | PASS：`stored=2 idempotent=1 cross_tenant_success=0 unsafe_role_rejected=1 pool_residual=0 revoked=1 expired=1 redis_rebuilt=0` |
| 新锁依赖门禁 | PASS：`uv sync --all-packages --all-groups --locked` |
| WP-040 迁移验证器 | PASS：`39 passed`，旧 4 failures 清零 |
| Full pytest | PASS：`1398 passed, 1 skipped`；skip 为需显式开启的既有在线 Provider smoke |
| Ruff（S6 范围） | PASS |
| strict Mypy（Persistence 与新增证据） | PASS：12 source files |
| Contract Conformance | PASS：20 schemas / 35 cases / 52 features |

按最终派发复用 `WP-084-a1-CHECKPOINT.md` 的 Data 101 与实库故障矩阵，没有重复
Compose、Keycloak 或产品实现。S7 固定 0003 验证器和 `DEPENDENCY_LOCK_PENDING_WP083`
两个 checkpoint 外部阻断已由 Join 关闭。

## 安全结论与风险

- 双租户正常访问成立，跨租户成功读取/写入为 0；请求方 tenant 不是权威绑定来源。
- 数据库运行角色存在 `SUPERUSER` 或 `BYPASSRLS` 时适配器拒绝；迁移会纠正并复验。
- SecurityContext 撤销、过期、完整性错配以及连接池残留均失败关闭。
- Redis 丢失后只从 PostgreSQL 重建，不虚构 Task 或执行事实。
- 未执行在线 Provider、付费调用或 M9 后续；本交接不代表 M8 Release。
- 阻断：none。

## 子 Agent 与复用摘要

- 复用 checkpoint 中两个只读审查结果：RLS/Migration 与 SecurityContext/UoW 边界。
- 子 Agent 写入、Git 与 Wake 权限均为 0；本次 final resume 未新增子 Agent。
- `LEARNING_CANDIDATE=none`。

## 下一步

S1 核验最终 Head、Handoff Hash、ContractSet、授权范围与 clean 后执行架构验收。本会话
不唤醒 S2/S4/S7，也不启动 Join 2。

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M8-IDENTITY-TENANCY-01
STEP_ID=M8-02D-S6-FINAL
ATTEMPT_ID=WP-084-a1-r1
SESSION_ROLE=S6-DATA
IMPLEMENTATION_HEAD=bbea6363a9e1b262087c1ef7d17dc207187293be
INPUT_HEAD=36710c21b07d4145565af0cbc83c73846ea6b63b
NEW_HEAD=<this-handoff-commit>
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/data/evidence/WP-084-a1-HANDOFF.md
NEXT_ROLE=S1-ARCH
USER_INPUT_REQUIRED=none
```
