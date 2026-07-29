# FlowPilot 工作包索引

## 当前阶段

- 里程碑：M0 仓库与契约基线
- 阶段状态：`IN_PROGRESS`
- 架构责任：`S1-ARCH`
- 发布状态：Architecture Baseline + M0 增量实现；Core/Runtime/Data 组合已接受，尚无 MCP/Provider/端到端业务闭环

## M0 工作包

| 工作包 | 责任会话 | 状态 | 依赖 | 目标 |
|---|---|---|---|---|
| [WP-000](./WP-000-m0-contract-freeze.md) | S1-ARCH | IN_PROGRESS | 无 | 实现基线已评审；发布级冻结等待质量资产 |
| [WP-010](./WP-010-runtime-bootstrap.md) | S2-RUNTIME | ACCEPTED_M0 | WP-040/S1 final gate 通过 | Graph/Runtime/Context/Worker 骨架 |
| [WP-012](./WP-012-langgraph-studio-observability.md) | S2-RUNTIME | READY_AFTER_WP040_ACCEPTANCE | WP-010/011/021/040 | Studio 非黑箱入口、安全状态投影与恢复调试 |
| [WP-011](./WP-011-core-bootstrap.md) | S5-CORE | IN_PROGRESS | H1 已合入；继续 API/Domain Pack | Domain/Application/API/Python Workspace 骨架 |
| [WP-020](./WP-020-platform-bootstrap.md) | S3-PLATFORM | READY_ON_BASELINE_SYNC | WP-021 Ledger 与 Workspace 已进入最终候选 | Gateway/Policy/Security 骨架 |
| [WP-021](./WP-021-data-bootstrap.md) | S6-DATA | ACCEPTED_M0 | WP-040/S1 final gate 通过；Compose 自动应用 0002 为 P2 | Persistence/Migration/RLS/Compose 骨架 |
| [WP-030](./WP-030-quality-bootstrap.md) | S4-QUALITY | IN_PROGRESS | 离线骨架已合入；跨组件部分仍阻塞 | 离线契约质量、评测与证据骨架 |
| [WP-040](./WP-040-integration-verification.md) | S7-INTEGRATION | ACCEPTED | a1 RELEASE 候选 + a2/a3 FAST final-phase Verifier + S1 final gate | 跨分支组合、依赖闭包与证据复现 |

`IN_PROGRESS` 表示 WP-000 已完成实现基线评审证明，但尚未满足发布级冻结条件。`BLOCKED` 在此只描述工作包前置条件，不代表项目或 Codex 目标进入 blocked 状态。

rc1 已被 S2、S3、S4 一致拒绝并完成 S1 裁决；当前评审目标是 `flowpilot-m0-contracts-v1-rc2`。旧结论不得作为 rc2 的接受证据。

## 启动与集成顺序

1. S2、S3、S4、S5、S6 只读审查 WP-000 和 rc2 的精确 `content_digest`。
2. S1 处理评审意见并执行契约校验；五角色对同一摘要全部 ACCEPT 后，该 candidate 成为实现基线。
3. S1 形成激活提交；五个实现会话从该提交创建独立 Worktree 与目标分支。
4. 第一波启动 WP-011；WP-030 可并行建设不依赖运行代码的离线校验器与证据骨架。
5. S1 接受 `WP-011-H1`（Python Workspace、Application/Repository Port）交接后，并行启动 WP-010 与 WP-021；任何时刻最多三个写会话。
6. WP-011 Workspace 可用且 WP-021 交付执行账本 Port 后启动 WP-020；WP-030 跨组件部分等待 WP-010/011/020/021 交接。
7. WP-010/011/021 的本轮逻辑依赖是 S5 Port → S6 Persistence → S2 Adapter → S5 Lock；因中间 Head 不构成完整 Workspace，最终以 S7 完整候选原子集成。
8. S1 接受 WP-040 后启动 WP-012；S3/WP-020 与 S4 跨组件范围按依赖另行派发。
9. Registry、Dataset、Fixture 和 Traceability 完成后再进行发布级 `frozen` 复审。

每次向多个会话派发时必须显式标注 `PARALLEL`、`READ_ONLY_PARALLEL` 或 `ORDERED`。消息到达顺序不代表执行顺序；`ORDERED` 派发必须写明前置交付和解锁条件。WP-040 可以只读并行复核，写模式计入“最多三个写会话”上限。

## 共享文件单写者

| 文件/范围 | M0 写入者 | 说明 |
|---|---|---|
| `pyproject.toml`、`uv.lock`、`Makefile` | S5-CORE / WP-011 | 建立 Python Workspace 与基础命令 |
| `.env.example`、根级 Compose/容器配置 | S6-DATA / WP-021 | 环境和部署依赖 |
| `scripts/acceptance/**` | S4-QUALITY / WP-030 | 证据生成入口；不得同时修改 Makefile |
| `contracts/**`、本目录 | S1-ARCH / WP-000 | 公共契约与工作包仲裁 |

S4 若需要接入 `make acceptance`，应在 WP-011 合并后申请一个新的共享文件工作包；不得在 WP-030 中并行修改 `Makefile`。
