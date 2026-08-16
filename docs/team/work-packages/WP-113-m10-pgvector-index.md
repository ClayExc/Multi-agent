# WP-113：pgvector 与索引生命周期

- 状态：ACCEPTED_M10
- Attempt：WP-113-a1
- Owner：S6-DATA
- 风险：R2
- Feature：FP-DATA-001、FP-SEC-003
- 依赖：WP-112
- 执行：ORDERED / HOT_CONTINUE

接入本地 pgvector、关键词索引、确定性 Embedding Port、增量索引、失效、删除和全量重建。
授权条件必须在 SQL/元数据候选阶段执行，Retrieval 不得先看到未授权正文。索引重复投递、
Worker 重启、Redis 清空和重建不得改变文档事实。

写入 `packages/persistence/**`、`migrations/**`、`infra/**`、`tests/data/**`。交付版本化评分输入、
稳定排序键和候选查询 Port；Compose 使用独立项目和空卷验证，清理残留为 0。PASS 后唤醒
S4 WP-114。
