# WP-040：跨分支集成与证据复现

## 元数据

- 状态：`DEPENDENCY_WAIT`（`WP-040-a0` 只读组合复核完成；等待 S6→S2→S5 有序整改）
- 责任会话：S7-INTEGRATION
- 评审会话：S1-ARCH；按风险选择 S3-PLATFORM、S4-QUALITY 或 S5-CORE
- 功能 ID：FP-FLOW-001、FP-SEC-004、FP-DATA-001、FP-OPS-002
- 依赖工作包：待核验交接本身；写模式另需独立 Worktree 与 S1 Attempt
- 目标分支：`codex/s7/wp-040-integration-verification`
- S1 评审：[`WP-040-A0-S1-REVIEW.md`](../../review/WP-040-A0-S1-REVIEW.md)

## 目标

- 独立复现 S2～S6 交接证据与跨分支组合结果。
- 验证 Workspace、锁文件、wheel、Migration、Compose 和验收命令形成可重复闭包。
- 在进入主分支前暴露跨组件契约、依赖、状态权威、安全和恢复冲突。
- 向 S1 提供可复现的可合并性建议，不替代最终裁决。

## 非目标

- 修改任何产品实现、公共契约、数据库迁移或其他会话测试。
- 承担 S4 的产品体验、评测分母或发布级验收。
- 决定功能状态、合并顺序或自动合并到主分支。
- 在没有明确派发时推断并行或顺序执行。

## 允许修改路径

- 初始 `READ_ONLY_PARALLEL`：无。
- S1 激活写模式后：
  - `scripts/integration/**`
  - `tests/integration/**`
  - `artifacts/integration/**` 的生成器与结构

生成证据默认不提交。任何共享文件接入都必须另行指定单一写入者。

## 输入契约

| 契约 | 版本 | 提供者 |
|---|---|---|
| ContractSet | 当前实现基线摘要 | S1-ARCH |
| Base/Head/Branch/Worktree Manifest | 当前 Attempt | S1-ARCH |
| Handoff 与 Proof | 工作包版本 | S2～S6 |
| Workspace 与依赖锁 | 当前候选 | S5-CORE |
| Migration/Compose Manifest | 当前候选 | S6-DATA |

## 输出契约

| 契约 | 版本 | 消费者 |
|---|---|---|
| Integration Composition Manifest | WP-040 v1 | S1 |
| Evidence Reproduction Report | WP-040 v1 | S1、责任会话 |
| Cross-component Failure Case | WP-040 v1 | S3/S4/S5/S6 |

## 架构与安全约束

- 主分支必须保持可验证；临时组合失败不得污染主 Worktree。
- S7 不得修改输入分支，也不得用 rebase/reset/force-push 改写历史。
- ContractSet 摘要、Approval/Ledger 绑定、RLS、状态权威和 Audit 不变量必须在组合后继续成立。
- 临时环境和报告不得包含密钥、真实 PII、生产 Prompt/Trace 或原始附件。

## 实施内容

1. 建立 Base/Head、路径所有权、工作区洁净度和 Handoff 哈希复算清单。
2. 生成显式提交组合矩阵；每个组合记录顺序与预期依赖。
3. 复现单分支门禁，再在临时组合树运行联合门禁。
4. 验证 root Workspace、`uv.lock`、wheel 与内部包闭包。
5. 验证 Migration 单 Head、升级路径、Compose 依赖和恢复入口。
6. 输出阻塞项、责任角色、最小复现和解锁条件。

## 必须测试

- 正常路径：所有声明提交可组合并复现门禁。
- 边界条件：空增量、重复输入 Head、未启动可选依赖。
- 失败路径：错误 Base、脏 Worktree、缺失内部包、锁文件漂移、Migration 多 Head。
- 安全负向：Secret、跨租户、Approval/Ledger 绑定和 Audit 校验仍失败关闭。
- 恢复/幂等：从同一 Manifest 重建得到相同组合与报告哈希。

## 验收命令

```bash
# WP-040 初始只读阶段先复现各交接声明的现有命令。
# 统一 scripts/integration 入口尚未实现，不能标记为 PASS。
```

## 证据

- Base/Head/路径范围清单
- 单分支与组合树命令、退出码和输出哈希
- Integration Composition Manifest
- 按 `docs/team/HANDOFF_TEMPLATE.md` 创建的交接

## 完成定义

- 结果可由 S1 从干净 Base 独立复现。
- 所有失败都绑定责任会话和解锁条件。
- 未修改输入分支、产品路径或公共契约。
- S1 完成复核后，才能把建议用于合并裁决。
