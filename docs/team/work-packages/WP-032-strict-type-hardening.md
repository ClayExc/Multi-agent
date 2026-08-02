# WP-032：M6 严格类型基线修复

## 元数据

- 状态：READY
- Attempt ID：WP-032-a1
- 风险等级：R1
- 责任会话：S2-RUNTIME、S4-QUALITY、S5-CORE（互斥路径并行）
- 评审会话：S1-ARCH
- 功能 ID：FP-OPS-002
- 依赖工作包：WP-031-a1 已由 S1 接受并快进集成
- 执行模式：PARALLEL
- Chain ID：CHAIN-M6-ACCEPTANCE-REMEDIATION-01
- Step ID：M6-REM-02-TYPES
- 汇合策略：S1_GATE
- 基线提交：`71afa72a4975a506796e1e02d8d475d142616652`

## 目标

- 消除 14 个 Python Workspace 产品包与 Web Shell 的严格 Mypy 基线错误。
- 保持运行时语义、公共契约和外部 API 不变；只修复已证明的类型不一致或缺失收窄。
- 建立一条可复现的跨包严格类型命令，作为后续 S1/S7 门禁输入。

## 当前可复现基线

以下命令在基线提交上检查 116 个源码文件，得到 7 个文件中的 25 个错误：

```powershell
uv run --all-packages --all-groups --locked mypy --strict apps/api/src apps/mcp-gateway/src apps/worker/src mcp-servers/knowledge/src mcp-servers/ticket/src packages/agent-runtime/src packages/application/src packages/context/src packages/domain/src packages/graph/src packages/model-gateway/src packages/persistence/src packages/policy/src packages/security/src packages/tool-contracts/src web/src
```

## 并行分片与写入范围

| Agent | 角色 | 独占写入范围 | 当前错误 |
|---|---|---|---|
| `runtime-type-hardener` | S2-RUNTIME | `packages/graph/**`、`packages/model-gateway/**`、必要的 `tests/runtime/**` | 3 个错误 / 3 个文件 |
| `experience-type-hardener` | S4-QUALITY | `web/src/**`、必要的 `tests/experience/**` | 12 个错误 / 2 个文件 |
| `core-type-hardener` | S5-CORE | `packages/application/**`、`apps/api/**`、必要的 `tests/core/**` | 10 个错误 / 2 个文件 |

三个分片路径互斥，可以并行写入。不得修改 `contracts/**`、根 Workspace 文件、其他角色目录或生成物。

## 实施约束

- 不以全局 `ignore_errors`、放宽 strict、`Any` 扩散或无理由 `type: ignore` 消除门禁。
- `cast`、类型守卫和 Literal 收窄必须有运行时不变量或失败路径支撑。
- 发现真实运行时缺陷时增加最小回归测试；不得只为静态检查改变业务结果。
- 公共 Port、Schema、API 响应语义或错误码若需变化，停止并上报 S1。

## 分片验收

### S2-RUNTIME

```powershell
uv run --all-packages --all-groups --locked mypy --strict packages/graph/src packages/model-gateway/src
uv run --all-packages --all-groups --locked python -B -m pytest tests/runtime -q
uv run --all-packages --all-groups --locked ruff check packages/graph packages/model-gateway tests/runtime
```

### S4-QUALITY

```powershell
uv run --all-packages --all-groups --locked mypy --strict web/src
uv run --all-packages --all-groups --locked python -B -m pytest tests/experience -q
uv run --all-packages --all-groups --locked ruff check web/src tests/experience
```

### S5-CORE

```powershell
uv run --all-packages --all-groups --locked mypy --strict packages/application/src apps/api/src
uv run --all-packages --all-groups --locked python -B -m pytest tests/core -q
uv run --all-packages --all-groups --locked ruff check packages/application apps/api tests/core
```

## S1 汇合门禁

- 三个 Head 必须来自同一基线、工作树干净、提交范围互斥且无契约变化。
- 逐分片验收通过后，由 S1 依次 `--ff-only` 消费；若第一个消费后其余分支不再线性，则使用不修改内容的三方组合分支验证后再集成，禁止隐式重写他人历史。
- 复跑 116 源码文件严格 Mypy、责任范围 Ruff 及相关回归测试。

## 非目标

- 不处理 `packages/evaluation/incremental_c.py`、`web/server.py`、`web/tools/**` 的非 Workspace 工具脚本类型债；它们另行登记为 P2。
- 不更新 ContractSet、Attestation、Judge 校准或真实 Case Executor。
- 不修改依赖、锁文件、Makefile 或 CI。

## 完成定义

- 上述 116 源码文件严格 Mypy 为 0 errors。
- 三个分片的测试与 Ruff 通过，且没有新增广义忽略。
- S1 完成组合复核并记录后，才解锁 `M6-REM-03-S1-CONTRACT`。
