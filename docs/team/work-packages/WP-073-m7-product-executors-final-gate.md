# WP-073：M7 产品执行器与最终组合门禁

## 元数据

- 状态：BLOCKED_BY_WP-072
- Attempt ID：待激活
- 风险等级：R2
- 责任角色：S4-QUALITY
- 参与角色：S7-INTEGRATION
- 评审角色：S1-ARCH
- 功能 ID：FP-EVAL-001、FP-EVAL-002、FP-EVAL-003、FP-OPS-002
- 依赖工作包：WP-072
- 执行模式：ORDERED

## 目标

- 为 M7 已支持的只读产品 Case 注册真实执行器和证据采集器。
- 保持全部 156 条 Case 固定分母；未实现类别继续明确失败，不得跳过或缩分母。
- 形成 Web/API/Worker/Graph/Data/Provider/Studio 的 M7 组合证据。

## 允许修改路径

- S4：`packages/evaluation/**`、`scripts/acceptance/**`、`tests/acceptance/**`。
- S7：`scripts/integration/**`、`tests/integration/**`。
- S1：只读复算并作最终接受裁决。

## 必须测试

- 正常：支持的 M7 Case 通过真实产品入口执行并绑定 Evidence Hash。
- 边界：执行器唯一匹配，重复运行结果可复算。
- 失败：未注册、错身份、错版本、缺证据和伪造输出失败关闭。
- 安全：安全 Case 的确定性断言优先于 Judge，跨租户成功数为 0。
- 恢复：重启与断线 Case 不重复产生逻辑模型/工具调用。

## 解锁条件

- WP-070～WP-072 全部通过各自门禁；S7 仅在 M7 垂直候选汇合时运行 RELEASE。
- S1 完成最终复算后停在用户门禁，不自动启动 M8。
