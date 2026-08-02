# WP-032-a1-S2 S2-RUNTIME 交接

## 基本信息

- Work Package：WP-032
- Attempt ID：WP-032-a1-S2
- Chain ID：CHAIN-M6-ACCEPTANCE-REMEDIATION-01
- Step ID：M6-REM-02-TYPES
- 责任会话：S2-RUNTIME（`runtime-type-hardener`）
- 接收会话：S1-ARCH
- 交接策略：S1_GATE
- 功能 ID：FP-OPS-002
- 产品基线提交：`71afa72a4975a506796e1e02d8d475d142616652`
- 激活提交：`f8dff51df0998d826ffc51ecf8cce0dd50bf7c02`
- 分支：`codex/s2/wp-032-type-hardening`
- 最终提交：本文件所在提交；精确 SHA 由交接消息返回
- ContractSet 摘要：
  `sha256:f3c2dd6eb7d398d9a0a0891110cbc913bb998ed72208ea179a644c97af655e56`
- 状态：完成，等待 S1 汇合验收

## 完成内容

- 将 `SANDBOX_PROVIDER` 从其定义模块 `wire` 直接重导出，消除经
  `sandbox` 隐式再导出的 strict Mypy 错误；公共导出名称和值不变。
- 将 `_budget_exhausted` 的现有输入类型明确为
  `ContextEnvelope | GraphState | None`；两条既有调用路径和值读取逻辑不变。
- 为 Onboarding summary 的 citation 列表增加精确的
  `list[Mapping[str, str]]` 中间类型；citation 仍以 list 参与 result digest，
  并以 tuple 写入 artifact draft，序列化与哈希语义不变。
- S2 strict Mypy 从 3 errors / 3 files 降为 0 errors；没有新增 `Any`、
  `type: ignore`、`noqa` 或静态检查放宽。

## 未完成与非目标

- 116-source canonical strict Mypy 的 S4/S5 分片与三分支汇合由 S1 复核，
  不在本 S2 分片内宣称完成。
- 未修改公共 Contract、API/Port、依赖、锁文件、共享配置或其他角色路径。
- 未新增测试：现有 Runtime 套件已覆盖预算耗尽的 `GraphState` 调用路径、
  Onboarding artifact 输出以及 Model Gateway 公共导入，并全部通过。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/model-gateway/src/flowpilot_model_gateway/__init__.py` | 从定义模块显式重导出 sandbox provider 常量 | S2-RUNTIME |
| `packages/graph/src/flowpilot_graph/engine.py` | 精确声明预算耗尽辅助函数的既有输入联合类型 | S2-RUNTIME |
| `packages/graph/src/flowpilot_graph/onboarding.py` | 精确声明 summary citation 集合类型 | S2-RUNTIME |
| `tests/runtime/evidence/WP-032-a1-S2-HANDOFF.md` | 本 Attempt 验证与交接证据 | S2-RUNTIME |

## 契约、数据库与配置变化

- 契约版本：无修改。
- Migration：无。
- 环境变量：无。
- 兼容性：公共导出、Runtime 控制流、artifact 内容/digest 与错误码不变。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| `uv run --all-packages --all-groups --locked mypy --strict packages/graph/src packages/model-gateway/src` | PASS：15 source files，0 errors | S2 canonical 分片门禁 |
| `uv run --all-packages --all-groups --locked python -B -m pytest tests/runtime -q` | PASS：134 passed | 正常、边界、失败、安全与恢复回归 |
| `uv run --all-packages --all-groups --locked ruff check packages/graph packages/model-gateway tests/runtime` | PASS：All checks passed | S2 责任范围 lint |
| `git diff --check` | PASS | 无 whitespace error |
| 修改范围与新增抑制审计 | PASS | 仅 3 个授权源码文件；新增 `Any` / `type: ignore` / `noqa` 为 0 |

## 安全与失败路径

- 已验证负向路径：完整 Runtime 套件继续覆盖预算耗尽、恢复、租户、审批、
  Handoff、工具与 Provider 错误路径；本 Attempt 未改变这些分支。
- 未验证风险：跨 S2/S4/S5 的 116-source 组合门禁尚待 S1 汇合复跑。
- Secret/PII 检查：修改仅涉及类型声明、导入来源和合成 citation 类型，未新增
  Secret、凭据、真实 PII 或外部端点。

## 已知问题

- 无本分片阻断问题。并行分片组合后的全局 strict Mypy 结果由 S1 门禁负责，
  不以本分片结果代替。

## 学习候选

```text
LEARNING_CANDIDATE=none
MATURITY=VERIFIED
TRIGGER=none
MECHANISM=none
STRUCTURE=none
EVIDENCE=tests/runtime/evidence/WP-032-a1-S2-HANDOFF.md
RESIDUAL_RISK=三分片汇合后需复跑 canonical 116-source strict Mypy
TARGET=none
```

## DELTA 上下文记录

- `CONTEXT_MODE=DELTA`
- `CONTEXT_BASE_COMMIT=71afa72a4975a506796e1e02d8d475d142616652`
- `CONTEXT_TARGET_COMMIT=f8dff51df0998d826ffc51ecf8cce0dd50bf7c02`
- 祖先校验：PASS。
- 强制基线 name-status diff：0 个变化文件，未触发 FULL。
- 实际读取：当前 Chain Authorization、WP-032、对应 Agent Registration、
  Handoff Template、3 个目标源码文件及直接相关 Runtime 测试。

## 接收会话下一步

1. 核验返回的 S2 `FINAL_HEAD`、父提交、分支、修改范围与 clean 状态。
2. 按 WP-032 汇合策略消费 S2/S4/S5 的互斥分片，并复跑各分片门禁。
3. 在组合 Head 上复跑 canonical 116-source strict Mypy；通过后由 S1 决定是否
   解锁 `M6-REM-03-S1-CONTRACT`。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M6-ACCEPTANCE-REMEDIATION-01
STEP_ID=M6-REM-02-TYPES
ATTEMPT_ID=WP-032-a1-S2
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=f8dff51df0998d826ffc51ecf8cce0dd50bf7c02
CONTRACT_CONTENT_DIGEST=sha256:f3c2dd6eb7d398d9a0a0891110cbc913bb998ed72208ea179a644c97af655e56
GATE=PASS
HANDOFF=tests/runtime/evidence/WP-032-a1-S2-HANDOFF.md
NEXT_ROLE=S1-ARCH
NEXT_ATTEMPT_ID=none
ESCALATE_TO_S1=no
```

## 可回滚方式

- 使用 `git revert <FINAL_HEAD>` 回滚本 Attempt；禁止 reset、rebase 或
  force-push。
