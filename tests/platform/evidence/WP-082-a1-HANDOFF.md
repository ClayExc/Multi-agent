# WP-082 S3-PLATFORM 可信身份边界正式交接

## 基本信息

- Work Package：WP-082
- Attempt ID：WP-082-a1-r2
- Chain ID：CHAIN-M8-IDENTITY-TENANCY-01
- Step ID：M8-01D-S3-FINAL
- 责任会话：S3-PLATFORM
- 接收会话：S1-ARCH
- 交接策略：S1_GATE
- 风险：R2
- 功能 ID：FP-SEC-001、FP-SEC-007
- 原始基线提交：`be068c9cc315c657f04e3327e18e15a41b01f9fb`
- S3 checkpoint：`532e86b2e8dd2c68a70966afb8b13eff9da1e0b5`
- 最终汇合输入：`de89b4d8c4ed9db312eb2d0882174abf686cefb9`
- 分支：`codex/s3/m8-identity-security`
- 最终提交：本文件所在提交；精确 SHA 由交接结果返回
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：完成；`DEPENDENCY_LOCK_PENDING_WP083`

## DELTA 与消费者门禁

- `CONTEXT_MODE=DELTA`，没有重新读取未变化的 M7、README 或全仓历史。
- S3 checkpoint 工作树 clean，Head 精确为 `532e86b...`，且是授权输入
  `de89b4d...` 的祖先；只使用 `git merge --ff-only de89b4d...` 消费汇合。
- 汇合精确包含 S1 决策 `b84a418...`、S2 Fixture `8a2ae39...` 和 S4 Fixture
  `73c7cf7...`；汇合后工作树 clean、ContractSet 摘要不变。
- 复用了 S2 的 3 条定向结果与 S4 的 33 条定向结果，没有把它们作为独立工作重复
  执行；最终共享 Security 和全仓测试共同覆盖了迁移后的消费者 Fixture。

## 完成内容

- 新增 OIDC/JWKS Port 与确定性 Adapter：只允许非对称算法白名单，校验签名、issuer、
  audience、authorized party、subject、时间窗、nonce 与 JWKS 强制刷新边界。
- 用户 Token 与 workload Token 使用不同 audience/azp/注册映射；用户 Token 不能作为
  MCP workload credential。工作负载注册精确绑定 `issuer + azp + sub`。
- 新增唯一可挂载网络 Transport 的 `GatewayIngress`：只接收瞬时 workload bearer，
  验证完成后才在进程内构造 `GatewayInvocation`；核心 Gateway 不保存原始 Token。
- `AuthenticatedWorkload.attested` 默认拒绝；attested workload 必须携带完整 issuer、
  azp、sub 与严格 `sha256:[a-f0-9]{64}` credential evidence。
- Claim 只通过服务端白名单映射为 tenant、role/scope 与 assurance；purpose、Context ref、
  classification、Agent 与工具权限不能由浏览器、模型或 Token 自行提升。
- nonce Port 明确要求 API/BFF 服务端一次性会话存储预登记并原子消费摘要；浏览器 nonce
  不能直接成为权威 expected nonce。回调 Claim 映射失败后同一 nonce 也不能重放。
- `context_hash` 绑定不可变授权快照：tenant/subject、issuer/azp、roles/scopes、认证信息、
  purpose、classification、issued/expires 和源 Token hash；`active` 独立可撤销。
- ContextSource 与 SecurityVerifier 每次解析都确定性重算快照；role/scope 或身份 evidence
  被替换时，在 policy、ledger、credential issuance 和上游调用前失败关闭。
- S2/S4 已在各自 Owner 路径迁移 Runtime 与 Acceptance Fixture；最终共享与全仓门禁通过。

## 未完成与非目标

- 根 `uv.lock` 尚未记录 `flowpilot-security` 的 PyJWT 直接依赖；按 S1 裁决由 WP-083/S5
  单写者收口，状态为 `DEPENDENCY_LOCK_PENDING_WP083`。本 Attempt 未修改根锁或根
  `pyproject.toml`。
- API/BFF 登录会话、Keycloak 配置、RLS、Rego/DLP、真实外部 IdP 与生产 TLS/HA 不在
  WP-082 范围。
- 未修改公共 JSON Schema、ContractSet、数据库、Migration、Redis 或环境变量。
- 本交接不启动 WP-083，不唤醒 S5/S6/S7，不声明 Release 或 Freeze。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/security/src/flowpilot_security/identity.py` | OIDC/JWKS、用户/workload 映射、nonce 与可撤销 ContextSource | S3 |
| `packages/security/src/flowpilot_security/context_integrity.py` | 不可变授权快照 hash 与重算 | S3 |
| `packages/security/src/flowpilot_security/digests.py` | 严格 SHA-256 evidence 校验 | S3 |
| `packages/security/src/flowpilot_security/models.py` | 默认拒绝 workload 与完整 identity evidence | S3 |
| `packages/security/src/flowpilot_security/verifier.py` | Context/workload 入口重验 | S3 |
| `packages/security/src/flowpilot_security/errors.py`、`__init__.py` | 稳定安全码与内部 API 导出 | S3 |
| `packages/security/pyproject.toml` | 声明 `pyjwt[crypto]>=2.13,<3` 直接依赖 | S3 |
| `apps/mcp-gateway/src/flowpilot_mcp_gateway/ingress.py` | 瞬时 bearer 生产入口 | S3 |
| `apps/mcp-gateway/src/flowpilot_mcp_gateway/models.py`、`gateway.py`、`__init__.py` | credential-free ingress request 与进程内边界 | S3 |
| `tests/platform/test_identity_boundary.py` | OIDC、轮换、映射、重放、泄漏和组合负例 | S3 |
| `tests/platform/factories.py`、`test_gateway_security.py` | 严格快照 Fixture 与执行前拒绝证据 | S3 |
| `tests/platform/evidence/WP-082-a1-r1-CHECKPOINT.md` | 修复汇合前 checkpoint | S3 |
| `tests/platform/evidence/WP-082-a1-HANDOFF.md` | 本正式交接 | S3 |

S2/S4 Fixture 变更由各自提交和证据负责，S3 仅通过授权 fast-forward 消费：

- `tests/runtime/evidence/WP-082-a1-r1-S2-FIXTURE-HANDOFF.md`
- `tests/acceptance/platform_security/evidence/WP-082-a1-r1-S4-FIXTURE-HANDOFF.md`

## 契约、数据库、依赖与配置变化

- ContractSet / JSON Schema：无变化；Conformance PASS。
- Migration / PostgreSQL / Redis：无变化。
- 根 Workspace / `uv.lock` / Makefile：无变化。
- 包级依赖：`flowpilot-security` 新增 PyJWT crypto 直接声明。用途为 JWT/JWK 的签名与
  Claim 验证；复用锁中已有 PyJWT/cryptography，避免引入第二套身份 SDK。攻击面由算法
  白名单、issuer/audience/azp/sub 精确校验、JWK metadata 校验和安全错误映射约束。
- 兼容性：公共 Contract 兼容；内部可信身份对象改为 fail-closed，S2/S4 Fixture 已迁移。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| `uv run --all-packages --all-groups --locked python -c ...` | EXPECTED_BLOCKED | `uv.lock` 待 WP-083；未修改锁文件 |
| `uv run --frozen python -B -m pytest -q tests/platform/test_identity_boundary.py` | PASS | 24 passed |
| `uv run --frozen python -B -m pytest -q tests/platform` | PASS | 356 passed |
| shared Security 命令 | PASS | 163 passed |
| `uv run --frozen ruff check apps packages mcp-servers domain-packs scripts tests web` | PASS | All checks passed |
| `uv run --frozen mypy --strict ...` | PASS | 133 source files |
| `uv run --frozen python -B contracts/conformance/validate.py` | PASS | 20 schemas / 35 cases / 43 semantic / 52 features |
| `uv run --frozen python -B -m pytest -q` | PASS | 1367 passed, 1 skipped |

全仓唯一 skip：`tests/runtime/integration/test_m7_provider_online_smoke.py`，需要显式
`FLOWPILOT_ENABLE_ONLINE_PROVIDER_SMOKE=1` 的在线 Provider 环境；与 WP-082 无关。

## 安全与失败路径

- 验证错算法、错签名、issuer、audience、azp、subject、过期、未来 iat/nbf、未知 key、
  JWKS 轮换和不可用均失败关闭，异常、repr 与日志不含原始 Token/nonce。
- 验证未知 tenant/role、浏览器 Claim 覆盖、用户 Token 直达 MCP、手工缺失 attestation、
  错 workload subject、未签发 nonce、重复 nonce 和 Context role 篡改均在副作用前拒绝。
- Gateway 每次敏感执行重新解析 Context；撤销或 hash/evidence 不一致时 policy、ledger、
  credential issuance 与 upstream 调用计数保持 0。
- 原始 Bearer、完整 Claim、nonce 与会话标识不进入 GatewayInvocation、ContextRef、结果、
  Lifecycle、Trace、Audit、Security Event、日志或 Evidence。
- Secret/PII：共享 Security 与全仓测试通过；仓库只包含合成身份和不可逆摘要。

## 已知问题

- `DEPENDENCY_LOCK_PENDING_WP083`：根锁门禁在 WP-083/S5 更新前会按预期拒绝。
- 当前验证使用本地确定性 RSA/JWK Fixture；真实 Keycloak/网络配置由 WP-081/WP-083
  组合阶段负责，不将其冒充为本 Attempt 结果。

## 已知事实与避免重复

- `KNOWN_FACTS`：严格身份实现、S2 Runtime Fixture 和 S4 Acceptance Fixture 已在
  `de89b4d...` 机械汇合；ContractSet 未变。
- `DO_NOT_RECHECK`：S2 独立 3 tests、S4 独立 33 tests、M7 Provider/知识执行器与历史
  Handoff；最终共享/full gate 已覆盖消费者闭包。
- `FAILURE_SIGNATURES`：`uv.lock needs to be updated, but --locked was provided` 映射为
  `DEPENDENCY_LOCK_PENDING_WP083`，不能通过修改根锁或移除安全依赖绕过。
- `REUSED_DECISIONS`：ADR-0005、IDENTITY_TENANCY、S1 `b84a418...`、S2/S4 Fixture
  Handoff 和 checkpoint `532e86b...`。
- `DUPLICATE_WORK_AVOIDED`：2 组上游定向测试未重复作为独立工作执行。

## 学习候选

```text
LEARNING_CANDIDATE=none
MATURITY=VERIFIED
TRIGGER=none
MECHANISM=已由 ADR-0005 与 IDENTITY_TENANCY 固化，无新增未记录机理
STRUCTURE=none
EVIDENCE=tests/platform/test_identity_boundary.py；本 Handoff 验证表
RESIDUAL_RISK=根依赖锁与真实 Keycloak 组合留给 WP-083
TARGET=none
```

## 子 Agent 使用摘要

```text
SUBAGENTS_USED=1
SUBAGENT_MODES=READ_ONLY_PARALLEL
SUBAGENT_TASKS=oidc-jwks-claims,identity-negative-review
SUBAGENT_WRITERS=0
PARENT_REPRODUCED_RESULTS=yes
REUSED_DECISIONS=ADR-0005,b84a418,S2/S4 fixture handoffs
DUPLICATE_WORK_AVOIDED=2
```

## 接收会话下一步

1. S1 核验最终 Head、本 Handoff SHA、clean、ContractSet、授权范围和全部门禁。
2. S1 将本结果纳入 M8 Join；根依赖与 `uv.lock` 只交给 WP-083/S5 单写者收口。
3. 在 WP-083 完成前保留 `DEPENDENCY_LOCK_PENDING_WP083`，不得声明 M8 Release/Freeze。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M8-IDENTITY-TENANCY-01
STEP_ID=M8-01D-S3-FINAL
ATTEMPT_ID=WP-082-a1-r2
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=de89b4d8c4ed9db312eb2d0882174abf686cefb9
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
DEPENDENCY_LOCK=DEPENDENCY_LOCK_PENDING_WP083
HANDOFF=tests/platform/evidence/WP-082-a1-HANDOFF.md
NEXT_ROLE=S1-ARCH
NEXT_ATTEMPT_ID=M8_JOIN_01
ESCALATE_TO_S1=no
SUBAGENTS_USED=1
```

## 可回滚方式

- revert 本 Handoff 提交和 S3 checkpoint `532e86b...`；消费者 Fixture 由 S1 按各自
  Owner 提交反向处理。禁止 reset、rebase 或 force-push。
