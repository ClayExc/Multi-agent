# WP-040-a7 S7-INTEGRATION P2 Durable Runtime RELEASE 交接

## 基本信息

- Work Package：WP-040
- Attempt ID：WP-040-a7
- Chain ID：CHAIN-P2-DURABLE-RUNTIME-01
- 权威 Step ID：P2-DURABLE-03-VERIFY
- 唤醒别名：P2-DURABLE-03-RECOVERY-VERIFY；已按仓库 Chain Authority
  规范化，不改变授权或顺序
- Agent ID：recovery-verifier
- DEDUP Key：
  `CHAIN-P2-DURABLE-RUNTIME-01/P2-DURABLE-03-RECOVERY-VERIFY/WP-040-a7/052e61beff5711e3e69dbaf45b792ad8d1a309dc`
- 责任会话：S7-INTEGRATION
- 接收会话：S1-ARCH
- 交接策略：FINAL_GATE
- 风险等级：R2
- Gate Level：RELEASE
- Flow Lite 目标：仅 g1；g2/g3 未启动
- 功能 ID：FP-FLOW-005、FP-DATA-003、FP-OPS-002
- 输入提交：`052e61beff5711e3e69dbaf45b792ad8d1a309dc`
- S7 实现提交：`4c3c9521e589a1fd54c0fee6b7a1b5d16f56ce2a`
- 分支：`codex/s7/wp-040-integration-verification`
- 最终提交：本文件所在提交；精确 SHA 由唤醒信封返回
- ContractSet 摘要：
  `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- Proof：`tests/integration/evidence/WP-040-a7-PROOF.json`
- Proof SHA-256：
  `sha256:25e87ff59df67f3aa05d9a18296d9ef3b836e2728d0e0ac2f4c13f995b2e25e4`
- 状态：RELEASE 组合复现通过，等待 S1 final gate 与用户门禁

## 消费门禁与线性候选

- 按 DELTA Context Bootstrap 核对当前任务映射、Worktree/分支、DEDUP、
  Agent Registry、Chain Authority、S2 Head、S2/S6 Handoff 原始字节 Hash、
  ContractSet、祖先关系和 clean；无须切换 FULL。
- 唤醒遗漏的 `CONTEXT_*` 字段已从注册表和 Chain Authority 确定性恢复；这是
  调度信封 P2 Advisory，不影响身份或权限。
- 输出 `CONSUMER_VERDICT=ACCEPT` 后，S7 只执行一次 `git merge --ff-only`，
  从 `0da13854beafd0e82f5f6151cc9f78ef1e090fc9` 精确到达 S2
  `052e61beff5711e3e69dbaf45b792ad8d1a309dc`；未 merge commit、rebase、
  reset、复制产品文件或 push。
- P2 激活到输入共 5 个单父提交：S1 Context 控制增量 → S6 实现 → S6
  Handoff → S2 实现 → S2 Handoff。五段路径范围均为 0 越权。
- contracts、pyproject.toml、uv.lock、Makefile、migrations 和 infra 对 P2
  激活提交的 Git 对象未变化。
- 原始证据 Hash 独立复算：S6 Handoff `sha256:17759d0b...ee1823`、S2
  Handoff `sha256:5fb65bcb...6b24d1`、Chain Authority
  `sha256:0e171dd2...bbc34`、Agent Registry `sha256:6062a4f5...688a9`。

## 完成内容

- 在既有组合验证器中新增 `P2_DURABLE_CANDIDATE` 与
  `P2_DURABLE_S1_FINAL`：
  - Candidate 要求 S2 输入是 S7 Head 祖先，S2→S7 只能出现 S7 独占路径，
    并逐对象保护产品、ContractSet、Lock、Migration 与 Infra。
  - Final 要求经审查 S7 Head 是 S1 final Head 祖先，分支必须是
    `codex/s1/*` 或 `master`；增量只允许 S1/S7 独占路径及授权
    `.gitignore`，仍逐对象证明产品树和两个输入 Head 未被改写。
- 固定输入静态复算 33 项全部 PASS：线性父链、五段路径所有权、四份上游
  证据、14 包 Workspace / 116 项 Lock、ContractSet 内容摘要、共享文件对象、
  Worker 类型化端口、显式 control checkpointer、Lease generation、Checkpoint
  CAS、可信租户 Redis 重建以及 Worker 无 PostgreSQL/Redis Driver 旁路。
- 新增真实服务验证器，使用生产 `build_durable_runtime`、
  `PostgresDataUnitOfWorkFactory`、`CoordinationRebuilder` 和
  `RedisCoordinationAdapter`；直接 Driver 只在 S7 建库、RLS 观测和 Redis
  状态观测夹具中使用，Worker 未直连数据库或 Redis。
- 隔离 Compose 中实际复现：
  - Redis 清空后，可信 tenant-a 从 PostgreSQL Task/Outbox 重建 1 个信号；
    tenant-b 重建 0 个。
  - 第一个 Worker 在持久化 retry 点保存 checkpoint sequence 3，使用
    generation 1；新 Worker 使用 generation 2，从同一 tenant + task +
    thread 的 PostgreSQL 最新 checkpoint 续跑至 `COMPLETED`，sequence 6。
  - 旧 Worker 尝试写入 1 次，成功写入 0；陈旧 Checkpoint CAS 成功写入 0。
  - Task 投影更新为 `COMPLETED` 后再次清空 Redis，重建信号 0；重复终态投递
    的节点重跑 0、checkpoint 新写入 0、runtime 调用增量 0。
  - RLS 与类型化 Port 的跨租户 Task/Checkpoint 成功读取总数 0。
  - 显式 control checkpointer 共观测 3 个；没有生产默认内存 Checkpointer。
- 新增 16 个 P2 正常/边界/失败回归，覆盖错误父链、证据 Hash、S7 越权、
  S1 final 产品越权、缺少 reviewed S7 Head，以及所有安全计数非零时失败关闭。
- 全新锁定 Python 环境完成 RELEASE 测试、Wheel 安装、漏洞/Secret 扫描，
  Compose 项目最终容器/卷/网络均为 0。

## 一次范围内修复

- 第一次真实运行在连接 PostgreSQL 前被 Windows 默认 Proactor Event Loop
  拒绝；没有进入本次业务用例或产生产品状态。
- S7 验证器改用 psycopg 支持的 Selector Event Loop 后连续两次通过。修复仅在
  `scripts/integration/**`，未改 S1～S6 产品、依赖或公共 API。

## 未完成与非目标

- 本交接不批准合并、Feature VERIFIED/RELEASED 或发布；最终裁决属于 S1，
  且链尾必须设置 `USER_GATE_REQUIRED=yes` 等待用户。
- g2 Outbox→SSE 与 g3 安全 Ticket 写入未获本链授权，未启动、未验证。
- 未连接生产 PostgreSQL/Redis、企业网络、外部 Provider、生产凭据或真实 PII。
- 未修改契约、ADR、Migration、Compose、Workspace/Lock、Makefile、产品代码
  或其他角色路径。
- `make acceptance` 仍无目标，且当前 Windows 无 `make.exe`；显式 Acceptance
  89 passed 已记录，但不把不存在的稳定入口标成 PASS。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `scripts/integration/verify_wp040.py` | P2 candidate/final 静态组合验证 | S7 |
| `scripts/integration/verify_durable_recovery.py` | 真实 PostgreSQL/Redis 恢复验证器 | S7 |
| `tests/integration/test_wp040_p2_durable.py` | P2 正常、漂移、越权与安全计数负例 | S7 |
| `tests/integration/evidence/WP-040-a7-PROOF.json` | RELEASE 命令与组合证据 | S7 |
| `tests/integration/evidence/WP-040-a7-HANDOFF.md` | 本交接 | S7 |

## 契约、数据库与配置变化

- 公共 ContractSet：无变化；内容摘要与 tree 独立复算一致。
- Workspace / Lock：无变化；14 个成员、116 个锁包，Lock SHA-256 为
  `9c9ab3febad1a13571d51e567c6546f27be809f86927e03b0e64339e4ac957c2`。
- Migration / RLS / Infra：无提交变化；只在独立卷中连续应用 `0002` 两次并
  运行 RLS 黑盒，随后删除该卷。
- 生产依赖、生产凭据、外部系统：无新增、无连接。

## 验证结果

环境：Windows、CPython 3.12.11、uv 0.12.0、Ruff 0.16.0、Mypy 1.20.2、
pip-audit 2.10.1、Docker 29.6.2、Compose v5.3.1、PostgreSQL 17.5、
Redis 7.4.2。

| 命令 / 门禁 | 结果 |
|---|---|
| P2 Candidate 静态复算 | PASS：33/33；实际 S7 Head 与固定输入均可确定性复算 |
| 全新 `uv sync --all-packages --all-groups --locked` | PASS：116 Lock / 14 Workspace |
| 全量 Python | PASS：265 passed |
| Platform Security | PASS：68 passed |
| Acceptance | PASS：89 passed |
| Integration | PASS：60 passed；其中新增 P2 16 passed |
| Contract Conformance | PASS：20 schemas / 35 cases / 43 semantic negatives / 52 features |
| Offline Gate | PASS：2 cases / 0 findings |
| P2 影响范围 Ruff | PASS |
| 严格 Mypy | PASS：89 source files |
| 14 wheels 构建、锁定依赖安装及导入 | PASS：`LOCKED_WHEEL_IMPORT_OK packages=14` |
| `pip-audit` | PASS：0 known vulnerabilities |
| UTF-8/LF/BOM / Secret Scan | PASS：30 paths / 0 / 0 |
| 隔离 Compose/Migration/RLS/Recovery | PASS：5 healthy；所有恢复与安全计数满足门禁 |
| Compose Cleanup | PASS：containers=0 / volumes=0 / networks=0 |
| `make acceptance` | NOT_IMPLEMENTED：无目标；当前 Windows 无 make |
| 全仓 Ruff 诊断 | INHERITED：29 项，均不在 P2 激活后的变更范围 |

静态实际 S7 Head 产物：

```text
WP040_P2_DURABLE_COMPOSITION_PASS checks=33 failed=0
MANIFEST_SHA256=sha256:f325af3b0a59f0dab75174135dc44cff950094c9db2544bec0bc9fb83c8819c7
REPORT_SHA256=sha256:3d2c1e107416d3fcf4b6043c6fb781f632ee57706346d0e6d75a4996cbdc2c34
```

固定输入纯逻辑 Hash：

```text
MANIFEST_SHA256=sha256:45c75585f03e0a652b7e1a724a05a2d3e28e6fb7d28b4f776b18ae506e3cfdd9
REPORT_SHA256=sha256:ab5cf5280d6ec8208f9820d5fb42a5b6a73feed0f31a3cd7628fafdcf8aa76fd
```

真实恢复摘要：

```text
DURABLE_RECOVERY_OK generation=1->2 checkpoint=3->6 old_worker_writes=0 terminal_reruns=0 cross_tenant_reads=0
```

## Blockers 与 Advisories

- BLOCKERS：none。
- P2 Advisory：全仓 Ruff 有 29 个继承 finding，位于 P1
  evaluation/observability/acceptance 路径；P2/S7 影响范围 Ruff PASS，且这些
  finding 对激活提交无新增。Owner：对应路径责任会话后续工作包。
- P2 Advisory：`make acceptance` 未实现，当前使用显式 Acceptance 89 passed；
  不影响本次恢复语义，但稳定命令入口仍应由 S4/S1 后续处理。
- P2 Advisory：唤醒信封缺少 `CONTEXT_*` 字段且使用长 Step 别名；本次可从
  权威文档确定性消歧，建议调度器后续直接发权威 Step 与 DELTA 字段。

## 学习候选

```text
LEARNING_CANDIDATE=Windows 上 psycopg async 集成夹具必须使用 SelectorEventLoop；默认 Proactor 会在连接前失败。该规则只适用于测试/集成 Harness，不应扩散到产品接口。
```

## 接收会话下一步

1. 核验 S7 最终 NEW_HEAD、Handoff/Proof 原始字节 Hash、S7 路径范围、clean、
   ContractSet 和 S6/S2 输入 Head 祖先关系。
2. S1 只以 `--ff-only` 精确消费 S7 NEW_HEAD，在 final 分支形成待验 Head。
3. 运行：

   ```text
   python scripts/integration/verify_wp040.py --repo . \
     --phase P2_DURABLE_S1_FINAL \
     --s7-head <S7_NEW_HEAD> \
     --target-head <S1_FINAL_HEAD>
   ```

4. 独立复算产品树、contracts、S6/S2 Heads、Lock、Migration、Infra 和 33 项
   静态清单。若 S1 只增加控制面文档，按 FAST final gate，不重复本次
   Wheel/Compose RELEASE。
5. 设置 `USER_GATE_REQUIRED=yes`，停止自动链并等待用户；不得自动启动 g2/g3。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-P2-DURABLE-RUNTIME-01
STEP_ID=P2-DURABLE-03-VERIFY
ATTEMPT_ID=WP-040-a7
AGENT_ID=recovery-verifier
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=052e61beff5711e3e69dbaf45b792ad8d1a309dc
INPUT_HEAD=052e61beff5711e3e69dbaf45b792ad8d1a309dc
IMPLEMENTATION_HEAD=4c3c9521e589a1fd54c0fee6b7a1b5d16f56ce2a
CONTRACT_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
GATE=PASS
GATE_LEVEL=RELEASE
HANDOFF=tests/integration/evidence/WP-040-a7-HANDOFF.md
PROOF=tests/integration/evidence/WP-040-a7-PROOF.json
PROOF_SHA256=sha256:25e87ff59df67f3aa05d9a18296d9ef3b836e2728d0e0ac2f4c13f995b2e25e4
NEXT_ROLE=S1-ARCH
NEXT_ATTEMPT_ID=none
USER_GATE_REQUIRED=yes
ESCALATE_TO_S1=yes
```

## 可回滚方式

- S7 实现与证据提交可由 S1 按逆序 `git revert`；禁止 reset/rebase。
- 隔离 Compose 容器、卷和网络已删除；无生产或外部持久写入需要回滚。
