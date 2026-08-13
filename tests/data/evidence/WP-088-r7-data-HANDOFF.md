# WP-088-r7-data S6-DATA Handoff

## 基本信息

- `CHAIN_ID`: `CHAIN-M8-IDENTITY-TENANCY-01`
- `STEP_ID`: `M8-05M-S6-KEYCLOAK-CLAIM-MAPPERS`
- `ATTEMPT_ID`: `WP-088-r7-data`
- `SESSION_ROLE`: `S6-DATA`
- `FEATURE`: `FP-SEC-001`
- `BASE_COMMIT`: `c9ee39d02414fd513ff009c342b99060ba7a8a1f`
- `IMPLEMENTATION_HEAD`: `e2cad5b7215269394ebaf2ebc92d58757fd923f8`
- `CONTRACT_CONTENT_DIGEST`: `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- `OUTCOME`: `PASS_HANDOFF`

## 完成内容

- 在既有 `flowpilot-identity` 默认 Client Scope 内增加 Keycloak 26 canonical
  `oidc-sub-mapper`，仅为 Access Token 与 introspection 启用 `sub`。
- 增加 canonical `oidc-acr-mapper`，为 Access Token、ID Token、introspection 与
  userinfo 启用 ACR LoA claim。
- 未修改 tenant、audience、groups、realm roles、scope、Client 或安全默认值。
- 静态测试固定 mapper 类型及精确配置，防止宽松配置漂移。
- 真实 Authorization Code + PKCE 验证要求 Access Token `sub` 为非空字符串，且
  Access/ID Token `acr` 为 Keycloak 支持的字符串值；输出不包含 Token、PII、原始
  sub/sid/jti/nonce 或 Secret。

## 修改路径

- `infra/keycloak/flowpilot-local-realm.json`
- `tests/data/security/test_keycloak_fixture_security.py`
- `tests/data/integration/verify_keycloak.py`
- `tests/data/evidence/WP-088-r7-data-HANDOFF.md`

Realm SHA-256：`sha256:ec6587c1c81410bd6387fbdeb525d0dc948095b63065f25de8d3b371ce32afdb`。

## 验证

| 检查 | 结果 |
|---|---|
| 定向 Realm/Compose 静态测试 | PASS：`13 passed` |
| Data Security 回归 | PASS：`21 passed` |
| 真实 Keycloak 26 Code + PKCE | PASS：`clients=4 users=4 user_flows=2 service_flows=2 refresh_rotation=1 revocations=2 negative_cases=13 access_sub_nonempty=1 access_id_acr_supported=1` |
| 隔离资源清理 | PASS：`containers=0 volumes=0 networks=0` |
| Ruff | PASS |
| strict Mypy | PASS：直接验证器 1 source file |
| Contract Conformance | PASS：20 schemas / 35 cases / 52 features |
| `git diff --check` | PASS |

按派发要求未重跑 WP-084 PostgreSQL/RLS、全仓测试或通用 S3 身份矩阵；未修改 S3/S5
代码，未执行外部付费调用。

## 风险与下一步

- `BLOCKERS=none`。Canonical mapper 已在真实 Keycloak 26 中产生要求的 claim 形状。
- 本交接仅关闭 Keycloak Access Token 的 `sub`/`acr` 缺口，不表示 M8 Release。
- S1 应核对最终 Head、Handoff Hash、授权路径、Contract 摘要与 clean；本会话不唤醒
  其他长期角色。
- `LEARNING_CANDIDATE=none`。

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M8-IDENTITY-TENANCY-01
STEP_ID=M8-05M-S6-KEYCLOAK-CLAIM-MAPPERS
ATTEMPT_ID=WP-088-r7-data
SESSION_ROLE=S6-DATA
BASE_COMMIT=c9ee39d02414fd513ff009c342b99060ba7a8a1f
IMPLEMENTATION_HEAD=e2cad5b7215269394ebaf2ebc92d58757fd923f8
NEW_HEAD=<this-handoff-commit>
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
HANDOFF=tests/data/evidence/WP-088-r7-data-HANDOFF.md
GATE=PASS
NEXT_ROLE=S1-ARCH
USER_INPUT_REQUIRED=none
```
