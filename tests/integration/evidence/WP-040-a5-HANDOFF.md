# WP-040-a5 S7-INTEGRATION M2 Studio 组合验证交接

## 基本信息

- Work Package：WP-040
- Attempt ID：WP-040-a5
- Chain ID：CHAIN-M2-STUDIO-01
- Step ID：M2-STUDIO-04-S7
- 责任会话：S7-INTEGRATION
- 接收会话：S1-ARCH
- 交接策略：FINAL_GATE
- 风险等级：R2
- 功能 ID：FP-FLOW-001、FP-FLOW-004、FP-FLOW-005、FP-FLOW-006、
  FP-OBS-001、FP-OPS-002
- 基线 / 输入提交：
  `8a351326ad33db195098ffd4c2f8a4b9f6b5a598`
- 实现提交：`d34e1f578dff395ae3c4cc4d88c0c1fb554b57b4`
- 分支/最终提交：`codex/s7/wp-040-integration-verification`；本文件所在
  提交，精确 SHA 由唤醒信封返回
- ContractSet 摘要：
  `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- 状态：完成，等待 S1 final gate；不代表已合并、已发布或已完成数据集

## 完成内容

- 核对任务标题、Project、Worktree、Branch 与 DEDUP_KEY；验证 S4 工作树
  精确位于输入 Head 且 clean，S7 原 Head 是输入 Head 的祖先后，只用
  `git merge --ff-only` 精确到达 S4 Head。
- 从激活提交
  `31f244c7ab28f8c635cc973dab1f591b55105429` 到输入 Head 复算六个
  单父提交，顺序为 S5 Workspace/Lock → S5 Handoff → S2 Studio Runtime
  → S2 Handoff → S4 Agent Server 黑盒 → S4 Handoff。
- 逐 Step 核验路径所有权：S5 只写授权共享文件和 Core Handoff，S2 只写
  Runtime/Graph、Runtime 测试和显式授权的 `langgraph.json`，S4 只写
  Acceptance 测试/生成器/证据。
- 从精确 Git Revision 复算 S5、S2、S4 Handoff 与 S4 Proof 原始字节
  SHA-256；复算链授权文件并验证 R2、最终 S7→S1 门禁和本 Attempt。
- 新增 `M2_STUDIO_CANDIDATE` / `M2_STUDIO_S1_FINAL` 两阶段验证：
  Candidate 只允许输入 Head 后出现 S7 独占路径；Final 要求精确 S7 Head
  是 S1 final Head 的祖先，分支为 `codex/s1/*` 或 `master`，并只允许
  S1/S7 控制路径。两阶段都逐对象保护产品树、Contract、Lock 和 Migration。
- M2 静态清单 40/40 PASS；历史 M0 36/36、M1 34/34 和既有固定 Hash
  保持不变。
- 复算 14 包 Workspace、116 项锁闭包和 Agent Server 四个关键版本；
  `langgraph.json` 只暴露 `flowpilot_it_service`，默认
  `studio-safe`、外网关闭、Trace 关闭、无 Tunnel。
- 交叉验证 S2 Runtime 拓扑快照 14 节点/20 结构边与 S4 独立 Agent
  Server Oracle 16 节点/22 展开边；Worker/Studio 共同消费同名 graph
  factory，生产 Profile 与未装配 Integration Profile 保持失败关闭。
- 在全新锁定环境运行真实无浏览器 Agent Server：完成 clarification 与
  approval 两次 Interrupt/Resume、并行只读、Handoff、retry 和
  `COMPLETED`；`checkpoint_sequence=4`、`run_generation=1`、18 帧
  安全投影、19 项完整父 Checkpoint 链。
- 真实 Server 生成器证明其启动进程、分配的随机监听端口和
  `.langgraph_api` 全部清零；业务源文件指纹前后一致。
- 由于 `uv.lock` 变化触发 RELEASE 档，补跑 14 Wheel、锁定环境重装导入、
  漏洞扫描和隔离 Compose/Migration/RLS/PostgreSQL Adapter/Redis 丢失
  恢复；Compose 最终容器与 Volume 均为 0。

## 未完成与非目标

- 未修改 S1～S6 产品代码、公共契约、Workspace/Lock、Migration、Infra、
  Compose、Makefile、`langgraph.json` 或上游测试。
- 未批准合并、发布或 Feature 状态；最终裁决仍属于 S1。
- `studio-integration` 的可信 Application/Gateway/测试 Realm 端口仍未
  装配，显式选择继续失败关闭。
- `make acceptance` 仍未实现；未声明 120/36 数据集完成、质量提升或发布
  验收。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `scripts/integration/verify_wp040.py` | M2 Candidate/Final 组合复算与失败关闭检查 | S7 |
| `tests/integration/test_wp040_composition.py` | M2 正常、边界、越权、Final 与历史回归测试 | S7 |
| `tests/integration/evidence/WP-040-a5-PROOF.json` | RELEASE 命令与组合证据 | S7 |
| `tests/integration/evidence/WP-040-a5-HANDOFF.md` | 本交接 | S7 |

## 契约、数据库与配置变化

- 公共契约：无变化；Contract Tree 为
  `3b67857c6aacce574080089ce1d8b763dd766a77`。
- ContractSet：
  `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`。
- Workspace / Lock / Makefile：无 S7 修改；输入锁 SHA-256 为
  `9c9ab3febad1a13571d51e567c6546f27be809f86927e03b0e64339e4ac957c2`。
- Migration / RLS / 数据库：无提交变化；只在隔离 Compose 项目复现，
  已删除测试容器、网络和 Volume。
- 生产依赖 / 生产凭据 / 外部系统：无新增或连接；Agent Server 只绑定
  回环地址并使用 `studio-safe`。

## 验证

环境：Windows、锁定 CPython 3.12.11、uv 0.11.32、Pytest 9.1.1、
Ruff 0.16.0、Mypy 1.20.2、LangGraph CLI 0.4.31、Agent Server 0.11.2、
GNU Make 4.4.1、Docker Client/Server 29.6.2、Compose v5.3.1。

| 命令 / 门禁 | 结果 |
|---|---|
| M2 Candidate 静态复算 | PASS：40/40 |
| 历史 M0 / M1 静态复算 | PASS：36/36、34/34；既有固定 Hash 不变 |
| 全新 `uv sync --all-packages --all-groups --locked` | PASS：116 locked / 14 Workspace |
| 产品测试 | PASS：213 passed |
| Acceptance / 真实 Agent Server | PASS：65 passed |
| Integration | PASS：32 passed |
| Security | PASS：51 passed |
| Contract Conformance | PASS：20 schemas、43 语义负例、52 features |
| 离线 Gate | PASS：2 Case / 0 Findings |
| 影响范围与 14 包 Workspace Ruff | PASS |
| 严格 Mypy | PASS：88 source files |
| 14 Wheel 构建、锁定环境重装和导入 | PASS：`LOCKED_WHEEL_IMPORT_OK packages=14` |
| `pip-audit` 2.10.1 | PASS：0 known vulnerabilities |
| 真实 Agent Server 独立证据 | PASS：16 节点/22 边、COMPLETED、残留 0 |
| 直接锁内 `langgraph --version` / `dev --help` | PASS |
| `make studio-smoke` | ENV_BLOCKED：Windows GNU Make 的 `/usr/bin/bash` 丢失绝对 UV 路径盘符；两条等价锁内命令直接 PASS |
| 隔离 Compose、Migration、RLS、Adapter、Redis 恢复与清理 | PASS：5 healthy；容器/Volume 0 |
| 全 Acceptance Ruff 诊断 | INHERITED：4 个 WP-030-a1 I001；本链影响范围 PASS |
| `make acceptance` | NOT_IMPLEMENTED：无 Target，退出码 2 |
| `git diff --check` | PASS |

M2 固定输入清单：

```text
MANIFEST=sha256:732b971522f5bb4b4840814952efcdceae3ffd1bea8a1996e75edfb642e3dc84
REPORT=sha256:69d01b16ae97165d1c9122c9f7bc3bf755fa31b2d1522710f71d05b1e60d17b0
```

完整结果见
`tests/integration/evidence/WP-040-a5-PROOF.json`。

## 安全与失败路径

- S5/S2/S4 越权、错误父链、S7 产品路径、S1 final 非 S1/S7 路径和缺少
  `--s7-head` 均失败关闭。
- Studio 默认关闭外网和远程 Trace，稳定 Make 入口不含 `--tunnel`；
  生产 Profile 编辑、未知 Scenario、Approval 拒绝和权威字段注入继续由
  S2/S4 黑盒失败关闭。
- 安全投影保持闭合白名单；Secret、PII、原始 Context、Provider Session
  与未来未知字段均不进入投影或最终结果。
- 真实 Server 进程、其分配端口和 `.langgraph_api` 残留为 0；隔离
  Compose 清理后容器和 Volume 为 0。

## 已知问题与 Advisories

- P2：`make acceptance` 仍未实现，不能宣称完整发布验收。
- P2：`make studio-smoke` 在当前 Windows GNU Make 与绝对 UV 覆盖组合下
  仍 ENV_BLOCKED；直接锁内等价命令和更强真实 Server 黑盒均 PASS。
- P2：全 Acceptance 仍有 4 个继承的 I001，均位于 WP-030-a1 文件且不在
  M2 差异；本链影响范围 Ruff PASS。
- P2：`studio-integration` 可信端口尚未装配，当前失败关闭。
- P2：S7 检查前已存在一个绑定 `127.0.0.1:2024` 的本地 Agent Server
  Listener；它在本轮真实随机端口验证前后数量均为 1，不属于 S7 启动树，
  因此未越权终止。S7 自身启动的进程和端口残留均为 0。
- P3：全新环境与 Wheel 临时目录位于系统 Temp，不在仓库中，不影响候选。

## 学习候选

```text
LEARNING_CANDIDATE=本地开发服务器的无残留证明必须绑定本次分配的进程树和端口
MATURITY=VERIFIED
TRIGGER=宿主机在 S7 启动前已有默认 2024 端口 Listener，而本次生成器使用独立随机端口
MECHANISM=只断言宿主机某个固定端口为 0 会把其他会话的预存资源误归因于当前 Attempt；只断言子进程退出又可能漏掉子进程树和运行目录
STRUCTURE=启动前记录预存资源；为本次运行分配独立端口并绑定根 PID；结束后同时证明根进程树、该端口和 .langgraph_api 清零，预存未知进程只报告不越权终止
EVIDENCE=artifacts/acceptance/generators/studio_agent_server.py；tests/integration/evidence/WP-040-a5-PROOF.json
RESIDUAL_RISK=长期占用默认端口会阻止开发者运行 make studio，需要由资源 Owner 手工确认后关闭
TARGET=docs/architecture/ENGINEERING_PLAYBOOK.md local development server cleanup section
```

## 接收会话下一步

1. 核验最终 NEW_HEAD、Handoff/Proof Hash、S7 路径范围、工作树洁净度、
   ContractSet 与输入 Head 祖先关系。
2. 在 S1 final 分支形成待验 Head 后运行：

   ```text
   python scripts/integration/verify_wp040.py --repo . \
     --phase M2_STUDIO_S1_FINAL \
     --s7-head <S7_NEW_HEAD> \
     --target-head <S1_FINAL_HEAD>
   ```

3. 独立复算产品树、Contracts、S5/S2/S4 输入 Heads、Lock、Migration 和
   M2 40 项静态清单；产品候选未变时按 FAST final gate，不重复 RELEASE。
4. 到达 final gate 后设置 `USER_GATE_REQUIRED=yes`，停止自动链并等待用户。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M2-STUDIO-01
STEP_ID=M2-STUDIO-04-S7
ATTEMPT_ID=WP-040-a5
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=8a351326ad33db195098ffd4c2f8a4b9f6b5a598
CONTRACT_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
GATE=PASS
HANDOFF=tests/integration/evidence/WP-040-a5-HANDOFF.md
NEXT_ROLE=S1-ARCH
NEXT_ATTEMPT_ID=none
ESCALATE_TO_S1=yes
```

## 可回滚方式

- S7 实现与 Handoff 提交可由 S1 按逆序 `git revert`；禁止 reset/rebase。
- 本 Attempt 没有持久外部写入；隔离 Compose 项目已 `down -v`。
