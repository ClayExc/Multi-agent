# WP-086-a1 S4 Web identity experience handoff

## 基本信息

- Work Package：`WP-086`
- Attempt ID：`WP-086-a1`
- Chain ID：`CHAIN-M8-IDENTITY-TENANCY-01`
- Step ID：`M8-03B-S4-WEB`
- 责任会话：`S4-QUALITY`
- 接收会话：`S1-ARCH`
- 交接策略：`S1_GATE`
- 功能 ID：`FP-SEC-001`、`FP-EVAL-002`
- 基线提交：`e0a929cb15c213d6b65f0d03ba0bbe3742824fbb`
- 分支/最终提交：`codex/s4/m8-identity-experience`；本文件所在提交，精确 SHA 由交接信封提供
- 实现提交：`c49448231fa84b1b3c301f2c224d44c03fd5c1b7`
- ContractSet 摘要：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：完成

## 完成内容

- 实现中文登录、会话检查、刷新失败、会话过期/撤销、重新认证和登出体验；状态区使用 `role=status` 与 `aria-live`，受保护视图在身份未确认时保持关闭。
- Web BFF 仅转发同源不透明 Cookie，不接收或注入浏览器 tenant/role/subject 权威字段；`ApiClient` 不再配置 `X-FlowPilot-Tenant-Id`。
- Live 缓存、任务投影和事件时间线按严格解析后的 `__Host-flowpilot-session` 不可逆 SHA-256 指纹隔离；任意、空值或重复会话 Cookie 失败关闭。
- 登录 callback/refresh 只接受严格 `HttpOnly`、`Secure`、`Path=/`、`SameSite=Lax|Strict` 的 `__Host-` Cookie；拒绝 Domain、重复/冲突属性和属性值子串伪装。
- SSE 转发 Cookie 与 `Last-Event-ID`，逐事件回读权威 Task 投影核对租户；浏览器对上游全量重放做事件 ID 去重，断线后先刷新会话再重连。
- 浏览器使用统一 auth epoch 与 `AbortController`；登出、重新认证和刷新切换会取消旧请求，旧 Task 响应或旧刷新不能重新写入受保护 DOM、恢复会话或重连 SSE。
- 上游认证、命令和依赖错误只投影稳定本地错误码/文案；原始 message、Token/nonce canary 不进入响应、DOM 或日志。
- 新增真实双 HTTP 服务黑盒、M8 acceptance、浏览器竞态执行器及静态/可访问性检查，覆盖登录/登出/过期/撤销/刷新失败、跨会话缓存、跨租户伪造头、SSE 重放、Cookie 畸形和错误泄漏。

## 未完成与非目标

- 未修改公共 Contract、Migration、RLS、Keycloak、S5 API、S2 Runtime、共享依赖锁、Makefile 或 Compose。
- 未运行 Keycloak、RLS、Compose、全仓回归或 M7 固定 156 Case；这些门禁按工作包要求留给并行 Join/后续集成。
- 未执行真实外部 IdP 登录；验收使用本地、合成、无网络的身份 API 黑盒。
- 本交接不声明 M8、Feature 或 Release 状态提升。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `web/src/flowpilot_shell/models.py`、`web/src/flowpilot_shell/__init__.py` | 稳定身份/授权错误类型与导出 | S4-QUALITY |
| `web/src/flowpilot_shell/api_client.py` | Cookie-only API 适配、禁止 tenant/role 头、稳定错误映射 | S4-QUALITY |
| `web/src/flowpilot_shell/live.py`、`web/src/flowpilot_shell/store.py` | 权威 Task 回读、重复事件处理与会话清理 | S4-QUALITY |
| `web/server.py` | 会话隔离 BFF、认证代理、严格 Cookie、SSE 与失败关闭 | S4-QUALITY |
| `web/shell/index.html`、`web/shell/app.js`、`web/shell/shell.css` | 中文身份状态、auth epoch、重连/去重和可访问性体验 | S4-QUALITY |
| `web/README.md` | Cookie-only Live 配置与安全边界说明 | S4-QUALITY |
| `tests/experience/test_adapter_boundary.py`、`tests/experience/test_live_mode.py` | 适配器与事件边界回归 | S4-QUALITY |
| `tests/experience/test_identity_shell.py` | 双服务身份、安全与错误黑盒 | S4-QUALITY |
| `tests/experience/browser_identity_race.cjs` | 登出/刷新异步竞态执行门禁 | S4-QUALITY |
| `tests/acceptance/m8/test_web_identity_blackbox.py` | WP-086 独立浏览器/BFF acceptance | S4-QUALITY |
| `tests/acceptance/m8/evidence/WP-086-a1-HANDOFF.md` | 本交接证据 | S4-QUALITY |

## 契约、数据库与配置变化

- 契约版本：无变化；ContractSet 摘要保持 `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`。
- Migration：无。
- 环境变量：未修改共享环境文件；Live Web 只要求既有 `WEB_SHELL_API_BASE`，删除 Web 内部对 `WEB_SHELL_TENANT_ID` 的信任和文档要求。
- 兼容性：Demo 模式保持；Live Web 内部构造接口改为 Cookie-only，不属于公共跨进程 Contract。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| `uv run --frozen python -m pytest tests/experience tests/acceptance/m8 -q` | PASS：`101 passed` | 终端输出 |
| `node tests/experience/browser_identity_race.cjs` | PASS：`browser identity race gate: PASS` | 终端输出 |
| `uv run --frozen ruff check web tests/experience tests/acceptance/m8` | PASS：`All checks passed!` | 终端输出 |
| `uv run --frozen mypy --strict web/src web/server.py` | PASS：`21 source files` | 终端输出 |
| `uv run --frozen python -m pytest tests/experience/test_secret_scan.py -q` | PASS：`2 passed` | 终端输出 |
| `git diff --check` | PASS | 终端输出 |
| 本地真实浏览器 DOM/交互复核 | PASS：`zh-CN`、`role=status`、tenant/role 输入 `0`、Token 模式 DOM 命中 `0`、console warning/error `0` | 浏览器观察记录 |

## 安全与失败路径

- 已验证负向路径：缺失/过期/撤销/伪造/重复会话、跨租户伪造头、旧异步 DOM 写回、旧刷新恢复、SSE 断线与全量重放、畸形 Cookie 属性、上游敏感错误、Live 演示参数绕过。
- 确定性结果：跨会话缓存污染 `0`；伪造 tenant/role 头上游转发 `0`；Token/nonce canary 在代理响应、DOM 和日志中命中 `0`；登出后旧视图写回和旧刷新重连 `0`。
- 未验证风险：真实 Keycloak/IdP 与 S2 并行 Runtime 组合由 Join 门禁验证；本 Attempt 不引入外部网络或付费调用。
- Secret/PII 检查：Secret Scan `2 passed`；测试数据均为合成 canary，不含真实凭据或 PII。

## 已知问题

- 无本 Attempt 阻断问题或未关闭 P0/P1。
- S5 当前未提供只读 session-status 端点；Web 启动以受保护 refresh 验证会话并接受 Cookie 轮换，这是当前公开 API 下的预期组合方式。

## 已知事实与避免重复

- `KNOWN_FACTS`：WP-081～084 与 M7 Web/Studio 证据可复用；S5 WP-083 已提供 cookie-only login/callback/refresh/logout 公开边界。
- `DO_NOT_RECHECK`：未重跑 Keycloak、RLS、全仓、Compose、M7 固定 156 Case或历史 Handoff。
- `FAILURE_SIGNATURES`：进程全局 tenant/cache 会跨会话混淆；旧异步请求会在 logout 后回写；Cookie 属性子串匹配可伪装 `HttpOnly`；上游 error.message 可向浏览器泄漏。
- `REUSED_DECISIONS`：ADR-0005 完整 Context 与 cookie-only BFF 决策；S5 `WP-083` Handoff `sha256:1b4bcfa22057656d7189153f338537e1b2e52c570e975b87938462cb78036183`。
- `DUPLICATE_WORK_AVOIDED`：复用 WP-081～084、M7 证据与 S5 白盒结论，改用 Web/BFF、真实 DOM 和异步竞态观察边界。

## 学习候选

```text
LEARNING_CANDIDATE=Cookie-only BFF 的双重会话隔离
MATURITY=VERIFIED
TRIGGER=浏览器 tenant 头、进程全局缓存或 logout 后旧异步完成可重新形成身份权威或受保护输出
MECHANISM=仅隐藏 Token 不足以隔离会话；缓存键、事件回读和异步提交点若不同时绑定已验证会话代次，旧请求仍能跨越身份切换
STRUCTURE=严格 session-cookie 解析+不可逆会话指纹缓存+权威 Task 回读+auth epoch/AbortController+稳定错误投影
EVIDENCE=c49448231fa84b1b3c301f2c224d44c03fd5c1b7；101 tests；browser identity race gate；真实 DOM 复核
RESIDUAL_RISK=真实 IdP/Keycloak 与并行 Runtime 组合仍由 Join 验证
TARGET=docs/architecture/ENGINEERING_PLAYBOOK.md identity/session boundary
```

## 子 Agent 使用摘要

```text
SUBAGENTS_USED=2
SUBAGENT_MODES=READ_ONLY_PARALLEL
SUBAGENT_TASKS=wp086-web-surface,wp086-api-blackbox
SUBAGENT_WRITERS=0
PARENT_REPRODUCED_RESULTS=yes
REUSED_DECISIONS=ADR-0005,S5-WP-083,WP-081-through-WP-084,M7-Web-Studio
DUPLICATE_WORK_AVOIDED=5
```

## 接收会话下一步

1. S1 核验最终 Head、Handoff SHA-256、ContractSet、授权路径与 clean 状态。
2. 与并行 `M8-03A-S2-RUNTIME` 汇合后执行 WP-086 Join；本 S4 任务不直接唤醒其他角色。
3. S1 保留 Feature 状态、M8 集成和后续链路裁决。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M8-IDENTITY-TENANCY-01
STEP_ID=M8-03B-S4-WEB
ATTEMPT_ID=WP-086-a1
NEW_HEAD=<this-handoff-commit>
IMPLEMENTATION_HEAD=c49448231fa84b1b3c301f2c224d44c03fd5c1b7
BASE_COMMIT=e0a929cb15c213d6b65f0d03ba0bbe3742824fbb
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/acceptance/m8/evidence/WP-086-a1-HANDOFF.md
NEXT_ROLE=S1-ARCH
NEXT_ATTEMPT_ID=none
ESCALATE_TO_S1=no
SUBAGENTS_USED=2
```

## 可回滚方式

- 按提交逆序回滚本分支的交接证据和实现提交；无契约、数据库、Migration、共享配置或依赖锁回滚动作。
