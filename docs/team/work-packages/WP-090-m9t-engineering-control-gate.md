# WP-090：M9T 工程控制面门禁

## 元数据

- 状态：DONE
- Attempt：WP-090-a1
- Owner：S1-ARCH
- Reviewer：S5-CORE、S4-QUALITY、S7-INTEGRATION
- 风险：R1
- Feature：FP-OPS-002
- 依赖：M8 final
- 执行：ORDERED

## 目标

固定仓库地图、Delta Context Capsule、测试选择、Evidence Cache 和效率报告的边界，
注册最小 Agent 链并派发可测试的工作包。原 M9 的策略、DLP、Capability 和审计不启动。

## 输出

- [`ENGINEERING_CONTROL_PLANE.md`](../../architecture/ENGINEERING_CONTROL_PLANE.md)
- `CHAIN-M9T-ENGINEERING-CONTROL-01`
- FP-OPS-002 关联与 M9T 独立工作包
- WP-091～WP-094

## 完成定义

- 不改变公共 ContractSet、产品代码、Migration 或发布状态。
- 三个实现/验证角色的路径不并行冲突。
- M9T 失败可回退到现有 DELTA/FULL/RELEASE 流程。
