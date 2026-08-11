# WP-081-a1 S6 本地 Keycloak 基座交接

## 基本信息

- Work Package：WP-081
- Attempt ID：WP-081-a1
- Chain ID：CHAIN-M8-IDENTITY-TENANCY-01
- Step ID：M8-01A-S6-KEYCLOAK
- 责任会话：S6-DATA（identity-data-builder）
- 接收会话：S1-ARCH
- 交接策略：S1_GATE / M8_JOIN_01
- 功能 ID：FP-SEC-001、FP-SEC-007、FP-OPS-001
- 基线提交：`be068c9cc315c657f04e3327e18e15a41b01f9fb`
- 实现提交：`4b7539b82ed45e906490a3c7e9e65d0189272613`
- 分支：`codex/s6/m8-identity-data`
- 最终提交：本文件所在提交；精确 SHA 由交接消息返回
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：完成；`GATE=PASS`

## 完成内容

- 新增可在空数据卷导入的 `flowpilot-local` Realm Fixture，带显式修订号、强制
  RS256、短期 Token/授权码、刷新令牌轮换、会话上限、暴力破解保护及关闭的自助注册、
  密码重置和用户名编辑入口。
- 建立 `/tenants/tenant-a|tenant-b/users|approvers` 唯一嵌套 Group，每租户各有普通
  用户和审批用户。Token 同时携带 allow-listed `tenant_id`、完整 Group 路径和 Realm
  Role；后续可信身份边界必须核对 Tenant Claim 与 Group 一致，Role 只作策略输入。
- 建立四个职责分离 Client：Web 使用 confidential Authorization Code + PKCE S256；
  API 只作 bearer-only audience；Worker/Gateway 只允许 Client Credentials，并使用
  不同 Secret、`workload_kind` 和精确 audience。
- Compose 使用只读 Realm 挂载、持久化 `keycloak-data`、进程环境 Secret 注入和容器
  内 management port 9000 `/health/ready`；management port 不暴露到宿主机，产品端口
  仍只绑定 `127.0.0.1`。
- 新增动态验证器，覆盖真实 Authorization Code + PKCE、双租户声明、刷新轮换、前后端
  撤销、服务 Client、错误 Client/Secret/redirect/PKCE/audience/密码授权和过期授权码。
- 实库同一数据卷执行首次导入、restart 与 force-recreate，三次实体指纹一致：
  `sha256:96ce8d765cfd676d7eb22625662245afaa9bb5f5b67e7c39aa2abd1432537531`。

## 未完成与非目标

- 本包不实现 JWT 验证、SecurityContext/TenantContext 映射、RLS 或 Migration；这些由
  WP-082/WP-083/WP-084 在各自授权路径完成。
- 本地 `start-dev`、内置 Keycloak 存储和回环 HTTP 不是生产 IdP、HA、TLS、备份或
  企业身份配置；不得把当前 Realm 暴露到本机之外。
- 未运行独立发布型 `scripts/acceptance/run_acceptance.py`；WP-081 不提升 RELEASE，且
  全仓 pytest 已覆盖现有 acceptance/experience/integration 集合。
- 未执行在线 Provider 或任何付费调用；唯一 skip 是显式关闭的既有 Provider smoke。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `.env.example` | 增加本地回调、Origin、三类 Client Secret 与四个用户密码占位符 | S6-DATA（WP 授权共享文件） |
| `infra/compose/compose.yaml` | Realm 导入、数据卷、健康检查和必填环境变量 | S6-DATA |
| `infra/compose/README.md` | 导入、幂等重启、健康与验证说明 | S6-DATA |
| `infra/keycloak/README.md` | Fixture 边界、Client/Tenant 语义和本地限制 | S6-DATA |
| `infra/keycloak/flowpilot-local-realm.json` | Realm、Group、用户、Role、Client 与 Mapper | S6-DATA |
| `tests/data/e2e/test_compose_baseline.py` | Compose/环境/只读导入静态证据 | S6-DATA |
| `tests/data/security/test_keycloak_fixture_security.py` | Tenant、Client、Secret、回环和失败关闭负例 | S6-DATA |
| `tests/data/integration/verify_keycloak.py` | Keycloak 真实协议与恢复验证器 | S6-DATA |
| `tests/data/evidence/WP-081-a1-HANDOFF.md` | 本交接 | S6-DATA |

## 契约、数据库与配置变化

- 公共契约：无修改；Contract Conformance 和 ContractSet 摘要保持一致。
- Migration/RLS：无修改；留给 WP-084。
- Keycloak 持久化：新增命名卷 `keycloak-data`；首次导入，Realm 已存在时跳过重导，
  restart/force-recreate 保留实体 ID 和配置。
- 环境变量：新增 `FLOWPILOT_WEB_ORIGIN`、`FLOWPILOT_OIDC_REDIRECT_URI`、
  `KEYCLOAK_WEB_CLIENT_SECRET`、`KEYCLOAK_WORKER_CLIENT_SECRET`、
  `KEYCLOAK_GATEWAY_CLIENT_SECRET` 及四个租户测试用户密码。除 Origin/redirect 外均为
  Compose 必填 Secret；仓库只提交明显的 `local-dev-*-change-me` 占位值。
- 兼容性：复用既有 Keycloak `26.1.4`、control-plane 网络和宿主回环端口；未新增镜像、
  Python 依赖、Compose 服务、Migration 或公共 Schema。

## 验证

环境：Windows、CPython 3.12.11、Docker Engine 29.6.2；真实外部/付费调用为 0。

| 命令/检查 | 结果 | 证据 |
|---|---|---|
| 隔离 Compose 空卷导入 + 动态验证 | PASS | 4 Client、4 User、2 User Flow、2 Service Flow、13 个负例 |
| 同卷 restart + force-recreate | PASS | 三次 Fixture 指纹完全一致 |
| Keycloak 日志 Secret 精确扫描 | PASS | `secret_hits=0` |
| Compose 资源清理 | PASS | `containers=0 volumes=0 networks=0` |
| `pytest tests/data -q` | PASS | `92 passed` |
| `scripts/quality.ps1 test-security` | PASS | `169 passed` |
| `scripts/quality.ps1 test-contract` | PASS | 20 schemas / 35 cases / 52 features |
| `scripts/quality.ps1 lint` | PASS | Ruff + strict Mypy，129 source files |
| `scripts/quality.ps1 test` | PASS | `1350 passed, 1 explicit online skip` |
| `scripts/quality.ps1 audit` | PASS | `No known vulnerabilities found` |
| `git diff --check` | PASS | 无空白错误 |

## 安全与失败路径

- 已验证错误/缺失 Client、缺失/互换 Secret、未登记 redirect、缺失/错误 PKCE、错误
  verifier、错误 token redirect、过期授权码、禁用密码授权和 bearer-only API 拒绝。
- 已验证请求方附加 `tenant_id`/`audience` 参数不能改变签发 Tenant 或 audience；双租户
  用户 Token 的 `tenant_id`、唯一 Group 路径和 Role 相互一致；服务 Token 不继承用户
  Tenant/Group。
- 拒绝路径不打印响应正文、Token、授权码、Cookie、密码或 Client Secret；动态输出只含
  计数和不可逆实体 ID 指纹。
- Realm Fixture、Compose 和 `.env.example` 仅包含环境变量或明显本地占位值；既有 Secret
  Scan 通过，运行日志对十个随机注入 Secret 的精确命中数为 0。
- 残余风险：Keycloak 26.1.4 的认证 Cookie 带 Secure 标记；动态验证器只在目标为明确
  IPv4/IPv6 回环地址时模拟现代浏览器对可信本地来源的 Cookie 发送语义，非回环地址
  立即失败关闭。生产环境仍必须使用 TLS。

## 已知问题

- 无 WP-081 阻断。S1 仍需与并行 WP-082 做路径交集、Issuer/audience/Claim 约定和最终
  身份边界组合审查；本 Handoff 不代表 M8 发布完成。

## 已知事实与避免重复

- `KNOWN_FACTS`：复用 Keycloak 26.1.4、control-plane 与既有 Data 基线；RLS/Migration
  留给 WP-084。
- `DO_NOT_RECHECK`：未重跑 M7 Provider/知识执行器专项、M7 合并证明或既有 PostgreSQL
  RLS 正确性；全仓 pytest 只作为最终回归门禁。
- `FAILURE_SIGNATURES`：Python `http.cookiejar` 不把回环 HTTP 视为可信 Cookie 通道；
  Keycloak 26 首次登录会对缺少姓名的导入用户进入资料补全流程。
- `REUSED_DECISIONS`：ADR-0005 与 `IDENTITY_TENANCY.md` 的 BFF、职责分离 Client、可信
  Tenant 映射和不持久化 Token 边界。
- `DUPLICATE_WORK_AVOIDED`：复用两项只读子 Agent 的 Realm 与 Compose 独立审查，主
  Agent 仅复核差异并运行静态/实库/全仓门禁。

## 学习候选

```text
LEARNING_CANDIDATE=可信回环地址的 Secure Cookie 测试客户端差异
MATURITY=VERIFIED
TRIGGER=Keycloak 登录页设置了 Secure 认证 Cookie，但 httpx 后续表单请求未携带 Cookie
MECHANISM=现代浏览器/6265bis 可把可信回环来源视为安全连接，Python http.cookiejar 仍只按 URL scheme 过滤 Secure Cookie
STRUCTURE=验证器先精确验证目标为 IPv4/IPv6 loopback，再显式回传同 host/path Cookie；非回环立即失败关闭且不输出 Cookie 值
EVIDENCE=WP-081-a1 动态登录、三阶段重启验证和 secret_hits=0
RESIDUAL_RISK=该适配只用于本地协议验证；生产仍必须使用 TLS 和真实浏览器/BFF 黑盒证据
TARGET=none
```

## 子 Agent 使用摘要

```text
SUBAGENTS_USED=2
SUBAGENT_MODES=READ_ONLY_PARALLEL
SUBAGENT_TASKS=realm-fixture-review,compose-security-review
SUBAGENT_WRITERS=0
PARENT_REPRODUCED_RESULTS=yes
REUSED_DECISIONS=ADR-0005,IDENTITY_TENANCY,WP-081
DUPLICATE_WORK_AVOIDED=2
```

## 接收会话下一步

1. 核验最终 Head、本 Handoff SHA256、ContractSet、基线祖先、授权路径和 clean。
2. 在 `M8_JOIN_01` 与并行 WP-082 对齐固定 Issuer、Web/API/Worker/Gateway audience、
   `tenant_id`、完整 Group 路径及 Role 约定；请求方 Tenant 仍不得成为权威输入。
3. 未经 WP-083/WP-084 授权不得提前实现 API/Worker SecurityContext 或数据库 RLS。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M8-IDENTITY-TENANCY-01
STEP_ID=M8-01A-S6-KEYCLOAK
ATTEMPT_ID=WP-081-a1
NEW_HEAD=<this-handoff-commit>
IMPLEMENTATION_HEAD=4b7539b82ed45e906490a3c7e9e65d0189272613
BASE_COMMIT=be068c9cc315c657f04e3327e18e15a41b01f9fb
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/data/evidence/WP-081-a1-HANDOFF.md
NEXT_ROLE=S1-ARCH
NEXT_ATTEMPT_ID=M8_JOIN_01
ESCALATE_TO_S1=no
SUBAGENTS_USED=2
USER_INPUT_REQUIRED=none
```

## 可回滚方式

- 按逆序 revert 本 Handoff 提交与实现提交
  `4b7539b82ed45e906490a3c7e9e65d0189272613`；禁止 reset、rebase 或覆盖其他会话提交。
- 本地 Keycloak 数据可用 `docker compose down -v` 删除并从 Fixture 重建，但这会删除
  当前 Compose 项目的本地身份数据；执行前必须确认目标 Project 与数据卷，仅限可丢弃
  的开发环境。
