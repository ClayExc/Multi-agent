# WP-115-r2-data S6-DATA Handoff

## 基本信息

- Chain / Step：`CHAIN-M10-KNOWLEDGE-01` / `M10-05R2-S6-CITATION-PROJECTION`
- Work Package / Attempt：`WP-115-R2` / `WP-115-r2-data`
- 输入：`45ed719207e5b00e4a0d71b80ed01e42fabdb8f0`
- 实现提交：`932ad28dba5098b61ac48457b4660d91f68f3128`
- ContractSet：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 消费者结论 / 结果：`ACCEPT` / `PASS_HANDOFF`

## 完成内容

- 实现 `KnowledgeContentProjectionPort.get_exact(tenant_id, document_id,
  document_version)`，并在既有可信 SecurityContext / tenant-bound PostgreSQL Query UoW
  中暴露 `content_projections`。
- SQL 对正文表与版本表分别绑定 tenant、document、version，不查询 latest、不重定向旧引用；
  只读取 `left(content_body, 2048)`，并返回 content_ref/hash/classification 的闭合投影。
- 防御性复核 document active、版本 effective/expiry、正文 hash 与版本 hash 一致；应用层仍按
  v2 顺序先完成 Context、生命周期、StableCitation、classification ceiling 与 authorization，
  然后才调用本 Port。
- 缺失正文返回 `None`；跨租户由强制 RLS 和单事务 tenant 绑定双重拒绝；畸形/超长驱动投影
  构造失败关闭。excerpt 使用 `repr=False`，错误路径不包含正文或原始驱动异常。

## 验证

| 检查 | 结果 |
|---|---|
| S6 投影定向 | PASS：`4 passed` |
| Data + Knowledge Core | PASS：`160 passed` |
| Ruff | PASS |
| strict Mypy | PASS：`13 source files` |
| Contract Conformance | PASS：20 schemas / 35 cases / 43 semantic / 52 features |
| Secret Scan | PASS：`2 passed` |
| 真实 PostgreSQL exact v0/v1 | PASS：v0 保持 v0；v1 保持 v1 |
| excerpt 上限 | PASS：3000 字符正文只返回 2048 |
| 跨租户 / retired / 删除正文 | PASS：候选数均为 `0` |
| 删除后安全元数据 | PASS：exact version 元数据数仍为 `1` |
| Docker 清理 | PASS：隔离容器、卷、网络均为 `0` |
| `git diff --check` | PASS |

## 范围与下一步

- 修改仅 `packages/persistence/**`、`tests/data/**`；无 Migration、Compose、依赖锁、公共
  Contract 或其他 Owner 路径变化。
- `BLOCKERS=none`。S4 下一有序步骤应迁移 v1 `resolve_citation` Fakes/断言到 v2 excerpt
  结果，并复验 Retrieval 不在授权前读取正文；不得加入兼容默认值。
- 不唤醒 S3；只唤醒预授权 S4 Citation Projection 步骤。
- `SUBAGENTS_USED=0`；`LEARNING_CANDIDATE=none`。

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M10-KNOWLEDGE-01
STEP_ID=M10-05R2-S6-CITATION-PROJECTION
ATTEMPT_ID=WP-115-r2-data
INPUT_HEAD=45ed719207e5b00e4a0d71b80ed01e42fabdb8f0
IMPLEMENTATION_HEAD=932ad28dba5098b61ac48457b4660d91f68f3128
NEW_HEAD=<this-handoff-commit>
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/data/evidence/WP-115-r2-data-HANDOFF.md
NEXT_ROLE=S4-QUALITY
NEXT_ATTEMPT_ID=WP-115-r2-quality
ESCALATE_TO_S1=no
USER_INPUT_REQUIRED=none
```
