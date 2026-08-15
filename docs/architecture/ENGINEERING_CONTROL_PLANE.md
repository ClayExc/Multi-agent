# 工程控制面

## 目标

M9T 为 Codex 开发链提供一套可执行的增量上下文和验证控制面。它解决四个问题：新
Attempt 重复读取大半仓库、路径变化后测试选择靠经验、相同门禁被反复执行、交接只写
“已阅读”却没有可复算记录。

控制面只管理工程上下文，不进入 FlowPilot 产品运行时，也不接触 Prompt、Token、用户
数据或模型隐藏推理。LangGraph Context、用户记忆和 Codex 开发上下文仍是三个独立概念。

## 组件

`flowpilot-eng` 提供五类命令：

1. `map build`：从 Git、Workspace、路径 Owner、包依赖和测试目录生成确定性仓库地图。
2. `capsule build`：根据 Base、Target、Owner、Work Package 和 Handoff 生成初始读取集。
3. `tests select`：输出定向、共享、全仓和真实环境四级测试计划及升级原因。
4. `evidence check/record`：按保护树和环境指纹判断既有证据是否可复用。
5. `attempt report`：记录选择文件数、字节数、估算 Token、范围扩展和测试计算时间。

本地结果写入 `.flowpilot-engineering/`，该目录不提交。正式验收结果仍进入既有
`artifacts/acceptance/**` 或 `artifacts/integration/**`。

## 仓库地图

仓库地图使用版本化 JSON，至少包含：

- Git Head、生成器版本、Workspace 成员和包依赖边；
- 路径 Owner、共享文件单写者、公共 Port 与入口文件；
- 源码到定向/共享/安全/集成测试的映射；
- Contract、Migration、Lock、产品树和环境保护项；
- 文件大小与内容 Hash，不保存文件正文。

`.git`、虚拟环境、IDE 目录、缓存、覆盖率文件和生成证据不计入源码规模。未知路径、
重复 Owner、无法解析的 Workspace 成员或非线性 Git 基线必须失败关闭。

## Delta Context Capsule

Capsule 是一次 Attempt 的机器输入，不是自然语言摘要。它记录 Base/Target、变更路径、
受影响包、直接依赖、公共签名、必读文件、允许的初始读取范围、`KNOWN_FACTS`、
`DO_NOT_RECHECK`、测试计划和证据引用。

初始读取范围由工具生成；Agent 可以因未解析依赖、公共签名变化、测试失败或安全边界
变化申请扩展。扩展必须记录原因和新增路径。当前 Codex 客户端无法从操作系统层拦截
任意文件读取，因此硬约束覆盖生成、范围校验、Git 差异和 Handoff 证据，任意终端读取
仍由 AGENTS.md 与审查约束。文档不得宣称实现了不存在的文件系统读取沙箱。

## 测试选择

选择器只减少开发阶段的重复计算，不取消发布门禁。

- 普通包内变化选择定向测试和受影响依赖测试。
- 公共 Port、共享安全机理或跨包签名变化升级为共享回归。
- Contract、Migration、Lock、身份/租户、安全、未知路径或非线性基线升级为全仓或
  RELEASE 门禁。
- 选择器无法证明测试集合完整时返回拒绝，不返回空测试集。

每个选择结果说明“为什么选”和“为什么升级”。测试命令以参数数组保存，不允许拼接
Shell 字符串。

## Evidence Cache

缓存键包含命令 ID、产品树、Contract tree/digest、Migration tree、Lock Hash、环境和
工具链指纹。只有退出码为 0、证据 Hash 完整、生产者 Head 可追溯且复用策略允许时才
产生命中。

以下门禁默认不跨 Attempt 复用：付费/在线 Provider、Secret Scan、依赖漏洞查询、真实
Migration、破坏性恢复和显式要求重新执行的安全测试。缓存失效必须给出具体变化项，
不能静默退回旧结果。

## 验收

- 相同输入连续生成的仓库地图、Capsule、测试计划和缓存键逐字节一致。
- 删除、重命名、未知路径、非线性基线和脏工作区有稳定失败码。
- 代表性包内增量的初始读取文件数和字节数低于全仓 20%，同时变异矩阵漏选测试数为 0。
- Contract、Migration、Lock 和安全边界变化全部升级，不允许缓存命中。
- 报告区分实际读取记录和按字节估算的 Token，不把估算值宣传为客户端真实用量。
- 控制面故障时回退到既有 FULL/RELEASE 门禁，不能阻断正常人工范围扩展。
