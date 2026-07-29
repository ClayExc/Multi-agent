# WP-011-a2 S5-CORE 交接

## 基本信息

- Work Package：WP-011
- Attempt：WP-011-a2
- 风险等级：R2
- 责任会话：S5-CORE
- 接收会话：后续 S6-DATA 依赖对齐；对齐完成后交 S1-ARCH 验收
- 功能 ID：FP-FLOW-007、FP-FLOW-008、FP-FLOW-009、FP-APR-001
- 分支：`codex/s5/wp-011-core-bootstrap`
- 基线提交：`93597a5023320d48875b292dc08106f03227a3fb`
- 实现提交：`d75159c591cdf18bce910a8ddfdad3454b006360`
- 补充安全测试提交：`61d52917921cc7dcab48d7574960a18b9c78b9ea`
- ContractSet 摘要：
  `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- 状态：WP-011-a2 实现完成；按用户调整后的顺序，先等待 S6 完成和
  Workspace 对齐，尚未发起 S1 验收

## 完成内容

- 新增 FastAPI ASGI 包，提供 `/health`、版本化
  `POST /v1/task-commands` 和租户作用域的只读
  `GET /v1/tasks/{task_id}`。
- API 使用额外字段拒绝的 Pydantic 模型适配公共 v1 TaskCommand/Task；
  不接受任务状态、Graph 节点、PolicyDecision 或其他权威字段。
- 新增 `RequestSecurityPort`。认证得到的可信 Tenant、Subject、Purpose 和
  SecurityContext 引用/摘要必须与 Command 一致；Command 摘要和安全绑定在
  调用授权端口前校验，Application Intake 再次防御校验。
- 新增 `TaskQueryPort` 和 `TaskQueryService`。Repository 必须按
  `(tenant_id, task_id)` 查询；返回其他租户或任务的投影时稳定失败。
- API 把校验、冲突、Repository、Runtime 和未知异常映射为稳定、安全的错误
  Envelope，不返回原始异常文本。
- 新增数据型 IT Service Domain Pack：Manifest、Intent、Required Fields、
  Risk Rules 和最小 VPN Fixture。
- Domain Pack Loader 限制文件大小和根目录范围，使用 SafeLoader，拒绝
  YAML Alias、重复 YAML/JSON Key、未知字段、重复 ID、未知 Intent 引用和
  可执行 Python；注册按 `(domain_id, version)` 唯一。
- 扩展内存 Fake 以支持 Task 投影查询，不改变 H1 的
  `TaskRepositoryPort`、`ExecutionPort`、Command Inbox 和 Unit-of-Work
  语义。
- 新增正常、边界、失败、安全、幂等、OpenAPI 和 Domain Pack 测试。

## S2 依赖请求处理

- 已只读接收 S2 分支证据
  `tests/runtime/evidence/WP-010-a1-DEPENDENCY_REQUEST.md` 中的
  `WP-010-a1-DR-001`。
- 根 Workspace 已声明 `apps/worker`、`packages/agent-runtime`、
  `packages/context`、`packages/graph`、`packages/model-gateway` 及对应
  Workspace Sources；测试发现范围保留 `tests/core` 并加入
  `tests/runtime`。
- 已锁定 `langgraph>=1.2,<2` 为 1.2.10。没有加入 OpenAI、Anthropic、
  LiteLLM、数据库、Redis、MCP SDK 或第三方 Checkpointer。
- 在工作树外的临时组合 Workspace 中放入当前 S5 包和 S2 已完成包后，
  `uv lock` 成功解析 64 个包；使用当前锁定环境直接运行 S2
  `tests/runtime` 为 36 passed。
- 当前 S5 分支不包含 S2 所有权源码，因此可复现的本分支锁文件只包含
  LangGraph 第三方依赖，不包含五个 `flowpilot-*` 内部 Workspace 包条目。
  S1 合入 S2 源码后必须由 S5 再运行 `uv lock`；在此之前提交含额外内部
  包条目的锁会使本分支 `uv lock --locked` 失败，故未伪造该通过状态。
- S6 尚未开始且没有提交依赖请求；本 Attempt 没有为 S6 预加依赖。

## 依赖审查

| 依赖 | 用途 | 许可证 | 替代方案 | 攻击面与控制 |
|---|---|---|---|---|
| FastAPI 0.140.13 | ASGI 路由、OpenAPI、错误钩子 | MIT | 直接使用 Starlette | HTTP/Schema 边界；严格模型、稳定异常映射、无隐式业务依赖注入 |
| Pydantic 2.13.4 | API 请求/响应模型 | MIT | 手写字典校验 | 解析不可信 JSON；所有嵌套模型拒绝额外字段，Domain 再校验 |
| PyYAML 6.0.3 | 声明式 Domain Pack | MIT | JSON-only 或自研解析器 | Parser/对象构造；SafeLoader、大小/路径/字段限制，拒绝 Alias 和重复 Key |
| HTTPX 0.28.1（开发） | 进程内 ASGI 契约测试 | BSD-3-Clause | Starlette TestClient | 仅测试组，无外部网络 |
| types-PyYAML（开发） | 严格 Mypy | Apache-2.0 | 本地 Stub | 仅构建期，不进入生产 Wheel |
| LangGraph 1.2.10 | S2 的唯一跨节点持久化状态机 | MIT | 永久自研状态机、Provider Session 或 Vendoring 均不符合 ADR-0001/供应链要求 | 引入序列化、SDK 和遥测客户端传递依赖；本请求不启用第三方 Checkpointer、Provider SDK 或网络适配器 |

LangGraph 新增传递依赖的锁定元数据显示：LangGraph/Checkpoint/Prebuilt/SDK、
LangChain Core/Protocol/LangSmith 为 MIT；JSON Patch/Pointer、UUID Utils、
WebSockets、xxhash、zstandard 为 BSD 家族；distro、Requests、Requests
Toolbelt、Tenacity 为 Apache-2.0；orjson 为
`MPL-2.0 AND (Apache-2.0 OR MIT)`；ormsgpack 和 sniffio 为 Apache/MIT
组合。没有发现不兼容的强 Copyleft 许可证。

首次扫描发现开发依赖 Pytest 8.4.2 的 `PYSEC-2026-1845`，已把约束提升到
`pytest>=9.0.3,<10`，最终锁定 9.1.1；复扫为 0 个已知漏洞。

## 未完成与非目标

- 没有实现真实认证/授权 Adapter、Runtime、Repository、数据库、Migration、
  LangGraph、Worker、Provider、MCP、Policy 或企业网络接入。
- 没有实现 Task Event/SSE、完整 IT Service 闭环或生产部署组合。
- 没有修改 `contracts/**`、架构/验收文档或其他角色目录。
- 没有合并、Rebase 或自行集成 S2/S6 分支。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `apps/api/**` | FastAPI、模型、安全端口、错误、测试 Fake、依赖记录 | S5-CORE |
| `packages/application/**` | Task 查询端口/用例、Domain Pack Loader/Registry、稳定错误与 Fake | S5-CORE |
| `domain-packs/it-service/**` | 数据型最小 IT Service Pack 与 Fixture | S5-CORE |
| `tests/core/**` | API、Domain Pack、失败、安全和幂等测试及本证据 | S5-CORE |
| `pyproject.toml`、`uv.lock` | API/Domain Pack 依赖、S2 Workspace 声明、LangGraph、测试范围和安全升级 | S5-CORE（WP-011 共享文件单写者） |

## 契约、数据库与配置变化

- 契约版本：无变化；只消费 reviewed ContractSet v1。
- Migration：无。
- 环境变量：无。
- API：运行时生成 OpenAPI；模块级 ASGI App 默认未配置，健康检查可用，
  Command/Task 路由在缺少组合依赖时以 503 失败关闭。
- 兼容性：Python `>=3.12`；H1
  `flowpilot.application-ports.m0.v1` 常量和已有 Port 未放宽。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| `make bootstrap` | PASS | Python 3.12.11；干净临时环境从锁安装 58 个包 |
| `make test` | PASS | 43 collected，43 passed |
| `make test-contract` | PASS | `CONTRACT_CONFORMANCE_OK`：20 schemas、35 cases、19 mutation cases、43 semantic cases、5 audit-chain cases、21 manifest cases、52 features |
| Ruff | PASS | `All checks passed!`，Domain/Application/API/Core Tests |
| 严格 Mypy | PASS | 23 source files，0 issues |
| 三个 Wheel 构建 | PASS | Domain、Application、API Wheel 均构建成功 |
| `uv lock --locked` + 锁 Hash 前后比较 | PASS | `sha256:8aa134c4c653fd8084124e23ab35fb72f1ed2ee506187f77f36b0386f5561c74`，前后不变 |
| `pip-audit` | PASS | 0 known vulnerabilities；三个本地 Editable 包按工具规则跳过数据库查询 |
| S2 `tests/runtime`（只读跨工作树验证） | PASS | 36 passed；LangGraph 1.2.x 约束可用 |
| ContractSet 摘要核对 | PASS | 与派单摘要完全一致 |
| `git diff --check` | PASS | 无 whitespace 错误 |

验收机没有全局 GNU Make/uv。本次使用工作树外临时 GNU Make 4.4.1、
uv 0.8.24、虚拟环境、Cache、Wheel 输出和组合 Workspace；未将其提交。

## 安全与失败路径

- 已验证负向路径：未知/注入字段、错误 Command 摘要、SecurityContext
  Tenant/Subject/Purpose 错配、可信请求身份错配、同幂等键不同摘要、Runtime
  故障、Repository 故障、跨租户 Task 查询、非法 Task ID、未配置依赖、
  Domain Pack 路径逃逸、Alias、重复 Key、未知字段和重复注册。
- 授权端口只接收已通过摘要和安全绑定校验的 Command；Application 仍进行
  二次校验。
- 未验证风险：真实 IdP/Policy、S2/S6 Adapter、多进程并发、数据库 RLS、
  网络超时和生产 ASGI Server，分别留给后续责任工作包。
- Secret/PII 检查：Secret Pattern 0 命中；只使用虚构 Tenant、Subject、
  引用和错误文本，没有真实 PII、凭据、Prompt、Trace 或原始附件。

## 已知问题

- `WP-010-a1-DR-001` 的第三方锁和共享声明已完成，但五个 S2 内部包的锁条目
  只能在 S2 源码进入集成树后生成。S1 集成 S2 后需返回 S5 刷新锁，再执行
  最终 `make bootstrap/test/test-contract`。
- S6 尚未开始。按用户指示，本次停止后等待 S6 完成，再进行 S5/S6
  Workspace、依赖和 Port 实现对齐；在对齐前不发起 S1 验收。
- Domain Pack 是注册和验证骨架，不执行 Prompt、分类模型、工具或业务副作用。

## 接收会话下一步

1. 停止当前 Attempt，等待用户在 S6/WP-021 完成后发起 S5/S6 对齐。
2. S6 提供正式依赖请求后，S5 作为共享 Workspace 单写者审查并更新
   `pyproject.toml`、`uv.lock` 和稳定测试范围。
3. S1 按 WP 顺序集成 S5、S2、S6 源码后，将集成树返回 S5 刷新完整锁并重跑
   三条 Make 门禁。
4. 锁和跨角色门禁通过后，再由 S1/S2/S4 完成 WP-011 跨角色验收。

## 可回滚方式

- 实现可按逆序执行
  `git revert 61d52917921cc7dcab48d7574960a18b9c78b9ea`
  和 `git revert d75159c591cdf18bce910a8ddfdad3454b006360`
  回滚；不要 Reset/Rebase 其他角色分支。
- 本包没有数据库、Migration、环境变量或公共契约变化，无需数据回滚。
