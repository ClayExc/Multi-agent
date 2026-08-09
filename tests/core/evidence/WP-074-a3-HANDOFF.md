# WP-074-a3 S5-CORE 安全 TaskEvent 错误交接

## 基本信息

- Work Package：WP-074
- Attempt ID：WP-074-a3
- Chain ID：CHAIN-M7-LOCAL-PRODUCT-01
- Step ID：M7-SEC-07-S5-SAFE-EVENT-ERRORS
- 责任会话：S5-CORE
- 接收会话：S4-QUALITY
- 交接策略：CONSUMER_GATE
- 风险与严重度：R3 / P0；S1 架构修复链
- 功能 ID：FP-SEC-002、FP-SEC-006
- 基线提交：`1afb1acf2aa3c5bcd7ca5dee0e6964930cf0ca38`
- 上游 S3 Handoff：`tests/platform/evidence/WP-074-a2-HANDOFF.md`
- 上游 Handoff SHA256：
  `sha256:ca8bf8a4cf2bc0ba8e344b0ac19cdd88b8648dda482b20baba9401d56ead3dcc`
- 分支：`codex/s5/m7-core-composition`
- 最终提交：本文件所在提交；精确 SHA 由消费者唤醒信封返回
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：完成
- 消费者裁决：`CONSUMER_VERDICT=ACCEPT`

## 完成内容

- 核验 S3 精确 Head、Handoff Hash、ContractSet、线性祖先、上游范围与 clean 后，
  只使用 `--ff-only` 到达输入提交。
- 新增 Application 内部稳定 `TaskEventErrorCode` 与 `TaskEventValidationError`：
  - 对外字符串严格只有稳定 code、结构 path 和 count。
  - path 只接受固定结构片段及数字索引，非法 path 降级为 `task_event`。
  - 保持 `ValueError` 子类兼容，不改变公共 JSON Schema 或跨进程 Contract。
- payload additional/missing 字段只报告数量，不再拼接字段名；字段类型、格式、ref、
  producer 与 Envelope shape 使用稳定安全码。
- TaskEvent payload 冻结与隐藏投影递归路径统一为 `keys[n]` / `values[n]`，不把未知
  Mapping key 复制到异常、repr 或日志。
- S3 `assert_no_secret_material` 仍是内容验证第一道门禁；没有复制、扩展或弱化凭据
  family，offset-safe Scanner 对 Envelope、payload、stream/replay 和 SSE 继续生效。
- Stream route/type/tenant mismatch 和 SSE shape/serialization 错误在任一 queue、replay
  或 frame 写出前转为同一稳定安全错误；原 tenant、Schema、producer 与 opaque ref
  门禁保持不变。
- 新增 construction -> emit -> subscriber -> replay -> SSE 组合负例，成功污染数均为 0；
  `str(exc)`、`repr(exc)` 与捕获日志均不包含未知原始 key/value。

## 未完成与非目标

- 未修改 `contracts/**`、Runtime、Security、Persistence 或 Evaluation。
- 未迁移 Persistence/Evaluation 的错误投影；未创建第二套凭据 Scanner。
- 未启用外部网络、真实 Provider、真实凭据或付费调用。
- S4 独立黑盒复核尚未执行，本 Handoff 不替代消费者验收。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/application/src/flowpilot_application/errors.py` | 稳定 TaskEvent 安全错误码与结构化异常 | S5 |
| `packages/application/src/flowpilot_application/task_events.py` | count-only Schema 错误、结构路径与集中 Scanner 顺序 | S5 |
| `packages/application/src/flowpilot_application/models.py` | 安全 payload 冻结、构造与 Envelope 重验 | S5 |
| `packages/application/src/flowpilot_application/__init__.py` | 导出内部稳定错误类型 | S5 |
| `apps/api/src/flowpilot_api/stream.py` | route/type/tenant 错误稳定化及写前失败关闭 | S5 |
| `apps/api/src/flowpilot_api/app.py` | SSE frame 生成前 shape/serialization 安全错误 | S5 |
| `tests/core/test_event_security.py` | 原值零泄漏与五边界零污染矩阵 | S5 |
| `tests/core/evidence/WP-074-a3-HANDOFF.md` | 本交接证据 | S5 |

## 契约、数据库与配置变化

- ContractSet / JSON Schema / OpenAPI：无变化；Conformance PASS。
- Migration / PostgreSQL / Redis：无变化。
- Workspace / `uv.lock` / Makefile / 环境变量：无变化。
- 新生产依赖：无；继续使用既有内部 `flowpilot-security` 依赖。
- 兼容性：`TaskEventValidationError` 是 `ValueError` 子类；合法事件 wire mapping、SSE
  frame、opaque URI、普通业务 ID 和 producer matrix 不变。
- 攻击面：没有新增 I/O 或外部调用；诊断面从原始业务字段收敛为枚举、数量与结构索引。

## 验证

| 命令 | 结果 |
|---|---|
| `uv run --all-packages --all-groups --locked python -B -m pytest tests/core/test_event_security.py -q` | PASS；172 passed |
| `uv run --all-packages --all-groups --locked python -B -m pytest tests/core -q` | PASS；260 passed |
| 新增安全错误/五边界定向筛选 | PASS；6 passed / 166 deselected |
| `uv run --all-packages --all-groups --locked python -B -m pytest --ignore=tests/acceptance/studio -q` | PASS；1309 passed / 1 explicit online skip |
| `.\scripts\quality.ps1 test-contract` | PASS；20 schemas / 35 cases / 43 semantic cases / 52 features |
| `.\scripts\quality.ps1 test-security` | PASS；163 passed |
| `.\scripts\quality.ps1 lint` | PASS；Ruff + strict Mypy 126 source files |
| `.\scripts\quality.ps1 audit` | PASS；0 known vulnerabilities |
| `uv build --package flowpilot-security/application/api --wheel`（分别执行） | PASS；三个 wheel 构建成功 |
| `git diff --check`、授权路径与 Contract tree | PASS；仅 S5 WRITE_SCOPE，Contract tree 零变化 |

稳定闭包继续排除 S4 所有权下的 `tests/acceptance/studio` oracle；唯一 skip 是必须显式
启用的在线 Provider Smoke。本 Attempt 未把排除项或在线调用描述为通过。

## 安全与失败路径

- Additional fields：异常只含 `CORE_TASK_EVENT_ADDITIONAL_FIELDS`、`path=payload` 与
  `count=n`；两个恶意 key/value 的原文在 `str`、`repr`、日志中均为 0。
- Nested shape：错误路径为 `payload.values[n].values[n]`，未知父/子业务 key 原文为 0。
- 未知 event type、producer、classification：只返回对应稳定码、固定结构 path 与 count。
- Construction：非法对象未构造成功，输出对象数为 0。
- Emit/subscriber：既有 subscriber queue 写入数为 0，失败 emit 后 replay 数为 0。
- Tampered replay：新 subscriber 注册数为 0，queue 写入数为 0。
- SSE：错误发生在字符串生成前，partial frame 数为 0。
- 高置信 Secret 扫描：0 matches。测试 logger 名避免形成 offset-safe family 的测试噪音，
  未为消除噪音修改 Scanner。

## 已知问题

- S4 必须独立复算原始 unknown key/value 在五个边界与日志中的输出数为 0，并复验
  offset-wrapped 凭据、合法业务 ID、Schema/producer/tenant/ref 均无回归。
- Persistence/Evaluation 错误投影不属于本 Attempt，不得据此宣告这些消费者已迁移。

## 学习候选

```text
LEARNING_CANDIDATE=错误路径不能复用不受信 Mapping key
MATURITY=VERIFIED
TRIGGER=additional-field 列表和递归 payload.foo 路径会把未知业务 key 复制到异常、repr、日志与流式错误
MECHANISM=校验虽然拒绝非法输入，但诊断字符串使用原始 key/value 生成字段列表或对象路径，形成二次泄漏通道
STRUCTURE=稳定错误枚举 + count-only 集合错误 + keys[n]/values[n] 结构路径 + path allowlist + 每个输出边界写前重验
EVIDENCE=packages/application/src/flowpilot_application/errors.py；task_events.py；models.py；tests/core/test_event_security.py；172 passed
RESIDUAL_RISK=其他消费者若继续把业务 key 拼入错误详情，仍可在日志或 API 映射中重现
TARGET=ENGINEERING_PLAYBOOK 安全错误与诊断路径候选
```

## 接收会话下一步

1. S4 核验精确 S5 Head、本 Handoff Hash、ContractSet、线性祖先、范围和 clean，只用
   `--ff-only` 到达唤醒信封的 INPUT_HEAD。
2. 独立黑盒复算 unknown additional key/value、nested invalid shape、unknown Envelope 值
   在 construction、emit、subscriber、replay、SSE、`str/repr/log` 中的原文输出数为 0。
3. 复算 offset-wrapped 凭据、Schema/producer/tenant/opaque ref 与合法业务 ID；新的
   P0/P1、公共契约需求、越权或门禁失败时停止链路并上报 S1。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M7-LOCAL-PRODUCT-01
STEP_ID=M7-SEC-07-S5-SAFE-EVENT-ERRORS
ATTEMPT_ID=WP-074-a3
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=1afb1acf2aa3c5bcd7ca5dee0e6964930cf0ca38
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/core/evidence/WP-074-a3-HANDOFF.md
NEXT_ROLE=S4-QUALITY
NEXT_ATTEMPT_ID=WP-074-q2
ESCALATE_TO_S1=no
```

## 可回滚方式

- revert 本 Attempt 的单一 S5 提交；禁止 reset、rebase 或 force-push。回滚后 raw
  additional field 与业务路径泄漏重新暴露，必须同时停止 TaskEvent/SSE 交付。
