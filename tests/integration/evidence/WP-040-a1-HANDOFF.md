# WP-040-a1 S7-INTEGRATION 最终组合交接

## 基本信息

- Work Package：WP-040
- Attempt ID：WP-040-a1
- Chain ID：CHAIN-WP040-A0-REMEDIATION-01
- Step ID：WP040-REM-04-S7
- 风险等级：R2
- 执行模式：ORDERED / IMPLEMENTATION
- 责任会话：S7-INTEGRATION
- 接收与最终裁决会话：S1-ARCH
- 功能 ID：FP-FLOW-001、FP-SEC-004、FP-DATA-001、FP-OPS-002
- S7 基线：`55125ae3992311eab03cc888ea9c908486b4b727`
- 授权时控制 Head：`6a16320a16fc76f2a5ffdedfc0ab893c87a636fa`
- 候选组合快照：`56c90b1355213357415778bda43fc3acf96aa8ed`
- 候选 Tree：`534393229a1d87075ea520ba27a802ae3b6689f7`
- S7 最终 Head：本文件所在提交；精确 SHA 由最终链路消息返回
- ContractSet：
  `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- 建议：`ACCEPT_FOR_COMPOSITION`，仅限完整候选原子集成

## 输入消费门禁

S7 在写入前已返回 `CONSUMER_VERDICT=ACCEPT`，并核验：

| 角色 | Base | Head | 提交数 | 路径数 | Handoff SHA-256 |
|---|---|---|---:|---:|---|
| S2-RUNTIME | `34bec05003cb59b3e16f1a16ae166b1f77465c46` | `c3da3118eac5ee7d57c6b333c2aac3a0f119d799` | 3 | 10 | `d27b4fae55b8006a5337184ff0754fd6f037e86a2b8577b1cf991a6c1618bb83` |
| S5-CORE | `0be20f5b56d330f4da494ce4c3d46b183b09ae8b` | `315822de1c8a50f5ede304836686ce5e63f9ad1d` | 1 | 2 | `8db60024d62b63c03b8f9fdc7abdce38a6eb3b861e27411805b2ed38c5afe5fe` |
| S6-DATA | `3e0101999061a44a3a5b2fd455ec792e3f73954e` | `e41f0266e6e588417332043b68a3309b2d40bcf7` | 2 | 18 | `da2f44abc2c9f34f8549df905898949bc6de59ac419232a2f2654efa19ccd479` |

- 三个 Head 与 S7 Base 的 Merge Base 均为
  `93597a5023320d48875b292dc08106f03227a3fb`。
- 三个输入的完整增量路径两两无交集，责任范围违规为 0。
- Base 与三个输入的 `contracts/**` Tree 均为
  `3b67857c6aacce574080089ce1d8b763dd766a77`。
- ContractSet 内容摘要按
  `flowpilot.contract-set-content-rfc8785-sha256-v1` 独立复算一致。
- S2、S5、S6 和 S7 Worktree 在消费门禁时均处于声明分支、精确 Head 且
  洁净；未修改任一输入分支。

## 组合结论

S7 临时树的取材提交为：

1. `8f162841cec085221320c638d2ec7f1c04308cff`：加入 S5；
2. `9e8f427e5b02f9e48252ef706ebc9b82f31f1aa3`：加入 S6；
3. `56c90b1355213357415778bda43fc3acf96aa8ed`：加入 S2。

三次合并无冲突，最终内容闭包有效。该父提交顺序只是临时组合树的构造
记录，不是主分支逐步集成顺序。

更严格的中间态复核发现：不存在一个完整输入 Head 的线性顺序，能让每次
主分支更新后都同时满足“新增包存在、九包 Workspace 完整、最终锁覆盖且
联合测试可运行”。原因是：

- S5 同一 Head 同时携带 S6 所需 Port 与最终九包 Workspace/锁；
- 孤立 S5 Head 缺少 S2/S6 提供的六个 Workspace Member；
- S2 Worker 直接依赖 S6 `flowpilot-persistence`；
- S2/S6 不更新根 Workspace/锁。

因此建议 S1 把完整候选作为一次原子主分支转换，或在私有集成分支构造
等价最终 Tree 后一次合入。不得把消息到达顺序、整改链顺序或 S7 临时
父提交顺序当成三个可独立接受的主分支状态。详细失败用例见
`tests/integration/evidence/WP-040-a1-ATOMICITY.md`。

## 静态 Manifest 与依赖闭包

命令：

```powershell
python scripts/integration/verify_wp040.py `
  --output-dir artifacts/integration/runs/WP-040-a1
```

结果：

```text
WP040_COMPOSITION_PASS checks=36 failed=0
MANIFEST sha256:1e9140e267470a0b4404a34b07254569875c3d8c582517599cc328ba8b5dddb1
REPORT   sha256:533a2540a2d41264fe38bbc84c92ae5fa9bd5f3e1292b57598139e470c4e143c
```

Manifest 直接复算：

- 三输入 Base/Head、Merge Base、提交数、路径范围和 Handoff Hash。
- ContractSet 内容摘要与 Git Tree 一致性。
- 九个 Workspace Member/Source 全部存在且名称匹配。
- `uv.lock` 共 73 个唯一 Package，含九个内部可安装包和根 Workspace。
- `uv.lock`：
  `sha256:eb0f7ef676b42d81bd60d47de02b202197cc6d300ae8d4715814c3ebf3da70f8`。
- S2 Worker 显式消费 S5 Application/Domain 与 S6 Persistence。
- S6 Persistence 消费 S5 Application/Domain，且不反向导入 S2
  Graph/Worker。
- `TaskQueryPort.get()` 返回完整 `Task | None`，PostgreSQL 使用
  `Task.from_mapping()`。
- `PlannedAction.digest()` 使用
  `canonical_sha256(self.to_mapping())`。
- Migration 保持单 Head：
  `0001_persistence_baseline -> 0002_checkpoint_sequence_cas`。

## 联合验证

环境：Windows、CPython 3.12.11、GNU Make 4.4.1、Docker
Client/Server 29.6.2。S7 可用 uv 为 0.8.24；S5 Handoff 使用 0.11.32，
两者均解析同一锁且未产生锁漂移。

| 命令/门禁 | 退出码 | 结果 |
|---|---:|---|
| `uv lock --locked` | 0 | PASS：73 packages，锁 Hash 不变 |
| `make bootstrap` | 0 | PASS：九包和锁定依赖安装 |
| `make test` | 0 | PASS：143 passed（Core 44、Runtime 43、Data 56），4.92s |
| `make test-contract` | 0 | PASS：20 Schema、35 Case、43 语义负例、52 Feature |
| Ruff：九包源码、Core/Runtime/Data | 0 | PASS |
| Mypy `--strict`：九包源码 | 0 | PASS：56 source files |
| `pip-audit --path .venv/Lib/site-packages` | 0 | PASS：0 known vulnerabilities；九个本地包按预期跳过 PyPI 查询 |
| 高置信 Secret Pattern Scan | 0 | PASS：0 tracked-file matches |
| `docker compose config --quiet` | 0 | PASS |
| `pytest tests/integration` | 0 | PASS：10 passed |
| S7 verifier Ruff | 0 | PASS |
| S7 verifier Mypy `--strict` | 0 | PASS：1 source file |
| `git diff --check` | 0 | PASS |
| `make test-security` | 2 | NOT_IMPLEMENTED：Makefile 无该 Target |
| `make acceptance` | 2 | NOT_IMPLEMENTED：Makefile 无该 Target |

Contract Conformance 完整摘要：

```text
CONTRACT_CONFORMANCE_OK schemas=20 cases=35 positive=18 negative=17 mutation_cases=19 mutation_positive=3 mutation_negative=16 semantic_cases=43 semantic_positive=0 semantic_negative=43 audit_chain_cases=5 audit_chain_positive=1 audit_chain_negative=4 manifest_cases=21 manifest_positive=1 manifest_negative=20 features=52
```

## Wheel 闭包

`uv build --all-packages --wheel` 构建 9 个 Wheel；在工作树外全新虚拟环境
安装并导入通过：

```text
WHEEL_IMPORT_OK packages=9
```

| Wheel | SHA-256 |
|---|---|
| flowpilot-agent-runtime | `2a1c00c6df113684bc53cd1b6b9e9c96596f8f3c102927f013e8feb8c8901c68` |
| flowpilot-api | `7835669500d7b6ca94d75c9de76ff5a94ac255de341cefd89d8155c0c0115762` |
| flowpilot-application | `df993695183d1eb2a4a57cfe65654a15f9cc651180648ea7d59035e54c8435e0` |
| flowpilot-context | `2468b9bab13524a049b382ee7e5400e20b566d0c043b3b2784bad4bc2aaaef96` |
| flowpilot-domain | `084e983901ea916c657eb5a06e3573c539e54a45501fd0e24ed66f0a1413365e` |
| flowpilot-graph | `9601d8cfa05c5b427923f27aad6597d60e275d3cc1a8554bf8e694fbceb974c8` |
| flowpilot-model-gateway | `3a788780dec5942f2f89ece17a42032d0b72e872500ba999096f4b3d27110772` |
| flowpilot-persistence | `547f06e920eaf3fcb41495b3af348ec7a24b7376d47182d4343662180f698212` |
| flowpilot-worker | `acc800f719c85de98215424c9a39a93dd01e06cc4b6673e8b4ba81d37bf492f2` |

生成目录和全新虚拟环境位于 Windows Temp，不进入仓库或候选 Tree。

## Migration、Compose 与恢复

Migration 文件哈希：

| 文件 | SHA-256 |
|---|---|
| `0001_persistence_baseline.down.sql` | `c7efb33a30dae969d2dba39a06b921863390794ec618188bf9ea0969a42c56df` |
| `0001_persistence_baseline.sql` | `0a6c20e172f59c5c70cdd9370c996672a79841771575541c3c8bc372f38808cd` |
| `0002_checkpoint_sequence_cas.down.sql` | `beb71df8b0f82fdc11f9b59a3f323f9d43857356b76d136742f43fc67ff1f22c` |
| `0002_checkpoint_sequence_cas.sql` | `e5ca8fca2de8e913caedd488821356e441b2adc5ae72a20d015fe4df5b403112` |

在唯一项目 `flowpilot-wp040-a1-20260729` 的空卷环境中：

- PostgreSQL、Redis、Keycloak、OPA、OTel 五服务全部 healthy。
- `0002` 连续应用两次均成功；数据库记录 `0001`、`0002` 且均绑定当前
  ContractSet 摘要。
- `checkpoints.checkpoint_sequence` 为 `bigint NOT NULL`。
- `verify_postgres.sql` 通过 RLS、跨租户、审批到期和 UNKNOWN 负例。
- `verify_postgres_adapter.py` 通过完整 Task、Checkpoint CAS 1→2、
  同 Thread 双 Task 隔离、Ledger VERIFIED 和重试。
- Redis `DBSIZE 1 -> FLUSHDB -> DBSIZE 0` 后 PostgreSQL Task 数
  `3 -> 3`，业务事实未丢失。
- 结束时五服务仍 healthy。
- 证据完成后仅删除上述唯一测试项目的 5 个容器、3 个网络和 1 个
  PostgreSQL Volume；复核剩余容器和 Volume 均为 0。其他 Compose 项目
  未修改。

## 安全与失败路径

- 组合测试继续覆盖跨租户 Task 查询、Checkpoint tenant/task/thread
  错配、旧序号、旧 generation/fence、Lease 过期、幂等重放、存储异常
  净化和 Worker 重启恢复。
- Contract Gate 的 43 个语义负例、Audit Chain 与 Manifest 失败关闭。
- PlannedAction/Ledger 使用单一领域摘要实现；未发现第二套规范化路径。
- Secret Scan 为 0；证据不含真实凭据、生产 PII、Prompt、Trace 或原始
  附件。
- S7 新增的错误 Base、错误合并拓扑、跨 Owner 路径和锁漂移负例均失败
  关闭。

## BLOCKERS

- 对完整候选原子组合：无 P0/P1 Blocker。
- 若拟把 S2/S5/S6 完整 Heads 逐个作为可验收主分支状态：`P1`，
  `WP040-A1-CF-001` 阻断；解锁条件是改为完整候选原子集成并由 S1
  复算最终门禁。

## ADVISORIES

- `P2`：Compose 仍只自动挂载 `0001`；S7 手工应用并验证了 `0002`，但
  自动 Migration Runner/挂载必须在 M0 Compose 验收前由 S6/S1 关闭。
- `P2`：根 Makefile 仍未实现 `test-security` 和 `acceptance`，因此本
  Handoff 不宣称发布级安全套件或发布验收完成。
- `P3`：S7 环境 uv 0.8.24 与 S5 环境 0.11.32 不同；锁 Hash、73 包
  解析和安装结果一致，建议后续固定工具版本以减少环境漂移。

## 修改范围

本 Attempt 只新增：

- `scripts/integration/**`：只读组合复算器；
- `tests/integration/**`：正常、边界、失败与确定性回归；
- `artifacts/integration/**`：生成物目录结构和忽略规则。

未修改产品实现、公共契约、Migration、共享根配置或任何输入分支。生成
Manifest/Report 默认忽略，不提交运行结果。

## S1 下一步

1. 从 S7 最终 Head 复跑静态 Manifest，期望 36/36 PASS 且 Hash 一致。
2. 复核 `WP040-A1-CF-001`，选择完整候选的原子主分支集成方式。
3. 在单次最终 Tree 上复跑锁、143 测试、Contract、Wheel 与必要的实库
   门禁。
4. 单独安排 S6/Infra 关闭 Compose 未自动应用 `0002` 的 P2。
5. S1 保留正式 Work Package 验收、合并与发布裁决；S7 不批准合并。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-WP040-A0-REMEDIATION-01
STEP_ID=WP040-REM-04-S7
ATTEMPT_ID=WP-040-a1
NEW_HEAD=<this-handoff-commit; exact-sha-in-final-message>
BASE_COMMIT=55125ae3992311eab03cc888ea9c908486b4b727
CANDIDATE_MERGE_HEAD=56c90b1355213357415778bda43fc3acf96aa8ed
INPUT_HEADS=S2-RUNTIME:c3da3118eac5ee7d57c6b333c2aac3a0f119d799,S5-CORE:315822de1c8a50f5ede304836686ce5e63f9ad1d,S6-DATA:e41f0266e6e588417332043b68a3309b2d40bcf7
CONTRACT_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
MANIFEST_SHA256=sha256:1e9140e267470a0b4404a34b07254569875c3d8c582517599cc328ba8b5dddb1
REPORT_SHA256=sha256:533a2540a2d41264fe38bbc84c92ae5fa9bd5f3e1292b57598139e470c4e143c
RECOMMENDED_MAINLINE_MODE=ATOMIC_FINAL_CANDIDATE
SAFE_WHOLE_INPUT_SEQUENTIAL_ORDER=none
GATE=PASS
HANDOFF=tests/integration/evidence/WP-040-a1-HANDOFF.md
NEXT_ROLE=S1-ARCH
FORMAL_WORK_PACKAGE_ACCEPTANCE=S1_REQUIRED
```

## 可回滚方式

- S1 可使用 `git revert` 回滚 S7 证据提交或最终原子集成提交；禁止
  reset/rebase 改写输入历史。
- 本 Attempt 的唯一数据库/Compose 写入位于已删除的唯一测试项目和
  Volume，无外部数据回滚。
