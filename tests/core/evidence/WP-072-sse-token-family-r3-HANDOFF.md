# WP-072-sse-r3 S5-CORE Task Event Token Family 安全交接

## 基本信息

- Work Package：WP-072
- Attempt ID：WP-072-sse-r3
- Chain ID：CHAIN-M7-LOCAL-PRODUCT-01
- Step ID：M7-09R3-S5-SSE-TOKEN-FAMILY
- 责任会话：S5-CORE
- 接收会话：S4-QUALITY
- 交接策略：CONSUMER_GATE
- 功能 ID：FP-SEC-002、FP-OBS-001
- 输入提交：`aab97e1d80834c164da5d632750523f6378d26e5`
- 分支：`codex/s5/m7-core-composition`
- 最终提交：本文件所在提交；精确 SHA 由唤醒信封返回
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 上游 Handoff：`tests/runtime/evidence/WP-072-studio-security-r3-HANDOFF.md`
- 上游 Handoff SHA256：
  `sha256:444447c4088b1ae1d8b02283ffc87c7db8ac6b87167b72ee8792f01f875b0518`
- 状态：PASS_HANDOFF

## 完成内容

- 将单一宽泛凭据前缀表达式替换为 13 个命名、可独立测试的 Token/Secret
  语法族：
  - OpenAI legacy `sk-`、project `sk-proj-`、service account
    `sk-svcacct-` 长 Token。
  - Slack `xox[baprs]-` 多分段 Token；允许短版本段，但要求至少两个分段且
    总 Token body 足够长。
  - GitHub classic `gh[pousr]_` 与 fine-grained `github_pat_`。
  - Bearer、Basic、AWS access key、私钥头、JWT、敏感 key/value 与凭据 URI。
- 同一中央扫描器继续覆盖 Envelope 的 event/tenant/task/thread/trace/run、
  correlation/causation、producer principal 等全部可变输出字符串，以及 payload/ref
  任意嵌套 Mapping/Sequence 字符串。
- 保留 r2 的 opaque URI、字段名敏感扫描、Schema 精确 payload/producer、Tenant
  emit 门禁与构造/emit/SSE 三层重验证。
- 增加全部命名 family 的构造负例、Slack/GitHub 前缀变体、九个 Envelope 字符串
  位置、payload nested sequence、opaque ref 与 stream/SSE 零污染矩阵。
- 普通连字符业务 ID 正例保持通过；没有把任意含连字符的字符串当作 Token。

## 未完成与非目标

- 不修改 `contracts/**`、公共 task-event.v1、API 形状或字段语义。
- 不修改 S2 Runtime/Graph、S4 Web/acceptance、S3 Policy 或 S6 Persistence。
- 不更新 `tests/acceptance/studio` 的旧 oracle；继续由下一 S4 步骤更新和组合复算。
- 未执行在线 Provider、真实凭据、外部网络或付费调用。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/application/src/flowpilot_application/task_events.py` | 13 类命名 Token/Secret 语法族及统一扫描 | S5-CORE |
| `tests/core/test_event_security.py` | family、字段位置、nested/ref、零污染与业务 ID 正例 | S5-CORE |
| `tests/core/evidence/WP-072-sse-token-family-r3-HANDOFF.md` | 本交接证据 | S5-CORE |

## 契约、数据库、依赖与配置变化

- ContractSet、JSON Schema、OpenAPI：无变化；Conformance PASS。
- Migration、PostgreSQL、Redis：无变化。
- `pyproject.toml`、`uv.lock`、`Makefile`、环境变量：无变化。
- 新生产依赖：无。
- API 公共形状：无变化；仅将已识别的凭据语法族收窄为失败关闭。

## 复现与修复证据

修复前独立复现：

```text
OPENAI_PROJECT_TOP_LEVEL_CONSTRUCTED=True
OPENAI_SERVICE_TOP_LEVEL_CONSTRUCTED=True
SLACK_MULTISEGMENT_TOP_LEVEL_CONSTRUCTED=True
GITHUB_FINE_GRAINED_TOP_LEVEL_CONSTRUCTED=True
TOKEN_FAMILY_DELIVERED=True
SUBSCRIBER_POLLUTED=True
REPLAY_POLLUTED=True
TOKEN_FAMILY_SSE=True
```

修复后相同复现：

```text
OPENAI_PROJECT_TOP_LEVEL_CONSTRUCTED=False
OPENAI_SERVICE_TOP_LEVEL_CONSTRUCTED=False
SLACK_MULTISEGMENT_TOP_LEVEL_CONSTRUCTED=False
GITHUB_FINE_GRAINED_TOP_LEVEL_CONSTRUCTED=False
TOKEN_FAMILY_DELIVERED=False
SUBSCRIBER_POLLUTED=False
REPLAY_POLLUTED=False
TOKEN_FAMILY_SSE=False
```

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| Task Event 定向安全矩阵 | PASS；135 passed | 13 family、provider 前缀变体、九个顶层位置、nested/ref 和三层零污染 |
| Core | PASS；223 passed | 领域/Application/API 回归 |
| `.\scripts\quality.ps1 lint` | PASS | Ruff；strict Mypy 125 source files |
| `.\scripts\quality.ps1 test-contract` | PASS | 20 schemas / 35 cases / 43 semantic cases / 52 features |
| `.\scripts\quality.ps1 test-security` | PASS；160 passed | 配置的跨角色安全集合与 Web Secret 扫描 |
| `.\scripts\quality.ps1 audit` | PASS | 0 known vulnerabilities；editable Workspace 包按入口定义跳过 |
| 全仓稳定闭包（`--ignore=tests/acceptance/studio`） | PASS；1025 passed、1 explicit online skip | 包含 S2 r3 真实 Server 与 S5 r3 Token family 测试 |
| Application/API wheel | PASS；2/2 | `flowpilot_application-0.1.0`、`flowpilot_api-0.1.0` |
| S5 变化文件高置信 Secret 扫描 | PASS；0 matches | Token 测试数据由分段合成，不写入密钥形态字面量 |
| `git diff --check`、路径范围 | PASS | 仅 S5 授权路径 |

## 安全与失败路径

- 构造负例：13 个命名语法族以及 assignment 的关键敏感字段变体。
- 顶层负例：event/tenant/task/thread/trace/run、producer principal、correlation、
  causation 的 Token-like 值全部失败关闭。
- payload/ref 负例：任意 nested sequence 字符串与 opaque `result_ref` 内嵌 Token
  均失败关闭。
- 入流/SSE 负例：每个命名 family 的 subscriber queue=0、replay=0、partial frame=0。
- 正例：合法 task-event 分支、opaque URI、普通连字符业务 ID、既有产品 ref scheme
  和可选空 ref 保持兼容。
- 跨租户：route tenant 与 event tenant 不一致时成功交付继续为 0。

## 已知问题

- S4 现有 `tests/acceptance/studio` oracle 仍待其所有者按 S2 r3 的空状态/历史失败
  关闭语义更新；本 Attempt 按上游声明运行稳定闭包，没有越权修改或把该目录计为
  PASS。
- 在线 Provider Smoke 未授权，保持显式 skip。
- 返修预算：本轮已经把扫描从样本正则提升为集中命名语法族。若 S4 再发现同类
  Token family 等价绕过，必须停链向 S1 提议集中验证器重构，不追加第四轮样本。

## 学习候选

```text
LEARNING_CANDIDATE=凭据扫描必须按 Token family 的完整语法建模
MATURITY=VERIFIED
TRIGGER=单一 sk/gh/xox 前缀加连续字母数字表达式遗漏 namespaced、service-account 和多分段 Token
MECHANISM=把多个 Provider 压进一个单段正则会丢失各自的 prefix、separator、segment 与长度语义；合法字段和值扫描虽已覆盖，family 本身仍可穿透
STRUCTURE=命名 family registry + 每族正例 + provider prefix 变体 + 所有输出位置/nested/ref/emit/SSE 同一中央扫描 + 普通业务 ID 反误报
EVIDENCE=tests/core/test_event_security.py；WP-072-sse-r3 提交
RESIDUAL_RISK=Provider 引入新 Token family 时必须作为命名 family 添加并复跑全边界矩阵；等价绕过不再以单样本补丁处理
TARGET=ENGINEERING_PLAYBOOK Event/SSE 凭据语法族候选
```

## 接收会话下一步

1. 核验 S5 精确 `NEW_HEAD`、本文件 SHA256、ContractSet、线性祖先、范围与 clean，
   只用 `--ff-only` 到达精确 Head。
2. 恢复原 `WP-072-a1`，更新 S4 Studio oracle 以匹配 S2 r3 的 Resume/Interrupt
   绑定与空状态/历史失败关闭，不得放宽 Runtime 权威边界。
3. 组合复算：错序 Resume 与 update_state 绕过=0、跨租户 SSE=0、全部 Token
   family SSE=0、subscriber/replay/frame 污染=0，并继续 Web/SSE 验收。
4. 若发现新的等价 Token family 绕过，按返修预算停链向 S1 提议集中验证器重构；
   其他 P0/P1、Contract 变化、越权或新门禁失败同样停链上报。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M7-LOCAL-PRODUCT-01
STEP_ID=M7-09R3-S5-SSE-TOKEN-FAMILY
ATTEMPT_ID=WP-072-sse-r3
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=aab97e1d80834c164da5d632750523f6378d26e5
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/core/evidence/WP-072-sse-token-family-r3-HANDOFF.md
NEXT_ROLE=S4-QUALITY
NEXT_ATTEMPT_ID=WP-072-a1
ESCALATE_TO_S1=no
```

## 可回滚方式

- Revert 本 Handoff 所在提交；禁止 reset、rebase 或 force-push。
