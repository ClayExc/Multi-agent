# WP-092：测试选择与 Evidence Cache

## 元数据

- 状态：BLOCKED
- Attempt：WP-092-a1
- Owner：S5-CORE
- Reviewer：S4-QUALITY
- 风险：R2
- Feature：FP-OPS-002
- 依赖：WP-091
- 执行：ORDERED / HOT_CONTINUE

## 目标与范围

在 WP-091 同一 S5 Worktree 上增加测试选择、证据缓存和 Attempt 报告。继续使用
`packages/engineering-control/**`、`scripts/engineering/**`、
`tests/core/engineering_control/**`、`tests/core/evidence/WP-092-a1-HANDOFF.md`；若增加
稳定 CLI 入口，可由 S5 单写 `Makefile`。

## 必须行为

- 包内变化选择定向与依赖测试；公共 Port 升级共享回归。
- Contract、Migration、Lock、安全、未知路径和非线性基线升级 FULL/RELEASE。
- 不能证明完整性时失败关闭，不返回空命令。
- 缓存键绑定命令、产品/Contract/Migration/Lock、环境和工具链；失败结果不缓存。
- 在线 Provider、Secret、漏洞查询和真实 Migration 默认不可复用。
- 报告区分实际记录和估算 Token，保留选择原因、失效原因和范围扩展。

## 必须测试

正常、rename/delete、跨包、共享签名、安全升级、环境漂移、缓存命中/失效、篡改证据、
命令参数注入和重复运行幂等。Core、Ruff、严格 Mypy、锁与 CLI Smoke 通过。
