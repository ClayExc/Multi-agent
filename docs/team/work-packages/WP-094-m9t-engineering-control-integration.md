# WP-094：工程控制面组合验证

## 元数据

- 状态：BLOCKED
- Attempt：WP-094-a1
- Owner：S7-INTEGRATION
- Reviewer：S1-ARCH
- 风险：R2
- Feature：FP-OPS-002
- 依赖：WP-093
- 执行：ORDERED / FINAL_GATE

## 目标与范围

在空本地输出目录复算仓库地图、Capsule、测试选择、缓存失效和效率报告，验证 Workspace、
Lock、Contract 与既有门禁没有回退。允许修改：

- `scripts/integration/verify_engineering_control.py`
- `tests/integration/engineering_control/**`
- `artifacts/integration/**` 生成器

## 完成定义

- 两次生成的机器输出逐字节一致。
- Acceptance 证据、Feature ID、输入 Head、保护树和命令结果可追溯。
- 代表性增量不漏测试，跨边界变化全部升级；缓存误命中为 0。
- 定向、共享、Contract、Ruff、严格 Mypy、Secret 和供应链门禁通过。
- 交回 S1；S7 不批准自身结果，不启动原 M9 产品链。
