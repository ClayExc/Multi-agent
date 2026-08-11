# FlowPilot 可替换 Web 外壳

本目录提供 Fixture 演示与 M8 Cookie-only 真实 API/SSE 两种可切换模式，注册身份为
`experience-builder`（`S4-QUALITY`）。本目录不修改公共 ContractSet。

## 边界（硬约束，tests/experience/ 静态断言）

- Web 不保存业务事实：外壳状态全部在内存中，会话结束即失，无持久化。
- Web 不推断审批成功：审批卡只做展示，渲染层不输出任何审批写控件；
  适配层不提供审批命令构建/提交方法。
- Web 不直接访问 PostgreSQL/MCP：`web/src` 运行期仅依赖标准库
  （依赖图断言），数据只经 API/SSE 适配边界流入。
- 浏览器只持有 API/BFF 设置的 HttpOnly 不透明 Cookie，不读取或解析 Token；tenant、
  subject、role、scope 和 purpose 不能由浏览器 Header、Query、表单或本地状态选择。
- 数据形态对齐 `apps/api` 的 Task/Command/Event v1 契约与
  `apps/api/stream.py` 的 SSE 帧格式（`id:` / `event: task.event` /
  `data:` + `: ping`）。
- 审批卡渲染输入契约与 M5-1 审批卡数据契约同构（Approval v1 +
  PlannedAction v1 联合视图：影响=resource+purpose、参数=arguments、
  依据=policy_version+policy_decision_id、摘要=tool+action_id+agent、
  过期时间=expires_at）；M5-1 合入后由契约测试校验一致性。

## 目录结构

```text
web/
  server.py                     # 本地演示服务器（纯 stdlib）
  shell/                        # 静态外壳：index.html / app.js / shell.css
  fixtures/                     # 本地合成 Fixture（manifest.json 登记 + sha256）
  tools/fixup_fixtures.py       # fixture digest 回填工具（可复现）
  src/flowpilot_shell/
    models.py                   # 契约适配视图（严格校验，拒绝未知字段）
    api_client.py               # API 适配边界（只读投影 + 非审批命令）
    sse_client.py               # SSE 消费：帧解析/去重/序列缺口检测
    live.py                     # 权威 Task 刷新、重连断点与投影租户复核
    projection.py               # 五阶段安全 Studio 产品投影
    store.py                    # 内存外壳状态（无持久化）
    commands.py                 # task.message.submit.v1 / task.retry.request.v1
    canonical.py                # RFC 8785 规范化（与 domain 位级互操作）
    render/                     # 纯渲染函数（任务列表/详情/时间线/审批卡/
                                # 补全表单/错误面板/引用）
tests/experience/               # fixture 契约 + 适配边界 + 渲染断言 + 安全
```

## 运行

```bash
# 演示页（合成 Fixture 驱动；--port 或环境变量 WEB_SHELL_PORT，默认 8765）
uv run --frozen python web/server.py --port 8765
# 打开 http://127.0.0.1:8765/

# 真实 API/SSE 模式（身份与租户只由 API/BFF 不透明会话解析）
WEB_SHELL_MODE=live \
WEB_SHELL_API_BASE=http://127.0.0.1:8000 \
uv run --frozen python web/server.py --port 8765

# 测试
uv run --frozen python -m pytest -q tests/experience
```

演示页可浏览：任务列表、任务详情与时间线（运行/等待/失败）、信息补全表单、
审批卡（影响/参数/依据/摘要/过期时间）、引用与结果引用、错误面板与重试入口、
SSE 断线提示与自动重连（服务端透传 Last-Event-ID，客户端按 event_id 与内容指纹
去重；当前 API 可能完整重放，不能依赖只返回断点后事件；同 ID 异内容或同 sequence
异事件失败关闭）。真实模式下每个合法事件都会重新
读取权威 Task 投影，事件只构建时间线，不直接改写业务终态。

## 恢复语义（适配层模拟）

- 重连后服务端重放事件流，客户端仅对同 `event_id` 同内容去重；冲突失败关闭。
- 每任务按 outbox `sequence` 检测缺口（对应
  `TaskEventSubscriptionService.gaps`），缺口在时间线渲染为
  「事件缺口 · 重建」条目。
- 恢复入口「重建」= 重新拉取权威 Task 投影并重建视图，外壳状态与后端
  终态一致；事件流缺口如实展示，不伪造事件。

## 安全边界

- Live Proxy 只向 API 转发不透明 Cookie、`Last-Event-ID` 和协议 Header；浏览器传入的
  tenant/role/subject/purpose Header、Query 或表单值不向上游传播。
- Task 缓存、时间线和 SSE 去重状态按 Cookie 的不可逆会话指纹隔离；刷新、登出和
  重新认证会清除旧会话状态，不能跨会话复用。
- 真实模式拒绝浏览器直接提交 authority-bearing 原始 TaskCommand；外壳只允许
  从权威 Task 投影构建已注册的补全/重试命令。
- 当前工作包不增加正文上传接口；请求正文必须先通过受信任的引用入口落地，Web
  只提交公共契约允许的 opaque message reference。
