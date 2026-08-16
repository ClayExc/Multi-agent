# WP-101：版本化 Rego 与策略决定

## 元数据

- 状态：ACCEPTED_M9
- Owner：S3-PLATFORM
- Attempt：WP-101-a1
- 风险：R2
- Feature：FP-SEC-004、FP-APR-002、FP-APR-003
- 依赖：WP-100
- 执行：ORDERED
- 写入：`packages/policy/**`、`tests/platform/**`、`tests/platform/evidence/WP-101-a1-HANDOFF.md`

## 主写目标

实现带 Bundle 摘要的 Rego/OPA Policy Port、本地发布/回滚、已验证缓存和 deny-overrides，
让主体、资源、动作、租户、用途、分级、风险与审批条件形成不可变 PolicyDecision。

## 验收

- 发布、回滚、缓存命中与版本失效确定性可复现。
- 缺字段、未知 Obligation、OPA 超时/异常、错 tenant/context/action、撤销版本均拒绝。
- SoD、审批重验和策略版本绑定不能被模型输出覆盖。
- 领域测试、Platform 测试、Ruff、strict Mypy、Contract 摘要和 Secret Scan 通过。

## 非目标

不实现 Capability、Secret、Gateway DLP、Compose 或生产 OPA。完成后在同一 Worktree
热继续 WP-102，不回流 S1。
