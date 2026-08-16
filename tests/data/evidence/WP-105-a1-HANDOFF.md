# WP-105-a1 S6-DATA Handoff

## 基本信息

- `CHAIN_ID`: `CHAIN-M9-GOVERNANCE-01`
- `STEP_ID`: `M9-05-S6-AUDIT-PERSISTENCE`
- `ATTEMPT_ID`: `WP-105-a1`
- `SESSION_ROLE`: `S6-DATA`
- `EXECUTION_MODE`: `ORDERED`
- `RISK_CLASS`: `R3`
- `BASE_COMMIT`: `0205bb2695dab86685cfd86d8397a60a486a28ed`
- `IMPLEMENTATION_HEAD`: `fcea36f71a8aec75b506cfda22c0ec2534c3681b`
- `CONTRACT_CONTENT_DIGEST`: `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- `CONSUMER_VERDICT`: `ACCEPT`
- `OUTCOME`: `PASS_HANDOFF`

## 完成内容

- 实现 `flowpilot.governance-query.m9.v1` 的五个 PostgreSQL Query Port：Policy
  Version、Policy Decision、Audit Event、Security Event 与 Correlation Chain。
- Query UoW 在单一只读事务设置 tenant、context ref/hash、subject、purpose，并由
  PostgreSQL SecurityContext 事实源验证 active、未撤销、未过期和五维一致性。
- HMAC 游标签名并绑定 tenant、resource、filter、sort、version；篡改、跨租户、跨资源
  或跨筛选器重放稳定返回 `CORE_GOVERNANCE_CURSOR_INVALID`。
- 新增线性 Migration 0005：Policy Version、append-only Security Event、闭合 Audit
  投影视图、确定性查询索引、强制 RLS、最小授权及非空数据/后继安全降级 guard。
- 复用 0001 `append_audit_event` 的行锁、可信 sequence/previous-hash 链；新增
  `append_security_event`，只有 Audit Event 反向绑定同一 Security Event ID 时才允许
  原子插入。Audit/Security 更新与删除均由数据库拒绝。
- Query 只构造 WP-104 闭合 View，不返回原始 arguments/result/evidence、Policy input、
  原始事件 JSON 或敏感正文。

## 修改范围

- `packages/persistence/**`
- `migrations/**`
- `tests/data/**`

未修改 Contract、S2/S3/S4/S5/S7 路径、根锁、Compose 或环境文件。

## Migration

- Up：`migrations/0005_governance_audit_query.sql`
  - SHA-256：`ec65060c923230dfac8095c2d241b02f9936111433874aea490fc7c31b5b84a0`
- Down：`migrations/0005_governance_audit_query.down.sql`
  - SHA-256：`05fc80f118b3d3134c0dff1d083543b2d751cd5574ad50f32423dba80dc79228`
- 线性链：`0001 -> 0002 -> 0003 -> 0004 -> 0005`。

## 验证

| 检查 | 结果 |
|---|---|
| WP-105 单元与静态 Migration | PASS：`4 passed` |
| Data suite | PASS：`106 passed` |
| WP-104 consumer + Data + Core Security | PASS：`138 passed` |
| 真实 PostgreSQL Migration | PASS：up=0 / replay=0 / empty down=0 |
| Docker 资源清理 | PASS：containers=0 / volumes=0 / networks=0 |
| Ruff | PASS |
| strict Mypy | PASS：12 source files |
| Contract Conformance | PASS：20 schemas / 35 cases / 43 semantic / 52 features |
| `git diff --check` | PASS |

Docker Desktop 初始未运行；启动本地引擎后已完成真实 Migration 复现，因此无
`ENV_BLOCKED` 残留。未重跑全仓、WP-084 矩阵或无关身份链。

## 风险与下一步

- `BLOCKERS=none`。
- Policy Version 发布写端与生产游标 Secret 注入由组合层提供；S6 不持久化 Secret。
- 0005 尚未加入 Compose 初始化挂载；按预授权下一步 WP-106 的 Infra 写范围收口。
- 本 Handoff 不批准 M9 Release，也不启动 S2/S4/S7。
- `LEARNING_CANDIDATE=none`。

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M9-GOVERNANCE-01
STEP_ID=M9-05-S6-AUDIT-PERSISTENCE
ATTEMPT_ID=WP-105-a1
SESSION_ROLE=S6-DATA
BASE_COMMIT=0205bb2695dab86685cfd86d8397a60a486a28ed
IMPLEMENTATION_HEAD=fcea36f71a8aec75b506cfda22c0ec2534c3681b
NEW_HEAD=<this-handoff-commit>
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
HANDOFF=tests/data/evidence/WP-105-a1-HANDOFF.md
GATE=PASS
NEXT_PREAUTHORIZED_STEP=M9-06-S6-OPA-SECRET-INFRA/WP-106-a1
USER_INPUT_REQUIRED=none
```
