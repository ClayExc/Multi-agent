# FlowPilot 轨道 C — 可替换 Web 外壳（第一阶段）

本目录实现路线图「轨道 C：Web 外壳提前并行」的第一阶段交付，注册身份
`experience-builder`（`S4-QUALITY` 路径档案）。激活门禁 = S1 分配 UI Feature
ID 并在 `docs/acceptance/TRACEABILITY.md` 登记；**未通过前保持 DESIGNED**，
本目录不修改 ContractSet/Traceability 摘要。

## 边界（硬约束，tests/experience/ 静态断言）

- Web 不保存业务事实：外壳状态全部在内存中，会话结束即失，无持久化。
- Web 不推断审批成功：审批卡只做展示，渲染层不输出任何审批写控件；
  适配层不提供审批命令构建/提交方法。
- Web 不直接访问 PostgreSQL/MCP：`web/src` 运行期仅依赖标准库
  （依赖图断言），数据只经 API/SSE 适配边界流入。
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

# 测试
uv run --frozen python -m pytest -q tests/experience
```

演示页可浏览：任务列表、任务详情与时间线（运行/等待/失败）、信息补全表单、
审批卡（影响/参数/依据/摘要/过期时间）、引用与结果引用、错误面板与重试入口、
SSE 断线提示与自动重连（服务端按 Last-Event-ID 重放，客户端按 event_id 去重）。

## 恢复语义（适配层模拟）

- 重连后服务端重放事件流，客户端按 `event_id` 去重（at-least-once）。
- 每任务按 outbox `sequence` 检测缺口（对应
  `TaskEventSubscriptionService.gaps`），缺口在时间线渲染为
  「事件缺口 · 重建」条目。
- 恢复入口「重建」= 重新拉取权威 Task 投影并重建视图，外壳状态与后端
  终态一致；事件流缺口如实展示，不伪造事件。

## 已知事项（交接给 S1/S7）

- S1 未分配 UI Feature ID：TRACEABILITY 未登记，本交付保持 DESIGNED。
- `tests/experience/` 不在根 `pyproject.toml` testpaths 内（共享文件，改动
  需 S1/S5 批准）；当前以显式路径运行，`make test` 不受影响。
- 真实 OIDC 认证不在第一阶段范围：适配层以 `X-FlowPilot-Tenant-Id`
  约定传输租户（演示身份来自 fixture），生产接入时由受信任的请求安全
  端口（RequestSecurityPort）替换。
