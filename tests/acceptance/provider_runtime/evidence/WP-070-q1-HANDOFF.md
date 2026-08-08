# WP-070-q1 S4-QUALITY Provider Runtime 离线黑盒交接

## 基本信息

- Work Package：WP-070
- Attempt ID：WP-070-q1
- Repair Attempt ID：WP-070-a2-r1
- Chain ID：CHAIN-M7-LOCAL-PRODUCT-01
- Step ID：M7-04-S4-PROVIDER-REVIEW
- DEDUP Key：`CHAIN-M7-LOCAL-PRODUCT-01/M7-04-S4-PROVIDER-REVIEW/WP-070-q1/aa3842ab746942eda6751dbff3a6619d4bfac9fb`
- 责任会话：S4-QUALITY
- 接收会话：S5-CORE
- 交接策略：CONSUMER_GATE
- 功能 ID：FP-AGT-002、FP-AGT-003、FP-OPS-003、FP-SEC-006
- 基线提交：`aa3842ab746942eda6751dbff3a6619d4bfac9fb`
- 实现提交：`e0cc0dafea997370928cec646d5981d8035b2a18`
- 分支/最终提交：`codex/s4/m7-experience-evaluation`；本文件所在提交，精确 SHA 由唤醒信封提供
- ContractSet 摘要：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：完成，等待 S5 消费门禁

## 完成内容

- 从公开 `ProviderPort`、`AgentRuntimePort` 和三种 Online Transport 构造器建立
  31 项独立离线黑盒；不导入 `tests/runtime/**` Fixture，也不调用真实 Provider。
- 验证在线开关只接受精确值 `1`；默认关闭和缺密钥路径在 SDK 模块加载前失败
  关闭。所有真实 SDK 入口均由 Tripwire 或合成模块替换。
- 验证 LiteLLM、OpenAI Agents 和 Claude Agent 的超时、限流、空输出、非法
  JSON、硬预算与稳定错误映射。失败结果不能保留伪成功输出或 Session。
- 验证 Provider Session 失效只重建一次，调用序列严格为旧 Session、空 Session；
  业务调用指纹不变，原始请求不被修改。
- 独立复算 S4 原 P1：Context、structured output、Tool arguments、Tool resource
  深层 `session_ref` 均失败关闭且不泄漏值；顶层强类型 Request/Result Session
  通道继续可用，并且 Session 不进入业务 `input_json`。
- 验证 Runtime 与 LiteLLM 的凭据形状输入在 Transport 前拒绝，凭据形状输出
  被清空；合成凭据不进入公开结果、错误或捕获参数。
- 验证 OpenAI 的 Tool/Handoff 为空且敏感 Trace 关闭；Claude 的基础 Tool、
  MCP、Plugin、Agent、Hook、Skill、设置源均为空或关闭，strict MCP 生效。

## 未完成与非目标

- 未执行真实在线 Provider Smoke、未读取真实凭据、未启动真实 Claude CLI、未
  产生 Provider 或付费调用。该 Smoke 仍需隔离 Realm、测试密钥和成本授权。
- 本 Step 不是 M7 发布门禁，未宣称 156 Case 固定分母、模型质量数字、Token
  提升、VERIFIED 或 RELEASED；这些属于 WP-073/S7/S1。
- 未修改 Production、Contract、ADR、Workspace/Lock、Makefile、数据库、
  Migration、S3 安全边界或其他角色路径。
- 未重新执行依赖审计；S2 输入 Handoff 的根锁审计为 PASS，且本 Step 没有依赖
  变化。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `tests/acceptance/provider_runtime/blackbox.py` | S4 独立请求工厂、调用指纹与公开 Adapter 选择 | S4-QUALITY |
| `tests/acceptance/provider_runtime/test_provider_runtime_blackbox.py` | 31 项离线黑盒与安全负例 | S4-QUALITY |
| `tests/acceptance/provider_runtime/evidence/WP-070-q1-PROOF.json` | 机器可读门禁与范围证据 | S4-QUALITY |
| `tests/acceptance/provider_runtime/evidence/WP-070-q1-HANDOFF.md` | 本交接 | S4-QUALITY |

## 契约、数据库与配置变化

- 契约版本 / ContractSet：无变化；摘要与输入一致。
- Migration / 数据库 / RLS / Outbox：无变化。
- `pyproject.toml` / `uv.lock` / Makefile / 环境变量文件：无变化。
- 兼容性：只消费 S2 已交付公开 Python Port；没有复制、扩展或放宽公共枚举。

## 验证

环境：Windows、CPython 3.12.11；真实在线 Provider Smoke 默认关闭。

| 命令 | 结果 | 证据 |
|---|---|---|
| `uv run --all-packages --all-groups --locked python -B -m pytest tests/acceptance/provider_runtime -q` | PASS：31 passed | `WP-070-q1-PROOF.json` |
| `uv run --all-packages --all-groups --locked python -B -m pytest tests/acceptance -q` | PASS：264 passed | 同上 |
| `powershell -NoProfile -File scripts/quality.ps1 test` | PASS：815 passed、1 explicit online skip | 同上 |
| `powershell -NoProfile -File scripts/quality.ps1 test-security` | PASS：114 passed | 同上 |
| `uv run --all-packages --all-groups --locked python -B contracts/conformance/validate.py` | PASS：20 Schema、35 Case、43 语义负例、52 Feature | 同上 |
| `powershell -NoProfile -File scripts/quality.ps1 lint` | PASS：Ruff；strict Mypy 119 source files | 同上 |
| `make acceptance` | NOT_RUN：M7 发布固定分母门禁属于 WP-073 | 同上 |

Contract Conformance：

```text
CONTRACT_CONFORMANCE_OK schemas=20 cases=35 positive=18 negative=17 mutation_cases=19 mutation_positive=3 mutation_negative=16 semantic_cases=43 semantic_positive=0 semantic_negative=43 audit_chain_cases=5 audit_chain_positive=1 audit_chain_negative=4 manifest_cases=21 manifest_positive=1 manifest_negative=20 review_attestation_cases=10 review_attestation_positive=2 review_attestation_negative=8 retired_review_attestation_cases=5 retired_review_attestation_positive=0 retired_review_attestation_negative=5 features=52
```

## 安全与失败路径

- 默认在线关闭和缺密钥时，三种 Online Transport 均在模块加载前返回稳定配置
  错误；S4 Acceptance 的真实 SDK/Provider 网络调用为 0。
- 超时与限流只映射为 retryable unavailable；空/非法输出、凭据和私有 Session
  映射为终态错误；硬预算超限不能被输出内容提升为成功。
- Provider Session 重建不改变业务调用、Task、Context、模型或预算，也不形成
  第二 Checkpoint；本黑盒观测到的调用序列严格限制为两次。
- S4 测试只使用合成密钥，Secret Scan 与结果投影暴露数为 0。
- 只读 SDK 形状子 Agent曾导入 LiteLLM，导入过程尝试获取公共 GitHub model-cost
  元数据并超时回退本地；没有 Provider/付费调用。S4 测试因此禁止真实 SDK 导入，
  始终注入 Fake Module。该事实已保存在 Proof，未宣称整个 Attempt 零网络尝试。

## 已知问题

- P2：真实在线 Provider Smoke 未授权执行，模型质量与真实 Endpoint 行为仍未验证。
- P2：`from_environment()` 默认关闭测试通过替换实例 `_module_loader` 设置 Tripwire，
  对实现字段名存在轻微测试耦合；字段漂移会显式失败，不会静默触网。
- P2：LiteLLM 导入可能尝试获取公共模型成本元数据；隔离发行环境需预置本地数据
  或显式阻断该请求，不能把“未调用 completion”误当作完全无网络。
- P2：Claude CLI 生产再分发与独立 Runtime Wheel 根锁应用仍是 S2 已登记风险。

## 学习候选

```text
LEARNING_CANDIDATE=none
MATURITY=VERIFIED
TRIGGER=none
MECHANISM=none
STRUCTURE=none
EVIDENCE=tests/acceptance/provider_runtime/evidence/WP-070-q1-PROOF.json
RESIDUAL_RISK=none
TARGET=none
```

## 接收会话下一步

1. 核验 S4 `NEW_HEAD`、本 Handoff Hash、ContractSet、`aa3842ab...` 到
   `NEW_HEAD` 的线性祖先、分支、授权路径和 clean 状态。
2. 仅用 `--ff-only` 精确到达 S4 `NEW_HEAD`；未精确到达立即停链。
3. 按 `WP-071-a1-core` 消费统一 Provider/Runtime Port，保持 Online Smoke 默认
   关闭；不得把本离线黑盒外推为真实模型质量或发布成功率。
4. 正常完成后按链路继续下一已授权角色；P0/P1、Contract/S3 边界、越权路径或
   未授权 Provider/付费调用须停链上报 S1。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M7-LOCAL-PRODUCT-01
STEP_ID=M7-04-S4-PROVIDER-REVIEW
ATTEMPT_ID=WP-070-q1
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=aa3842ab746942eda6751dbff3a6619d4bfac9fb
INPUT_HEAD=aa3842ab746942eda6751dbff3a6619d4bfac9fb
IMPLEMENTATION_HEAD=e0cc0dafea997370928cec646d5981d8035b2a18
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/acceptance/provider_runtime/evidence/WP-070-q1-HANDOFF.md
NEXT_ROLE=S5-CORE
NEXT_ATTEMPT_ID=WP-071-a1-core
ESCALATE_TO_S1=no
```

## 可回滚方式

- 按逆序 `git revert` 本 Handoff 提交、格式清理提交和实现提交；禁止 reset、
  rebase 或 force-push。
- 本 Step 没有数据库、外部系统或生产数据写入，无数据回滚。
