# WP-036：README 中文化与本地体验核验

## 元数据

- 状态：READY
- Attempt ID：WP-036-a1
- 风险等级：R1
- 责任角色：S2/S3/S4/S5/S6/S7（各自仅修改独占路径）
- 评审角色：S1-ARCH
- 功能 ID：FP-OPS-003
- 执行模式：PARALLEL
- 输入 Head：`8cb111853ad82ed38a581524137a4f4afd270906`

## 目标

1. 将仓库内以英文为主的 README 改为中文工程说明。
2. 命令、文件路径、环境变量、Schema 字段、协议名和代码标识保持原文。
3. 不改变产品行为、依赖、配置或验收结论。
4. S1 独立验证本地基础设施、API/Worker 与 LangGraph Studio 的可启动性，形成可体验与不可体验清单。

## 路径与责任

- S2：`apps/worker/README.md`、`packages/{graph,agent-runtime,model-gateway,context}/README.md`
- S3：`apps/mcp-gateway/README.md`、`mcp-servers/knowledge/README.md`、`packages/{tool-contracts,policy,security}/README.md`
- S4：`packages/{evaluation,observability}/README.md`、`scripts/acceptance/README.md`、`artifacts/acceptance/README.md`
- S5：`apps/api/README.md`、`packages/{domain,application}/README.md`
- S6：`migrations/README.md`、`packages/persistence/README.md`、`infra/{compose,postgres,redis}/README.md`
- S7：`artifacts/integration/README.md`

## 测试与验收

- Markdown 中已有命令、路径和代码块不得被翻译破坏。
- README 链接必须仍可解析。
- 只允许 README 路径变化。
- S1 必须实际运行启动/Smoke 命令；未运行或环境阻断不得写成可体验。

## 非目标

- 不补写尚未实现的功能。
- 不为了演示修改业务代码。
- 不调用外部模型或生产系统。
