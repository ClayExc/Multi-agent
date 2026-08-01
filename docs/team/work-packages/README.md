# FlowPilot 工作包索引

## 当前阶段

- 里程碑：产品 P1 VPN 确定性只读知识闭环
- 阶段状态：`MERGED_P1_READONLY`
- 架构责任：`S1-ARCH`
- 已接受基线：M0 Core/Runtime/Data、M1 Platform、M2 Studio
- 当前有序链：[`CHAIN-P1-VPN-READONLY-01`](../chain-authorizations/CHAIN-P1-VPN-READONLY-01.md)
- 发布状态：未发布、未 frozen；真实 Provider、写工单与完整业务 E2E 尚未完成

## 工作包状态

| 工作包 | 责任会话 | 状态 | 依赖 | 目标 |
|---|---|---|---|---|
| [WP-000](./WP-000-m0-contract-freeze.md) | S1-ARCH | IN_PROGRESS | 无 | 实现基线已评审；发布级冻结等待质量资产 |
| [WP-010](./WP-010-runtime-bootstrap.md) | S2-RUNTIME | ACCEPTED_BASELINE / MERGED_P1 | P1 已合并 | Graph/Runtime/Context/Worker；P1 产品图 Attempt `a3` |
| [WP-012](./WP-012-langgraph-studio-observability.md) | S2-RUNTIME | ACCEPTED_M2 | M2 已合并 | Studio 非黑箱入口、安全状态投影与恢复调试 |
| [WP-011](./WP-011-core-bootstrap.md) | S5-CORE | MERGED_P1 | P1 已合并 | Domain/Application/API/Domain Pack；P1 Attempt `a6` |
| [WP-020](./WP-020-platform-bootstrap.md) | S3-PLATFORM | ACCEPTED_M1 / MERGED_P1 | P1 已合并 | Gateway/Policy/Security；P1 知识工具 Attempt `a2` |
| [WP-021](./WP-021-data-bootstrap.md) | S6-DATA | ACCEPTED_M0 | P1 不修改数据边界 | Persistence/Migration/RLS/Compose 骨架 |
| [WP-030](./WP-030-quality-bootstrap.md) | S4-QUALITY | MERGED_P1 | P1 已合并 | 20 条候选 Case、黑盒质量与证据 Attempt `a4` |
| [WP-040](./WP-040-integration-verification.md) | S7-INTEGRATION | ACCEPTED_P1 | P1 已合并 | RELEASE 组合复现与 S1 final 输入 Attempt `a6` |

`IN_PROGRESS` 表示 WP-000 已完成实现基线评审证明，但尚未满足发布级冻结条件。`BLOCKED` 在此只描述工作包前置条件，不代表项目或 Codex 目标进入 blocked 状态。

rc1 已被 S2、S3、S4 一致拒绝并完成 S1 裁决；当前评审目标是 `flowpilot-m0-contracts-v1-rc2`。旧结论不得作为 rc2 的接受证据。

## 当前启动与集成顺序

产品 P1 采用严格 `ORDERED`：

```text
S5/WP-011-a6
  -> S3/WP-020-a2
  -> S2/WP-010-a3
  -> S4/WP-030-a4
  -> S7/WP-040-a6
  -> S1 final/user gate
```

本链所有实现、复现和用户门禁步骤已经完成；S7 因租户/ACL 检索边界变化
运行一次 RELEASE 门禁，S1 完成 FAST final gate 后将精确候选 fast-forward
到主分支。下一链改用 Agent 注册制选择最小参与者，不从本链自动续跑。

历史 M0/M1/M2 链和证据仍保留在各授权记录与 Handoff 中，不再作为当前
启动说明。Registry、完整 Dataset、Fixture 和 Traceability 完成后才能进行
发布级 `frozen` 复审。

每次向多个会话派发时必须显式标注 `PARALLEL`、`READ_ONLY_PARALLEL` 或 `ORDERED`。消息到达顺序不代表执行顺序；`ORDERED` 派发必须写明前置交付和解锁条件。WP-040 可以只读并行复核，写模式计入“最多三个写会话”上限。

## 共享文件单写者

| 文件/范围 | M0 写入者 | 说明 |
|---|---|---|
| `pyproject.toml`、`uv.lock`、`Makefile` | S5-CORE / WP-011 | 建立 Python Workspace 与基础命令 |
| `.env.example`、根级 Compose/容器配置 | S6-DATA / WP-021 | 环境和部署依赖 |
| `scripts/acceptance/**` | S4-QUALITY / WP-030 | 证据生成入口；不得同时修改 Makefile |
| `contracts/**`、本目录 | S1-ARCH / WP-000 | 公共契约与工作包仲裁 |

S4 若需要接入 `make acceptance`，应在 WP-011 合并后申请一个新的共享文件工作包；不得在 WP-030 中并行修改 `Makefile`。
