# WP-088-r2 S3-PLATFORM OIDC Token Pair 安全交接

## 基本信息

- Work Package：WP-088-r2-security
- Attempt ID：WP-088-r2-security
- Chain ID：CHAIN-M8-IDENTITY-TENANCY-01
- Step ID：M8-05D-S3-OIDC-TOKEN-PAIR-FINAL
- 责任会话：S3-PLATFORM
- 接收会话：S1-ARCH
- 交接策略：S1_GATE
- 风险：R3
- 功能 ID：FP-SEC-001
- 原始基线：`4617e833bc6a9af3eec6eb04ab86ac1f68aa74ae`
- S4 修复输入：`87c5e4b35e5d41b72035e9818cd40c301b71cc31`
- 分支：`codex/s3/m8-identity-security`
- 最终提交：本文件所在提交；精确 SHA 由交接结果返回
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：完成；`PASS_HANDOFF`

## DELTA、恢复与消费者门禁

- `CONTEXT_MODE=DELTA`；只读现有 Identity 实现/测试、S5 WP-083 P1 证据和
  `tests/data/integration/verify_keycloak.py` 的 callback/refresh 相关片段。
- 初始工作树 clean，S3 Head 是精确基线 `4617e833...`；ContractSet 摘要匹配。
- 首次唯一全仓回归发现输入基线的 S4 Fixture 漂移：旧 M7 测试仍向 cookie-only
  `LiveBackend` 传 `tenant_id`。S3 按 P1 停链，没有越权修改 Web/Acceptance。
- 恢复前 S3 dirty 补丁仅包含 Security/Platform 路径；`git diff --binary` SHA-256 为
  `sha256:c1b0e00c34213a79605d6936c0a08899e12fc15be98d2412cc23b3c933b07b7f`。
- 未 stash/reset/rebase/checkout；只用 `git merge --ff-only 87c5e4b...` 消费 S4 修复。
  消费后 S3 补丁二进制 Hash 完全相同，dirty 路径仍只有 S3 授权文件。
- S4 文件 `tests/acceptance/m7/test_web_live_blackbox.py` Hash 精确为
  `sha256:239d4ac284aba55a8f89d4bb5b2a5b78efea214e459b7da2843ba77786b2e1f5`，
  保持独立祖先，不进入本 S3 提交差异。

## 完成内容

- `UserClaimPolicy` 新增独立 ID Token Policy：ID Token 使用 Web Client audience，
  Access Token 使用 API audience；issuer 与 authorized party 必须一致，audience 必须
  不同，防止 token swap。
- 新增 `UserTokenPairVerifierPort` 和 `verify_user_token_pair(...)`。S5 可显式传入
  `id_token + access_token + expected_nonce`，无需自行 decode Claim 或拼接身份。
- Callback 分别验证 ID/Access Token 的签名、issuer、audience、azp、时间与 JWK；nonce
  只从 ID Token 校验并经服务端预登记 Port 原子消费。
- Callback 精确绑定 `iss/sub/azp/sid`，并按 ID Token 的实际 JWS 算法计算 `at_hash`：
  支持已允许的 SHA-256/384/512 系列，比较使用 constant-time。
- `VerifiedUserIdentity` 的 tenant、role、scope、assurance、issued/expires 全部只由受信
  Access Token Claim 映射；ID Token 中同名伪造 Claim 不参与授权。`token_hash`/Context
  source hash 指向 Access Token，而非 ID Token。
- 新增 `verify_user_refresh(...)`：验证 rotated Access Token，不消费登录 nonce；精确绑定
  前一身份的 issuer、subject、authorized party、tenant 与 session hash。
- Refresh 允许新签名 Access Token 更新 roles、scopes、assurance 和有效期，但要求 Token
  hash 变化且 `iat` 严格前进，从而拒绝当前或历史 Access Token。
- Refresh ID Token 为可选；若存在，必须按独立 ID Policy 验证、不得携带/复用旧 nonce，
  并以同样的 `iss/sub/azp/sid + at_hash` 绑定新 Access Token。
- 兼容 `verify_user_token(...)` 保留为“单 Access Token + 受信 expected nonce”的显式
  校验入口，并在 docstring 中声明它不是 Authorization Code callback API；既有失败关闭
  语义未放宽。

## 未完成与非目标

- 未修改 `apps/api/**`、`infra/**`、`contracts/**`、Keycloak Realm、HTTP Transport、
  默认 API composition、数据库、Migration、环境变量或根依赖。
- S5 后续只需消费新 Port/API；本 Attempt 不代替 S5 修改 callback/refresh 编排。
- 未运行真实 Keycloak、在线 IdP、生产凭据、远程 Trace 或付费调用。
- 本交接不启动后续步骤，不唤醒 S5，不声明 M8 Release/Freeze。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/security/src/flowpilot_security/identity.py` | Token Pair、at_hash、Access Identity、Refresh continuity | S3 |
| `packages/security/src/flowpilot_security/__init__.py` | 导出 User Token Pair Port | S3 |
| `tests/platform/test_identity_boundary.py` | callback/refresh 正常、边界、攻击与泄漏回归 | S3 |
| `tests/platform/evidence/WP-088-r2-security-HANDOFF.md` | 本正式交接 | S3 |

## 契约、数据库、依赖与配置变化

- ContractSet / JSON Schema：无变化；Conformance PASS。
- Database / Migration / PostgreSQL / Redis：无变化。
- Keycloak Realm / 环境变量 / HTTP Transport：无变化。
- 根 Workspace / `uv.lock` / Makefile / 包依赖：无变化。
- 兼容性：公共跨进程 Contract 不变；Security 内部 API 兼容新增。旧单 Token 入口未被
  用作标准 callback，新消费者应使用 `UserTokenPairVerifierPort`。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| 原失败 `test_web_live_blackbox.py::test_live_web_uses_server_tenant_and_preserves_sse_resume` | PASS | 1 passed |
| Identity 定向 | PASS | 47 passed；原 24 + 新 23 |
| Shared Security | PASS | 240 passed |
| Contract Conformance | PASS | 20 schemas / 35 cases / 43 semantic / 52 features |
| 全仓 Ruff | PASS | All checks passed |
| Makefile 同源 strict Mypy | PASS | 135 source files |
| 恢复后授权的唯一最终全仓 pytest | PASS | 1475 passed, 1 skipped |
| `git diff --check`、路径、Contract tree | PASS | 仅 S3 WRITE_SCOPE；Contract 零变化 |

唯一 skip：`tests/runtime/integration/test_m7_provider_online_smoke.py` 需要显式
`FLOWPILOT_ENABLE_ONLINE_PROVIDER_SMOKE=1`；与本 Attempt 无关，未冒充通过。

## 安全与失败路径

- Callback：覆盖缺 ID/Access Token、token swap、错签名、issuer、ID client audience、
  API audience、azp、sub、sid、at_hash、nonce 错误与 nonce replay。
- `at_hash` 正常路径以 RS384 ID Token 验证，证明不是固定 SHA-256；实现同时支持允许的
  SHA-256/384/512 JWS family。
- Access Identity：ID Token 注入 tenant/role/scope 不影响最终 Identity；source hash
  精确等于 Access Token SHA-256。
- Refresh：覆盖 roles/scopes/expires 更新、无 ID Token、标准 nonce-less ID Token、
  refresh ID Token 复用 nonce、错 at_hash、跨用户、跨租户、跨 session、当前 Token 与
  历史 Access Token。
- 泄漏：错误 `str/repr` 与捕获日志均不含 ID Token、Access Token 或 nonce；返回对象只
  保存不可逆摘要。

## 已知风险

- Refresh continuity 要求新 Access Token `iat` 严格大于当前身份的 `iat`。这会在 IdP
  同一秒重复签发时安全失败；调用方不得放宽为 `>=`，应等待/重试 IdP refresh 或使用能
  提供确定性单调签发语义的 Provider 组合。
- 真实 Keycloak Token Pair/Refresh 的网络组合仍需 S5/S7 在其 Owner 路径消费新 API；
  本 Attempt 只验证 Security 内核和确定性 RSA/JWK Fixture。

## 已知事实与避免重复

- `KNOWN_FACTS`：S4 修复为独立祖先；S3 补丁 Hash 在 ff-only 前后不变；ContractSet
  未变化。
- `DO_NOT_RECHECK`：M7 历史、完整 README、Keycloak Realm、S5 BFF 非相关路径、在线
  Provider；全仓只在恢复后按授权运行一次最终门禁。
- `FAILURE_SIGNATURES`：旧 M7 test 向 cookie-only `LiveBackend` 传 `tenant_id` 会在
  构造阶段 TypeError；已由 S4 `87c5e4b...` 关闭。
- `REUSED_DECISIONS`：ADR-0005、WP-082 Identity Boundary、WP-083 BFF Handoff、S4
  修复授权。
- `DUPLICATE_WORK_AVOIDED`：未把旧全仓成功项作为调查重跑；恢复后只重跑原失败 Case
  和规定门禁。

## 学习候选

```text
LEARNING_CANDIDATE=OIDC callback 的身份来源必须分离 ID Token 与 Access Token
MATURITY=VERIFIED
TRIGGER=单 Token 验证无法同时表达 client audience/nonce 与 API audience/authorization claims
MECHANISM=把 ID 与 Access Token 语义合并会允许调用方自行 decode/拼接身份，并缺失 at_hash swap 绑定
STRUCTURE=独立 Token Policy + nonce on ID Token + iss/sub/azp/sid + algorithm-derived at_hash + Access-only identity mapping
EVIDENCE=packages/security/src/flowpilot_security/identity.py；tests/platform/test_identity_boundary.py；47 identity / 240 security / 1475 full passed
RESIDUAL_RISK=真实 IdP 同秒 refresh iat 可能安全失败；由 Provider 组合验证，不放宽历史 Token 防护
TARGET=ENGINEERING_PLAYBOOK OIDC callback/refresh boundary candidate
```

## 子 Agent 使用摘要

```text
SUBAGENTS_USED=0
SUBAGENT_MODES=none
SUBAGENT_TASKS=none
SUBAGENT_WRITERS=0
PARENT_REPRODUCED_RESULTS=not-applicable
REUSED_DECISIONS=ADR-0005,WP-082,WP-083,S4-87c5e4b
DUPLICATE_WORK_AVOIDED=2
```

## 接收会话下一步

1. S1 核验最终 Head、Handoff Hash、clean、ContractSet、S4 独立祖先与 S3 范围。
2. S1 决定后续 S5/S7 消费时机；S3 不直接唤醒 S5。
3. 消费方使用 `verify_user_token_pair` / `verify_user_refresh`，不得自行 decode Token、
   从 ID Token 形成授权 Identity，或在 refresh 重新消费登录 nonce。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M8-IDENTITY-TENANCY-01
STEP_ID=M8-05D-S3-OIDC-TOKEN-PAIR-FINAL
ATTEMPT_ID=WP-088-r2-security
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=87c5e4b35e5d41b72035e9818cd40c301b71cc31
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/platform/evidence/WP-088-r2-security-HANDOFF.md
NEXT_ROLE=S1-ARCH
NEXT_ATTEMPT_ID=none
ESCALATE_TO_S1=no
SUBAGENTS_USED=0
```

## 可回滚方式

- revert 本 S3 提交；S4 修复 `87c5e4b...` 保持独立祖先，不随 S3 回滚。禁止 reset、
  rebase 或 force-push。
