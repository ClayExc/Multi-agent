# WP-106：本地 OPA 与 Secret Infra

## 元数据

- 状态：ACCEPTED_M9
- Owner：S6-DATA
- Attempt：WP-106-a1
- 风险：R3
- Feature：FP-MCP-006、FP-SEC-006、FP-OPS-001
- 依赖：WP-105
- 执行：ORDERED / HOT_CONTINUE
- 写入：`infra/**`、`.env.example`、`tests/data/**`、`tests/data/evidence/WP-106-a1-HANDOFF.md`

## 主写目标

把本地 OPA、固定 Policy Bundle、开发 Secret 配置和 Audit PostgreSQL 迁移装入独立
Compose，使空环境可以启动、重启和清理。

## 验收

- Bundle 版本/摘要与 S3 决定一致，重复发布、回滚和 OPA 重启可恢复。
- Secret 通过未提交的本地输入或 Compose Secret 注入；默认值不含可用密钥。
- 空卷启动、健康检查、Migration 重放、OPA/数据库重启和资源 cleanup 为 0 残留。
- 错 Bundle、缺 Secret、错权限、明文日志和不安全挂载失败关闭。

## 非目标

不实现生产 TLS/HA、Vault/KMS、SIEM 或企业网络。完成后唤醒 S4 WP-107。
