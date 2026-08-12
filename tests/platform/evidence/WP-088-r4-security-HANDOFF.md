# WP-088-r4 S3-PLATFORM OIDC Refresh Lineage 安全交接

## 基本信息

- Work Package / Attempt ID：`WP-088-r4-security`
- Chain ID：`CHAIN-M8-IDENTITY-TENANCY-01`
- Step ID：`M8-05G-S3-REFRESH-LINEAGE-FINAL`
- 责任会话：`S3-PLATFORM`
- 接收会话：`S1-ARCH`
- 风险 / Feature：`R3` / `FP-SEC-001`
- 输入 Head：`a14ed25b90c774f9343a1c850c7fd92571c09935`
- 分支：`codex/s3/m8-identity-security`
- 最终提交：本文件所在提交；精确 SHA 由交接结果返回
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 前次 Handoff 摘要：
  `sha256:a4aa9b94472c0fbd6335ae7ba4f44c5659443a45f268944d4e8636ce6fc1405b`
- 状态：完成；`PASS_HANDOFF`

## DELTA、消费者门禁与裁决

- `CONTEXT_MODE=DELTA`；复用 WP-088-r2 Token Pair、WP-083 S5 BFF Port 与既有
  callback/refresh 结论，只读取相关身份实现、测试和 S5 P1 交接片段。
- 开始时 Head 精确等于输入 `a14ed25...`、工作树 clean、ContractSet 与前次 Handoff
  摘要匹配；没有 merge/rebase/reset/stash。
- 初次 120 秒全仓运行被命令执行上限终止，`exit 124`，未冒充测试结果。延长超时后的
  完整运行得到 `1482 passed / 1 failed / 1 explicit skip`；唯一失败为 S4
  `test_malformed_cookie_and_command_error_have_no_sensitive_projection`，POST 瞬时返回
  503 而非预期 409。
- S3 按 P1 停链，没有修改 S4/S5 路径、提交或生成部分 Handoff。S1 在相同 dirty Head、
  零文件变化下精确独立复跑该 Case，`1 passed in 0.89s`，确认没有 Lineage/API 错误映射
  复现，并裁决为 `P2_TRANSIENT_TEST_INFRA`。
- 本交接按 S1 明确恢复授权生成；没有再次运行全仓，也不宣称“单次全仓全绿”。

## 完成内容

- 新增不可变 `RefreshLineageState`：只含受信 Session Identity 组合摘要、当前 Access
  Token 摘要、`jti` 摘要、`iat` 与 generation；所有摘要严格为小写 SHA-256，不保存
  明文 Token 或原始 `jti`。
- Session Identity 摘要绑定 `issuer + subject + tenant + authorized_party + sid hash`，
  避免只按 IdP `sid` 建账。
- 新增 `RefreshLineageGuardPort`：定义原子 `establish` 和 `compare_and_swap` 语义；实现
  必须以当前 Token Hash 与 generation 为 CAS 前提，拒绝已见 Token/JTI 摘要，并在拒绝
  或异常时保持零推进。
- 标准 callback 在完整 ID/Access Token、nonce、`at_hash` 与身份绑定验证后建立
  generation 1 起点；Guard 缺失、异常或重复建立均失败关闭。
- Refresh 先完成签名、issuer、audience、azp、时间、可选 ID Token、`at_hash` 及
  issuer/subject/tenant/session 连续性验证，再调用 Guard CAS。仅 CAS 成功才返回下一
  generation 的 `VerifiedUserIdentity`。
- 同秒 `iat` 被允许，但 Token Hash 必须变化、`jti` 必须存在且变化；`iat` 回退、当前
  Token 重复、历史 Token、旧 generation、错误当前 Hash、已见 `jti` 和 Guard 异常均
  稳定拒绝。
- 兼容单 Token 入口继续可验证并映射身份，但返回 `refresh_lineage=None`，不能伪装成
  具备权威刷新重放防护的 callback Session。
- 内存/持久 Guard 实现未放入 Security 包；S5 本地 Session Store 与未来 S6 多实例存储
  负责实现该 Port，保持依赖方向和所有权边界。

## 未完成与非目标

- 未修改 `apps/api/**`、`infra/**`、`contracts/**`、Keycloak Realm、数据库、Migration、
  Redis、根 Workspace、依赖锁、HTTP Transport 或默认组合。
- 未实现 S5 本地内存 Guard 或 S6 多实例持久 Guard；本 Attempt 只交付验证器、Port 语义
  与 S3 确定性 Fake/测试。
- 未运行真实 IdP、真实凭据、在线 Provider、远程 Trace 或付费调用。
- 不声明 M8 Release/Freeze，不唤醒 S5。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/security/src/flowpilot_security/identity.py` | 哈希化 Lineage State、原子 Guard Port、callback 起点和 refresh CAS | S3 |
| `packages/security/src/flowpilot_security/__init__.py` | 导出 Lineage State/Port | S3 |
| `tests/platform/test_identity_boundary.py` | 同秒、并发、历史重放、CAS、JTI、回退、异常与泄漏测试 | S3 |
| `tests/platform/evidence/WP-088-r4-security-HANDOFF.md` | 本正式交接 | S3 |

## 契约、数据库、依赖与配置变化

- ContractSet / JSON Schema：无变化；Conformance PASS。
- Database / Migration / PostgreSQL / Redis：无变化。
- Keycloak Realm / 环境变量 / HTTP Transport：无变化。
- `pyproject.toml` / `uv.lock` / Makefile / 生产依赖：无变化。
- 兼容性：公共跨进程 Contract 不变；Security 内部 Identity 新增可选 Lineage 快照，旧
  手工 Fixture 与单 Token 验证保持可构造。标准 callback/refresh 要求 Guard 和 `jti`，
  这是关闭重放缺口所需的安全强化。

## 验证

| 门禁 | 结果 | 证据 |
|---|---|---|
| Identity 定向 | PASS | 55 passed |
| Shared Security | PASS | 248 passed |
| Contract Conformance | PASS | 20 schemas / 35 cases / 43 semantic / 52 features |
| 全仓 Ruff | PASS | All checks passed |
| Makefile 同源 strict Mypy | PASS | 135 source files |
| 延长超时后的完整全仓 pytest | ADVISORY | 1482 passed / 1 S4 transient failed / 1 explicit online skip；229.15s |
| S1 精确独立复现唯一失败 Case | PASS | 1 passed in 0.89s；相同 dirty Head、零文件变化 |
| `git diff --check`、授权路径、Contract tree | PASS | 仅 S3 WRITE_SCOPE；Contract 零变化 |

产品与定向门禁 PASS；全仓瞬态失败已由精确独立复现清除，保留 `P2 S4 fixture
stability advisory`。本交接不写“单次全仓全绿”。唯一 skip 是必须显式启用的 M7 在线
Provider Smoke，与本 Attempt 无关，未冒充通过。

## 安全与失败路径

- 正常：callback 建立 generation 1；跨秒与同秒 refresh 均通过 CAS 推进到下一代。
- 并发：两个同秒 refresh 从同一 expected generation 出发，最多一个成功。
- 重放：当前 Token 重复、同秒历史 Token、旧 generation、错误当前 Hash、复用/缺失
  `jti`、`iat` 回退全部拒绝；权威 State 零推进。
- 依赖失败：Guard 缺失或异常映射为固定 `IDENTITY_SOURCE_UNAVAILABLE`，不回退到无状态
  判定。
- 身份连续性：issuer、subject、authorized party、tenant、session 仍精确绑定；callback
  Token Pair、nonce、audience 与 `at_hash` 门禁未放宽。
- 泄漏：Guard 只接收哈希和时间；返回对象、错误 `str/repr` 与捕获日志不含 ID Token、
  Access Token、nonce 或原始 `jti`。

## 已知风险

- P2：S4 Web Identity 黑盒 Fixture 在完整全仓运行中曾有一次 POST 瞬时 503；S1 在完全
  相同代码状态下精确复跑通过。该稳定性建议不改变产品/身份安全结论，但后续 S4 可检查
  LiveBackend/临时服务生命周期与错误采集。
- S5/S6 生产 Guard 必须满足 Port 的原子性、已见集合和异常零推进语义；仅在进程内做
  `iat >=` 比较不能替代该 CAS。
- 若 Provider 不提供 `jti`，标准 callback/refresh 将安全失败；不得退化为仅凭同秒
  `iat` 或 Token 自报状态判断历史重放。

## 已知事实与避免重复

- `KNOWN_FACTS`：WP-088-r2 Token Pair 门禁已通过；ContractSet 与依赖锁未变；S1 精确
  独立复跑唯一 S4 transient Case 已 PASS。
- `DO_NOT_RECHECK`：M7 Provider、Keycloak Realm、完整项目文档、未变化历史 Handoff；
  S1 恢复后明确禁止再次运行全仓。
- `REUSED_DECISIONS`：ADR-0005、WP-082、WP-083、WP-088-r2、S1 Refresh Lineage 架构
  裁决与 `P2_TRANSIENT_TEST_INFRA` disposition。
- `DUPLICATE_WORK_AVOIDED`：未实现第二套 Session Store、未复制 S5/S6 Port 实现、未在
  S1 复现后重跑全仓。

## 学习候选

```text
LEARNING_CANDIDATE=OIDC refresh 重放判定必须使用权威原子 lineage CAS
MATURITY=VERIFIED
TRIGGER=同一秒签发使 stateless iat 严格递增误拒合法 Token，而放宽为 >= 又无法识别历史重放
MECHANISM=验证器只证明 JWT 与身份连续性，无法独立证明 Token 是否为当前代或从未出现
STRUCTURE=哈希化 Session Identity + current Token Hash + JTI Hash + generation + atomic establish/CAS
EVIDENCE=55 identity / 248 shared security / concurrent-at-most-one / replay-zero-progress tests
RESIDUAL_RISK=生产原子存储组合归 S5/S6；Guard 不可用必须失败关闭
TARGET=ENGINEERING_PLAYBOOK OIDC refresh/session lineage candidate
```

## 子 Agent 使用摘要

```text
SUBAGENTS_USED=0
SUBAGENT_MODES=none
SUBAGENT_TASKS=none
SUBAGENT_WRITERS=0
PARENT_REPRODUCED_RESULTS=not-applicable
```

## 接收会话下一步

1. S1 核验最终 Head、Handoff Hash、clean、ContractSet 和 S3 路径范围。
2. S1 后续派发 S5 将 Port 绑定到 BFF Session CAS；S3 不直接唤醒 S5。
3. S5/S6 实现不得向 Guard 保存或传递明文 Token；必须保留原子 unseen Token/JTI、
   generation 和异常零推进语义。
4. S4 可将瞬时 503 作为 Fixture stability P2 调查，不阻塞本安全交接。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M8-IDENTITY-TENANCY-01
STEP_ID=M8-05G-S3-REFRESH-LINEAGE-FINAL
ATTEMPT_ID=WP-088-r4-security
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=a14ed25b90c774f9343a1c850c7fd92571c09935
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS_WITH_P2_FIXTURE_STABILITY_ADVISORY
HANDOFF=tests/platform/evidence/WP-088-r4-security-HANDOFF.md
NEXT_ROLE=S1-ARCH
NEXT_ATTEMPT_ID=none
ESCALATE_TO_S1=no
SUBAGENTS_USED=0
```

## 可回滚方式

- revert 本 S3 提交；不要 reset、rebase 或 force-push。回滚会恢复 WP-088-r2 的严格
  `iat` 单调判定，并重新打开同秒合法 refresh 与无权威历史重放判定之间的缺口。
