# WP-000：工作包标题

## 元数据

- 状态：DRAFT / READY / IN_PROGRESS / REVIEW / DONE / BLOCKED
- Attempt ID：
- 风险等级：R0 / R1 / R2 / R3
- 责任会话：
- 评审会话：
- 功能 ID：
- 依赖工作包：
- 执行模式：PARALLEL / READ_ONLY_PARALLEL / ORDERED
- Chain ID：无 / `<chain-id>`
- Step ID：无 / `<step-id>`
- 交接策略：S1_GATE / CONSUMER_GATE / FINAL_GATE
- 下一角色：
- 目标分支：`codex/<session>/<work-package>`
- 子 Agent 策略：`disabled` / `read-only` / `bounded-write`
- 子 Agent 并发上限：`0` / `1` / `2` / `3`

## 目标

-

## 非目标

-

## 允许修改路径

-

## 输入契约

| 契约 | 版本 | 提供者 |
|---|---|---|
| | | |

## 已知事实与复用

- `KNOWN_FACTS`：
- `DO_NOT_RECHECK`：
- 可复用证据/Decision Hash：
- 必须独立复核且需要更换的观察边界：

## 输出契约

| 契约 | 版本 | 消费者 |
|---|---|---|
| | | |

## 架构与安全约束

-

## 实施内容

1. 

## 子 Agent 分派

- 可自主分派的子任务：
- 禁止分派的决策：
- 子 Agent 允许读取路径：
- 子 Agent 允许写入路径：`none` / 明确子集
- 主 Agent 复现要求：
- 子任务 `TASK_DEDUP_KEY` 规则：

## 必须测试

- 正常路径：
- 边界条件：
- 失败路径：
- 安全负向：
- 恢复/幂等：

## 验收命令

```bash
# 尚未实现的命令必须明确标注
```

## 证据

-

## 完成定义

-
