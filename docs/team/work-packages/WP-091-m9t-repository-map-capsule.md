# WP-091：仓库地图与 Context Capsule

## 元数据

- 状态：ACTIVE
- Attempt：WP-091-a1
- Owner：S5-CORE
- Reviewer：S4-QUALITY
- 风险：R2
- Feature：FP-OPS-002
- 依赖：WP-090
- 执行：ORDERED

## 目标与范围

新增 `flowpilot-engineering-control` Workspace 包和 `flowpilot-eng` CLI，实现确定性仓库
地图与 Delta Context Capsule。允许修改：

- `packages/engineering-control/**`
- `scripts/engineering/**`
- `tests/core/engineering_control/**`
- `tests/core/evidence/WP-091-a1-HANDOFF.md`
- `pyproject.toml`、`uv.lock`、`.gitignore`

仓库地图必须排除 Git、虚拟环境、IDE、缓存、coverage 和生成证据；解析路径 Owner、
Workspace 依赖、公共入口、测试映射和保护树。Capsule 必须支持 rename/delete、脏工作区、
非线性基线、未知路径及范围扩展记录。

## 必须测试

- 相同输入字节一致；Windows/POSIX 路径归一化一致。
- Owner 冲突、缺失包、未知路径、非祖先 Base 和脏工作区失败关闭。
- 输出只含路径、签名、Hash、计数和授权元数据，不含文件正文或 Secret。
- 包内增量选择文件与字节低于全仓 20%，依赖与必读边界无漏项。
- Core、Ruff、严格 Mypy、构建与锁检查通过。

## 非目标

不实现测试选择、证据缓存、OS 级读取拦截或产品 Runtime Context。

交接：`tests/core/evidence/WP-091-a1-HANDOFF.md`。
