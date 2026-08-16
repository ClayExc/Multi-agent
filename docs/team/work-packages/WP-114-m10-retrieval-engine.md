# WP-114：混合检索与稳定引用

- 状态：BLOCKED
- Attempt：WP-114-a1
- Owner：S4-QUALITY
- 风险：R2
- Feature：FP-SEC-003、FP-EVAL-001
- 依赖：WP-113
- 执行：ORDERED

新建 `packages/retrieval`，实现关键词与向量分数合并、阈值、重排、版本去重、稳定同分排序、
候选元数据复验和稳定引用生成。没有证据、低相关、过期、撤销、Hash 漂移和错误版本都必须
明确失败或返回无结果。

写入 `packages/retrieval/**`、`tests/acceptance/m10/**`。引擎只依赖 Port，不直接访问数据库、
Gateway 或模型；不得在日志/证据中保存正文。PASS 后唤醒 S3 WP-115。
