# WP-073-a1-release S7-INTEGRATION M7 组合复现交接

## 基本信息

- Chain：`CHAIN-M7-LOCAL-PRODUCT-01`
- Step：`M7-11-S7-RELEASE`
- Attempt：`WP-073-a1-release`
- Agent：`m7-verifier`
- 输入 Head：`b8a18af3afa5a84bf6b16fcaae259805599c7c42`
- S7 实现 Head：`532112f9a6a3bb19fdbf638c110beeddf11ce34f`
- ContractSet：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 最终 Head：本文件所在提交；精确 SHA 由唤醒信封提供
- 结论：S7 组合证据复现 PASS；M7 Manifest Gate 仍为 `fail`，不得声明 RELEASE

## 消费门禁

- 当前 S7 Head 是 S4 输入 Head 祖先且工作树 clean；只执行一次
  `git merge --ff-only`，精确到达 S4 Head。
- S4 Handoff 原始字节 Hash 独立复算为
  `sha256:8f8582439dd7148fcc8cc1c248fe39118486e028d68960f357c95feeec4b6134`。
- S4 Proof 原始字节 Hash 独立复算为
  `sha256:966cb8a301ee6990506c3564a4af424302f1f642a7e01661bd29427ac4d35612`。
- ContractSet 内容摘要独立复算一致，且 S7 原 Head 到输入 Head 的 contracts tree
  未变化。

## 独立复现结论

```text
DENOMINATOR=all_declared_cases
DECLARED=156
RESULTS=156
PASSED=24
FAILED=132
SKIPPED=0
QUARANTINED=0
EXECUTOR_CASES=24
EXPLICIT_UNREGISTERED_FAILURES=132
ARTIFACT_HASH_CLOSURE=39/39
MANIFEST_GATE=fail
RELEASE_CLAIMED=false
```

- 24 个 `knowledge_qa_citation` Case 精确绑定
  `flowpilot.m7.enterprise-knowledge@1.0.0`，通过真实 API → Worker → LangGraph
  产品根；Case ID 与输入 Digest 唯一。
- 132 个未实现 Case 均为 `EXECUTOR_NOT_REGISTERED`，没有 skip、quarantine、
  缩分母或 Judge 提升。
- 24 份执行 Evidence 的跨租户成功、Provider Session 暴露、请求正文持久化暴露、
  重启后逻辑模型调用增量和工具调用增量均为 0。
- 六类测试 Gate 全部 PASS；Acceptance Runner 因固定分母中 132 个显式失败按预期
  返回非零并生成完整 Bundle。
- 39 项 Manifest Artifact Hash 逐文件读取原始 bytes 独立复算一致。

关键 Hash：

- S7 Bundle Manifest：
  `sha256:de29039d86cbac81b84329aa865d33d8e2292770154de0204762eda0d489c4e0`
- Aggregate：
  `sha256:f2412649ebfe063bc1fb8b540f69edf3af4c9fea6e04bdd1152d83d8ec4d939d`
- Executor Registry：
  `sha256:f72d14eefa7c1ed2c78b152b6d19953de4966c4d6dc0370baea3c9cb2f0d157b`
- Execution Results：
  `sha256:47d8ced756d6133f569819644b0a27d6c64e94f612ac4289d11f3a4b02678dba`
- Verdicts：
  `sha256:bbf40432f4ef2b849fa43bf9369cd880074d9e5fe4ef0372c8c3608bc4686046`
- Failures：
  `sha256:9425baa3fc40a1859d45e2615886fc86a3b337f95acd458daa50d6ddc07cf079`
- S7 Verification：
  `sha256:8706228e477ac774c75ae592b532a0c529d6b0eebdde5f5fc1808317f90217c1`

## S7 验证器与负例

- 新增 `scripts/integration/verify_m7_release.py`，对输入 Head、ContractSet、clean
  标记、固定分母、Gate 状态、六层测试、精确执行器集合、显式失败、安全计数和
  Artifact Hash 闭包进行失败关闭验证。
- 新增 5 个测试：合法阻塞 Gate、缩分母、错误提升 RELEASE、Artifact 漂移、
  跨租户成功数非零。
- 验证结果保存于
  `tests/integration/evidence/WP-073-a1-release-VERIFICATION.json`。

## 测试结果

- M7 执行器定向：11 passed。
- S7 M7 verifier：5 passed；真实 Bundle 9/9 checks PASS。
- 全量 `tests/integration`：68 passed。
- Runner 六类测试：362 unit、53 contract、122 integration（121 pass / 1 explicit
  online skip）、280 e2e、40 recovery、19 security；全部 Gate PASS。
- Ruff：PASS。
- strict Mypy：PASS（本次 2 个 Python 文件）。
- `git diff --check`：PASS。

## 一次环境复跑

- 首次 Runner 被外层工具超时强制中断；紧接着启动第二次 Runner 时，前一次真实
  Agent Server 夹具短暂残留 `.langgraph_api`，触发启动前清洁门禁 1 个失败。
- 待夹具完成清理并确认无工作区子进程后，单独复跑 integration 为 117 passed / 1
  explicit online skip；随后不重叠地重新生成 Bundle，六类 Gate 全部 PASS。
- 未修改产品、测试期望或残留检测来绕过此门禁。

## Blockers、风险与下一步

- RELEASE BLOCKER：132 个固定分母 Case 尚无产品执行器；M7 Gate 必须保持 fail。
- P2：在线 Provider Smoke 未授权并保持显式跳过；本次不代表真实 Provider 的质量、
  延迟、成本或 Token 指标。
- 本步不批准合并、VERIFIED、RELEASED 或发布；S1 保留最终裁决并必须停在用户门禁。
- S1 应只以 `--ff-only` 精确消费 S7 最终 Head，独立复算 Handoff、Verification、
  156/24/132/39 及产品/Contract/Lock/Migration 保护，不得自动启动 M8。

```text
LEARNING_CANDIDATE=Long-running real-server acceptance runs must not overlap after an outer timeout; verify child-process and .langgraph_api cleanup before retrying the bundle.
```

## 机器摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M7-LOCAL-PRODUCT-01
STEP_ID=M7-11-S7-RELEASE
ATTEMPT_ID=WP-073-a1-release
AGENT_ID=m7-verifier
INPUT_HEAD=b8a18af3afa5a84bf6b16fcaae259805599c7c42
IMPLEMENTATION_HEAD=532112f9a6a3bb19fdbf638c110beeddf11ce34f
NEW_HEAD=<this-handoff-commit>
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
S7_COMPOSITION_GATE=PASS
M7_MANIFEST_GATE=fail
RELEASE_CLAIMED=false
HANDOFF=tests/integration/evidence/WP-073-a1-release-HANDOFF.md
VERIFICATION=tests/integration/evidence/WP-073-a1-release-VERIFICATION.json
VERIFICATION_SHA256=sha256:8706228e477ac774c75ae592b532a0c529d6b0eebdde5f5fc1808317f90217c1
NEXT_ROLE=S1-ARCH
NEXT_AGENT_ID=S1-ARCH
USER_GATE_REQUIRED=yes
ESCALATE_TO_S1=yes
```
