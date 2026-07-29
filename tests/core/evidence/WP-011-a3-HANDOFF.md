# WP-011-a3 S5-CORE 九包 Workspace 交接

## 基本信息

- Work Package：WP-011
- Attempt ID：WP-011-a3
- Chain ID：CHAIN-WP040-A0-REMEDIATION-01
- Step ID：WP040-REM-03-S5
- 风险等级：R2
- 执行模式：ORDERED
- 责任会话：S5-CORE
- 接收会话：S7-INTEGRATION
- 交接策略：CONSUMER_GATE
- 功能 ID：FP-FLOW-007、FP-FLOW-008、FP-FLOW-009、FP-APR-001
- 基线提交：`0be20f5b56d330f4da494ce4c3d46b183b09ae8b`
- 上游提交：
  - `S2-RUNTIME:c3da3118eac5ee7d57c6b333c2aac3a0f119d799`
  - `S6-DATA:e41f0266e6e588417332043b68a3309b2d40bcf7`
- 分支：`codex/s5/wp-011-core-bootstrap`
- 最终提交：本文件所在提交；精确 SHA 由链路交接消息返回
- ContractSet 摘要：
  `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- 状态：完成，等待 S7 消费门禁

## 消费者门禁

S5 在任何写入前完成以下只读检查并返回
`CONSUMER_VERDICT=ACCEPT`：

- 控制工作区 HEAD 精确等于授权提交
  `6a16320a16fc76f2a5ffdedfc0ab893c87a636fa`。
- 链路、Step、Attempt、风险等级、基线、写范围和下一角色与授权记录一致。
- S2/S6 Worktree 均处于授权分支、精确 Head 且洁净。
- S2 增量只包含 `apps/worker/**`、`packages/graph/**`、
  `packages/agent-runtime/**`、`packages/model-gateway/**`、
  `packages/context/**` 和 `tests/runtime/**`。
- S6 增量只包含 `packages/persistence/**`、`migrations/**` 和
  `tests/data/**`。
- S6 Handoff 声明的三个证据 SHA-256 均复算一致。
- S2 Handoff 创建时记录的 `.idea/**` 暂停状态已由授权提交明确关闭；
  当前相关 Worktree 洁净，授权记录将 S2 精确 Head 标记为
  `CONSUMER_READY`。
- 公共契约未被上游修改，Contract Conformance 复算通过。

Handoff 文件哈希：

- S2：
  `sha256:d27b4fae55b8006a5337184ff0754fd6f037e86a2b8577b1cf991a6c1618bb83`
- S6：
  `sha256:da2f44abc2c9f34f8549df905898949bc6de59ac419232a2f2654efa19ccd479`

## 完成内容

- 从 S5 基线和两个上游精确 Head 构造工作树外临时组合源码集；没有
  merge、rebase、reset，也没有修改 S2/S6 分支。
- 组合源码集包含九个可安装内部包：
  `flowpilot-api`、`flowpilot-worker`、`flowpilot-agent-runtime`、
  `flowpilot-application`、`flowpilot-context`、`flowpilot-domain`、
  `flowpilot-graph`、`flowpilot-model-gateway` 和
  `flowpilot-persistence`。
- 根 `pyproject.toml` 已正确声明上述九个 Workspace Member/Source；
  `Makefile` 已使用 `--all-packages --all-groups --locked` 并覆盖
  Core/Runtime/Data，因此本 Attempt 不产生无意义配置改写。
- 在完整源码集合上刷新 `uv.lock`。锁解析 73 个包，包含九个内部可安装
  包及根 Workspace 元包；最终锁哈希为
  `sha256:eb0f7ef676b42d81bd60d47de02b202197cc6d300ae8d4715814c3ebf3da70f8`。
- 接受 `WP-010-a2-DR-001`：Worker 对本地
  `flowpilot-persistence` 的依赖由 S2 包声明，S5 Workspace/锁已形成统一
  安装闭包。该请求没有新增第三方依赖。
- 保持此前接受的 SQLAlchemy、Psycopg 和 Redis 依赖及其版本约束；
  本 Attempt 没有新增生产依赖、放宽版本或扩大公共契约。

## 未完成与非目标

- 未修改或提交 S2/S6 所有权源码、公共契约、架构/验收文档、Migration、
  Infra 或其他角色路径。
- 未执行真实 PostgreSQL/Redis/Compose 故障注入；S6 Handoff 已提供实库
  与恢复证据，S7 负责最终组合复现。
- 根 `Makefile` 仍未实现 `make test-security`、`make acceptance`、
  `make dev` 和 `make eval`。本轮只通过已有稳定入口及授权要求的联合门禁，
  不把局部测试宣称为全仓安全或发布验收。
- S5 独立分支按路径所有权不包含 S2/S6 源码；因此 S7 必须先组合三个精确
  Heads，再运行依赖锁门禁。只在孤立 S5 树解析最终锁不是有效复现方式。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `uv.lock` | 加入完整 S2/S6 内部包的最终 Workspace 锁条目 | S5-CORE |
| `tests/core/evidence/WP-011-a3-HANDOFF.md` | 消费校验、九包门禁与 S7 交接证据 | S5-CORE |

## 契约、数据库与配置变化

- 公共契约：无变化。
- ContractSet：
  `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`。
- 内部 Port：消费 S2/S6 已提交实现；S5 未修改 Port 语义。
- Migration：无修改；组合输入包含 S6 线性 Head
  `0002_checkpoint_sequence_cas`。
- 环境变量：无修改；联合 Data 测试读取 S6 精确 Head 的
  `.env.example`。
- `pyproject.toml` / `Makefile`：内容无需变化。
- `uv.lock`：完整九包闭包，73 个包。

## 依赖、许可证与攻击面

本 Attempt 无新增第三方依赖。此前 S5 已在
`tests/core/evidence/WP-011-a2-S6-ALIGNMENT.md` 记录数据库依赖的用途、
许可证、替代方案和攻击面；版本保持：

- SQLAlchemy 2.0.51：MIT。
- Psycopg/Binary 3.3.4、Pool 3.3.1：LGPL-3.0-only，分发许可证含
  LGPL Section 3 Exception。
- Redis 5.3.1：MIT。
- LangGraph 1.2.10：MIT。

`pip-audit` 对联合环境中的第三方安装闭包报告
`No known vulnerabilities found`；九个本地 Editable 包由测试、Ruff、
Mypy、wheel 安装冒烟和 Secret Scan 覆盖。

## 验证

验证环境：Windows、CPython 3.12.11、uv 0.11.32、GNU Make 4.4.1。

| 命令/门禁 | 结果 |
|---|---|
| `uv lock` / `uv lock --locked` | PASS：73 packages；锁哈希稳定 |
| `make bootstrap` | PASS：九包及全部锁定组可安装 |
| `make test` | PASS：143 passed（Core 44、Runtime 43、Data 56） |
| `make test-contract` | PASS：`CONTRACT_CONFORMANCE_OK` |
| Ruff（九包源码及 Core/Runtime/Data 测试） | PASS：All checks passed |
| Mypy `--strict`（九包源码） | PASS：56 source files |
| `uv build --all-packages --wheel` | PASS：9 wheels |
| 全新 Wheel 环境安装并导入九包 | PASS：`WHEEL_IMPORT_OK packages=9` |
| `pip-audit` 联合安装环境 | PASS：0 known vulnerabilities |
| 高置信 Secret pattern scan | PASS：0 matches |
| `git diff --check` | PASS |

Contract Conformance 完整结果：

```text
CONTRACT_CONFORMANCE_OK schemas=20 cases=35 positive=18 negative=17 mutation_cases=19 mutation_positive=3 mutation_negative=16 semantic_cases=43 semantic_positive=0 semantic_negative=43 audit_chain_cases=5 audit_chain_positive=1 audit_chain_negative=4 manifest_cases=21 manifest_positive=1 manifest_negative=20 features=52
```

首次临时组合仅遗漏 S6 所有的根级 `.env.example`，导致 Data E2E 在测试
收集期失败；补齐精确 S6 Head 的该输入文件后，完整稳定入口连续通过。
这是组合清单校正，不是产品代码、锁文件或门禁豁免。

## 安全与失败路径

- Core/Runtime/Data 联合测试覆盖 Command 绑定、跨租户查询、Checkpoint
  tenant/task/thread 错配、CAS 冲突、Lease 过期、旧 generation/fence、
  Worker 重启恢复、Ledger digest、RLS/Migration 静态安全和 Redis 丢失。
- Contract Gate 保持 43 个语义负例、Audit Chain 和 Manifest 失败关闭。
- Secret/PII：高置信 Secret Pattern 0 命中；未写入真实凭据、生产 PII、
  Prompt、Trace 或原始附件。
- wheel 冒烟使用工作树外全新虚拟环境；生成物未提交。

## 已知问题

- S6 `0002` 尚未由 Compose 自动挂载，是授权记录保留的 P2 后续项；
  不阻塞本轮 Workspace/锁交接，但必须在 M0 Compose 验收前关闭。
- 全仓 `test-security` 与 `acceptance` 稳定命令尚未实现，不能据本 Handoff
  宣称安全套件或发布验收完成。

## 接收会话下一步

1. S7 精确核验本分支 NEW_HEAD、本 Handoff、ContractSet 摘要与路径范围。
2. 从干净控制基线组合：
   `S2-RUNTIME:c3da3118eac5ee7d57c6b333c2aac3a0f119d799`、
   `S5-CORE:<本交接 NEW_HEAD>`、
   `S6-DATA:e41f0266e6e588417332043b68a3309b2d40bcf7`。
3. 复现锁文件、九包 wheel、Core/Runtime/Data、类型、契约、Secret、
   Migration Head 和 Compose 门禁。
4. 按 `WP040-REM-04-S7` 输出组合 Manifest 与可合并性建议，并只在最终
   S7 门禁后返回 S1。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-WP040-A0-REMEDIATION-01
STEP_ID=WP040-REM-03-S5
ATTEMPT_ID=WP-011-a3
NEW_HEAD=<this-handoff-commit; exact-sha-in-final-message>
BASE_COMMIT=0be20f5b56d330f4da494ce4c3d46b183b09ae8b
CONTRACT_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
GATE=PASS
HANDOFF=tests/core/evidence/WP-011-a3-HANDOFF.md
NEXT_ROLE=S7-INTEGRATION
NEXT_ATTEMPT_ID=WP-040-a1
ESCALATE_TO_S1=no
```

## 可回滚方式

- S1/S7 可按提交使用 `git revert <WP-011-a3-commit>` 回滚锁与证据。
- 本 Attempt 没有数据库、Migration 或外部系统写入，无数据回滚。
- 禁止 reset/rebase 或修改 S2/S6 输入分支。
