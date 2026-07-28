# FlowPilot 工作包索引

## 当前阶段

- 里程碑：M0 仓库与契约基线
- 阶段状态：`IN_PROGRESS`
- 架构责任：`S1-ARCH`
- 发布状态：Architecture Baseline；无功能实现、无通过证据

## M0 工作包

| 工作包 | 责任会话 | 状态 | 依赖 | 目标 |
|---|---|---|---|---|
| [WP-000](./WP-000-m0-contract-freeze.md) | S1-ARCH | IN_PROGRESS | 无 | 实现基线已评审；发布级冻结等待质量资产 |
| [WP-010](./WP-010-runtime-bootstrap.md) | S2-RUNTIME | BLOCKED | 五实现角色同摘要 ACCEPT、激活提交、WP-011 Workspace | Graph/Runtime/Context/Worker 骨架 |
| [WP-011](./WP-011-core-bootstrap.md) | S5-CORE | READY_ON_COMMIT | 从激活提交创建 S5 Worktree | Domain/Application/API/Python Workspace 骨架 |
| [WP-020](./WP-020-platform-bootstrap.md) | S3-PLATFORM | BLOCKED | 五实现角色同摘要 ACCEPT、激活提交、WP-011 Workspace | Gateway/Policy/Security 骨架 |
| [WP-021](./WP-021-data-bootstrap.md) | S6-DATA | BLOCKED | 五实现角色同摘要 ACCEPT、激活提交、WP-011 Workspace | Persistence/Migration/RLS/Compose 骨架 |
| [WP-030](./WP-030-quality-bootstrap.md) | S4-QUALITY | READY_ON_COMMIT | 从激活提交创建 S4 Worktree；跨组件部分仍阻塞 | 离线契约质量、评测与证据骨架 |

`IN_PROGRESS` 表示 WP-000 已完成实现基线评审证明，但尚未满足发布级冻结条件。`BLOCKED` 在此只描述工作包前置条件，不代表项目或 Codex 目标进入 blocked 状态。

rc1 已被 S2、S3、S4 一致拒绝并完成 S1 裁决；当前评审目标是 `flowpilot-m0-contracts-v1-rc2`。旧结论不得作为 rc2 的接受证据。

## 启动与集成顺序

1. S2、S3、S4、S5、S6 只读审查 WP-000 和 rc2 的精确 `content_digest`。
2. S1 处理评审意见并执行契约校验；五角色对同一摘要全部 ACCEPT 后，该 candidate 成为实现基线。
3. S1 形成激活提交；五个实现会话从该提交创建独立 Worktree 与目标分支。
4. 第一波启动 WP-011；WP-030 可并行建设不依赖运行代码的离线校验器与证据骨架。
5. S1 接受 `WP-011-H1`（Python Workspace、Application/Repository Port）交接后，并行启动 WP-010 与 WP-021；任何时刻最多三个写会话。
6. WP-011 Workspace 可用且 WP-021 交付执行账本 Port 后启动 WP-020；WP-030 跨组件部分等待 WP-010/011/020/021 交接。
7. 默认集成顺序：WP-011 → WP-010 → WP-021 → WP-020 → WP-030；每次集成后运行现有门禁。
8. Registry、Dataset、Fixture 和 Traceability 完成后再进行发布级 `frozen` 复审。

## 共享文件单写者

| 文件/范围 | M0 写入者 | 说明 |
|---|---|---|
| `pyproject.toml`、`uv.lock`、`Makefile` | S5-CORE / WP-011 | 建立 Python Workspace 与基础命令 |
| `.env.example`、根级 Compose/容器配置 | S6-DATA / WP-021 | 环境和部署依赖 |
| `scripts/acceptance/**` | S4-QUALITY / WP-030 | 证据生成入口；不得同时修改 Makefile |
| `contracts/**`、本目录 | S1-ARCH / WP-000 | 公共契约与工作包仲裁 |

S4 若需要接入 `make acceptance`，应在 WP-011 合并后申请一个新的共享文件工作包；不得在 WP-030 中并行修改 `Makefile`。
