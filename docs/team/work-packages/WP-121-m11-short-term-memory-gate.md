# WP-121：M11 短期记忆门禁

## 元数据

- 状态：DONE
- Attempt：WP-121-a1
- Owner：S1-ARCH
- Reviewer：S2、S3、S4、S5、S6、S7
- 风险：R2
- Feature：FP-CTX-001～005、FP-DATA-001、FP-SEC-003/005、FP-UI-001、FP-EVAL-001/002
- 依赖：WP-120
- 执行：ORDERED

## 目标与输出

固定短期记忆状态权威、摘要事实等级、Token 预算、持久化、恢复、Handoff、隐私清理、Web
投影和验收边界。输出 `SHORT_TERM_MEMORY.md`、ADR-0006、M11 Chain/Registry、WP-122～129
与 S1 Delta Capsule；不修改公共 ContractSet 或产品代码。

激活提交必须是当前 M10 主分支的线性后继，作为所有 M11 Worktree 的相同基线。

## 激活证据

- 架构控制提交：`0b36f85c22a7a972403b465982db8afba7bdab86`
- S1 Context Capsule：`.flowpilot-engineering/m11/s1-capsule.json`
- Capsule 内容摘要：`2cf97f6f59efe1380dab9546fcc0cc440216b80084388a6e40227bb2b3d98c79`
- Capsule 文件 SHA-256：`c479011ad96fdd4fb9c8408ed7b6fcdb7f3b2b8aaff111d0833413530a4d08b2`
- Repository Map 内容摘要：`62ff84605131523a52d773bfeea1c6a949639a8f896854bcdefdbefa4aac25b4`
- Repository Map 文件 SHA-256：`f2bef02f9accf98001b97cd0ae7cea4a28057d85b3868db373a2f9a76ec2a77b`
- 初始读取集：29 个文件、177286 bytes，占全仓映射字节数 2.44%；范围扩展为 0。

以上证据只固定 M11 控制面和热启动输入，不代表 WP-122 已派发或实现。S3 由用户明确
授权唤醒后才进入实现状态。
