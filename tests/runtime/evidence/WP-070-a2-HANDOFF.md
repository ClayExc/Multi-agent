# WP-070-a2-r1 S2-RUNTIME Session Boundary 修复交接

## 基本信息

- Work Package：WP-070
- Attempt ID：WP-070-a2-r1
- Chain ID：CHAIN-M7-LOCAL-PRODUCT-01
- Step ID：M7-03-S2-SESSION-BOUNDARY-REPAIR
- 责任会话：S2-RUNTIME
- 接收会话：S4-QUALITY
- 交接策略：CONSUMER_GATE
- 功能 ID：FP-AGT-002、FP-AGT-003、FP-OPS-003、FP-SEC-006
- 原始 Conformance 基线：`0fb5f78f5fe876f6323a5d8afb12623b395ff974`
- 修复基线提交：`fd7f8418ecf3c9f2dbd4e05f27015b91c535f6ed`
- Conformance 实现提交：`45bf8cddcc244ad2c3a0e1aa609e01c0720ed342`
- Session Boundary 修复提交：`6f2cbb472dc8e6eed9dccc418c527d39b316ef61`
- 分支：`codex/s2/wp-070-provider-runtime-adapters`
- 最终提交：本文件所在提交；精确 SHA 由唤醒信封返回
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：S4 P1 已修复，等待 S4 恢复原 `WP-070-q1` 黑盒复核

## 完成内容

- 接受 S5 依赖锁 Handoff：核验当前 Head、线性祖先、Handoff SHA256、
  ContractSet、分支和洁净状态，只用 `--ff-only` 精确到达 S5 Head。
- 在根锁环境消费 `litellm==1.95.0`、`openai-agents==0.19.4` 和
  `claude-agent-sdk==0.2.134`，没有修改共享依赖或公共 Contract。
- 使用真实锁定 LiteLLM 模块命名空间验证 DeepSeek 私有路由、JSON 输出、精确
  Usage 和零密钥参数；测试替换唯一网络入口，Provider 调用数为 0。
- 使用真实锁定 OpenAI Agents SDK 的 `Agent`、`RunConfig` 和 `Runner` 形状，
  验证空 Tool/Handoff/MCP、敏感 Trace 关闭、结构化结果、Usage 和 Session
  引用；`Runner.run` 被离线替身替换，不调用 Provider。
- 复跑真实 Claude `ClaudeAgentOptions` 与 CLI Serializer，确认
  `tools=[]` 继续序列化为 `--tools ""`，strict MCP 生效，MCP、Plugin、
  Agent、Hook、Skill 和设置源均为空。
- 补齐 LiteLLM unavailable、rate limit、timeout、configuration 和 invalid
  response 的瞬态/终态稳定错误映射；错误消息不包含凭据或原始 Provider 异常。
- 生成机器可读
  `flowpilot.provider-runtime-conformance.v1` 报告，并用测试绑定精确依赖版本、
  逻辑模型、DeepSeek 模型 ID、Port 类型、全部 PASS 检查和零在线调用。
- 消费 S4 P1 最小复现并统一 Runtime/Model Gateway 深层映射边界：
  `session_ref` 现在与 `provider_session` 一样，在 Context、structured output、
  Tool Proposal arguments/resource 的任意 Mapping/Sequence 嵌套位置失败关闭。
- 保留公共契约允许的顶层强类型 `AgentRunRequest.session_ref` 与
  `AgentRunResult.session_ref`；其值只沿 `SDKRunCall.session_ref` 不透明传递，
  不进入 Context JSON、structured output、业务 Checkpoint 或 Trace。
- 将 Agent Runtime 的深层敏感字段集合收口为单一来源，SDK 输出扫描复用该
  集合，避免 validation/SDK 两份枚举再次漂移；Tool Proposal 共享校验新增
  `resource` 深层扫描。

## 未完成与非目标

- 未执行真实在线 Provider Smoke；它仍要求显式开关、隔离 Realm、测试密钥和
  成本授权。本 Attempt 未读取真实凭据、未启动 Claude CLI、未产生付费调用。
- 未修改 Model Gateway、Web/API/Worker/Graph、S3 安全边界、公共 Contract、
  数据库、Migration、共享依赖或环境变量文件。
- S4 仍需从黑盒边界独立验证缺密钥、超时、限流、结构错误、预算、Session
  失效与零凭据泄漏；本 Handoff 只解锁该复核，不代表 S4 或发布验收已通过。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/agent-runtime/src/flowpilot_agent_runtime/validation.py` | 统一深层敏感字段集合并扫描 Tool resource | S2-RUNTIME |
| `packages/agent-runtime/src/flowpilot_agent_runtime/sdk.py` | SDK 输入/输出复用统一敏感字段集合 | S2-RUNTIME |
| `tests/runtime/contract/test_m7_provider_adapters.py` | LiteLLM 完整瞬态/终态错误矩阵 | S2-RUNTIME |
| `tests/runtime/contract/test_locked_provider_sdk_shapes.py` | 锁定 LiteLLM/OpenAI 真实模块离线形状验证 | S2-RUNTIME |
| `tests/runtime/contract/test_m7_conformance_evidence.py` | Conformance 报告与根锁/产品常量绑定 | S2-RUNTIME |
| `tests/runtime/security/test_provider_session_boundary.py` | Context/输出/Tool 深层负例与顶层强类型正例 | S2-RUNTIME |
| `tests/runtime/evidence/WP-070-a2-CONFORMANCE.json` | 三 Adapter 报告与修复 Attempt 绑定 | S2-RUNTIME |
| `tests/runtime/evidence/WP-070-a2-HANDOFF.md` | 本交接 | S2-RUNTIME |

## 契约、数据库与配置变化

- 契约版本：无修改；ContractSet 摘要保持不变。
- Migration：无。
- 数据库：无。
- 环境变量：无文件变化、无新增值；在线 Smoke 默认关闭。
- 兼容性：顶层强类型 Session 引用保持兼容；只收紧未类型化业务 Mapping/
  Sequence 中本就不应出现的 Provider 私有字段。S5 根锁保持不变。

## 验证

验证解释器为 Python 3.12.11，`uv.lock` SHA256 为
`f1c0edb307c3a1346bc291965fec43f3dee7ad8dbf44980534f18b7f4ad3b0a8`。

| 命令 | 结果 | 证据 |
|---|---|---|
| `.\\scripts\\quality.ps1 bootstrap` | PASS | 168 packages；三项锁定 SDK 已安装 |
| M7 Provider 七个定向测试文件 | PASS | 55 passed、1 explicit online skip |
| `.\\scripts\\quality.ps1 lint` | PASS | Ruff；strict Mypy 119 source files |
| `.\\scripts\\quality.ps1 test-all` | PASS | 784 passed、1 explicit online skip；Contract Conformance PASS |
| `.\\scripts\\quality.ps1 test-security` | PASS | 114 passed，包含 Secret Scan |
| `python -B -m pytest tests/runtime -q` | PASS | 189 passed、1 explicit online skip |
| `python -B -m pytest tests/core -q` | PASS | 77 passed |
| `.\\scripts\\quality.ps1 audit` | PASS | 0 known vulnerabilities；本地 editable Workspace 包按入口定义跳过 |
| `git diff --check`、路径与共享文件审计 | PASS | 仅授权 Agent Runtime/Runtime Tests；Contract/Model Gateway/共享文件零变化 |

Contract Conformance 完整结果：

```text
CONTRACT_CONFORMANCE_OK schemas=20 cases=35 positive=18 negative=17 mutation_cases=19 mutation_positive=3 mutation_negative=16 semantic_cases=43 semantic_positive=0 semantic_negative=43 audit_chain_cases=5 audit_chain_positive=1 audit_chain_negative=4 manifest_cases=21 manifest_positive=1 manifest_negative=20 review_attestation_cases=10 review_attestation_positive=2 review_attestation_negative=8 retired_review_attestation_cases=5 retired_review_attestation_positive=0 retired_review_attestation_negative=5 features=52
```

机器报告：
`tests/runtime/evidence/WP-070-a2-CONFORMANCE.json`。

## 安全与失败路径

- 已验证负向路径：默认在线关闭、缺失凭据、Provider 选择漂移、空/非法输出、
  模型漂移、限流、网络不可用、超时、配置错误、预算超限、Guardrail、工具范围、
  Session 失效及重建后再次失败。
- Provider Session 只作为不透明诊断/续接引用；失效时清除并重建一次，不改变
  `AgentRunRequest`、Context 或业务 Checkpoint。
- `session_ref` 在 Context 输入时于 Transport 前返回
  `RUNTIME_REQUEST_INCONSISTENT`；在 structured output 或 SDK Tool Proposal
  中返回 `RUNTIME_INVALID_OUTPUT`，均不得产生 `COMPLETED` 或泄漏值。
- 共享 Tool Proposal 校验对 `arguments` 与 `resource` 都执行深层扫描；顶层
  强类型 request/result Session 引用继续通过，并被证明不会进入 SDK input JSON。
- LiteLLM 只向 SDK 传递凭据无关请求；OpenAI/Claude Tool 面为空，Claude
  Serializer 的空基础工具和 strict MCP 继续由精确版本测试锁定。
- 所有真实 SDK 形状测试均替换网络入口；`online_provider_calls=0`，没有读取或
  记录真实密钥、Prompt、Trace、PII 或隐藏思考过程。

## 已知问题

- P2：真实在线 Provider Smoke 未运行。这是显式安全/成本策略，不阻断当前
  离线 Conformance；任何启用仍需独立 Realm、测试密钥和成本授权。
- P2：Claude SDK Wheel 携带大型 CLI 且受额外商业条款约束；S5 已完成工程
  许可记录，但生产再分发仍需单独批准。
- P2：内部 Runtime Wheel 单独分发时仍须显式应用根锁；本链的产品组合以根
  Workspace 和 `uv.lock` 为依赖闭包。

## 学习候选

```text
LEARNING_CANDIDATE=强类型私有引用允许不等于未类型化映射允许同名字段
MATURITY=VERIFIED
TRIGGER=S4 黑盒发现 structured_output 内嵌 session_ref 可得到 COMPLETED，而同名字段在 Model Gateway 深层映射中被拒绝
MECHANISM=Agent Runtime 的深层敏感字段集合漏掉 session_ref，且 SDK 与共享 validation 各自维护集合，导致顶层强类型许可被错误扩展到业务 Mapping
STRUCTURE=顶层 AgentRunRequest/Result.session_ref 保持专用强类型通道；所有 Context、structured output、Tool arguments/resource 共用单一深层敏感字段集合失败关闭
EVIDENCE=6f2cbb472dc8e6eed9dccc418c527d39b316ef61；tests/runtime/security/test_provider_session_boundary.py
RESIDUAL_RISK=新增 Provider 私有字段名时仍须同步 Model Gateway 独立边界并增加跨 Port 黑盒
TARGET=ENGINEERING_PLAYBOOK Provider Session 边界章节候选
```

## 接收会话下一步

1. 核验唤醒信封中的 S2 `NEW_HEAD`、本文件 SHA256、ContractSet、线性祖先、
   分支、允许路径和洁净状态，只用 `--ff-only` 精确到达 S2 Head。
2. 恢复原 `M7-04-S4-PROVIDER-REVIEW` / `WP-070-q1`，保留已完成的消费者
   门禁与只读设计；从公共 Adapter/Port 边界复算 Context、structured output、
   Tool arguments/resource 的嵌套 `session_ref` 拒绝，以及顶层强类型正例。
3. 在线 Smoke 保持默认关闭。P0/P1、契约/S3 安全边界、路径越权或未授权
   外部/付费调用须立即停链上报 S1；正常完成后按授权链继续 S5。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M7-LOCAL-PRODUCT-01
STEP_ID=M7-03-S2-SESSION-BOUNDARY-REPAIR
ATTEMPT_ID=WP-070-a2-r1
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=fd7f8418ecf3c9f2dbd4e05f27015b91c535f6ed
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/runtime/evidence/WP-070-a2-HANDOFF.md
NEXT_ROLE=S4-QUALITY
NEXT_ATTEMPT_ID=WP-070-q1
ESCALATE_TO_S1=no
```

## 可回滚方式

- 按逆序 revert 本 Handoff 提交、Session Boundary 修复提交
  `6f2cbb472dc8e6eed9dccc418c527d39b316ef61` 和 Conformance 实现提交
  `45bf8cddcc244ad2c3a0e1aa609e01c0720ed342`；禁止 reset、rebase 或
  force-push。
