# WP-093：工程控制面黑盒验收

## 元数据

- 状态：ACCEPTED_M9T
- Attempt：WP-093-a1
- Owner：S4-QUALITY
- Reviewer：S1-ARCH
- 风险：R2
- Feature：FP-OPS-002
- 依赖：WP-092
- 执行：ORDERED

## 目标与范围

从公开 CLI 黑盒验证仓库地图、Capsule、测试计划、缓存和报告。允许修改：

- `tests/acceptance/engineering_control/**`
- `artifacts/acceptance/engineering-control/**` 生成器

## 验收矩阵

- 固定的包内、跨包、Contract、Migration、Lock、安全和未知路径 Fixture。
- 变异矩阵要求测试漏选数为 0；包内 Fixture 初始读取文件数和字节低于全仓 20%。
- 缓存污染、失败结果复用、环境漂移、证据 Hash 篡改和命令注入全部失败关闭。
- Windows 路径、UTF-8、超大生成文件和 coverage 噪音不得改变源码统计。
- 工具异常时明确回退 FULL/RELEASE，不影响人工范围扩展。

输出正式 `artifacts/acceptance/engineering-control/WP-093-a1-PROOF.json`，但不自行提升
Feature 状态。
