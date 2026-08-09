# WP-074-a2 S3-PLATFORM 嵌入式凭据边界交接

## 基本信息

- Work Package：WP-074
- Attempt ID：WP-074-a2
- Chain ID：CHAIN-M7-LOCAL-PRODUCT-01
- Step ID：M7-SEC-06-S3-EMBEDDED-CREDENTIAL-BOUNDARY
- 责任会话：S3-PLATFORM
- 接收会话：S5-CORE
- 交接策略：CONSUMER_GATE
- 风险与严重度：R3 / P0；S1 架构修复链
- 功能 ID：FP-SEC-002、FP-SEC-006
- 输入提交：`7a5f3c0065bf4fe4c40bdf03747a759631750076`
- 实现提交：`2ffe768cc92fb164b5a1fb1214277996a55938c1`
- 分支：`codex/s3/wp-074-security-scanner`
- 最终提交：本文件所在提交；精确 SHA 由唤醒信封返回
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 上游 S5 证据：`tests/core/evidence/WP-074-a2-HANDOFF.md`
- 上游 S2 证据：`tests/runtime/evidence/WP-072-a1-LATEST-CHECKPOINT-HANDOFF.md`
- 输出状态：PASS_HANDOFF

## DELTA 上下文与消费者门禁

- `CONTEXT_MODE=DELTA`
- `CONTEXT_BASE_COMMIT=9e042227b6ce13964631381c19ee69002ee23dbf`
- `CONTEXT_TARGET_COMMIT=7a5f3c0065bf4fe4c40bdf03747a759631750076`
- S3 当前 Head、clean、祖先、分支、ContractSet 和输入 Head 均精确匹配，只使用
  `--ff-only` 消费两条线性上游提交。
- 强制基线文档变化为 0；当前 Chain/Registry Git Blob 未变化并已在上一 S3 Attempt
  加载，因此未重复全文读取。
- 已读取直接 S5/S2 Handoff；S4 已独立接受 S2 latest-checkpoint 修复，并以 clean
  `7a5f3c0` 复现本次 Credential P0，S3 未修改 Runtime。
- 上游差异仅含 S5 Application/API/Workspace 与 S2 Runtime Owner 路径；Contracts 未变。

## 根因与修复前复现

- 各 token family 的正则依赖左侧字符边界。当凭据前有 `evt_`、`corr_`、字母数字、
  下划线或连字符时，匹配起点被包装字符遮蔽。
- AWS 固定长度 family 还依赖右侧边界，无法对任意前后缀组合保持一致。
- Slack 使用 `xox[a-z]-`，把合法业务 ID `xoxo-customer-release-20260809` 误判为凭据。
- 修复前独立矩阵结果：OpenAI admin、GitHub、JWT 在 event/correlation/字母数字等
  包装中漏检；ASIA 在字母数字包装中漏检；上述 xoxo 业务 ID 被拒绝。

## 完成内容

- 所有强凭据 family 移除外部 token boundary 依赖：Scanner 从每个字符 offset 搜索
  精确 family prefix，并依靠受限 body alphabet 与合理最小长度决定命中。
- OpenAI admin 明确覆盖 24、36 和更长 body；没有把长度锁死到单一发行版本。
- AWS、OpenAI、Anthropic、GitHub、Bearer/Basic、JWT、credential assignment/URI、
  Slack 和 private-key header 在固定 ID、URI/path 及前后缀包装中统一生效。
- Slack xox family 从任意字母收窄为显式登记的 `xoxb/xoxa/xoxp/xoxr/xoxs`，并
  保留既有 xapp 结构；`xoxo-*` 与未登记长 `xoxz-*` 保持合法。
- `credential_field_name` 继续只在 Mapping key 上精确匹配，不把父路径或普通字段
  名片段误判为凭据。
- Scanner API、Finding 结构、安全路径和异常类型不变；没有把剥离包装责任推给调用方。

## 未完成与非目标

- 未修改 Application、API、Runtime、Persistence、Evaluation 或公共 Contracts。
- 未处理 TaskEvent additional-field/shape 错误消息；按 S1 固定顺序交给下一 S5 步骤。
- 未修改 Workspace、锁文件、Makefile、依赖、数据库或环境配置。
- 未连接真实 Provider、外部网络或企业系统，未使用真实凭据。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/security/src/flowpilot_security/credentials.py` | offset-safe family 与显式 Slack 前缀集合 | S3 |
| `tests/platform/test_credential_registry.py` | 结构组合、长度、容器一致性与误报矩阵 | S3 |
| `tests/platform/evidence/WP-074-a2-HANDOFF.md` | 本交接证据 | S3 |

## 契约、数据库、依赖与配置变化

- ContractSet / JSON Schema / OpenAPI：无变化；Conformance PASS。
- Migration / PostgreSQL / Redis：无变化。
- Python Workspace / `uv.lock` / `Makefile`：无变化。
- 新生产依赖：无。
- 公共 Scanner API：无形状变化；这是同一 API 的安全语义收敛。

## 验证

| 命令 | 结果 |
|---|---|
| 修复前/后独立 offset 与 xoxo 复现脚本 | 修复前确认绕过/误报；修复后全部期望为 true，xoxo safe=true |
| `uv run --all-packages --all-groups --locked python -B -m pytest tests/platform/test_credential_registry.py tests/core/test_event_security.py -q` | PASS；410 passed |
| `uv run --all-packages --all-groups --locked python -B -m pytest tests/platform -q` | PASS；332 passed |
| `.\scripts\quality.ps1 lint` | PASS；Ruff + strict Mypy 126 source files |
| `.\scripts\quality.ps1 test-contract` | PASS；20 schemas / 35 cases / 43 semantic cases / 52 features |
| `.\scripts\quality.ps1 test-security` | PASS；163 passed |
| `git diff --check`、授权路径和 Contract tree | PASS；仅 S3 路径，Contract tree 零变化 |

## 安全与失败路径

- 每个非 key-only 注册 family 均跨以下结构组合验证：`evt_`、`corr_`、`task_`、
  `result://`、自定义字母数字、单下划线、单连字符、URI/path、后缀及前后缀。
- 每个非 key-only family 均在顶层字符串、Mapping key、Mapping value 和 Sequence 中
  使用同一 offset 规则；key-only family 在嵌套 Mapping 中保持精确匹配。
- OpenAI admin body 24 / 36 / 72 均在前后缀包装下命中。
- `xoxo-*`、未登记 `xoxz-*`、短 xox/xapp、短 admin 和单段 Slack 结构均保持不命中。
- 组合测试继续断言 Finding path 不含匹配原值；既有异常、repr、日志零泄漏、循环
  容器和嵌套键/值测试全部通过。

## 已知风险

- 强 family 现在会故意命中更大业务字符串中的 token-like 子串；这是关闭结构化 ID
  污染的安全语义。误报控制由精确 provider prefix、body alphabet、最小长度和 Slack
  显式前缀集合承担，不能恢复为调用方剥离或外部字符边界。
- S5 当前 additional-field/shape 错误仍可能复制未知原始 key/value；在下一消费者提交
  完成前，S4 报告的 P0 端到端错误泄漏路径仍不能宣告关闭。
- 新 Provider family 仍必须只在本集中注册表登记并补齐组合/相邻误报矩阵。

## 学习候选

```text
LEARNING_CANDIDATE=凭据 family 的外部字符边界是攻击者可控输入
MATURITY=IMPLEMENTED
TRIGGER=真实 token 被拼入 evt_/correlation_/result_ref 后，左侧下划线或字母数字让正则 lookbehind 失败
MECHANISM=把 token 的有效性错误绑定到外部包装字符；调用方不需要改变 token 本身即可遮蔽扫描起点
STRUCTURE=精确 family prefix + 受限 body syntax + 任意 offset search + 全结构组合矩阵 + provider 前缀白名单
EVIDENCE=packages/security/src/flowpilot_security/credentials.py；tests/platform/test_credential_registry.py
RESIDUAL_RISK=新 family 若重新引入外部 boundary，会在结构化 ID/URI 中重现同类绕过
TARGET=ENGINEERING_PLAYBOOK 凭据扫描候选
```

## S5-CORE 下一步

1. 核验最终 Head、本 Handoff SHA256、ContractSet、线性祖先、范围和 clean，只使用
   `--ff-only` 到达精确输入 Head。
2. 继续消费同一 Scanner，不复制/扩展 family；不得修改 Runtime、Security 或 Contracts。
3. 让 TaskEvent 所有 additional-field、shape、stream 和 SSE 错误路径只输出稳定安全码、
   数量及不含业务 key 的结构路径，绝不拼接未知原始 key/value。
4. 增加 `str(exception)`、`repr(exception)`、捕获日志零原值，以及
   construction -> emit -> subscriber -> replay -> SSE 的组合污染为 0 测试。
5. 保留 Schema、producer、tenant、opaque ref 和合法业务 ID 门禁；依赖环、路径越权、
   公共契约或新 P0/P1 时停链回 S1。PASS 后只唤醒 S4 独立复核。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M7-LOCAL-PRODUCT-01
STEP_ID=M7-SEC-06-S3-EMBEDDED-CREDENTIAL-BOUNDARY
ATTEMPT_ID=WP-074-a2
NEW_HEAD=<this-handoff-commit>
IMPLEMENTATION_HEAD=2ffe768cc92fb164b5a1fb1214277996a55938c1
BASE_COMMIT=7a5f3c0065bf4fe4c40bdf03747a759631750076
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/platform/evidence/WP-074-a2-HANDOFF.md
NEXT_ROLE=S5-CORE
NEXT_ATTEMPT_ID=WP-074-a3
ESCALATE_TO_S1=no
```

## 可回滚方式

- 依次 revert 本 Handoff 提交与实现提交
  `2ffe768cc92fb164b5a1fb1214277996a55938c1`；禁止 reset、rebase 或 force-push。
