# WP-113-a1 S6-DATA Handoff

## 基本信息

- Work Package / Attempt：`WP-113` / `WP-113-a1`
- Chain / Step：`CHAIN-M10-KNOWLEDGE-01` / `M10-03-S6-KNOWLEDGE-INDEX`
- 责任 / 接收：`S6-DATA` / `S4-QUALITY retrieval-builder`
- 执行：`ORDERED / HOT_CONTINUE`，风险 `R2`
- 输入（WP-112 Handoff Head）：`1fb4455fdb323d81f8fa05769a84c7d3ecf0e425`
- 实现提交：`181a416a669d10077bd0ab2935a494e78a7cb335`
- ContractSet：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 结果：`PASS_HANDOFF`

## 完成内容

- Compose PostgreSQL 切换到固定 `pgvector/pgvector:0.8.0-pg17`，空卷按
  `0001 -> ... -> 0007` 自动初始化；镜像实测 digest 为
  `sha256:40b404964359299eefdd5f8518facf1886c562848cf4de13b6eaf91cb70c2b87`。
- 新增 384 维 pgvector HNSW 与 `tsvector` GIN 关键词索引，Embedding model/version 和
  score-input version 显式固定；本地 Hash Embedding 对同一规范文本确定性输出，不调用 Provider。
- PostgreSQL Indexer 使用 `FOR UPDATE ... SKIP LOCKED` 从事实源恢复 pending/stale Job；成功、
  删除、失败和全量 stale 转移不修改文档事实。相同 Section/Hash 可重放，不同 Hash 失败关闭。
- Candidate Port 在 SQL 候选阶段先验证 tenant RLS、active lifecycle、精确版本生效/过期、ACL
  principal、purpose、classification ceiling 和 embedding version；返回仅含引用元数据、向量距离、
  关键词 rank、版本化评分输入和稳定 `(document_id,version,section_id)` 排序键，不读取正文/source_ref。
- Redis 不参与 Job、Section、Embedding 或 Diagnostic 事实；清空协调层后 PostgreSQL pending/stale
  查询仍可确定性恢复，重建不改变 Document revision/current version。

## Migration 与配置

- Up：`migrations/0007_pgvector_knowledge_index.sql`
  - SHA-256：`46896552a9bbc12d47cfab333861e6876ad606cab2ca653c12532b8e43f51039`
- Down：`migrations/0007_pgvector_knowledge_index.down.sql`
  - SHA-256：`ca5f64794aa133b43b49320b12abde7d7a1911666133830d847829da976afe9b`
- 0007 空索引 down/up、up replay 均通过；非空索引 down 在 DDL 前失败关闭。未删除 extension，
  避免破坏由数据库管理的共享扩展对象；回滚只移除本 Migration 的列与索引。
- 无新增环境变量、Python 依赖、根锁或公共 Contract。

## 验证

| 检查 | 结果 |
|---|---|
| WP-113 定向 | PASS：`7 passed`（含静态 Migration/Compose） |
| Data suite | PASS：`123 passed` |
| SHARED Core/Runtime/Data/Platform | PASS：`1240 passed / 1 explicit online skip` |
| Secret Scan | PASS：`2 passed` |
| Ruff | PASS |
| strict Mypy | PASS：`13 source files` |
| Contract Conformance | PASS：20 schemas / 35 cases / 43 semantic / 52 features |
| 锁定 Workspace | PASS：`--all-packages --all-groups --locked` |
| 真实 pgvector 空卷 up/replay/down/up | PASS |
| SQL 授权候选 | PASS：允许 `1`；错主体 `0`；错用途 `0`；跨租户 `0` |
| 向量/关键词 | PASS：同向量距离 `0`；关键词 rank `>0` |
| 重建事实边界 | PASS：Job→stale 后 Document revision 仍为 `0` |
| Docker 清理 | PASS：隔离 containers/volumes/networks=`0` |
| `git diff --check` | PASS |

仓库裸 `pytest` 会命中上游已登记的根模块收集 failure signature；本 Handoff 只采用 WP-111
规定的锁定 Workspace SHARED 入口，其完整结果为 1240/1 skip。

## 安全、风险与下一步

- 跨租户候选成功数为 0；Candidate SQL 不投影正文、source_ref、ACL 主体或 SecurityContext。
- 首次实库向量查询发现扩展位于 `flowpilot` schema 时运算符必须显式限定；已改用
  `OPERATOR(flowpilot.<=>)` 并复验。这是本轮已关闭的局部兼容问题。
- `BLOCKERS=none`。S4 WP-114 应消费 `KnowledgeCandidateQuery/KnowledgeCandidate`，在候选已授权
  的基础上实现版本化融合/重排/去重和 StableCitation 复验；不得把授权移到正文读取之后。
- 未启动 S3/S5/S2/S7 或 M10 后续步骤。
- `SUBAGENTS_USED=0`，`LEARNING_CANDIDATE=none`。

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M10-KNOWLEDGE-01
STEP_ID=M10-03-S6-KNOWLEDGE-INDEX
ATTEMPT_ID=WP-113-a1
INPUT_HEAD=1fb4455fdb323d81f8fa05769a84c7d3ecf0e425
IMPLEMENTATION_HEAD=181a416a669d10077bd0ab2935a494e78a7cb335
NEW_HEAD=<this-handoff-commit>
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/data/evidence/WP-113-a1-HANDOFF.md
NEXT_ROLE=S4-QUALITY
NEXT_ATTEMPT_ID=WP-114-a1
ESCALATE_TO_S1=no
SUBAGENTS_USED=0
USER_INPUT_REQUIRED=none
```

## 可回滚方式

- 无索引数据且无后继时执行 `0007_pgvector_knowledge_index.down.sql`；存在索引时不得绕过 guard。
