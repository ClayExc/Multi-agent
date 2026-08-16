# WP-112-a1 S6-DATA Handoff

## 基本信息

- Work Package：`WP-112`
- Attempt ID：`WP-112-a1`
- Chain / Step：`CHAIN-M10-KNOWLEDGE-01` / `M10-02-S6-DOCUMENT-PERSISTENCE`
- 责任会话：`S6-DATA`
- 执行：`ORDERED`，风险 `R2`
- 基线 / 输入：`4c32c4d7f4095e5c93e8d2a017bcd099bbdb05e4` / `145236616e3079860aaf17fb1accb5efd1f9b317`
- 实现提交：`ea98cbaffce2cc9cc3cca6a9388e2e7748de2cf4`
- ContractSet：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 消费者结论 / 结果：`ACCEPT` / `PASS_HANDOFF`

## 完成内容

- 新增可信 SecurityContext 绑定的 PostgreSQL Knowledge UoW，并在同一事务暴露
  Document Repository、幂等 Inbox、闭合元数据 Outbox 和 Index Job Port。
- 文档 `revision=0` 与不可变版本 `version=0` 起步；更新使用数据库原子 CAS，旧 revision
  返回冲突；退役/删除只推进 revision。删除在同一事务擦除正文及章节投影，保留安全版本元数据。
- 幂等键绑定 tenant 与 request digest；同键同摘要回读原 receipt，同键异摘要或未完成并发 claim
  失败关闭。索引 Job 仅在完整内容一致时安全重放，身份相同而内容不同稳定冲突。
- Outbox 唯一载荷来自应用层 `KnowledgeOutboxEvent.safe_payload()`；未持久化正文、source_ref、
  ACL 主体、SecurityContext、Token、Secret 或原始异常。
- 0006 建立文档、版本、正文、章节、Inbox、Outbox、Index Job 与确定性 Diagnostic View；全部
  tenant 表启用并强制 RLS，PUBLIC 撤权，版本 UPDATE/DELETE 由数据库触发器拒绝。

## Migration

- Up：`migrations/0006_knowledge_document_facts.sql`
  - SHA-256：`584540ec35013fa452e3d2f680f76ba766b9a1cd2305f9a55d49f051519ba7c5`
- Down：`migrations/0006_knowledge_document_facts.down.sql`
  - SHA-256：`4d24b5ef6564588e1404f1a12a7a53508c35e2b51d77b7e25f88293d33279a23`
- 线性链：`0001 -> 0002 -> 0003 -> 0004 -> 0005 -> 0006`。
- Down 在知识事实非空或存在后继时先于破坏性 DDL 失败关闭。

## 验证

| 检查 | 结果 |
|---|---|
| Data suite | PASS：`116 passed` |
| WP-112 定向测试 | PASS：`7 passed` |
| Ruff | PASS |
| strict Mypy | PASS：`12 source files` |
| Contract Conformance | PASS：20 schemas / 35 cases / 43 semantic / 52 features |
| 锁定 Workspace 同步 | PASS：`uv sync --all-packages --locked` |
| 真实 PostgreSQL 空卷 up / replay | PASS：两次均退出 0 |
| 真实 PostgreSQL RLS | PASS：跨租户可见 `0`，跨租户 INSERT 被拒绝 |
| 真实 PostgreSQL CAS / rollback | PASS：首次 `1`、旧序号 `0`、回滚可见 `0` |
| 删除正文 | PASS：同事务删除后正文数 `0` |
| 非空 Down guard | PASS：在 DDL 前拒绝，错误码路径可复现 |
| Docker 隔离资源清理 | PASS：容器、卷、网络均已删除 |
| `git diff --check` | PASS |

连接归还、可信 Context 撤销/过期和角色安全复用 WP-084 已通过的 `_TenantTransaction`
实现及当前 Data 回归证据；本 Attempt 没有重复执行无关 Keycloak、Governance 或 M9 全矩阵。

## 范围、风险与下一步

- 修改仅在 `packages/persistence/**`、`migrations/**`、`tests/data/**`；未修改 Contract、根锁、
  Compose、环境配置或其他角色路径。
- `BLOCKERS=none`。0006 尚未进入 Compose 初始化挂载，pgvector、正文分段写入/消费、索引状态
  转移、Redis 丢失重建与索引 Worker 恢复由已预授权的 WP-113 收口。
- 本 Handoff 不批准 M10 Release，不唤醒其他角色；同一 S6 会话热继续 WP-113。
- `LEARNING_CANDIDATE=none`。
- `SUBAGENTS_USED=0`；`DUPLICATE_WORK_AVOIDED=WP-084 context/RLS evidence`。

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M10-KNOWLEDGE-01
STEP_ID=M10-02-S6-DOCUMENT-PERSISTENCE
ATTEMPT_ID=WP-112-a1
BASE_COMMIT=4c32c4d7f4095e5c93e8d2a017bcd099bbdb05e4
INPUT_HEAD=145236616e3079860aaf17fb1accb5efd1f9b317
IMPLEMENTATION_HEAD=ea98cbaffce2cc9cc3cca6a9388e2e7748de2cf4
NEW_HEAD=<this-handoff-commit>
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/data/evidence/WP-112-a1-HANDOFF.md
NEXT_PREAUTHORIZED_STEP=M10-03-S6-KNOWLEDGE-INDEX/WP-113-a1
ESCALATE_TO_S1=no
SUBAGENTS_USED=0
USER_INPUT_REQUIRED=none
```

## 可回滚方式

- 在 0006 无事实且无后继时执行 `0006_knowledge_document_facts.down.sql`；有事实时必须先按
  数据保留流程处理，禁止绕过 guard。
