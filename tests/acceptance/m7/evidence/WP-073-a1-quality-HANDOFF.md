# WP-073-a1-quality S4-QUALITY 产品执行器交接

## 基本信息

- Work Package：WP-073
- Attempt ID：WP-073-a1-quality
- Chain ID：CHAIN-M7-LOCAL-PRODUCT-01
- Step ID：M7-10-S4-EXECUTORS
- DEDUP Key：`CHAIN-M7-LOCAL-PRODUCT-01/M7-10-S4-EXECUTORS/WP-073-a1-quality/95466cc5efb65b3608bbc3ca82b73bbc2062bde7`
- 责任会话：S4-QUALITY
- 下一会话：S7-INTEGRATION（m7-verifier）
- 功能 ID：FP-EVAL-001、FP-EVAL-002、FP-EVAL-003、FP-OPS-002
- 输入提交：`95466cc5efb65b3608bbc3ca82b73bbc2062bde7`
- 实现提交：`2bdd346a67b3dc7acc298a345c866408a3fb7928`
- ContractSet：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：S4 执行器交付 PASS；M7 总 Gate FAIL；未宣称 RELEASE

## 完成内容

- 注册唯一 `flowpilot.m7.enterprise-knowledge@1.0.0` 执行器，完整 Case Digest
  精确匹配当前 24 条 `knowledge_qa_citation` Case。Case ID、版本或任何定义字段
  变化均不能选择该执行器。
- 每条支持 Case 通过真实 API -> Worker -> LangGraph 产品根执行；Gateway 与
  AgentRuntime 使用仓库合成离线 Transport，不调用真实 Provider 或企业系统。
- 逐 Case Evidence 只记录实际终态、引用、工具/模型调用、Event sequence、重启
  重放增量和安全计数；不把 Case `expected` 或浏览器字段当成观测输出。
- API duplicate submission 与 Worker 重组后 replay 均保持 idle；24 条 Case 的
  restart replay 逻辑模型调用增量和逻辑工具调用增量均为 0。
- 跨租户知识负例在模型和 Artifact 前失败，全部支持 Case 的跨租户成功数为 0；
  Provider Session 和请求正文进入持久化 Evidence 的次数均为 0。
- 其余 132 条 Case 继续留在固定分母，以 `EXECUTOR_NOT_REGISTERED` 明确失败；
  没有 skip、quarantine、缩分母或占位成功。
- Acceptance Bundle 新增 `eval/executor-registry.json`，绑定执行器身份、版本、
  24 个 Case ID 与 Case Digest；连同 24 份执行 Evidence 纳入 Manifest 哈希闭包。

## 固定分母结论

```text
DENOMINATOR=all_declared_cases
DECLARED=156
RESULTS=156
FUNCTIONAL=120
SAFETY_FAULT=36
CATEGORIES=13
PASSED=24
FAILED=132
SKIPPED=0
QUARANTINED=0
MANIFEST_GATE=fail
RELEASE_CLAIMED=false
```

`MANIFEST_GATE=fail` 是本工作包的预期正确结果：未实现类别必须计入失败。S4 的
PASS_HANDOFF 只表示执行器、固定分母和证据闭包实现正确，不表示 M7 可发布。

## 修改文件

- `packages/evaluation/m7_product.py`
- `packages/evaluation/README.md`
- `scripts/acceptance/run_acceptance.py`
- `scripts/acceptance/README.md`
- `tests/acceptance/evaluation/test_m7_product_executor.py`
- `tests/acceptance/m7/evidence/WP-073-a1-quality-PROOF.json`
- `tests/acceptance/m7/evidence/WP-073-a1-quality-HANDOFF.md`

## 契约、数据与配置

- Contract、Schema、ADR：无变化；ContractSet 摘要与输入一致。
- 数据库、Migration、RLS、Outbox：无变化。
- `pyproject.toml`、`uv.lock`、Makefile 与根配置：无变化。
- 真实/付费 Provider 调用为 0；online Provider Smoke 保持显式关闭。

## 验证

| 门禁 | 结果 |
|---|---|
| M7 执行器定向测试 | PASS：11 passed |
| Evaluation Acceptance | PASS：150 passed |
| 全部 Acceptance | PASS：276 passed |
| Offline Repository | PASS：2 Case、0 finding |
| Contract Conformance | PASS：20 Schema、35 Case、43 语义负例、52 Feature |
| Security | PASS：163 passed |
| Ruff / strict Mypy | PASS：129 source files |
| 全仓测试 | PASS：1338 passed、1 个显式 online skip |
| clean-Head Acceptance Runner | EXPECTED FAIL：24 PASS / 132 FAIL / 0 SKIP / 0 QUARANTINE |
| Runner 六类 JUnit | PASS：362 / 53 / 121+1 skip / 280 / 40 / 19 |
| Acceptance Artifact Hash | PASS：39 项全部匹配 |

clean-Head Runner：`artifacts/acceptance/wp073-a1-quality-clean/`，默认不提交。
关键生成物 Hash 与完整测试结果见 `WP-073-a1-quality-PROOF.json`。

## 失败关闭验证

- 未注册类别、Case 身份/版本篡改：不能选中执行器。
- 重复执行器 ID：Registry 构造失败。
- Result 执行器版本不匹配：`EXECUTOR_IDENTITY_MISMATCH`。
- Evidence 缺失或 Output Digest 伪造：`EXECUTION_RESULT_INVALID`，可疑引用清空。
- 安全 Case 不接收 Judge 分数；Judge 不能覆盖确定性断言或执行状态。
- failed/skipped/quarantined 均属于固定分母失败；本次实际为 132/0/0。

## 已知风险与非目标

- EXPECTED RELEASE BLOCKER：132 条非企业知识产品 Case 尚无真实执行器，当前
  Manifest Gate 必须为 fail。S7 只能复现并报告，不得改写分母或批准 RELEASE。
- P2：真实在线 Provider Smoke 未授权；本结果不代表真实模型语义质量、成功率、
  延迟、成本或 Token 改善。
- P2：当前产品注册只覆盖企业知识问答；业务读、写、审批、并行、长上下文和五类
  其他安全/故障类别必须由未来明确产品根与独立工作包接入。
- 生成 Acceptance Bundle 不提交；S7 必须在精确 clean Head 上独立重跑并复算。

## 学习候选

```text
LEARNING_CANDIDATE=Partial product coverage must remain executor absence inside the fixed denominator
MATURITY=VERIFIED
TRIGGER=A dataset contains declared cases whose product root is not implemented
MECHANISM=Register only exact case digests that reach a real product boundary; leave all other cases as EXECUTOR_NOT_REGISTERED failures
STRUCTURE=single executor identity + exact case digest pins + per-case evidence + all_declared_cases aggregate
EVIDENCE=tests/acceptance/m7/evidence/WP-073-a1-quality-PROOF.json
RESIDUAL_RISK=132 declared cases still block M7 RELEASE
TARGET=S7 M7 release reproduction and future product executor work packages
```

## S7 下一步

1. 核验 S4 NEW_HEAD、本 Handoff/Proof Hash、ContractSet、输入提交到 NEW_HEAD 的
   线性祖先、授权路径和 clean 状态，只用 `--ff-only` 精确消费。
2. 按 `M7-11-S7-RELEASE / WP-073-a1-release` 独立复跑 156 固定分母、24 个
   Product Executor Case、39 项 Artifact 闭包与完整组合门禁。
3. 保持 132 个未实现 Case 失败；不得 skip、quarantine、缩分母或用 Judge/Case
   expected 提升为通过。当前候选不得声明 RELEASE。
4. 正常复现后按链路唤醒 S1 最终门禁；新 P0/P1、公共契约、越权路径或门禁结果
   与本 Proof 不一致时停链上报 S1。

## 机器摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M7-LOCAL-PRODUCT-01
STEP_ID=M7-10-S4-EXECUTORS
ATTEMPT_ID=WP-073-a1-quality
INPUT_HEAD=95466cc5efb65b3608bbc3ca82b73bbc2062bde7
IMPLEMENTATION_HEAD=2bdd346a67b3dc7acc298a345c866408a3fb7928
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
S4_GATE=PASS
M7_MANIFEST_GATE=fail
RELEASE_CLAIMED=false
HANDOFF=tests/acceptance/m7/evidence/WP-073-a1-quality-HANDOFF.md
PROOF=tests/acceptance/m7/evidence/WP-073-a1-quality-PROOF.json
NEXT_AGENT_ID=m7-verifier
NEXT_ROLE=S7-INTEGRATION
NEXT_ATTEMPT_ID=WP-073-a1-release
NEXT_TASK_THREAD_ID=019fadaa-7fdc-7ea1-9f31-6ab134caa8e8
ESCALATE_TO_S1=no
```

## 回滚

- 按逆序 `git revert` Handoff 提交和实现提交；禁止 reset、rebase 或 force-push。
- 本 Attempt 无数据库、外部系统或生产数据写入，无数据回滚。
