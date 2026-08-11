# WP-083-a1 S5-CORE API/BFF OIDC 入口交接

## 基本信息

- Work Package：WP-083
- Attempt ID：WP-083-a1
- Chain ID：CHAIN-M8-IDENTITY-TENANCY-01
- Step ID：M8-02A-S5-API
- 责任会话：S5-CORE / `identity-api-builder`
- 接收会话：S1-ARCH
- 交接策略：S1_GATE
- 风险：R2
- 功能 ID：FP-SEC-001、FP-SEC-007
- 基线提交：`a1a0360153ec9f1ca1c9009056ae3ba483b2a22f`
- 实现提交：`137272cbc6ae9b2a24c381c6f958c5ad2bf36b61`
- 分支：`codex/s5/m8-api-identity`
- 最终提交：本文件所在提交；精确 SHA 由交接结果返回
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：完成

## 消费者门禁与复用

- 开始时 Head、Branch、clean、ContractSet 均精确匹配授权信封。
- 复用 WP-081 Keycloak Fixture PASS，不重跑实库：
  `tests/data/evidence/WP-081-a1-HANDOFF.md`，
  `sha256:72485f7ff01539489f3a8487a3006b7637c60c448eedb8ad7e45169f6af61fc4`。
- 复用 WP-082 S3 身份内核 PASS：
  `tests/platform/evidence/WP-082-a1-HANDOFF.md`，
  `sha256:5df11f4e26e943a3002f47c3b6e001d8d1ea65892fcce238631da09f7fd8d811`。
- 未重复执行 Keycloak 实库、S3 白盒生产者调查或 M7 在线 Provider；最终全仓和安全
  闭包仅用于验证本变更未破坏已汇合消费者。

## 完成内容

- 新增 API/BFF OIDC Authorization Code + PKCE 生命周期：登录发起、一次性回调、刷新
  轮换、登出与显式会话失效。
- state、nonce、PKCE verifier 和 Refresh Token 只进入服务端 Port；浏览器只接收
  `HttpOnly`、`SameSite`、生产默认 `Secure` 的 `__Host-` 不透明 Cookie。
- 登录事务在校验 state 前原子消费；回调重放、错 state、错 nonce、错 audience、过期
  身份和刷新重放均失败关闭。部分存储失败会撤销可信 Context，并尽力撤销 IdP Refresh
  Token，不向响应复制原始异常或 Token。
- 新增生产 `OidcRequestSecurity`：只从不透明 Cookie 解析服务器会话，再通过 S3
  `SecurityContextSource + SecurityVerifier` 解析和重验完整 `SecurityContextRef`。
- 浏览器 Bearer 与 tenant、subject、role、purpose、classification、Context override
  Header 被稳定拒绝；Command 正文中的 tenant/purpose/classification/role 自报不能覆盖
  受信 Identity，失败发生在 Intake/Repository/Execution 前。
- Task API 在认证/授权后才解析业务依赖；未认证请求不再通过 `503` 暴露配置状态。
- SSE 建连、每个事件和心跳前均重新授权；会话或 Context 撤销会关闭当前流，重连返回
  稳定 `401`，原 replay/tenant 隔离与 `Last-Event-ID` 语义未放宽。
- 新增稳定 API 错误码 `API_AUTHENTICATION_REQUIRED`、
  `API_AUTHENTICATION_INVALID`、`API_AUTHORIZATION_DENIED`、
  `API_AUTH_FLOW_INVALID`；响应只含安全固定文案。
- 根 Workspace 单写者收口 `flowpilot-api -> flowpilot-security`，`uv.lock` 现在精确记录
  S3 已声明的 `pyjwt[crypto]>=2.13,<3`；新增 `test-identity`，安全门禁纳入 Core BFF 与
  S3 Identity Boundary。

## 未完成与非目标

- 未修改 `contracts/**`、S3/S6 路径、Migration、RLS、Web、Graph、JWT/JWKS 内核或
  Keycloak 配置。
- 未实现生产 IdP 网络 Transport；`OidcProviderPort` 是唯一网络接缝。生产部署还需提供
  持久、原子、可多实例共享的 `OidcSessionStorePort`；仓库内仅提供确定性最小内存实现。
- 未启用公网 Tunnel、远程 Trace、在线 Provider、真实身份、生产凭据或付费调用。
- 本 Handoff 不声明 M8 Release/Freeze，也不替代 S1/S3/S4 的消费者验收。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `apps/api/src/flowpilot_api/oidc.py` | OIDC BFF Port、服务端事务/会话、轮换/撤销及组合 | S5 |
| `apps/api/src/flowpilot_api/security.py` | Cookie-only 生产 RequestSecurityPort 与可信 Context 重验 | S5 |
| `apps/api/src/flowpilot_api/app.py` | Auth 路由、Cookie 投影、Command/Task/SSE 可信入口 | S5 |
| `apps/api/src/flowpilot_api/models.py`、`errors.py` | 无 Token 响应与稳定 401/403 错误 | S5 |
| `apps/api/src/flowpilot_api/composition.py`、`__init__.py` | OIDC BFF/安全组合与内部 Port 导出 | S5 |
| `apps/api/pyproject.toml`、`uv.lock` | API 消费 S3 Security，闭合 PyJWT crypto 锁 | S5 shared-writer |
| `Makefile` | `test-identity` 与安全门禁身份闭包 | S5 shared-writer |
| `tests/core/test_oidc_api.py` | 正常、边界、失败、安全、轮换、撤销、重连与零泄漏 | S5 |
| `tests/core/test_api.py` | SSE 每事件重授权回归断言 | S5 |
| `tests/core/evidence/WP-083-a1-HANDOFF.md` | 本交接证据 | S5 |

## 契约、数据库、依赖与配置变化

- ContractSet / JSON Schema：无变化；Conformance PASS。
- Migration / PostgreSQL / Redis / RLS：无变化。
- 环境变量：无变化；没有提交 IdP URL、Client Secret、真实 Tenant 或凭据。
- API 内部兼容性：既有 `RequestSecurityPort` 保持；`TrustedRequestIdentity` 新字段均有
  安全默认值，既有测试 Fake 不受影响。公共跨进程 `SecurityContextRef v1` 未改变。
- 依赖用途：`flowpilot-api` 直接复用内部 `flowpilot-security` 的 OIDC Token 验证、可信
  Context 映射和撤销；没有复制 JWT 内核。
- 外部依赖与许可证：锁中 `PyJWT 2.13.0`，MIT；`crypto` extra 复用既有
  `cryptography` 闭包。
- 替代方案：Authlib、python-jose 或 API 自行解析 JWT 会引入第二套身份语义/依赖，故
  未采用；生产网络调用通过 `OidcProviderPort` 隔离。
- 攻击面：新增 OIDC redirect/code exchange 与服务端 Refresh Token 保存边界；通过
  HTTPS/loopback URL 限制、state/nonce/PKCE 一次性消费、issuer/azp/time 二次校验、
  opaque Secure Cookie、Context 每次重验、固定错误投影和 Token-safe repr 收敛。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| `make bootstrap/test/test-contract/test-security/test-identity` | ENV_BLOCKED | Windows 环境无 `make` 可执行文件；未冒充 PASS |
| `uv sync --all-packages --all-groups --locked` | PASS | 168 resolved / 165 checked |
| `uv lock --check` | PASS | lock current，168 packages |
| `uv run --all-packages --all-groups --locked python -B -m pytest tests/core/test_oidc_api.py tests/platform/test_identity_boundary.py` | PASS | 35 passed |
| `uv run --all-packages --all-groups --locked python -B -m pytest tests/core/test_oidc_api.py tests/core/test_api.py -q` | PASS | 31 passed |
| `uv run --all-packages --all-groups --locked python -B -m pytest` | PASS | 1385 passed / 1 explicit online skip |
| Makefile `test-security` 的等价 `uv ... pytest` 命令 | PASS | 204 passed |
| `uv run --all-packages --all-groups --locked python -B contracts/conformance/validate.py` | PASS | 20 schemas / 35 cases / 43 semantic / 52 features |
| Makefile `lint` 的 Ruff 命令 | PASS | All checks passed |
| Makefile `lint` 的 strict Mypy 命令 | PASS | 134 source files |
| `uv run --all-packages --all-groups --locked pip-audit --local --skip-editable --progress-spinner off` | PASS | 0 known vulnerabilities；editable internal packages skipped |
| `uv build --wheel apps/api --out-dir <system-temp>` | PASS | `flowpilot_api-0.1.0-py3-none-any.whl`；包含 `oidc.py` |
| `git diff --check`、授权路径、Contract tree | PASS | 仅 WP-083 WRITE_SCOPE；Contract 零变化 |

唯一测试 skip 是必须显式设置 `FLOWPILOT_ENABLE_ONLINE_PROVIDER_SMOKE=1` 的 M7 在线
Provider Smoke，本 Attempt 未把它描述为通过。

Acceptance 采用授权要求的 M7 既有事实，不作为 WP-083 新门禁重复复算。执行期间曾误触发
一次 `scripts/acceptance/run_acceptance.py`，只重现已知的 `24 PASS / 132
EXECUTOR_NOT_REGISTERED / gate=fail`；未发现新的失败签名。该命令生成的唯一 S4 目录
`artifacts/acceptance/run-20260811-132513` 已精确移出 Worktree，保存在系统临时隔离目录
`flowpilot-wp083-accidental-run-20260811-132513`，可恢复且未提交。

## 安全与失败路径

- 正常：login -> callback -> Cookie session；refresh 原子轮换；logout/explicit invalidate
  撤销服务器会话、可信 Context 和 Refresh Token。
- 边界：缺 state/code/cookie、错 state、已消费事务、刷新旧 Cookie、Context 仍有 Cookie
  但已撤销、SSE 撤销后重连。
- 失败：错 audience、过期身份、Provider/Context/Session 依赖失败映射为稳定
  `401/403/503`，原始异常不进入响应。
- 安全：Authorization 与身份 override Header、正文 tenant/role/purpose/classification
  伪造均失败关闭；拒绝发生在 Intake/Repository/Execution 前。
- Token 泄漏：Auth 响应、错误、repr、SSE 和仓库 Secret Scan 中原始 User Token、
  Refresh Token、Authorization Code 与 nonce 输出数为 0。
- 跨租户：Request tenant 只来自已验证 Context；Command 正文跨租户伪造返回 403，
  Task/SSE 只使用该受信 tenant。

## 已知问题

- 生产 IdP Transport 和多实例原子 Session Store 是后续部署组合责任；本 Attempt 只提供
  Port、BFF 状态机、生产请求安全适配器和最小内存 Fixture。
- M7 Acceptance 仍按项目基线为 24/156 产品 Case 通过，`RELEASED=false`、
  `FROZEN=false`；与 WP-083 无因果关系。

## 已知事实与避免重复

- `KNOWN_FACTS`：WP-081/WP-082 Handoff Hash 可复算且 PASS；ContractSet 未变；S3
  Identity Boundary 已验证算法/JWKS/Claim/nonce，S5 只做 BFF 黑盒与消费者组合。
- `DO_NOT_RECHECK`：Keycloak 实库、S3 白盒生产者结论、M7 24 个产品执行器与 132 个
  显式未实现 Case、在线 Provider。
- `FAILURE_SIGNATURES`：未认证请求若先解析业务依赖会错误返回 `503` 并泄露配置状态；
  已改为 authenticate/authorize 在依赖解析之前，回归为稳定 `401/403`。
- `REUSED_DECISIONS`：ADR-0005、IDENTITY_TENANCY、WP-081、WP-082。
- `DUPLICATE_WORK_AVOIDED`：3 组（Keycloak 实库、S3 身份内核、M7 历史产品 Case）。

## 学习候选

```text
LEARNING_CANDIDATE=认证必须先于业务依赖可用性检查
MATURITY=VERIFIED
TRIGGER=无效或已撤销 Cookie 访问 Task/SSE 时，路由先检查 Query/Stream 配置并返回 503
MECHANISM=依赖解析顺序让未认证主体观察内部配置状态，并遮蔽应有的稳定 401/403
STRUCTURE=路由先 authenticate + authorize，再解析业务 Port；长连接在事件和心跳写出前重授权
EVIDENCE=apps/api/src/flowpilot_api/app.py；tests/core/test_oidc_api.py；1385 passed / 204 security passed
RESIDUAL_RISK=未来新增路由若复制旧的依赖优先顺序，可能重新引入配置状态侧信道
TARGET=ENGINEERING_PLAYBOOK API authentication ordering candidate
```

## 子 Agent 使用摘要

两个子 Agent 只读回答不同问题，均未写文件、未执行 Git、未唤醒长期会话；主 Agent
检查实际差异并复跑定向、Core、身份、安全与全仓门禁。

```text
SUBAGENTS_USED=2
SUBAGENT_MODES=READ_ONLY_PARALLEL
SUBAGENT_TASKS=wp083_identity_ports,wp083_api_surface
SUBAGENT_WRITERS=0
PARENT_REPRODUCED_RESULTS=yes
REUSED_DECISIONS=ADR-0005,IDENTITY_TENANCY,WP-081,WP-082
DUPLICATE_WORK_AVOIDED=3
```

## 接收会话下一步

1. S1 核验精确最终 Head、本 Handoff Hash、clean、ContractSet、基线祖先与仅 S5
   WRITE_SCOPE 差异。
2. S1/S3 复核 OIDC state/nonce/PKCE/refresh 生命周期和 S3 Context 组合；S4 独立黑盒
   复算 Cookie 属性、稳定 401/403、SSE 撤销/重连和 Token 输出数为 0。
3. 与并行 WP-084 Join 后再决定 M8 组合/发布状态；本 Handoff 不自行唤醒其他实现会话。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M8-IDENTITY-TENANCY-01
STEP_ID=M8-02A-S5-API
ATTEMPT_ID=WP-083-a1
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=a1a0360153ec9f1ca1c9009056ae3ba483b2a22f
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/core/evidence/WP-083-a1-HANDOFF.md
NEXT_ROLE=S1-ARCH
NEXT_ATTEMPT_ID=none
ESCALATE_TO_S1=no
SUBAGENTS_USED=2
```

## 可回滚方式

- revert 本 Attempt 的 Handoff 提交与实现提交；禁止 reset、rebase 或 force-push。
- 回滚会重新打开 WP-082 的 `DEPENDENCY_LOCK_PENDING_WP083`，并移除 API/BFF OIDC
  入口和生产 Cookie-only 请求安全适配器。
