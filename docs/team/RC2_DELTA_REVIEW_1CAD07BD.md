# FlowPilot rc2 `1cad07bd` 五角色 DELTA 复审

## 固定目标

```text
CONTRACT_SET_ID=flowpilot-m0-contracts-v1-rc2
VERSION=1.0.0-rc.2
REVIEWED_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
CONTEXT_MODE=DELTA
MODE=READ_ONLY_PARALLEL
```

本轮只恢复最新 `candidate` 的实现基线审签，不代表发布级 `frozen`。相对被拒绝的
`6e85ce62…`，业务 Schema、Release Dependencies 和 Feature 定义仍未变化；唯一
增量是：

- `GATE` 只允许 `PASS`、`FAIL` 或带非空原因的 `NOT_RUN:<reason>`。
- `VERDICT=ACCEPT|ACCEPT_WITH_RFC` 必须同时满足 `GATE=PASS`。
- Attestation 用例由 6 个扩展为 10 个（2 正 / 8 负）；旧证据失效用例仍为 5 个。

## 共同门禁

只读检查 `contracts/contract-set.v1.json`、Validator、Case Matrix、本角色历史
Attestation 和必要 Session Contract；不得全文重读未变化文件，不得写文件或 Git。

```powershell
uv run --all-packages --all-groups --locked python -B contracts/conformance/validate.py
```

参考输出必须包含：

```text
review_attestation_cases=10 review_attestation_positive=2 review_attestation_negative=8 retired_review_attestation_cases=5 retired_review_attestation_positive=0 retired_review_attestation_negative=5
```

严格只返回：

```text
SESSION_ROLE=<S2-RUNTIME|S3-PLATFORM|S4-QUALITY|S5-CORE|S6-DATA>
VERDICT=<ACCEPT|ACCEPT_WITH_RFC|REJECT>
REVIEWED_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=<PASS|FAIL|NOT_RUN:reason>
BLOCKERS:
- <none 或具体 finding>
ADVISORIES:
- <none 或具体 finding>
IMPLEMENTABILITY:
- <本角色实现是否仍与未变化业务 Schema 兼容>
```

只有五个 `ACCEPT + PASS` 才解锁 S1 写入新 Attestation。`6e85ce62…` 的 S2 ACCEPT
与 S3/S4 REJECT 均为历史，不能迁移。
