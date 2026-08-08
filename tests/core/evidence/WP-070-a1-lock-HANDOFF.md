# WP-070-a1-lock S5-CORE 依赖锁交接

## 基本信息

- Work Package：WP-070
- Attempt ID：WP-070-a1-lock
- Chain ID：CHAIN-M7-LOCAL-PRODUCT-01
- Step ID：M7-02-S5-LOCK
- 责任会话：S5-CORE
- 接收会话：S2-RUNTIME
- 交接策略：CONSUMER_GATE
- 功能 ID：FP-AGT-002、FP-AGT-003、FP-OPS-003、FP-SEC-006
- 基线提交：`4110cbfd81594ad9de4f885b9fd0cc9691c5f4dd`
- 实现提交：`43215c8e07bea7aa867277b61330bdf12b05ae72`
- 分支：`codex/s5/m7-core-composition`
- 最终提交：本文件所在提交；精确 SHA 由唤醒信封返回
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- Context 模式：DELTA；Context Base
  `c6b250e3b3a5b7df93b60857b5ee438027ee2ff3`
- 状态：完成，等待 S2 消费复核

## 完成内容

- 接受 S2 修复交接：核验修复 Head、Handoff SHA256、线性祖先、ContractSet、
  分支、洁净状态和写入范围后，以 `--ff-only` 精确到达
  `4110cbfd81594ad9de4f885b9fd0cc9691c5f4dd`。
- 在根 Python Workspace 精确锁定实际使用的三项产品依赖：
  `litellm==1.95.0`、`openai-agents==0.19.4`、
  `claude-agent-sdk==0.2.134`；未启用额外 extras。
- 使用 uv 0.12.1 与 Python 3.12.11 重新生成并验证 `uv.lock`。锁文件共
  168 个包，SHA256 为
  `f1c0edb307c3a1346bc291965fec43f3dee7ad8dbf44980534f18b7f4ad3b0a8`。
- 复核新增依赖闭包。相对基线新增 28 个分发包；未发现 GPL/AGPL，许可证
  元数据为 MIT、Apache-2.0、BSD、ISC、PSF-2.0、CNRI-Python 以及
  MPL-2.0/MIT 等已知类别。漏洞审计报告 0 个已知漏洞。
- 构建全部 15 个内部 Workspace wheel；在全新 Python 3.12.11 虚拟环境中
  安装 15 个 wheel 与三项精确 SDK，全部内部模块和 SDK 均可导入。
- 在全新环境离线检查真实 API 形状：`litellm.acompletion`、
  `agents.Agent/RunConfig/Runner.run` 和
  `claude_agent_sdk.ClaudeAgentOptions/query` 可用；Claude CLI Serializer
  保持 `--tools ""`、strict MCP 和空 MCP/Plugin/Agent 面。未启动 Claude
  CLI，未执行 Provider 请求，网络/付费调用数为 0。
- `Makefile` 无需修改；现有稳定入口已覆盖 Workspace 同步、测试、契约、
  安全与审计。

### 依赖决策记录

| 依赖 | 用途 | 许可/条款 | 未采用替代方案 | 主要攻击面与控制 |
|---|---|---|---|---|
| `litellm==1.95.0` | LiteLLM 统一模型路由与 DeepSeek 私有映射 | 包元数据 `MIT` | 直接 Provider HTTP 或单一 Provider SDK；不满足 WP-070 的统一 Provider Adapter 语义 | Provider 网络客户端、环境凭据读取、响应解析；仅锁基础包、不启用 proxy extras，在线路径默认关闭，超时/预算/错误脱敏由 Adapter 约束 |
| `openai-agents==0.19.4` | OpenAI Agents SDK 单节点 Runtime Bridge | `MIT` | 直接 OpenAI SDK 或自建 Agent Loop；会偏离指定 SDK Runtime 语义 | SDK Runtime、网络客户端、Trace/工具面；延迟导入，默认关闭在线调用，tools/handoffs 为空并禁用敏感 Trace |
| `claude-agent-sdk==0.2.134` | Claude Agent SDK 单节点 Runtime Bridge | Python 包为 `MIT`；官方 README 同时声明除单独许可组件外，使用受 Anthropic Commercial Terms 约束 | Anthropic Messages SDK/直接 HTTP；不提供本 WP 指定的 Agent SDK Session/Runtime 语义 | Wheel 约 86.7 MiB，并包含约 274 MiB 的 `claude.exe`；存在子进程、工具、MCP、Plugin、Hook 和设置源面。Bridge 延迟导入且默认关闭，显式清空这些面并以真实 Serializer 测试固定行为 |

上述许可记录是工程依赖审查，不构成法律意见，也不代表已经批准 Claude 捆绑
CLI 的生产再分发；任何对外分发仍须单独确认 Anthropic Commercial Terms。

## 未完成与非目标

- 未执行真实在线 Provider Smoke；其仍要求显式开关、隔离测试 Realm、测试
  密钥和独立成本授权。本 Attempt 未读取真实凭据、未联网调用 Provider、未产生
  付费请求。
- 未修改 S2 Adapter、公共 Contract、S3 安全边界、Graph、API、数据库、
  Migration、部署配置或环境变量文件。
- 未为独立发布的 `flowpilot-agent-runtime` wheel 增加三方依赖声明；本链授权
  只允许 S5 修改根 Workspace 依赖，产品组合以根 `uv.lock` 为安装闭包。
  脱离根 Workspace 单独消费内部 wheel 时，消费者仍须显式应用该锁定集合。
- M7 产品 executor 将在授权链后续 `M7-10-S4-EVALUATION` 实现；因此当前
  发布级 `make acceptance` 不属于本 Step 的退出门禁。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `pyproject.toml` | 精确增加三项 Provider SDK 产品依赖 | S5-CORE（共享 Workspace 单写者） |
| `uv.lock` | 由 uv 0.12.1 复算完整依赖闭包 | S5-CORE（共享 Workspace 单写者） |
| `tests/core/evidence/WP-070-a1-lock-HANDOFF.md` | 本交接与依赖决策证据 | S5-CORE |

## 契约、数据库与配置变化

- 契约版本：无修改；ContractSet 摘要保持不变。
- Migration：无。
- 数据库：无。
- 环境变量：无文件变化、无新增值；在线 Adapter 已声明的变量语义保持不变。
- 兼容性：根 Workspace 增加精确产品依赖；15 个现有内部 wheel 均成功构建、
  安装和导入，公共业务契约与领域边界未放宽。

## 验证

验证解释器为 Python 3.12.11；默认测试均保持在线 Provider Smoke 关闭。

| 命令 | 结果 | 证据 |
|---|---|---|
| `.\\scripts\\quality.ps1 bootstrap` | PASS | 同步 165 个已安装分发包 |
| `uv lock --locked` | PASS | 168 packages；10 ms；锁文件 SHA256 见上 |
| `.\\scripts\\quality.ps1 lint` | PASS | Ruff PASS；strict Mypy 119 source files PASS |
| `.\\scripts\\quality.ps1 test-all` | PASS | 765 passed、1 explicit online skip；Contract Conformance PASS |
| `.\\scripts\\quality.ps1 test-security` | PASS | 102 passed |
| `.\\scripts\\quality.ps1 audit` | PASS | 0 known vulnerabilities；15 个本地 editable FlowPilot 包按审计入口定义跳过 |
| M7 Provider 四个定向测试文件 | PASS | 36 passed、1 explicit online skip |
| `uv build --all-packages --wheel` | PASS | 15/15 Workspace wheels 构建成功 |
| 全新 venv 安装、全模块导入与 SDK API/Serializer 形状检查 | PASS | 15 个内部 wheel + 3 个精确 SDK；`network_calls=0` |
| 高置信 Secret 扫描、`git diff --check`、范围审计 | PASS | 0 matches；仅 `pyproject.toml`、`uv.lock` 和本证据文件 |
| `uv run --frozen python -B scripts/acceptance/run_acceptance.py` | 不适用于本 Step（命令退出 1） | 0 PASS / 156 FAIL，全部为 `EXECUTOR_NOT_REGISTERED`；链路明确在后续 `M7-10-S4-EVALUATION` 注册 executor，不是依赖锁回归或本 Step 退出门禁 |

Contract Conformance 完整结果：

```text
CONTRACT_CONFORMANCE_OK schemas=20 cases=35 positive=18 negative=17 mutation_cases=19 mutation_positive=3 mutation_negative=16 semantic_cases=43 semantic_positive=0 semantic_negative=43 audit_chain_cases=5 audit_chain_positive=1 audit_chain_negative=4 manifest_cases=21 manifest_positive=1 manifest_negative=20 review_attestation_cases=10 review_attestation_positive=2 review_attestation_negative=8 retired_review_attestation_cases=5 retired_review_attestation_positive=0 retired_review_attestation_negative=5 features=52
```

## 安全与失败路径

- 已验证负向路径：默认在线关闭、缺失凭据、Provider 选择漂移、非法/空输出、
  超时、预算、Session 重建、错误脱敏，以及 Claude 默认工具不能因空批准清单而
  重新出现。
- Claude 的基础工具移除由 `tools=[]` 固定；真实 0.2.134 Serializer 证明其
  生成 `--tools ""`。同时固定空 MCP、Plugin、Agent、Hook、Skill 和设置源，
  不把 SDK Session 当作业务 Checkpoint。
- 锁定与验证过程没有启动 SDK CLI、没有执行在线 Provider 调用、没有读取真实
  凭据。唯一跳过项是需要 `FLOWPILOT_ENABLE_ONLINE_PROVIDER_SMOKE=1` 的显式
  在线 Smoke。
- Secret/PII 检查：安全入口 102 passed；变更高置信扫描 0 matches；Handoff
  只记录合成标识与包元数据，不含密钥、PII、Prompt、Trace 或隐藏思考过程。

## 已知问题

- P2：Claude SDK wheel 携带大型 CLI 二进制并受额外商业条款约束。根锁已固定
  版本且漏洞扫描通过，但生产分发/镜像尺寸和商业条款仍须在发布前单独批准。
- P2：真实在线 Provider Smoke 未运行；这是安全与成本策略要求，不阻断当前
  离线依赖锁 Step。
- P2：内部 Runtime wheel 自身未声明三项 SDK；当前产品安装必须从根 Workspace
  与 `uv.lock` 执行，独立 wheel 分发不是本 Step 目标。
- 发布级验收当前因产品 executor 尚未注册而确定性失败；这是链路后续已授权的
  WP-073 工作，不得把本 Handoff 解释为 M7 发布验收通过。

## 学习候选

```text
LEARNING_CANDIDATE=空工具批准清单不等于移除 SDK 基础工具
MATURITY=VERIFIED
TRIGGER=Claude Agent SDK 中仅设置 allowed_tools=[] 时，真实 CLI Serializer 仍保留默认 Read/Write/Edit/Bash 等基础工具
MECHANISM=allowed_tools 是自动批准列表，不控制基础工具集合；只清空该列表会形成误以为工具被禁用的安全缺口
STRUCTURE=同时固定 tools=[]、空 allowed/disallowed 列表、空 MCP/Plugin/Agent/Hook/Skill/设置源与 strict MCP，并用精确版本真实 Serializer 断言 --tools 后为空字符串
EVIDENCE=de0772389d54a896445bb16fac8fb1910416a8af；tests/runtime/contract/test_claude_agent_sdk_real_shape.py；本 Handoff 全新环境 Serializer 验证
RESIDUAL_RISK=SDK 升级可能改变 CLI 序列化语义；升级时必须重新运行真实 Wheel 形状测试
TARGET=ENGINEERING_PLAYBOOK SDK 安全适配章节候选
```

## 接收会话下一步

1. 核验 S5 `NEW_HEAD`、本文件 SHA256、ContractSet、线性祖先、分支、范围和
   洁净状态，只用 `--ff-only` 精确到达 S5 Head。
2. 进入 `M7-03-S2-CONFORMANCE` / `WP-070-a2`，使用根锁环境复跑真实三方 SDK
   的 Provider Conformance、稳定错误、Session 重建、预算、默认关闭和工具面
   负向测试；不得修改共享文件或公共 Contract。
3. 在线 Smoke 保持默认关闭。只有获得显式 Realm、测试密钥和成本授权后才可
   启用；P0/P1、契约/S3 边界、路径越权或未授权付费调用立即停链上报 S1。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M7-LOCAL-PRODUCT-01
STEP_ID=M7-02-S5-LOCK
ATTEMPT_ID=WP-070-a1-lock
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=4110cbfd81594ad9de4f885b9fd0cc9691c5f4dd
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/core/evidence/WP-070-a1-lock-HANDOFF.md
NEXT_ROLE=S2-RUNTIME
NEXT_ATTEMPT_ID=WP-070-a2
ESCALATE_TO_S1=no
```

## 可回滚方式

- 按逆序 revert 本 Handoff 提交与实现提交
  `43215c8e07bea7aa867277b61330bdf12b05ae72`；禁止 reset、rebase 或
  force-push。回滚会移除三项根依赖并恢复上一版锁文件。
