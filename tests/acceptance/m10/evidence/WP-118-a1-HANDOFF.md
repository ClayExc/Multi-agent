# WP-118-a1 S4-QUALITY Handoff

## 基本信息

- Work Package：`WP-118`
- Attempt ID：`WP-118-a1`
- Chain / Step：`CHAIN-M10-KNOWLEDGE-01` / `M10-08-S4-KNOWLEDGE-WEB`
- 责任会话 / 接收会话：`S4-QUALITY` / `S4-QUALITY`（热继续 `WP-119`）
- 交接策略：`CONSUMER_GATE`
- 功能 ID：`FP-UI-001`、`FP-SEC-003`
- 基线提交：`edd2059b2a37ac26a957efd98459aaadbddc646d`
- 分支：`codex/s4/wp-114-m10-retrieval`
- 最终提交：`<this-handoff-commit>`
- ContractSet 摘要：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 上游 Handoff：`tests/runtime/evidence/WP-117-a1-HANDOFF.md`
- 上游 Handoff SHA-256：`sha256:c5bd6a033c22ce5d5c0db38ba1d7361063650a81eae477a7574abbbf348a7686`
- 状态：完成

## 消费者门禁

- 消费前 S4 Head `d57782c3cf08fc52ee4a89dd5410ef0bb4f34ae4` 是输入 Head 的祖先，
  工作树 clean；仅执行 `git merge --ff-only`，精确到达 `edd2059b…`。
- 独立复算 ContractSet digest 与 WP-117 Handoff Hash 均匹配。
- 复用 WP-117 的 LangGraph 唯一状态机、Gateway-only Knowledge Tool、Handoff/Retry/
  restart 多点重校验与单次逻辑调用证据；未重复运行 Runtime、Gateway、PostgreSQL、
  Migration、Compose 或全仓测试。

## 完成内容

- 新增 Cookie-only 知识 Web：精确文档/版本查询、当前会话已由 API 复验的安全元数据列表、
  导入、更新、撤销、索引重建、索引诊断和 Citation Hash 回查。
- Web 不接收或转发浏览器 `tenant_id`、role 或权限字段；只向权威 API 转发不透明 Cookie。
  文档缓存以不可逆会话指纹隔离，退出/刷新失效时清理。
- API 投影使用 exact-field、类型、UTC、ID、版本与 SHA-256 校验；文档和诊断必须精确绑定
  `document_id/document_version/content_hash`。未知字段、Hash 漂移、错版本和不安全响应失败关闭，
  不回退 latest，不展示正文、source_ref、ACL 主体、向量、Secret 或隐藏思维链。
- 写操作只由服务端 BFF 构造，严格拒绝重复/未知表单字段；正文只进入一次上游请求体，不进入
  页面、响应、缓存或日志。幂等键绑定 `document_id + operation + payload`；更新/撤销/重建绑定
  `expected_revision`，重建额外绑定精确版本。
- `RUNTIME_KNOWLEDGE_NO_RESULT` 显式呈现“`不知道；需要更多信息`”，并声明没有生成推测性答案；
  Judge 或 UI 不得把无证据失败覆盖为成功。
- SSE 重放保留 `Last-Event-ID`，重复事件不重复进入时间线；知识页面收到 Task Event 后重新读取
  权威投影，不使用缓存替代失败的 API 读取。
- 实际内置浏览器验证 `#/knowledge` 导航、状态区与真实页面渲染，控制台 warning/error 为 0；
  演示模式明确拒绝读取或修改企业知识。

## 未完成与非目标

- API 当前没有 tenant-wide collection list 端点；页面明确把列表限定为“当前会话已由 API 精确
  复验的文档”，不把 Web 缓存伪装成完整业务目录。
- 未修改 Runtime/Gateway/API/Persistence、公共 Contract、数据库、Migration、Workspace、Lock、
  Makefile 或配置；未运行 Compose、真实 PostgreSQL/RLS、全仓或 Release 门禁。
- 未声明 M10、Feature、`RELEASED` 或 `FROZEN`。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `web/src/flowpilot_shell/knowledge.py` | 安全知识视图、精确校验与快照 | S4 |
| `web/src/flowpilot_shell/api_client.py` | Cookie-only Knowledge API 读写适配 | S4 |
| `web/src/flowpilot_shell/render/knowledge.py` | 中文知识/诊断/引用页面 | S4 |
| `web/src/flowpilot_shell/render/{__init__,error}.py` | 导出页面并接入无证据呈现 | S4 |
| `web/server.py` | 会话隔离缓存、BFF 写入、知识路由与安全错误 | S4 |
| `web/shell/{index.html,app.js,shell.css}` | 导航、严格路由、表单、SSE 刷新与样式 | S4 |
| `tests/experience/test_adapter_boundary.py` | 固化新增 API Adapter 能力边界 | S4 |
| `tests/acceptance/m10/test_knowledge_web_blackbox.py` | 独立 HTTP/Web 安全黑盒 13 条 | S4 |
| `tests/acceptance/m10/evidence/WP-118-a1-HANDOFF.md` | 本交接证据 | S4 |

## 契约、数据库与配置变化

- 契约版本：无变化；Contract digest 保持 `sha256:1cad07…b5b42a2`。
- Migration / 数据库 / 环境变量：无变化。
- 兼容性：保留现有 Task、Governance、Identity 和 SSE 页面行为；新增 Adapter 方法已更新能力
  边界测试，仍无 approval write 能力。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| `uv run --frozen python -m pytest tests/acceptance/m10/test_knowledge_web_blackbox.py -q` | PASS | `13 passed` |
| `uv run --frozen python -m pytest tests/experience tests/acceptance/m10 -q` | PASS | `167 passed` |
| `uv run --frozen ruff check web tests/experience tests/acceptance/m10` | PASS | `All checks passed` |
| `uv run --frozen mypy --strict web/src web/server.py` | PASS | `25 source files` |
| `uv run --frozen python -m pytest tests/experience/test_secret_scan.py -q` | PASS | `2 passed` |
| `uv run --frozen python contracts/conformance/validate.py` | PASS | `20 schemas / 35 cases / 43 semantic / 52 features` |
| 内置浏览器：导航 `#/tasks` → `#/knowledge`、DOM/ARIA/console | PASS | URL 精确、2 个 status 区可读、console issues `0` |
| `git diff --check` | PASS | 无空白错误 |

## 安全与失败路径

- 13 条独立黑盒覆盖：Cookie-only/伪造 tenant-role、跨租户读成功 0、会话缺失/伪造、精确版本
  不存在、Citation Hash 漂移、未知敏感投影字段、正文单次传输且零回显、并发 revision 冲突、
  浏览器权威字段拒绝、导入/更新/撤销/重建绑定、服务不可用后恢复、无证据呈现、SSE 重放去重。
- `CONTENT/SECRET/HIDDEN_REASONING/VECTOR` 合成 canary 在 HTML、JSON 错误、receipt 和缓存页面中
  命中数均为 0；错误只返回稳定安全码与中文提示。
- 未验证风险：真实 Keycloak/PostgreSQL/RLS 与 Agent Server 组合证据复用 Owner Handoff，最终由
  WP-119/S7 组合复算；本 Attempt 不冒充真实 Compose 结果。

## 已知事实与避免重复

- `KNOWN_FACTS`：WP-117 已验证 Runtime 多点重校验与单次逻辑知识调用；本 Attempt 使用不同的
  浏览器/BFF/HTTP 黑盒观察边界。
- `DO_NOT_RECHECK`：Runtime/Gateway/Persistence 内部、Compose、Migration、全仓与 Release。
- `FAILURE_SIGNATURES`：`RUNTIME_KNOWLEDGE_NO_RESULT`、`KNOWLEDGE_REVISION_CONFLICT`、
  `KNOWLEDGE_PROJECTION_INVALID`、`API_AUTHENTICATION_INVALID`、`API_AUTHORIZATION_DENIED`。
- `REUSED_DECISIONS`：Cookie-only 身份、服务端 tenant、精确版本 Citation、无证据不生成答案。
- `DUPLICATE_WORK_AVOIDED`：复用 WP-114～117 与既有 M8/M9 Identity/SSE/Governance Web 证据。

## 学习候选

```text
LEARNING_CANDIDATE=知识写入幂等键必须绑定资源路径身份
MATURITY=VERIFIED
TRIGGER=更新/撤销/重建请求体不含 document_id，若只对上游 body 求摘要，不同文档可能共享键
MECHANISM=资源身份位于 URL path 而非 JSON body，幂等摘要遗漏 path binding 会产生跨资源碰撞
STRUCTURE=服务端幂等投影固定包含 document_id + operation + payload，再生成 SHA-256
EVIDENCE=WP-118-a1 Knowledge Web 黑盒导入/更新/撤销/重建与最终差异
RESIDUAL_RISK=最终组合仍需验证 API tenant-scoped Inbox 的幂等键约束
TARGET=ENGINEERING_PLAYBOOK knowledge/idempotency section
```

## 子 Agent 使用摘要

```text
SUBAGENTS_USED=0
SUBAGENT_MODES=none
SUBAGENT_TASKS=none
SUBAGENT_WRITERS=0
PARENT_REPRODUCED_RESULTS=not-applicable
REUSED_DECISIONS=WP-114-a1,WP-115-r2-quality,WP-116-a1,WP-117-a1
DUPLICATE_WORK_AVOIDED=4
```

## 接收会话下一步

1. S4 在精确 WP-118 Head 上按授权热继续 WP-119，注册 M10 适用真实执行器并复算固定 156
   Case；不得修改分母、跳过/隔离规则或宣称 M10 Release。
2. WP-119/S7 组合复算真实 Agent Server、Gateway、PostgreSQL/RLS 与 Web 证据；若完整 tenant-wide
   知识目录成为硬需求，应由 S1/S5 先定义安全分页 API，不得由 Web 直连数据库补齐。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M10-KNOWLEDGE-01
STEP_ID=M10-08-S4-KNOWLEDGE-WEB
ATTEMPT_ID=WP-118-a1
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=edd2059b2a37ac26a957efd98459aaadbddc646d
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/acceptance/m10/evidence/WP-118-a1-HANDOFF.md
NEXT_ROLE=S4-QUALITY
NEXT_ATTEMPT_ID=WP-119-a1
ESCALATE_TO_S1=no
SUBAGENTS_USED=0
USER_INPUT_REQUIRED=none
```

## 可回滚方式

- 线性回滚本 Attempt 单提交；无数据库、Contract、Lock 或环境迁移需要额外回滚。
