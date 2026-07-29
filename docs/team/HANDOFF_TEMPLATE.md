# FlowPilot 会话交接模板

> 文件名：`<work-package>-<session>.md`

## 基本信息

- Work Package：
- Attempt ID：
- Chain ID：无 / `<chain-id>`
- Step ID：无 / `<step-id>`
- 责任会话：
- 接收会话：
- 交接策略：`S1_GATE` / `CONSUMER_GATE` / `FINAL_GATE`
- 功能 ID：
- 基线提交：
- 分支/最终提交：
- ContractSet 摘要：
- 状态：完成 / 部分完成 / 阻塞

## 完成内容

- 

## 未完成与非目标

- 

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| | | |

## 契约、数据库与配置变化

- 契约版本：
- Migration：
- 环境变量：
- 兼容性：

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| | PASS/FAIL/未运行 | |

## 安全与失败路径

- 已验证负向路径：
- 未验证风险：
- Secret/PII 检查：

## 已知问题

- 

## 学习候选

没有发现新的可复用机理时填写 `LEARNING_CANDIDATE=none`，不要为凑数重复常识。

```text
LEARNING_CANDIDATE=<none|短标题>
MATURITY=<HYPOTHESIS|DESIGNED|IMPLEMENTED|VERIFIED>
TRIGGER=<触发现象>
MECHANISM=<失败机理摘要>
STRUCTURE=<采用或建议的结构>
EVIDENCE=<提交/测试/报告/最小复现>
RESIDUAL_RISK=<残余风险>
TARGET=<playbook section|ADR|work package|none>
```

## 接收会话下一步

1. 

## 机器可读交接摘要

```text
OUTCOME=<PASS_HANDOFF|BLOCKED|FAILED>
CHAIN_ID=<id|none>
STEP_ID=<id|none>
ATTEMPT_ID=<id>
NEW_HEAD=<sha>
BASE_COMMIT=<sha>
CONTRACT_CONTENT_DIGEST=sha256:<64hex>
GATE=<PASS|FAIL|ENV_BLOCKED>
HANDOFF=<repository-relative-path>
NEXT_ROLE=<role|S1-ARCH|none>
NEXT_ATTEMPT_ID=<id|none>
ESCALATE_TO_S1=<yes|no>
```

## 可回滚方式

- 
