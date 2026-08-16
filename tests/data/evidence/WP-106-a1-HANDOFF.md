# WP-106-a1 S6-DATA Handoff

## 基本信息

- `CHAIN_ID`: `CHAIN-M9-GOVERNANCE-01`
- `STEP_ID`: `M9-06-S6-OPA-SECRET-INFRA`
- `ATTEMPT_ID`: `WP-106-a1`
- `SESSION_ROLE`: `S6-DATA`
- `MODE`: `HOT_CONTINUE`
- `RISK_CLASS`: `R3`
- `BASE_COMMIT`: `417a3ab3f71af0dea8cd924dee7636e793384410`
- `IMPLEMENTATION_HEAD`: `d372663e7e433c3bf5213d1feb656d6e5dda2d8c`
- `CONTRACT_CONTENT_DIGEST`: `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- `OUTCOME`: `PASS_HANDOFF`

## 完成内容

- Compose 空卷迁移链扩展为 `0001 -> 0005`，0005 只读挂载。
- 新增固定本地 OPA Bundle `policy-m9-local-v1`；PolicyBundle canonical digest 为
  `sha256:cc51d0ab568ed387d015309f136f90cb18d6be0137e308cf1d3594bcda524942`。
- Bundle 默认 deny；仅低风险且 action tenant 与可信 context tenant 精确一致时 allow，
  未知、缺失和跨租户输入保持 deny。
- OPA 只读加载 Bundle，健康检查实际解析并求值 `data.flowpilot.authz.decisions`；重启后
  从固定 Bundle 恢复。
- `governance-config` 在 OPA 启动前固定校验 Rego/Data/Manifest 三个 SHA-256，并验证
  environment-backed Compose Secret 至少 32 字节。缺失、短 Secret 或 Bundle 漂移均
  在 OPA 启动前失败关闭。
- `.env.example` 的治理游标签名 Secret 故意为空，无可用默认值；运行日志不输出 Secret。

## 修改范围

- `infra/**`
- `.env.example`
- `tests/data/**`

未修改 Contract、S2/S3/S4/S5/S7 路径、根锁或 WP-105 产品实现。

## 验证

| 检查 | 结果 |
|---|---|
| Compose config | PASS |
| OPA 真实求值 | PASS：default_deny=1 / cross_tenant_allow=0 / exact_allow=1 |
| OPA restart | PASS：前后 shape digest 均为 `sha256:9c90046eb9442c2e6935af2370104417c6073423cb0682f4118cd18ed79d2e8a` |
| PostgreSQL 空卷 + 0005 replay | PASS |
| Secret 负例 | PASS：missing exit=1 / short exit=1 |
| Secret 日志扫描 | PASS：精确命中 0 |
| 资源清理 | PASS：containers=0 / volumes=0 / networks=0 |
| Data + Secret Scan | PASS：`111 passed` |
| Ruff | PASS |
| strict Mypy | PASS：2 source files |
| Contract Conformance | PASS：20 schemas / 35 cases / 43 semantic / 52 features |
| `git diff --check` | PASS |

## 风险与下一步

- `BLOCKERS=none`。
- 本地 OPA Bundle、environment-backed Secret 与回环 HTTP 不是生产 Policy Distribution、
  Vault/KMS、TLS、HA 或企业网络；不得外网暴露。
- 本交接不批准 M9 Release。S4 WP-107 应只消费本 Head，不重做 WP-105/106 实库过程。
- `LEARNING_CANDIDATE=OPA bundle manifest roots must contain both module and data paths; health must evaluate the loaded bundle rather than only the OPA binary.`

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M9-GOVERNANCE-01
STEP_ID=M9-06-S6-OPA-SECRET-INFRA
ATTEMPT_ID=WP-106-a1
SESSION_ROLE=S6-DATA
BASE_COMMIT=417a3ab3f71af0dea8cd924dee7636e793384410
IMPLEMENTATION_HEAD=d372663e7e433c3bf5213d1feb656d6e5dda2d8c
NEW_HEAD=<this-handoff-commit>
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
HANDOFF=tests/data/evidence/WP-106-a1-HANDOFF.md
GATE=PASS
NEXT_ROLE=S4-QUALITY
NEXT_WORK_PACKAGE=WP-107
USER_INPUT_REQUIRED=none
```
