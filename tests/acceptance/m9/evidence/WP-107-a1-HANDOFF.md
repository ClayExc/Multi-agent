# WP-107-a1 S4 治理 Web 交接

## 基本信息

- Work Package：WP-107
- Attempt ID：WP-107-a1
- Chain ID：CHAIN-M9-GOVERNANCE-01
- Step ID：M9-07-S4-GOVERNANCE-WEB
- 责任会话：S4-QUALITY / governance-quality-builder
- 执行模式：ORDERED
- 风险等级：R2
- 功能 ID：FP-UI-001、FP-OBS-002、FP-OBS-003
- 输入提交：`53925ce0403e405c1d66e631d35634dfc5e70f7e`
- 分支：`codex/s4/wp-107-m9-governance-quality`
- ContractSet：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：PASS_HANDOFF；未声明 M9、Feature、RELEASED 或 FROZEN

## 完成内容

- 新增中文只读“治理与安全”页面，展示当前激活策略版本、策略决策、Audit、Security Event 与 correlation chain；Audit 与 Security Event 使用独立语义区域，明确不以 Trace 替代。
- Web 仅通过 S5 已交付的五个安全 Governance Query API 读取闭合 DTO；浏览器不接收治理 JSON，不直连 PostgreSQL 或 OPA，也不提供 tenant、role、subject 或 purpose 权威输入。
- `ApiClient` 只转发 HttpOnly 不透明会话 Cookie；治理响应必须为 JSON、`Cache-Control: no-store` 且 `Vary: Cookie`。未知字段、错误类型、额外敏感字段、凭据形态、跨 correlation 注入和悬空事件引用均失败关闭。
- 服务端严格白名单化 tab、limit、cursor、task、correlation 和 UTC 时间范围；重复字段、未知字段、伪造 tenant/role、非法时间范围在上游调用前拒绝。
- 页面覆盖分页、任务/关联/时间筛选、空状态、404、授权拒绝、会话撤销、上游不可用和被污染投影；失败面不复用缓存或旧页面，不回显上游错误正文。
- 浏览器身份 epoch 扩展到治理页面：退出或会话切换后，迟到的治理响应不能恢复 DOM；Task SSE 只触发权威治理投影重读，不成为 Audit/Security 事实源。
- 增加可访问性结构：中文标题、语义化区域、表格 caption/header、筛选 label、焦点样式、`aria-current`、错误 `role=alert` 与明确空状态。

## 修改路径

- `web/src/flowpilot_shell/governance.py`
- `web/src/flowpilot_shell/api_client.py`
- `web/src/flowpilot_shell/render/governance.py`
- `web/src/flowpilot_shell/render/__init__.py`
- `web/server.py`
- `web/shell/app.js`
- `web/shell/index.html`
- `web/shell/shell.css`
- `tests/experience/browser_identity_race.cjs`
- `tests/experience/test_adapter_boundary.py`
- `tests/experience/test_governance_shell.py`
- `tests/acceptance/m9/test_governance_web_blackbox.py`
- `tests/acceptance/m9/evidence/WP-107-a1-HANDOFF.md`

## 契约、数据库与配置变化

- 公共 Contract、Schema、ADR：无变化；Contract digest 与输入一致。
- PostgreSQL、Migration、RLS、Redis、OPA bundle、Secret 配置：无变化。
- `pyproject.toml`、`uv.lock`、Makefile 与根共享配置：无变化。
- Web 未引入生产依赖，未连接数据库/OPA，未运行 Compose、在线 Provider 或付费调用。

## 独立黑盒证据

- 两个不透明 Cookie 会话在真实 Web HTTP 边界读取不同策略/决策/事件；跨租户内容成功暴露数为 0。
- 浏览器伪造 `X-FlowPilot-Tenant-Id` 与 `X-FlowPilot-Roles` 不进入上游请求；治理 query 中的 tenant/role 在任何 API 调用前稳定 422。
- 分页 cursor 只进入被选择的列表端点；任务、correlation 与时间筛选只进入公开白名单参数。
- 会话撤销后返回 401 且旧策略内容为 0；上游 503 与被污染闭合 DTO 分别返回安全 503/502，缓存事实与 canary 暴露均为 0。
- Audit 与 Security Event 各有独立列表和 correlation chain；空状态不会用 Trace 或合成事实填充。
- 原始 Prompt、Tool arguments/results、Token/Secret canary、tenant/subject 字段在页面、错误、DOM 片段与浏览器脚本权威输入中的暴露数为 0。

## 验证

| 命令 | 结果 |
|---|---|
| `uv run --frozen python -m pytest tests/experience tests/acceptance/m9 -q` | PASS：109 passed |
| `uv run --frozen python -m pytest tests/experience/test_governance_shell.py tests/acceptance/m9 -q` | PASS：15 passed（最终版本） |
| `uv run --frozen ruff check web/src/flowpilot_shell web/server.py tests/experience tests/acceptance/m9` | PASS |
| `uv run --frozen mypy --strict web/src/flowpilot_shell web/server.py` | PASS：23 source files |
| `uv run --frozen python -m pytest tests/experience/test_secret_scan.py -q` | PASS：2 passed / Web Secret Scan 0 |
| `uv run --frozen python contracts/conformance/validate.py` | PASS：20 schemas、35 cases、43 semantic negatives、52 features |
| `node --check web/shell/app.js` | PASS |
| `git diff --check` | PASS |

## 复用与未重复执行

- 复用 S5 WP-104 的 Cookie-only Governance Query API、闭合安全 DTO、授权重检与稳定错误语义。
- 复用 S6 WP-105/WP-106 的 PostgreSQL/OPA/Secret/Migration 证据；本 Attempt 未重复实库、OPA、Secret preflight、Migration 或恢复测试。
- 未重跑 S2/S3/S5/S6 Owner 单测、全仓、Compose、固定 156 Case、Release 或在线 Provider。

## 风险

- P2：治理首页通过四个只读列表端点顺序取数，列表间可能存在短暂时间偏差；需要强关联一致性时使用单一 correlation endpoint，其跨链引用由 Web 再次闭合校验。
- P2：当前公开 SSE 是 Task 通知流，只用来触发权威 Governance API 重读；它不承载 Audit/Security 事实。未来若新增治理通知流，仍必须保持相同“通知而非事实”边界。
- 未发现新增 P0/P1；公共契约和上游安全边界未变化。

## 子 Agent 使用摘要

```text
SUBAGENTS_USED=0
SUBAGENT_WRITERS=0
REUSED_DECISIONS=WP-104,WP-105,WP-106
DUPLICATE_WORK_AVOIDED=S2/S3/S5/S6 owner gates,PostgreSQL,OPA,Secret preflight,Migration,Compose,full-repo
```

## 学习候选

```text
LEARNING_CANDIDATE=none
MATURITY=none
TRIGGER=none
MECHANISM=none
STRUCTURE=none
EVIDENCE=tests/acceptance/m9/test_governance_web_blackbox.py
RESIDUAL_RISK=multi-list reads are not a transactional snapshot; correlation endpoint is the strict chain view
TARGET=none
```

## 下一动作

1. 复核本 Handoff、输入提交到最终 Head 的线性祖先、Contract digest、授权路径与 clean 状态。
2. 按 Chain 授权由同一 S4 Worktree 热继续 WP-108，不向无关角色发送普通完成通知。
3. WP-108 不得将 WP-107 的 Web PASS 外推为固定 156 Case、M9 Release 或 Feature 状态提升。

## 机器可读摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M9-GOVERNANCE-01
STEP_ID=M9-07-S4-GOVERNANCE-WEB
WORK_PACKAGE=WP-107
ATTEMPT_ID=WP-107-a1
INPUT_HEAD=53925ce0403e405c1d66e631d35634dfc5e70f7e
NEW_HEAD=<this-handoff-commit>
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
HANDOFF=tests/acceptance/m9/evidence/WP-107-a1-HANDOFF.md
GATE=PASS
CONTRACT_CHANGED=no
DATABASE_CHANGED=no
SHARED_ROOT_CHANGED=no
SUBAGENTS_USED=0
NEXT_ROLE=S4-QUALITY
NEXT_WORK_PACKAGE=WP-108
ESCALATE_TO_S1=no
```
