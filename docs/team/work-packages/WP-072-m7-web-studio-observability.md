# WP-072：M7 Web、Studio 与可观测体验

## 元数据

- 状态：MERGED_M7_CANDIDATE
- Attempt ID：WP-072-a1
- 风险等级：R2
- 责任角色：S4-QUALITY
- 参与角色：S2-RUNTIME
- 评审角色：S1-ARCH
- 功能 ID：FP-FLOW-002、FP-FLOW-004、FP-OBS-001、FP-OBS-002
- 依赖工作包：WP-071
- 执行模式：ORDERED

## 目标

- 将 Fixture Web 替换为可切换的真实 API/SSE 适配模式。
- 在 Web 和 LangGraph Studio 显示节点、模型调用、引用、Interrupt、恢复和错误。
- 只展示结构化安全投影，不暴露隐藏思维链、凭据或未脱敏数据。

## 允许修改路径

- S2：`apps/worker/**`、`packages/graph/**`、`tests/runtime/**` 中的安全调试投影。
- S4：`web/**`、`packages/observability/**`、`tests/experience/**`、相关验收测试。

## 必须测试

- 正常：页面提交中文请求并实时看到状态、引用和最终结果。
- 边界：断线重连、重复事件、序列缺口和多次 Interrupt。
- 失败：后端未配置、模型超时和恢复失败有稳定可操作提示。
- 安全：浏览器不能伪造租户、权限或审批；页面和 Trace 无敏感值。
- 恢复：刷新页面后从权威 Task 投影重建，不依赖浏览器内存事实。

## 解锁条件

- WP-071 后端链稳定，API/SSE 输入输出契约冻结在 M7 Minor 版本内。
