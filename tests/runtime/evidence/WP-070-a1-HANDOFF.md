# WP-070-a1 S2-RUNTIME 交接

## 基本信息

- Work Package：WP-070
- Attempt ID：WP-070-a1
- Chain ID：CHAIN-M7-LOCAL-PRODUCT-01
- Step ID：M7-01-S2-PROVIDER
- 责任会话：S2-RUNTIME
- 接收会话：S5-CORE
- 交接策略：CONSUMER_GATE
- 功能 ID：FP-AGT-002、FP-AGT-003、FP-OPS-003、FP-SEC-006
- 基线提交：`b363070194a404cc33764b0ae90275be68c21cb8`
- 实现提交：`e747e73a4aa84186db78d29df53ad3bdf560abbc`
- 分支：`codex/s2/wp-070-provider-runtime-adapters`
- 最终提交：本文件所在提交；精确 SHA 由唤醒信封返回
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：完成，等待 S5 锁定共享依赖并组合装配

## 完成内容

- 新增 LiteLLM `ProviderPort` Adapter，业务层只使用逻辑模型
  `flowpilot.primary.fast`；DeepSeek 官方模型 ID 固定为
  `deepseek-v4-flash`，LiteLLM 路由字符串仅保存在 Adapter 私有配置中。
- 新增 OpenAI Agents SDK 与 Claude Agent SDK `AgentRuntimePort` Adapter，
  统一请求、结构化结果、稳定错误、预算、精确 Usage、Provider Session
  与 Provider Run 引用；每次调用限定在一个可重放 Runtime 节点内。
- Provider Session 无效时仅清除 Provider Session 并重建一次，原业务请求、
  Context 和 Checkpoint 语义不变；第二次失败映射为稳定 Runtime 结果。
- OpenAI Bridge 禁用工具、Handoff 和敏感 Trace；Claude Bridge 禁用工具并
  限制最大轮次。二者均不把 SDK Session 当作业务 Checkpoint。
- 在线 Transport 默认关闭，只有显式启用且存在对应环境变量时才延迟导入
  SDK；Adapter、Transport 和错误对象不保存或返回真实密钥与原始异常文本。
- 新增确定性 LiteLLM/SDK Fake Transport，默认测试零网络、零付费调用，
  覆盖正常、预算、超时、空输出、模型漂移、缺密钥、Session 重建、错误映射
  和敏感字段拒绝。
- 产品适配器保持领域中立；未新增 VPN 路由或业务硬编码。

## 未完成与非目标

- 本 Step 未修改 `pyproject.toml`、`uv.lock`、`Makefile` 或其他共享文件；
  LiteLLM、OpenAI Agents SDK 和 Claude Agent SDK 的版本/许可/锁文件闭包由
  S5 的下一 Step 完成。
- 未执行真实在线 Provider 调用；在线 Smoke 需要显式环境开关、测试密钥和
  独立成本授权，本 Attempt 没有读取密钥或产生付费请求。
- 未装配 Web、API、Worker 产品链，未增加写工具，未修改公共 Contract、
  S3 安全边界、Graph、数据库或 Migration。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/model-gateway/src/flowpilot_model_gateway/litellm_provider.py` | LiteLLM Adapter、DeepSeek 私有映射、Fake/在线 Transport | S2-RUNTIME |
| `packages/model-gateway/src/flowpilot_model_gateway/__init__.py` | 导出新增 Model Gateway API | S2-RUNTIME |
| `packages/agent-runtime/src/flowpilot_agent_runtime/sdk.py` | 统一 SDK Adapter、Fake Transport、错误与 Session 恢复 | S2-RUNTIME |
| `packages/agent-runtime/src/flowpilot_agent_runtime/online_sdk.py` | OpenAI/Claude 延迟导入在线 Bridge | S2-RUNTIME |
| `packages/agent-runtime/src/flowpilot_agent_runtime/__init__.py` | 导出新增 Agent Runtime API | S2-RUNTIME |
| `tests/runtime/contract/test_m7_provider_adapters.py` | Provider/SDK 正常、边界、失败、预算、恢复与 API 形状测试 | S2-RUNTIME |
| `tests/runtime/security/test_m7_provider_security.py` | 缺密钥、默认关闭、凭据泄漏和 Provider 选择负例 | S2-RUNTIME |
| `tests/runtime/integration/test_m7_provider_online_smoke.py` | 显式启用的 DeepSeek 在线 Smoke 入口 | S2-RUNTIME |

## 契约、数据库与配置变化

- 契约版本：无修改；ContractSet 摘要保持不变。
- Migration：无。
- 数据库：无。
- 环境变量：代码消费
  `FLOWPILOT_ENABLE_ONLINE_PROVIDER_SMOKE`、`DEEPSEEK_API_KEY`、
  `OPENAI_API_KEY`、`ANTHROPIC_API_KEY`、
  `FLOWPILOT_OPENAI_AGENTS_MODEL` 和 `FLOWPILOT_CLAUDE_AGENT_MODEL`；未修改
  `.env.example`，未读取或记录任何真实值。
- 兼容性：新增 API 为包内加法；现有 Sandbox Provider、Runtime Port、
  Context、Graph、Worker 和公共 Contract 行为不变。

### DEPENDENCY_REQUEST

```text
REQUEST_ID=WP-070-a1-S2-DEPENDENCY-REQUEST
OWNER=S5-CORE
PACKAGES=litellm;openai-agents;claude-agent-sdk
PURPOSE=锁定 LiteLLM 统一模型路由、OpenAI Agents SDK Runtime、Claude Agent SDK Runtime 的 Python 3.12 兼容版本
LICENSE_REVIEW=由 S5 对精确候选版本、传递依赖和产品分发条款执行并保存证据；S2 不预判许可结论
ALTERNATIVES=直接 Provider HTTP/基础 SDK 会绕过本 Work Package 指定的 LiteLLM 与 Agent SDK 运行语义，当前不采用
ATTACK_SURFACE=新增 Provider 网络客户端、响应解析、环境凭据读取和 SDK 传递依赖；在线路径默认关闭、禁止工具、延迟导入、错误脱敏并受超时/预算约束
LOCK_REQUIREMENTS=不得改变公共 Contract；必须使用 uv 锁定；安装后复跑全仓、契约、安全、审计、构建/导入与三种 Bridge API 形状测试
ONLINE_POLICY=真实在线 Smoke 仍需显式开关、测试 Realm、密钥与成本授权；锁依赖本身不授权外部调用
```

## 验证

验证解释器为 Python 3.12.11；默认门禁没有导入未锁定 SDK，也没有发起网络
请求。

| 命令 | 结果 | 证据 |
|---|---|---|
| `.\\scripts\\quality.ps1 lint` | PASS | Ruff；strict Mypy 119 source files |
| `.\\scripts\\quality.ps1 test-all` | PASS | 764 passed、1 explicit online skip；Contract Conformance PASS |
| `.\\scripts\\quality.ps1 test-security` | PASS | 102 passed |
| `.\\scripts\\quality.ps1 audit` | PASS | 0 known vulnerabilities；editable Workspace 包按入口定义跳过 |
| `pytest tests/runtime -q`（仓库根加入当前进程 `PYTHONPATH`） | PASS | 169 passed、1 explicit online skip |
| M7 三个新增测试文件 | PASS | 35 passed、1 explicit online skip |
| `git diff --check`、路径与共享文件审计 | PASS | 仅授权 S2 路径；Contract/共享文件零变化 |
| 产品路由扫描 | PASS | 仅安全测试中的 `vpn` 否定断言命中，产品源码 0 matches |

Contract Conformance 完整结果：

```text
CONTRACT_CONFORMANCE_OK schemas=20 cases=35 positive=18 negative=17 mutation_cases=19 mutation_positive=3 mutation_negative=16 semantic_cases=43 semantic_positive=0 semantic_negative=43 audit_chain_cases=5 audit_chain_positive=1 audit_chain_negative=4 manifest_cases=21 manifest_positive=1 manifest_negative=20 review_attestation_cases=10 review_attestation_positive=2 review_attestation_negative=8 retired_review_attestation_cases=5 retired_review_attestation_positive=0 retired_review_attestation_negative=5 features=52
```

## 安全与失败路径

- 已验证负向路径：凭据形状输入/输出、Session 引用泄漏、Provider 选择不一致、
  缺失密钥、在线模式未启用、错误模型 ID、空/非法 JSON、Rate Limit、网络/
  超时、预算超限、Guardrail、无效 Session 和第二次恢复失败。
- 在线 Bridge 只返回结构化结果、精确 Usage 和不透明引用；不返回原始异常、
  隐藏思维链、密钥或 SDK 内部对象。
- 生产 Adapter 不保留完整请求历史；只有确定性 Fake Transport 保存已经通过
  凭据边界的调用结构供测试断言。
- Secret/PII 检查：仓库安全入口 102 passed；测试只使用显式 synthetic
  sentinel，并断言其不会进入结果或 Transport 调用参数。

## 已知问题

- P2：三项 Provider SDK 依赖尚未由共享 Workspace 锁定，当前在线实现只通过
  确定性 API 形状 Fake 验证；S5 必须锁定精确版本并复跑导入/构建/API 形状
  门禁后才可装配产品链。
- P2：真实在线 Smoke 未运行。该测试保持默认跳过，以避免未经授权的密钥读取、
  外部网络和付费调用；后续执行需要独立显式授权。
- P3：`pip-audit` 输出了本机缓存反序列化警告，但命令退出 0 且报告
  `No known vulnerabilities found`；不影响本次依赖结论。

## 学习候选

```text
LEARNING_CANDIDATE=none
MATURITY=VERIFIED
TRIGGER=none
MECHANISM=none
STRUCTURE=none
EVIDENCE=e747e73a4aa84186db78d29df53ad3bdf560abbc
RESIDUAL_RISK=none
TARGET=none
```

## 接收会话下一步

1. 核验唤醒信封中的 S2 `NEW_HEAD`、本文件 SHA256、ContractSet、基线祖先、
   分支、写入范围和洁净状态，并只用 `--ff-only` 精确到达 S2 Head。
2. 审查上面的 `DEPENDENCY_REQUEST`，锁定 Python 3.12 兼容的
   `litellm`、`openai-agents`、`claude-agent-sdk` 精确版本；保存许可、传递
   依赖、漏洞和构建/导入证据。
3. 装配逻辑模型 `flowpilot.primary.fast`，不得把 LiteLLM 路由字符串或
   Provider Session 写入公共业务 Contract/Checkpoint；默认保持在线路径关闭。
4. 复跑 Handoff 指定门禁和三种 Bridge API 形状测试；正常完成后按 Chain
   授权继续下一 Step。P0/P1、契约/S3 安全边界/范围异常或新付费调用须停链
   上报 S1。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M7-LOCAL-PRODUCT-01
STEP_ID=M7-01-S2-PROVIDER
ATTEMPT_ID=WP-070-a1
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=b363070194a404cc33764b0ae90275be68c21cb8
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/runtime/evidence/WP-070-a1-HANDOFF.md
NEXT_ROLE=S5-CORE
NEXT_ATTEMPT_ID=WP-070-a1-lock
ESCALATE_TO_S1=no
```

## 可回滚方式

- 按逆序 revert 本 Handoff 提交和实现提交
  `e747e73a4aa84186db78d29df53ad3bdf560abbc`；禁止 reset、rebase 或
  force-push。
