# FlowPilot rc2 `6e85ce62` 五角色 DELTA 复审

> 已拒绝并停止：S3/S4 发现正向 Verdict 未绑定 `GATE=PASS`。当前唯一目标为
> [`RC2_DELTA_REVIEW_1CAD07BD.md`](./RC2_DELTA_REVIEW_1CAD07BD.md)。

## 固定目标

```text
CONTRACT_SET_ID=flowpilot-m0-contracts-v1-rc2
VERSION=1.0.0-rc.2
REVIEWED_CONTENT_DIGEST=sha256:6e85ce625879c108431ed79ab934127ddd5705d3ee3ddd4e1df347b5f1e2ac42
CONTEXT_MODE=DELTA
MODE=READ_ONLY_PARALLEL
```

本轮只恢复最新 `candidate` 的实现基线审签，不代表发布级 `frozen`。五个角色必须
审查同一摘要；任一被摘要覆盖的内容变化后，所有结论再次失效。

## 相对上一实现内容的强制 DELTA

业务 Schema、20 个 Schema Hash、Release Dependencies 和 52 项 Feature 定义均未
变化。本轮内容摘要变化仅来自：

- `contracts/conformance/validate.py`：Review Evidence 不再只校验文件 Hash；新增
  `SESSION_ROLE`、`VERDICT`、`REVIEWED_CONTENT_DIGEST` 和必需字段的内容绑定。
- `contracts/conformance/rc2-cases.json`：新增 6 个 Attestation 解析用例和 5 个旧
  `RC2-0A82-*` 证据失效用例。
- ContractSet 的上述两个 Artifact Hash 已更新；五条旧 Review 已重置为
  `PENDING`，旧文件只保留历史用途。

## 共同只读门禁

1. 验证唤醒输入 Head、当前摘要和本文件；不得重读未变化的全仓文档。
2. 只读复核上述两个变更文件、`contracts/contract-set.v1.json` 和本角色旧
   Attestation；按需读取直接相关 Session Contract。
3. 运行：

```powershell
uv run --all-packages --all-groups --locked python -B contracts/conformance/validate.py
```

参考输出必须包含：

```text
review_attestation_cases=6 review_attestation_positive=1 review_attestation_negative=5 retired_review_attestation_cases=5 retired_review_attestation_positive=0 retired_review_attestation_negative=5
```

4. 确认旧 Evidence 即使文件 Hash 正确，也不能为 `6e85ce62…` 提供 ACCEPT。
5. 只返回以下机器块；不修改文件、不提交、不启动实现：

```text
SESSION_ROLE=<S2-RUNTIME|S3-PLATFORM|S4-QUALITY|S5-CORE|S6-DATA>
VERDICT=<ACCEPT|ACCEPT_WITH_RFC|REJECT>
REVIEWED_CONTENT_DIGEST=sha256:6e85ce625879c108431ed79ab934127ddd5705d3ee3ddd4e1df347b5f1e2ac42
GATE=<PASS|FAIL|NOT_RUN:reason>
BLOCKERS:
- <none 或具体 finding>
ADVISORIES:
- <none 或具体 finding>
IMPLEMENTABILITY:
- <本角色实现是否仍与未变化业务 Schema 兼容>
```

## 角色关注点

- S2-RUNTIME：确认 Runtime/Context/Graph 所消费的业务 Schema 未变化；Attestation
  摘要错配必须阻断。
- S3-PLATFORM：确认 Approval/Policy/Tool/Audit 绑定未变化；角色或结论错配必须阻断。
- S4-QUALITY：确认新负例不能假通过，Review Evidence 的分母和结论不被文件存在替代。
- S5-CORE：确认 Domain/Application/API Port 未变化，PENDING 不可误判为激活审签。
- S6-DATA：确认 Persistence/Migration 数据契约未变化，旧 Evidence 不得跨摘要复用。

只有五个 `VERDICT=ACCEPT` 且 `GATE=PASS` 才能由 S1 写入新 Attestation。任何
`REJECT`、契约变化、越权请求或 P0/P1 都停止 Step 4。
