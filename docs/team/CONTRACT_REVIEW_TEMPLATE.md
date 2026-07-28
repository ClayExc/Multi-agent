# FlowPilot 契约可实现性审查模板

该模板用于 WP-000 的 S2/S3/S4 只读审查。审查会话在聊天中返回完整内容，不直接写入 S1 独占目录。

```text
SESSION_ROLE=<S2-RUNTIME|S3-PLATFORM|S4-QUALITY>
WORK_PACKAGE=WP-000-REVIEW
REVIEW_TARGET=flowpilot-m0-contracts-v1-rc2
REVIEWED_CONTENT_DIGEST=sha256:<64hex>
VERDICT=<ACCEPT|ACCEPT_WITH_RFC|REJECT>
```

## 1. 结论

- Verdict：
- 是否阻塞实现基线：
- 一句话原因：

## 2. 阻塞问题

没有问题时明确写“无”。

| Finding ID | Schema/字段 | 失败场景 | 兼容性影响 | 安全/恢复影响 | 最小建议 |
|---|---|---|---|---|---|
| `<ROLE>-CR-001` | | | compatible / breaking | | |

## 3. 非阻塞建议

| Finding ID | Schema/字段 | 建议 | 建议阶段 |
|---|---|---|---|
| | | | M0 / later |

## 4. 必须补充的契约测试

- 正常路径：
- 边界条件：
- 失败路径：
- 安全负向：
- 恢复/幂等：

## 5. 所有权确认

- 本会话是否能在自身目录内实现：是 / 否
- 是否要求修改其他会话目录：是 / 否
- 是否需要新功能 ID：是 / 否
- 是否需要 ADR：是 / 否

## 判定规则

- `ACCEPT`：当前摘要足以作为本会话 M0 实现基线；只有该结论计入基线激活。
- `ACCEPT_WITH_RFC`：仍有必须正式处理的问题，不计入实现基线激活。
- `REJECT`：存在无法安全实现、状态权威冲突或不兼容缺口；必须先解决。
- 不允许以代码中的私有字段、宽松枚举或未记录约定补偿公共契约缺口。
