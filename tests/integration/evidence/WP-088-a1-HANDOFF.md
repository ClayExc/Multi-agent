# WP-088-a1-r2 S7-INTEGRATION Handoff

## OUTCOME

`PASS_HANDOFF`. WP-088 的最终组合候选在精确输入 `977cf2c60aa1b4c80375fee2547a66ebca542f9b`
上通过真实身份、恢复和定向组合门禁。本结论只表示可交给 S1 复核，不批准 M8 Release，
不改变 156 固定分母的失败 Gate，也未启动 M9。

## EVIDENCE

- 真实空卷 Keycloak 26 经 production `create_local_keycloak_app` 完成 Code+PKCE、
  Cookie-only callback、同秒 refresh、并发 refresh 一成一拒、logout/revoke；浏览器 Cookie
  保持 opaque，跨租户伪造身份输入返回 403，成功读取数 0，模型/工具调用均 0。
- 使用同一真实 Keycloak 签发的 Token、真实 JWKS 与 production `OidcIdentityAdapter`
  独立完成有效 Token pair，以及 wrong nonce、nonce replay、ID/Access swap、wrong audience、
  tenant mapping 和 role mapping 六类失败关闭。未输出 Token、Cookie、PII 或 Secret。
- Worker durable harness 现在显式注入 `RuntimeSecurityContextValidator`、
  `PostgresSecurityContextSource` 与 `SecurityVerifier`。真实 PostgreSQL/Redis 复现 Redis 丢失、
  generation 1→2、checkpoint 3→6；旧 Worker、stale CAS、终态重跑和跨租户成功均为 0。
- WP-084 PostgreSQL/RLS 连接复用证据按派发复用：Migration tree
  `8383eda91972210ff16fb770679a48a9793e457a` 与 Persistence tree
  `80042f54f4334a59809ecdcbfd578330f561e5cf` 未变化，未重复执行完整数据库矩阵。
- WP-087 的 API/MCP 确定性负例明确标为 deterministic，未冒充 live。固定分母仍为
  156 = 30 PASS + 126 executor-not-registered FAIL，skip/quarantine 均 0，Gate=FAIL。

## GATES

- 真实 Keycloak 原协议矩阵：PASS（2 user flows、2 service flows、refresh rotation、
  2 revocations、13 negatives）。
- S7 BFF live：PASS；S7 signed-token crypto live：PASS；真实 durable recovery：PASS。
- 定向 unit/security/acceptance/integration/secret：`230 passed`。
- Contract Conformance：PASS（20 schemas / 35 cases / 43 semantic cases / 52 features）。
- Ruff：PASS；strict Mypy：3 个 S7 verifier PASS；`uv lock --check`：PASS。
- `pip-audit`：0 known vulnerabilities；Secret Scan：0；`git diff --check`：PASS。
- 专用 Compose cleanup：containers=0、volumes=0、networks=0；临时 Secret 文件=0。

## SCOPE AND REUSE

变更仅位于 `scripts/integration/**`、`tests/integration/**`、`artifacts/integration/**`。
Contract、产品代码、Workspace/Lock、Realm、Migration 均未修改。Contract digest 为
`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`；上游
Handoff SHA-256 为 `2814f1b3b980c14d613650c474e7185378bb540f1c793229d1c62ed1375ba4b1`。

本 Attempt 使用两个只读子 Agent，分别审查 live 边界和静态闭包；主 Agent 独立执行
消费者门禁、所有 live leg、最终门禁、清理和提交。按 `DO_NOT_RECHECK` 避免重复 WP-084。

## RISKS / NEXT ACTION

`BLOCKERS=none`。S1 必须独立复算 Proof、路径范围、Head 与 Hash 并执行最终发布裁决。
S7 不批准自身结果。`LEARNING_CANDIDATE=none`。

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M8-IDENTITY-TENANCY-01
STEP_ID=M8-05N-S7-INTEGRATION-FINAL
ATTEMPT_ID=WP-088-a1-r2
SESSION_ROLE=S7-INTEGRATION
BASE_COMMIT=977cf2c60aa1b4c80375fee2547a66ebca542f9b
NEW_HEAD=<this-handoff-commit>
HANDOFF=tests/integration/evidence/WP-088-a1-HANDOFF.md
PROOF=tests/integration/evidence/WP-088-a1-PROOF.json
GATE=PASS
NEXT_ROLE=S1-ARCH
USER_GATE_REQUIRED=yes
```
