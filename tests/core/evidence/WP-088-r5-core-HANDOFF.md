# WP-088-r5 S5-CORE Keycloak OIDC 运行时组合交接

## 基本信息

- Work Package：WP-088-r5-core
- Attempt ID：WP-088-r5-core
- Chain ID：`CHAIN-M8-IDENTITY-TENANCY-01`
- Step ID：`M8-05J-S5-OIDC-IMPLEMENTATION-HANDOFF`
- 责任会话：`S5-CORE`
- 接收会话：`S1-ARCH`
- 交接策略：`S1_GATE`
- 功能 ID：`FP-SEC-001`、`FP-EXP-001`
- 基线提交：`ebcb1b06c14b476c6eddd732a3c4c74df9e0aa63`
- 分支/最终提交：`codex/s5/m8-api-identity` / 本文件所在提交
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 输入 Handoff：`tests/platform/evidence/WP-088-r4-security-HANDOFF.md`
- 输入 Handoff SHA-256：
  `sha256:2251c1eca32e6b52f16e30e4695499767927c44726f316b3cb2a5063ec0d7d94`
- 状态：部分完成；S5 生产者实现完成，等待 S4 消费者 Fixture 迁移

## 完成内容

- 将 OIDC code exchange 改为显式 `id_token`、`access_token`、`refresh_token`
  Triplet；HTTP Provider 不再构造或返回可信 Identity。
- BFF callback 只调用 S3 `verify_user_token_pair`，refresh 只调用
  `verify_user_refresh`；Token 签名、Claims、nonce、`at_hash`、身份映射和 refresh
  lineage 全部保持在 S3 验证边界。
- 新增锁保护的本地 `RefreshLineageGuardPort` 实现，只保存 Session Identity、Access
  Token、JTI 的 SHA-256 摘要、`iat` 和 generation。`establish` / CAS 原子拒绝重复、
  历史 Token/JTI、旧 generation、错误当前值和 `iat` 回退；同秒合法轮换可推进。
- 在访问 IdP 前原子 claim 浏览器 Session，保证并发 refresh 最多一个请求调用 IdP；
  claim 后任意失败都失效本地 Session、撤销上下文和已知 Refresh Token，不重用已消费
  Token。并发 loser 不清理 winner 的在途状态。
- 新增严格 Keycloak OIDC HTTP/JWKS Adapter：固定 issuer/origin，Authorization Code +
  PKCE S256，token/refresh/revoke 表单，禁重定向、禁环境代理、固定 timeout、响应大小、
  JSON content-type/content-encoding、同源 discovery endpoint 与 JWKS key 上限；所有错误
  稳定脱敏且无自动重试。
- 新增默认和显式本地 composition。零 OIDC 配置继续 fail-closed 未配置；仅完整、合法
  环境配置才原子配对 BFF 与 Cookie-only RequestSecurity。模块 import 不访问网络。
- API wheel 增加运行时 `httpx>=0.28,<1` 并更新 `uv.lock`。用途为异步 OIDC/JWKS HTTP；
  许可证 BSD-3-Clause；替代方案为标准库 `urllib` 或 `aiohttp`；主要攻击面为代理泄密、
  SSRF、重定向、响应炸弹与上游错误泄漏，均由 Adapter 显式关闭或限制。

## 未完成与非目标

- 未修改 S4 路径。既有
  `tests/acceptance/m8/test_identity_tenancy_composition.py` 仍使用已移除的单 Token、
  Provider 预验证 Identity Fake，需要消费者在本 S5 API Head 上迁移。
- 未宣称全仓 PASS、WP-088 最终 PASS、M8 Release/Freeze 或 Feature 提升。
- 未实现多实例 RefreshLineageGuard、S6 持久 Guard、RP `end_session`、生产 IdP 运维、
  Compose/RLS 或远程 Trace。
- 禁止以 S5 兼容回退恢复 `user_token` 或 `OidcRefreshResult(identity=...)`；这会重新合并
  ID/Access Token 语义或绕过 S3 verifier。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `apps/api/src/flowpilot_api/oidc.py` | Triplet、S3 verifier 接线、原子 Session claim/rotation、本地哈希化 lineage | S5 |
| `apps/api/src/flowpilot_api/keycloak.py` | 严格 Keycloak discovery/authorize/token/refresh/revoke/JWKS Adapter | S5 |
| `apps/api/src/flowpilot_api/bootstrap.py` | 默认/显式本地 OIDC composition 与 fail-closed env loader | S5 |
| `apps/api/src/flowpilot_api/composition.py`、`main.py`、`__init__.py` | 原子 bundle 注入、默认启动与导出 | S5 |
| `apps/api/pyproject.toml`、`uv.lock` | API 运行时 httpx 依赖闭包 | S5 / 本 WP 单写者 |
| `tests/core/test_oidc_api.py` | Triplet、同秒、并发、失败清理与 lineage CAS | S5 |
| `tests/core/test_keycloak_oidc.py` | HTTP、SSRF、JWKS、错误、大小、重定向、轮换和 Secret 负例 | S5 |
| `tests/core/test_oidc_bootstrap.py` | 零/部分/完整配置、import 零网络、真实签名 Token Pair 与同秒 refresh 组合 | S5 |
| `tests/core/evidence/WP-088-r5-core-HANDOFF.md` | 本交接 | S5 |

## 契约、数据库与配置变化

- 契约版本：无变化；Contract content digest 保持
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`。
- Migration / PostgreSQL / Redis：无变化。
- 环境变量：运行时读取 `FLOWPILOT_OIDC_ISSUER`、`FLOWPILOT_OIDC_CLIENT_ID`、
  `KEYCLOAK_WEB_CLIENT_SECRET`、`FLOWPILOT_OIDC_REDIRECT_URI`、
  `FLOWPILOT_OIDC_ALLOW_INSECURE_LOOPBACK`；可选 timeout、response-size、post-login path
  和 purpose。全无保持未配置，部分或非法配置固定启动失败且不回显值。
- 依赖：API runtime 新增已锁定的 `httpx>=0.28,<1`；根 dev group 原已包含 httpx，未
  引入新的解析、JWT 或 Provider SDK。
- 兼容性：S5 内部 Python Port 从含糊单 Token/预验证 Identity 提升为显式 Token
  Triplet 和 S3 token-pair/refresh verifier。跨进程 Contract 不变；旧测试 Fake 必须迁移，
  不提供不安全兼容层。

## 验证

| 命令 / 门禁 | 结果 | 证据 |
|---|---|---|
| OIDC BFF + HTTP/JWKS + bootstrap + product composition 定向 | PASS | 51 passed |
| Core + S3 Identity | PASS | 360 passed |
| Shared Security closure | PASS | 283 passed |
| Contract Conformance | PASS | 20 schemas / 35 cases / 43 semantic negatives / 52 features |
| Workspace Ruff | PASS | All checks passed |
| Makefile 同源 strict Mypy | PASS | 137 source files |
| `uv sync --all-packages --all-groups --locked` / `uv lock --check` | PASS | 168 resolved / 165 checked |
| API wheel | PASS | `flowpilot_api-0.1.0-py3-none-any.whl`；含 bootstrap/keycloak，METADATA 含 httpx runtime |
| 全仓 pytest（唯一一次） | FAIL | 1515 passed / 3 deterministic S4 stale-fixture failures / 1 explicit online skip |

全仓三项失败均在 S4 所有路径
`tests/acceptance/m8/test_identity_tenancy_composition.py`：旧 Fixture 仍调用
`OidcCodeExchange(user_token, refresh_token)`、`OidcRefreshResult(identity,
refresh_token)`、`verify_user_token` 和带 `now` 的 Provider refresh。它们在新的安全 API
Head 上确定性返回 callback 503。该签名与此前 S4 瞬时 POST 503 P2 不同；没有把精确
失败冒充通过，也没有按 `NO_RETEST` 再次运行全仓。

## 安全与失败路径

- 已验证负向路径：state/nonce/PKCE、issuer/audience/azp/expiry、Token Pair、refresh
  lineage、同秒并发、历史/重复/旧 generation、Session claim、Refresh Token rotation、
  跨 origin/port/scheme、userinfo/query/fragment、redirect、timeout、4xx/5xx、错误
  content-type/encoding、畸形/超限 JSON、重复 JWKS kid、Cookie-only 和身份 Header 伪造。
- 失败清理：Provider、verifier、lineage、Context 或 Session commit 失败均不发布可用新
  Session；旧和已知新 Refresh Token best-effort revoke，旧 Session 不恢复。
- Secret/PII：client secret 只进入服务端 form；Token/code/verifier 不进入 repr、API
  错误、redirect、Cookie 值之外的浏览器响应或日志。高置信凭据扫描在提交前为 0。
- 未验证风险：真实 Keycloak 网络与生产 TLS/证书仍由后续 S7 获权组合门禁验证；本地
  Guard 仅适用于单进程，Port 没有 rollback，因此 callback store/CAS 后 commit 失败可
  留下 fail-closed orphaned lineage，不会发布 Session。

## 已知问题

- `P1_CONSUMER_FIXTURE_STALE`：S4 M8 acceptance Fake 未迁移新安全 API，导致全仓三项
  确定性失败。修复属于消费者迁移，不是 S5 产品语义返修。
- 在线 Provider smoke 的一项 skip 需要显式
  `FLOWPILOT_ENABLE_ONLINE_PROVIDER_SMOKE=1`，未冒充通过。

## 已知事实与避免重复

- `KNOWN_FACTS`：S3 WP-088-r4 lineage Handoff SHA 精确匹配；Contract、Migration 和
  Keycloak Realm 未变；S5 定向、Security、Ruff、Mypy、lock 和 wheel 已通过。
- `DO_NOT_RECHECK`：不得再次运行全仓或重复已通过门禁；不得为旧 S4 Fixture 增加 S5
  单 Token/预验证 Identity 兼容层；不得重跑已知 S4 历史 P2 调查。
- `FAILURE_SIGNATURES`：S4 acceptance `_Provider` / `_Verifier` 旧方法签名导致 callback
  503；精确 3 failures、1515 pass、1 explicit skip。
- `REUSED_DECISIONS`：ADR-0005、WP-082、WP-083、WP-088-r2/r4、S1
  `COMMIT_PRODUCER_BEFORE_CONSUMER_FIXTURE`。
- `DUPLICATE_WORK_AVOIDED`：复用 S3 Token Pair/Lineage 验证结论和 S4 既有验收观察；
  未复制 JWT Claims 验证、未运行第二次全仓、未扩张 RP logout 或多实例存储。

## 学习候选

```text
LEARNING_CANDIDATE=OIDC refresh 必须在访问 IdP 前原子 claim 本地 Session
MATURITY=VERIFIED
TRIGGER=两个并发请求可在末端 Session rotate 之前同时发送同一个一次性 Refresh Token
MECHANISM=仅在 Provider 返回后做 CAS 无法阻止上游重复消费；loser 清理还可能撤销 winner 的在途状态
STRUCTURE=ACTIVE→REFRESHING 原子 claim→S3 lineage CAS→ACTIVE(new) commit；claim loser 零清理，claim 后失败永久失效
EVIDENCE=tests/core/test_oidc_api.py concurrent-at-most-one / failure cleanup；51 targeted passed
RESIDUAL_RISK=多实例 claim/lineage 需要 S6 权威持久实现
TARGET=ENGINEERING_PLAYBOOK OIDC refresh/session lineage candidate
```

## 子 Agent 使用摘要

```text
SUBAGENTS_USED=2
SUBAGENT_MODES=READ_ONLY_PARALLEL
SUBAGENT_TASKS=r5-http-review,r5-lineage-review
SUBAGENT_WRITERS=0
PARENT_REPRODUCED_RESULTS=yes
REUSED_DECISIONS=WP-088-r2,WP-088-r4,S1-COMMIT_PRODUCER_BEFORE_CONSUMER_FIXTURE
DUPLICATE_WORK_AVOIDED=5
```

## 接收会话下一步

1. S1 核验 S5 提交、Handoff Hash、Contract digest、授权路径和 clean。
2. 由 S4 或 S1 精确授权迁移三项旧 acceptance Fake 到 Token Triplet、
   `verify_user_token_pair` / `verify_user_refresh` 和无 `now` Provider refresh。
3. 消费者只精确复跑原三项失败；除非 S1 明确覆盖 `NO_RETEST`，不得第二次运行全仓。
4. 三项通过后由 S1 决定后续 S7 组合时机；本 S5 Step 不直接唤醒 S4/S7。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M8-IDENTITY-TENANCY-01
STEP_ID=M8-05J-S5-OIDC-IMPLEMENTATION-HANDOFF
ATTEMPT_ID=WP-088-r5-core
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=ebcb1b06c14b476c6eddd732a3c4c74df9e0aa63
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=FAIL
HANDOFF=tests/core/evidence/WP-088-r5-core-HANDOFF.md
NEXT_ROLE=S1-ARCH
NEXT_ATTEMPT_ID=none
ESCALATE_TO_S1=yes
SUBAGENTS_USED=2
```

## 可回滚方式

- `git revert` 本 S5 提交；禁止 reset、rebase 或 force-push。回滚会恢复 WP-083 的旧
  单 Token/Provider 预验证 Identity seam，并重新打开真实 Keycloak 不兼容和同秒 refresh
  错误拒绝问题。
