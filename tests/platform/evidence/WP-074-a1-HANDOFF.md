# WP-074-a1 S3-PLATFORM 集中凭据识别内核交接

## 基本信息

- Work Package：WP-074
- Attempt ID：WP-074-a1
- Chain ID：CHAIN-M7-LOCAL-PRODUCT-01
- Step ID：M7-SEC-01-S3-CREDENTIAL-REGISTRY
- Agent ID：credential-guard-builder
- 责任会话：S3-PLATFORM
- 接收会话：S5-CORE
- 交接策略：CONSUMER_GATE
- 风险与严重度：R3 / P0；S1 人工架构修复派发
- 功能 ID：FP-SEC-002、FP-SEC-006
- 输入提交：`994dc0bfb73d8403e4c1cfc2a4faaa458d1c6b26`
- 实现提交：`4c1388e992617b7e0a20e5d9dd96a599143faf0f`
- 分支：`codex/s3/wp-074-security-scanner`
- 最终提交：本文件所在提交；精确 SHA 由唤醒信封返回
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 输入证据：`tests/core/evidence/WP-072-sse-token-family-r3-HANDOFF.md`
- 输出状态：PASS_HANDOFF

## DELTA 上下文与授权

- `CONTEXT_MODE=DELTA`
- `CONTEXT_BASE_COMMIT=994dc0bfb73d8403e4c1cfc2a4faaa458d1c6b26`
- `CONTEXT_TARGET_COMMIT=994dc0bfb73d8403e4c1cfc2a4faaa458d1c6b26`
- Base 与 Target 精确相同且祖先校验通过；强制基线文档变化为 0，未触发 FULL。
- 已读取当前 Chain Authorization、Agent Registry、增量上下文协议和直接输入证据。
- 仓库 Registry 原链风险上限为 R2；本 P0 按协议退出自动注册链，并由 S1 通过
  `ORDERED_ARCH_REPAIR` 信封人工派发 S3 Owner，未自行提升权限或风险上限。
- 写入范围保持为 `packages/security/**`、`tests/platform/**`。

## 完成内容

- 新增纯标准库、确定性、无副作用的集中凭据识别内核：
  - 冻结的 `CredentialFamily` 元数据与 tuple 注册表 `CREDENTIAL_FAMILIES`。
  - 冻结的 `SecretFinding`，字段严格只有 `family_id` 和结构化 `path`。
  - `scan_secret_material(value, field=...)` 和
    `assert_no_secret_material(value, field=...)` 稳定 API。
- 递归扫描 Mapping 的键和值、Sequence、ASCII bytes-like 值；循环容器按 identity
  去重，避免无限递归。
- Finding 路径只使用 Mapping entry/Sequence 索引，不复制原始键；异常只包含
  family ID 和安全路径，不保留或输出匹配原值。
- 注册表覆盖：
  - AWS `AKIA` / `ASIA`。
  - OpenAI legacy、project、admin、service-account。
  - Anthropic `sk-ant`。
  - Slack `xox*` 与 `xapp-1` 形态。
  - GitHub classic `gh*` 注册前缀与 `github_pat`。
  - Bearer、Basic、JWT、常见 credential assignment/字段名、credential URI。
  - RSA、EC、OPENSSH、DSA、generic 与 ENCRYPTED PRIVATE KEY 头。
- `assert_safe_projection` 保留原有禁止字段和 `SecurityErrorCode.UNSAFE_PROJECTION`
  行为，同时移除自己的凭据正则副本并包装同一集中注册表。

## 未完成与非目标

- 未修改 `contracts/**`、Schema、ADR、公共 API 契约或 ContractSet。
- 未迁移 `packages/application/**`、`packages/persistence/**`、
  `packages/evaluation/**`；本步遵守 S1 指令只交付安全内核与 Platform 证据。
- 未修改 Python Workspace、`pyproject.toml`、`uv.lock`、`Makefile` 或依赖。
- 未连接真实 Provider、企业系统或外部网络，未使用真实凭据。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/security/src/flowpilot_security/credentials.py` | 集中 registry、Finding、递归扫描与失败关闭 API | S3 |
| `packages/security/src/flowpilot_security/safety.py` | `assert_safe_projection` 兼容包装 | S3 |
| `packages/security/src/flowpilot_security/__init__.py` | 导出稳定 API | S3 |
| `tests/platform/test_credential_registry.py` | family、误报、嵌套、循环、泄漏与兼容测试 | S3 |
| `tests/platform/evidence/WP-074-a1-HANDOFF.md` | 本交接证据 | S3 |

## 契约、数据库、依赖与配置变化

- ContractSet、JSON Schema、OpenAPI：无变化；Conformance PASS。
- Migration、PostgreSQL、Redis：无变化。
- Python Workspace 与锁文件：无变化。
- 新生产依赖：无；新内核只依赖标准库和本包既有 `errors` 模块。
- 依赖方向：新内核不依赖 application、API、persistence、runtime；Domain 未新增
  对 Security 的依赖。

## 验证

| 命令 | 结果 |
|---|---|
| `uv run --all-packages --all-groups --locked python -B -m pytest tests/platform/test_credential_registry.py tests/platform/test_contracts_and_policy.py tests/platform/test_observability.py -q` | PASS；74 passed |
| `uv run --all-packages --all-groups --locked python -B -m pytest tests/platform -q` | PASS；147 passed |
| `uv run --all-packages --all-groups --locked ruff check packages/security/src tests/platform` | PASS |
| `uv run --all-packages --all-groups --locked mypy --strict packages/security/src` | PASS；6 source files |
| `.\scripts\quality.ps1 lint` | PASS；Ruff + strict Mypy 126 source files |
| `.\scripts\quality.ps1 test-security` | PASS；160 passed |
| `.\scripts\quality.ps1 test-contract` | PASS；20 schemas / 35 cases / 43 semantic cases / 52 features |
| `git diff --check`、授权路径、Contract tree 差异 | PASS；仅 S3 授权路径，Contract tree 零变化 |

首次直接调用桌面宿主 `python` 时因该精简解释器没有 pytest/ruff/mypy 而未执行；
随后全部门禁通过仓库锁定的 `uv --all-packages --all-groups --locked` 环境复现，
没有把宿主环境缺包计为产品测试失败或 PASS。

## 安全与失败路径

- 每个注册 family 均有独立正例和相邻误报负例，注册表增项漏测会直接失败。
- P0 复现族 ASIA、OpenAI admin、Slack xapp 与 ENCRYPTED PRIVATE KEY 全部失败关闭。
- Mapping 凭据键、嵌套值、tuple/list、循环引用和 bytes-like 值使用同一扫描入口。
- Finding、`str(exception)`、`repr(exception)` 与日志捕获均验证不含匹配原值；把
  原值恶意放入 `field` 也只产生安全根路径。
- `password_policy`、短 provider 前缀、PUBLIC KEY、无密码 URI 和普通短授权文本
  保持不命中，避免以无限宽前缀替代 family 语法。
- 既有 `assert_safe_projection` 正常投影继续通过；禁止字段和新增 family 均保持
  `PLATFORM_UNSAFE_PROJECTION` 失败关闭。

## 已知风险

- `packages/application/task_events.py`、Persistence 与 Evaluation 中仍存在各自的
  重复扫描器；这是本次架构修复的输入事实，不代表这些消费者已迁移。
- S5 必须在下一步先把 TaskEvent 构造、stream emit/replay/subscriber 与 SSE frame
  统一接入本 API；在其消费者门禁完成前，P0 端到端污染路径仍不能宣告关闭。
- Provider 后续增加凭据 family 时必须更新集中注册表并补齐正例/相邻负例，不能在
  消费者中追加样本正则。

## 学习候选

```text
LEARNING_CANDIDATE=Secret Finding 的路径本身也必须脱敏
MATURITY=IMPLEMENTED
TRIGGER=Mapping key 可以直接是凭据；把原始 key 拼入 path 会通过 Finding、异常或 repr 二次泄漏
MECHANISM=递归扫描若使用业务 key 构造路径，即使不返回 regex match，仍会在诊断对象中复制匹配原值
STRUCTURE=family registry + 结构索引路径 + finding 仅 family_id/path + safe field root + exception/repr/log 负例
EVIDENCE=packages/security/src/flowpilot_security/credentials.py；tests/platform/test_credential_registry.py
RESIDUAL_RISK=消费者不得绕过 Finding 自行记录待扫描对象或原始 Mapping key
TARGET=ENGINEERING_PLAYBOOK 安全投影与凭据扫描候选
```

## S5-CORE 下一步

1. 核验最终 Head、本 Handoff SHA256、ContractSet、线性祖先、范围和 clean，只用
   `--ff-only` 到达精确 Head。
2. 在 S5 所有权内让 Application Workspace 显式依赖 `flowpilot-security`，刷新
   `pyproject.toml` / `uv.lock`，不得复制注册表。
3. 将 TaskEvent 构造、stream emit/replay/subscriber 与 SSE frame 的凭据值扫描统一
   到 `assert_no_secret_material`；保留 TaskEvent Schema、producer、敏感字段和
   tenant 权威校验。
4. 复现 ASIA、OpenAI admin、Slack xapp、ENCRYPTED PRIVATE KEY 在构造、入流、
   subscriber、replay 和 SSE 的成功污染数均为 0，并覆盖原值不进入异常/日志。
5. 不迁移 Persistence/Evaluation；公共契约、依赖环、路径越权或新 P0/P1 时停链回 S1。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M7-LOCAL-PRODUCT-01
STEP_ID=M7-SEC-01-S3-CREDENTIAL-REGISTRY
ATTEMPT_ID=WP-074-a1
AGENT_ID=credential-guard-builder
NEW_HEAD=<this-handoff-commit>
IMPLEMENTATION_HEAD=4c1388e992617b7e0a20e5d9dd96a599143faf0f
BASE_COMMIT=994dc0bfb73d8403e4c1cfc2a4faaa458d1c6b26
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/platform/evidence/WP-074-a1-HANDOFF.md
NEXT_ROLE=S5-CORE
ESCALATE_TO_S1=no
```

## 可回滚方式

- 依次 revert 本 Handoff 提交和实现提交
  `4c1388e992617b7e0a20e5d9dd96a599143faf0f`；禁止 reset、rebase 或 force-push。
