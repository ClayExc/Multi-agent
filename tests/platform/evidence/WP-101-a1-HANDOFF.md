# WP-101-a1 S3-PLATFORM Handoff

## 基本信息

- Work Package：WP-101
- Attempt ID：WP-101-a1
- Chain ID：CHAIN-M9-GOVERNANCE-01
- Step ID：M9-01-S3-POLICY
- 责任会话：S3-PLATFORM
- 接收会话：S3-PLATFORM（同一 Worktree 热继续 WP-102）
- 交接策略：CONSUMER_GATE
- 功能 ID：FP-SEC-004、FP-APR-002、FP-APR-003
- 基线提交：`cd1ad2735157afa153799eaa911a2868c301ee7c`
- 分支/最终提交：`codex/s3/wp-101-m9-policy` / `<this-handoff-commit>`
- ContractSet 摘要：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：完成

## 完成内容

- 新增 `flowpilot.policy-adapter.m9.v1` 内部 Port：不可变 Rego Bundle 同时绑定代码、
  数据和 RFC 8785 摘要；Pinned Digest 开发验证器不冒充生产 OPA 信任系统。
- 新增线性本地发布/回滚控制面。发布使用 expected-current CAS；历史版本不可重新
  使用，回滚复制已验证内容但必须生成新版本，从而不复活旧决定或旧审批。
- 只缓存已验证的活动 Bundle 和短时不可变决定；发布/回滚会原子清空旧版本缓存，
  `resolve` 每次确认决定仍属于当前活动版本。
- OPA 只执行 Rego 并返回封闭规则结果。宿主构造 tenant、task、SecurityContext Ref +
  Hash、Agent、action digest、Tool Schema Hash、resource、purpose、classification、risk、
  environment fingerprint、policy version、Bundle digest 和 expires_at；全部进入输入原像并
  由公共 `PolicyDecision.input_hash` 绑定。
- 多规则结果执行确定性 deny-overrides；`deny > require_approval > allow`。未知、冲突、
  缺失或扩展结果、未知 Obligation、OPA 异常、未验证/撤销 Bundle 全部失败关闭。
- 保留现有 SoD、当前角色复验、action/policy/approval 三侧版本与过期绑定；OPA 和模型
  输出不能写入 Task、审批或执行状态，也不能覆盖这些验证。

## 未完成与非目标

- 未实现 Capability、SecretProvider、Gateway DLP；由同链 WP-102 热继续。
- 未实现生产 OPA、企业 Bundle 签名/分发或 Web 管理写面。
- 未修改公共契约、数据库、Migration、Compose、根依赖或锁文件。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/policy/src/flowpilot_policy/control_plane.py` | Bundle、OPA Port、发布/回滚、验证缓存、决策发行 | S3 |
| `packages/policy/src/flowpilot_policy/errors.py` | 内部策略生命周期稳定错误码 | S3 |
| `packages/policy/src/flowpilot_policy/__init__.py` | 导出 M9 Policy Port | S3 |
| `packages/policy/README.md` | 记录边界与不变量 | S3 |
| `tests/platform/test_versioned_policy.py` | 正常、边界、失败与安全回归 | S3 |
| `tests/platform/evidence/WP-101-a1-HANDOFF.md` | 本交接证据 | S3 |

## 契约、数据库与配置变化

- 契约版本：无变化；`contracts/**` 差异为 0。
- Migration：无。
- 环境变量：无。
- 依赖/锁：无；`pyproject.toml`、`uv.lock` 差异为 0。
- 兼容性：保留 `flowpilot.policy-adapter.m0.v1`；M9 使用新增内部 Port 版本，不扩展
  公共 `PolicyDecision v1`。Bundle 摘要等新增绑定通过受信输入原像和 `input_hash`
  表达。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| WP-101 定向 Policy/Gateway/SoD/恢复 pytest | PASS | 61 passed |
| `pytest tests/platform -q` | PASS | 403 passed |
| Makefile `test-security` 的等价权威 pytest 命令 | PASS | 252 passed |
| 影响范围 Ruff | PASS | All checks passed |
| `mypy --strict packages/policy/src` | PASS | 6 source files |
| `python contracts/conformance/validate.py` | PASS | 20 schemas / 35 cases / 43 semantic / 21 manifest / 10 review attestations / 52 features |
| `pytest tests/experience/test_secret_scan.py -q` | PASS | 2 passed |
| `make test-security` | ENV_BLOCKED | 当前 PowerShell 未安装 `make`；已读取 Makefile 并精确执行该 target 唯一命令，252 passed |

- 测试选择：使用工程控制面生成
  `.flowpilot-engineering/m9/wp101-test-selection.json` 与
  `.flowpilot-engineering/m9/wp101-attempt-report.json`；选择信号为 package/security
  change，执行定向 Policy、完整 Platform、一次共享 Security、Contract、Ruff、Mypy
  和 Secret Scan。按链授权未执行 Compose、全仓或 Release。
- Capsule 初始文件：6 个，规范化摘要复算与声明完全相同。
- Capsule 范围扩展：
  - `unresolved_dependency`：读取 `packages/engineering-control/**` 直接相关实现，以正确
    复算自引用 Capsule 摘要并使用 tests select/attempt report。
  - `unresolved_dependency`：读取现有 `packages/policy/**`、相关 domain/tool-contracts
    签名和 Platform policy/Gateway/SoD/recovery 测试。
  - `unresolved_dependency`：读取 `docs/team/HANDOFF_TEMPLATE.md` 生成本证据。

## 安全与失败路径

- 已验证负向路径：未固定/篡改 Bundle、发布 CAS 冲突、撤销版本、错 tenant/context/
  purpose/agent、越级 classification、缺 risk/environment digest、未知 Obligation、OPA
  额外字段、OPA timeout、模型伪造 allow、deny 多结果顺序、旧决定失效。
- 所有受信输入拒绝发生在 OPA 调用前；OPA 失败不会产生或缓存决定，原始异常标记不
  出现在稳定错误中。
- Secret/PII 检查：Secret Scan 2 passed；未记录真实策略、Token、PII、危险输入或
  原始异常。
- 未验证风险：生产 OPA/Bundle 信任与持久化发布存储不在 M9 本地范围内。

## 已知问题

- `make` 在当前 PowerShell 不可用；底层权威命令已精确执行并通过，不影响产品门禁。

## 已知事实与避免重复

- `KNOWN_FACTS`：M9T WP-090～094 已合入并由 S1 复算；现有公共 PolicyDecision、PEP、
  ApprovalVerifier 可复用；ContractSet 不变。
- `DO_NOT_RECHECK`：未重跑 WP-094、M8 Keycloak/RLS/恢复、Compose、全仓或在线 Provider。
- `FAILURE_SIGNATURES`：`MAKE_COMMAND_NOT_FOUND_WINDOWS`（入口环境缺失，底层命令 PASS）。
- `REUSED_DECISIONS`：`LOCAL_GOVERNANCE_CONTROL_PLANE.md` 的输入权威、deny-overrides、
  新版本回滚与 OPA 状态边界。
- `DUPLICATE_WORK_AVOIDED`：复用 M0 PEP/Approval 与 M9T 证据，不重建公共契约。

## 学习候选

```text
LEARNING_CANDIDATE=Rollback must mint a new policy version
MATURITY=IMPLEMENTED
TRIGGER=回滚到历史 Bundle 内容时，旧决定和旧审批可能随原版本重新激活
MECHANISM=若版本名可重新绑定或直接恢复，旧 policy_version 绑定无法区分新激活世代
STRUCTURE=Bundle 内容摘要可复用，但线性回滚必须创建唯一新版本并失效全部旧缓存
EVIDENCE=tests/platform/test_versioned_policy.py::test_publish_and_rollback_form_linear_unique_version_history
RESIDUAL_RISK=未来持久化仓库仍需数据库 CAS 与唯一约束
TARGET=ENGINEERING_PLAYBOOK policy lifecycle candidate
```

## 子 Agent 使用摘要

```text
SUBAGENTS_USED=1
SUBAGENT_MODES=READ_ONLY_PARALLEL
SUBAGENT_TASKS=wp101_policy_audit
SUBAGENT_WRITERS=0
PARENT_REPRODUCED_RESULTS=yes
REUSED_DECISIONS=public-v1-via-input-hash;rollback-new-version;deny-overrides
DUPLICATE_WORK_AVOIDED=1
```

## 接收会话下一步

1. S3 在同一 Worktree 热继续 WP-102，不回流 S1。
2. WP-102 在 Gateway 的 ledger/upstream 前接入 Capability、SecretProvider 与集中 DLP。
3. S2 在 WP-103 消费本 Port 时必须让策略版本和受信输入由宿主提供，不能让模型或
   OPA 返回权威绑定字段。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M9-GOVERNANCE-01
STEP_ID=M9-01-S3-POLICY
ATTEMPT_ID=WP-101-a1
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=cd1ad2735157afa153799eaa911a2868c301ee7c
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS_WITH_MAKE_ENTRYPOINT_ENV_ADVISORY
HANDOFF=tests/platform/evidence/WP-101-a1-HANDOFF.md
NEXT_ROLE=S3-PLATFORM
NEXT_ATTEMPT_ID=WP-102-a1
ESCALATE_TO_S1=no
SUBAGENTS_USED=1
```

## 可回滚方式

- revert 本 WP-101 提交；不要 reset、rebase 或 force-push。回滚会移除 M9 Policy Port，
  但保留 M0 公共 PolicyDecision/PEP/Approval 行为。
