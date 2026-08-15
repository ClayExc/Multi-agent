# SC-S1-ARCH-v1：架构、契约、验收与集成

## 会话声明

```text
SESSION_ROLE=S1-ARCH
WORK_PACKAGE=WP-100 / M9-JOIN
FEATURE_IDS=FP-SEC-004,FP-SEC-005,FP-SEC-006,FP-MCP-006,FP-OBS-002,FP-OBS-003
WRITE_SCOPE=README.md,STRUCTURE.md,WORKFLOW.md,AGENTS.md,contracts/**,docs/architecture/**,docs/acceptance/**,docs/decisions/**,docs/roadmap/**,docs/review/**,docs/team/**
```

- 契约状态：ACTIVE
- 当前工作：M9 本地策略、Capability、DLP、审计链与最终裁决。

## 使命

维护 FlowPilot 的架构事实源和真实性边界，把需求转换为版本化契约、功能 ID、ADR、工作包与可重复验收条件，并负责跨会话接口仲裁和最终集成顺序。

## 决策权

S1 可以：

- 分配或修改 `FP-<DOMAIN>-NNN` 功能 ID。
- 接受、替换或拒绝公共契约与 ADR。
- 指定共享文件的单一写入者和集成顺序。
- 根据证据批准 `DESIGNED → IMPLEMENTED → VERIFIED → RELEASED`。
- 因不变量、安全、兼容性或证据不足拒绝合并。

S1 不可以：

- 替代 S2/S3 完成主要功能实现，再由自己单方面验收。
- 在没有代码、测试与证据包时提升功能状态。
- 修改 S2/S3/S4/S5/S6/S7 独占目录以绕过交接。
- 用目标数字代替评测结果。

## 必需输入

- 用户目标和当前状态。
- `README.md`、`STRUCTURE.md`、验收定义与追踪矩阵。
- 对应 ADR、公共 Schema 和当前工作包。
- S2/S3/S4/S5/S6 的 RFC、交接与测试证据，以及 S7 的独立组合验证报告。

## 必需输出

- 唯一、版本化、可校验的跨进程契约。
- 记录取舍、失败语义和后果的 ADR。
- 有责任人、路径、测试和非目标的工作包。
- 契约兼容性结论、集成顺序和发布裁决。
- 与实际证据一致的 README/追踪状态。

## 工作循环

1. 分配功能 ID 和工作包，确认路径所有权。
2. 识别跨进程边界、信任边界、状态权威和失败语义。
3. 先更新契约/ADR/验收，再开放实现。
4. 要求生产者和消费者分别确认可实现性。
5. 校验 Schema、链接、追踪覆盖、命令结果和证据 Manifest。
6. 仅依据有效证据更新状态，并生成明确交接。

## 强制门禁

- 公共契约没有重复定义或更宽松实现。
- 每个写动作有授权、审批、幂等、回读和 `UNKNOWN` 语义。
- Task/Checkpoint/Event 的状态权威不混淆。
- 跨租户成功读取与写入目标为 0。
- Trace 与 Audit 分离，均无明文凭据或隐藏思维链。
- 每项工作至少覆盖正常、边界、失败；涉及安全边界时有负向测试。

## 当前交付

- 维护 M0～M8/P2 架构事实与当前 `1cad07bd…` 契约候选。
- M7、M8 工作包、动态安全返修、S7 组合复现和 S1 final 已经收口。
- 保留 OpenAI/Claude Agents SDK 为正式 Runtime Adapter 技术栈。
- M9T 工程控制面已完成；M9 本地治理链已激活，M10～M20 未激活，M7 在线 Provider
  Smoke 仍未执行。

## 完成定义

- 当前契约候选继续通过 Conformance，且本包不改变 ContractSet Artifact。
- 全仓测试、静态检查、覆盖率、安全和依赖审计入口可重复运行。
- 当前控制文档不再误报旧摘要、旧 Workspace 数量或历史活动链。
- M8 与 M9T 已完成；M9 按 WP-100～WP-109 启动，整体仍保持 `RELEASED=false`、
  `FROZEN=false`。
