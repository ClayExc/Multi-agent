# WP-040-a4 S7-INTEGRATION M1 Platform 组合验证交接

## 基本信息

- Work Package：WP-040
- Attempt ID：WP-040-a4
- Chain ID：CHAIN-M1-PLATFORM-01
- Step ID：M1-PLATFORM-05-S7
- 责任会话：S7-INTEGRATION
- 接收会话：S1-ARCH
- 交接策略：FINAL_GATE
- 风险等级：R2
- 功能 ID：FP-FLOW-001、FP-SEC-004、FP-DATA-001、FP-OPS-002
- 基线提交：`31f4b8b14150bd769910f144d9116578be6124ad`
- 实现提交：`2e7e1ebc87657ebd28e0cf677bd854b25d375c19`
- 分支/最终提交：`codex/s7/wp-040-integration-verification`；本文件所在
  提交，精确 SHA 由唤醒信封返回
- ContractSet 摘要：
  `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- 状态：完成，等待 S1 final gate；不代表已合并或发布

## 完成内容

- 从激活提交
  `c4062b2ac6a81aba4e3e1ac63cc01f54efecfed0` 到 S4 输入 Head
  `31f4b8b14150bd769910f144d9116578be6124ad` 复算了五个线性提交及其唯一
  父提交，顺序为 S3 Platform → S5 Workspace/Lock → S5 Handoff →
  S4 安全黑盒 → S4 Handoff。
- 逐 Step 核验路径所有权。S5 Handoff 单文件例外绑定 S1 Authority
  Commit `1ae7a79dd7e0d4da819b93dfa0d916771fb0d265`，授权文件 SHA-256 为
  `8279803e3b478196fe97757c638e53d93442ee266555606458053dd38ad1c8bf`。
- 复算 S3、S5、S4 Handoff 与 S4 Proof 原始字节 SHA-256，全部与声明
  一致；S4 Proof 的 9 个闭合覆盖项全部为真，且明确
  `release_gate=false`、`dataset_completion_claim=false`。
- 新增 `M1_PLATFORM_CANDIDATE` 与 `M1_PLATFORM_S1_FINAL` 两个验证阶段：
  - Candidate 要求 S4 输入 Head 是目标 Head 的祖先，S7 增量只在
    `scripts/integration/**`、`tests/integration/**` 或
    `artifacts/integration/**`。
  - Final 要求精确 S7 Head 是 S1 final Head 的祖先，分支必须是
    `codex/s1/*` 或 `master`，S1 增量只能在 S1/S7 授权路径。
  - 两阶段都逐对象证明产品树、ContractSet、`uv.lock` 与 Migration
    没有被 S7/S1 控制增量改写。
- 修复历史 M0 Verifier 的复算边界：M0 Workspace/Lock 改为从固定 Git
  Revision 读取，不再读取当前 checkout。M1 快进后原 M0 36/36 与两项
  固定 Hash 保持不变。
- M1 静态清单 34/34 PASS；14 个 Workspace 包、78 项锁闭包、内部依赖、
  稳定 Make 入口、Secret、Migration/Compose Tree 和上游证据闭包均通过。
- 在隔离 Compose 项目中验证 PostgreSQL、Redis、Keycloak、OPA 和 OTel
  五服务 healthy；`0002` 可重复应用；RLS、PostgreSQL Adapter、Redis
  丢失恢复通过；结束后项目容器和 Volume 都为 0。

## 未完成与非目标

- 未修改 S1～S6 产品代码、公共契约、Workspace/Lock、Migration、Infra、
  Compose、Makefile 或上游测试。
- 未决定合并顺序、正式接受、功能状态或发布；这些权力仍属于 S1。
- 未实现 `make acceptance`，未填充或宣称 120/36 数据集完成。
- 未把 Gateway 的 Audit/Security Draft 当成最终公共 AuditEvent；可信
  Sink/Store 仍负责 Stream、sequence、integrity 与租户绑定。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `scripts/integration/verify_wp040.py` | M1 Candidate/Final 静态复算、Revision 固定读取与失败关闭检查 | S7 |
| `tests/integration/test_wp040_composition.py` | M1 正常、边界、越权、Secret、Final 与历史回归测试 | S7 |
| `tests/integration/evidence/WP-040-a4-PROOF.json` | 结构化命令与组合证据 | S7 |
| `tests/integration/evidence/WP-040-a4-HANDOFF.md` | 本交接 | S7 |

## 契约、数据库与配置变化

- 公共契约：无变化；Contract Tree 仍为
  `3b67857c6aacce574080089ce1d8b763dd766a77`。
- ContractSet：
  `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`。
- Workspace / Lock / Makefile：无 S7 修改；输入锁 SHA-256 为
  `5111ba07d45f7d9ad3e1440663f6da2f4cfa078c4f52032621cd8cd6b89f08f1`。
- Migration / RLS / 数据库：无提交变化；仅使用隔离临时数据库复现。
- 环境变量 / 第三方生产依赖：无变化。

## 验证

环境：Windows、锁定 CPython 3.12.11、uv 0.11.32、Pytest 9.1.1、
GNU Make 4.4.1、Docker Client/Server 29.6.2、Compose v5.3.1。

| 命令 / 门禁 | 结果 |
|---|---|
| M1 Candidate 静态复算 | PASS：34/34 |
| 历史 M0 Candidate 静态复算 | PASS：36/36；原 Manifest/Report Hash 不变 |
| `make bootstrap` | PASS：78 locked packages / 14 internal packages |
| `make test` | PASS：194 passed |
| `make test-contract` | PASS：`CONTRACT_CONFORMANCE_OK`，43 个语义负例 |
| `make test-security` | PASS：51 passed |
| `python -m pytest tests/acceptance -q` | PASS：61 passed |
| `python -m pytest tests/integration -q` | PASS：24 passed |
| `python -B scripts/acceptance/validate_offline.py` | PASS：2 Case / 0 Findings |
| 影响范围与 14 包 Workspace Ruff | PASS |
| 严格 Mypy | PASS：82 source files |
| 14 Wheel 构建、全新离线环境安装与导入 | PASS：`WHEEL_IMPORT_OK packages=14` |
| `pip-audit` 2.10.1 | PASS：0 known vulnerabilities |
| 高置信 Secret Scan | PASS：0 matches |
| 隔离 Compose、Migration、RLS、Adapter、Redis 恢复与清理 | PASS：5 healthy；cleanup containers=0 volumes=0 |
| `git diff --check` | PASS |
| `make acceptance` | NOT_IMPLEMENTED：无 Target，退出码 2 |

M1 固定输入清单：

```text
MANIFEST=sha256:df72d6e13efb06bc34bedd96b14dcca6534a20752543b649c7a53e1d880c9633
REPORT=sha256:7021c14b0102abac385179a2cd7d345011297639bf8f3f004ea6ff211b35d75a
```

实现提交 Candidate CLI：

```text
WP040_M1_PLATFORM_COMPOSITION_PASS checks=34 failed=0
MANIFEST=sha256:56baed52111b40b9d78cd1426b94b3e5f2a38f00a8272f18373026da1639e7fc
REPORT=sha256:79e71d100d9454982555aa54ade40f566c00b869a04084f067c09759762c0204
```

完整命令结果见
`tests/integration/evidence/WP-040-a4-PROOF.json`。

## 安全与失败路径

- S3/S5/S4 越权路径、S7 产品路径、S1 final 非 S1/S7 路径均失败关闭。
- Final 缺少精确 `--s7-head` 会拒绝执行；Candidate 与 Final 保留各自分支
  身份校验和祖先校验。
- Workspace 精确路径规则不会把 `uv.lock.backup` 当作 `uv.lock` 授权。
- 高置信 Private Key、AWS、OpenAI 和 GitHub Token 模式均有负例。
- Platform 与 S4 黑盒继续覆盖跨租户、双主体、审批篡改、Obligation、
  工具旁路、重复写、`UNKNOWN`、回读和机器时间线失败关闭。
- 跨租户成功、重复逻辑写入和真实 Secret 泄漏均为 0。

## 已知问题与 Advisories

- `P2`：`make acceptance` 仍未实现；不能宣称发布验收或 120/36 数据集完成。
- `P2`：若把 Ruff 扩到未注册的旧 S4
  `packages/evaluation/**`、`packages/observability/**` 和对应旧 Acceptance
  测试，会得到 26 个既存 Findings。它们不在 M1 变更范围或 14 包 Workspace
  内，不阻断本候选；建议由 S4 后续统一关闭。
- `P2`：Compose 仍只自动挂载 `0001`；本轮再次手工重复应用 `0002`。
- `P2`：Audit/Security Draft 的最终 Stream、sequence、integrity 与租户
  绑定仍需可信 Sink/Store。
- `P3`：Wheel 临时目录
  `C:/Users/Administrator/AppData/Local/Temp/flowpilot-wp040-a4-60fb1885e13c4cc3bb266315fdad9b73`
  不在仓库内；本地执行策略拒绝递归删除，未影响 Git 候选。

## 学习候选

```text
LEARNING_CANDIDATE=固定候选复算必须从目标 Git Revision 读取字节
MATURITY=VERIFIED
TRIGGER=M1 快进后，历史 M0 Verifier 虽固定了 Head，却从当前 checkout 读取 Workspace/Lock，导致原 36/36 回归失败
MECHANISM=提交身份固定但文件读取来源未固定，会让历史证据随当前工作树演进而漂移，并破坏原 Manifest/Report Hash
STRUCTURE=所有历史候选文件通过 git show <revision>:<path> 读取；checkout 身份只在显式 Candidate CLI 校验
EVIDENCE=scripts/integration/verify_wp040.py；tests/integration/test_wp040_composition.py；M0 原两 Hash 与 M1 34/34 同时通过
RESIDUAL_RISK=新增静态检查若再次直接读取当前文件系统，仍可能复发；Review 应检查每个证据字段的数据来源
TARGET=docs/team/INTEGRATION_GATES.md
```

## 接收会话下一步

1. 核验最终 NEW_HEAD、Handoff/Proof Hash、S7 路径范围、工作树洁净度、
   ContractSet 与 `31f4b8b` 祖先关系。
2. 在 S1 final 分支形成待验 Head 后运行：

   ```text
   python scripts/integration/verify_wp040.py --repo . \
     --phase M1_PLATFORM_S1_FINAL \
     --s7-head <S7_NEW_HEAD> \
     --target-head <S1_FINAL_HEAD>
   ```

3. 独立复算产品树、Contracts、输入 Head、Lock、Migration、34 项 M1
   静态清单及关键动态门禁；S1 保留接受、集成与发布裁决。
4. 到达 final gate 后设置 `USER_GATE_REQUIRED=yes`，停止自动链并等待用户。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M1-PLATFORM-01
STEP_ID=M1-PLATFORM-05-S7
ATTEMPT_ID=WP-040-a4
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=31f4b8b14150bd769910f144d9116578be6124ad
CONTRACT_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
GATE=PASS
HANDOFF=tests/integration/evidence/WP-040-a4-HANDOFF.md
NEXT_ROLE=S1-ARCH
NEXT_ATTEMPT_ID=none
ESCALATE_TO_S1=yes
```

## 可回滚方式

- S7 的实现提交与 Handoff 提交可由 S1 按逆序 `git revert`；禁止
  reset/rebase。
- 本 Attempt 没有持久外部写入；隔离 Compose 项目已 `down -v`，容器与
  Volume 均为 0。
