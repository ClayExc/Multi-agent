# WP-111：知识领域与应用 Port

## 元数据

- 状态：BLOCKED
- Attempt：WP-111-a1
- Owner：S5-CORE
- 风险：R2
- Feature：FP-FLOW-003、FP-DATA-001、FP-SEC-003、FP-UI-001
- 依赖：WP-110
- 执行：ORDERED

## 目标

定义纯 Python 文档、版本、ACL、生命周期、稳定引用和索引任务模型，以及导入、更新、撤销、
删除、重建、查询和诊断 Application Port。可信身份、租户、用途、策略、幂等键和数据分级
必须显式传递。

## 路径与交付

- 写入：`packages/domain/**`、`packages/application/**`、`apps/api/**`、`tests/core/**`。
- 不写根锁、数据库、Retrieval、MCP、Runtime 或公共 Contract。
- 输出给 S6 的 Repository/UoW/Outbox Port 必须确定版本 0、并发更新、重复命令、撤销与删除
  语义；事件和错误不得包含正文或 Secret。

## 验收

覆盖合法导入/更新、同内容幂等、同键异摘要冲突、非法生命周期、错租户/用途/分级、旧引用
不重定向和事务回滚。PASS Handoff 唤醒 S6 WP-112。
