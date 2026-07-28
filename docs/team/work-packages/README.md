# FlowPilot 工作包索引

## 当前阶段

- 里程碑：M0 仓库与契约基线
- 阶段状态：`IN_PROGRESS`
- 架构责任：`S1-ARCH`
- 发布状态：Architecture Baseline；无功能实现、无通过证据

## M0 工作包

| 工作包 | 责任会话 | 状态 | 依赖 | 目标 |
|---|---|---|---|---|
| [WP-000](./WP-000-m0-contract-freeze.md) | S1-ARCH | REVIEW | 无 | 建立公共契约内容摘要；发布级冻结后置 |
| [WP-010](./WP-010-runtime-bootstrap.md) | S2-RUNTIME | BLOCKED | 同一摘要三方 ACCEPT、Git 基线 | Runtime/Python workspace 骨架 |
| [WP-020](./WP-020-platform-bootstrap.md) | S3-PLATFORM | BLOCKED | 同一摘要三方 ACCEPT、Git 基线 | Gateway/数据/安全/Compose 骨架 |
| [WP-030](./WP-030-quality-bootstrap.md) | S4-QUALITY | BLOCKED | 同一摘要三方 ACCEPT、Git 基线 | 契约质量、评测与证据骨架 |

`REVIEW` 表示产物已由责任会话提出，尚未完成跨角色可实现性审查。`BLOCKED` 在此只描述工作包前置条件，不代表项目或 Codex 目标进入 blocked 状态。

rc1 已被 S2、S3、S4 一致拒绝并完成 S1 裁决；当前评审目标是 `flowpilot-m0-contracts-v1-rc2`。旧结论不得作为 rc2 的接受证据。

## 启动与集成顺序

1. S2、S3、S4 只读审查 WP-000 和 rc2 的精确 `content_digest`，用 RFC 报告不可实现或不兼容问题。
2. S1 处理评审意见并执行契约校验；三方对同一摘要全部 ACCEPT 后，该 candidate 成为实现基线。
3. 建立 Git 基线；S2、S3、S4 从该提交创建独立 Worktree 与目标分支。
4. WP-010 与 WP-020 并行，严格遵守共享文件单写者。
5. WP-030 可在冻结契约后启动离线校验器；涉及运行时和平台的集成测试等待 WP-010/WP-020 交接。
6. 默认集成顺序：WP-010 → WP-020 → WP-030；每次集成后运行当时已存在的门禁。
7. Registry、Dataset、Fixture 和 Traceability 完成后再进行发布级 `frozen` 复审；不让空数据集冻结与代码实现形成循环依赖。

## 共享文件单写者

| 文件/范围 | M0 写入者 | 说明 |
|---|---|---|
| `pyproject.toml`、`uv.lock`、`Makefile` | S2-RUNTIME / WP-010 | 建立 Python workspace 与基础命令 |
| `.env.example`、根级 Compose/容器配置 | S3-PLATFORM / WP-020 | 环境和部署依赖 |
| `scripts/acceptance/**` | S4-QUALITY / WP-030 | 证据生成入口；不得同时修改 Makefile |
| `contracts/**`、本目录 | S1-ARCH / WP-000 | 公共契约与工作包仲裁 |

S4 若需要接入 `make acceptance`，应在 WP-010 合并后申请一个新的共享文件工作包；不得在 WP-030 中并行修改 `Makefile`。
