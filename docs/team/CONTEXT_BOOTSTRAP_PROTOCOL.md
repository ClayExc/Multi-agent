# FlowPilot 增量上下文启动协议

## 1. 目标

长期 Codex 任务已经拥有角色知识和历史上下文。把每个新 Attempt 都当作陌生
会话，重复读取 README、STRUCTURE、Traceability、会话契约和全部架构引用，
会消耗大量 Token，却很少改变工程判断。本协议用 Git 祖先关系和文档差异替代
无条件全量重读。

本协议用于长期领域主 Agent，只优化上下文加载，不降低路径所有权、ContractSet、
安全门禁、测试或最终验收要求。主 Agent内部创建的子 Agent 使用第 6 节的 Context
Capsule，不再重复执行完整 `DELTA/FULL` 流程。

## 2. 两种模式

### `DELTA`（默认）

满足以下条件时使用：

- 消费者是已经注册并承担过该 `SESSION_ROLE` 的长期任务。
- 唤醒信封包含消费者最后接受的 `CONTEXT_BASE_COMMIT`。
- 该提交是 `CONTEXT_TARGET_COMMIT` 的祖先。
- 角色、路径所有权、Contract Major 和架构不变量没有发生不兼容变化。

消费者只读取：

1. 当前 Chain Authorization、Work Package、Agent Registry。
2. 直接上游 Handoff/Proof（首 Step 可无）。
3. `CONTEXT_BASE_COMMIT..CONTEXT_TARGET_COMMIT` 之间基线文件的变化片段。
4. 实施过程中实际触达的代码、测试和直接引用。

直接 Handoff 已给出可验证的 `KNOWN_FACTS/DO_NOT_RECHECK` 时，消费者先核对相关
Blob 和证据 Hash；前提未变化则复用结论，不重新执行相同调查。

系统或客户端已经注入当前 `AGENTS.md` 内容时，视为已经加载，不得再次通过
终端全文读取。

### `FULL`（例外）

只有以下情况允许全量读取强制基线：

1. 首次注册的新任务，没有可信 `CONTEXT_BASE_COMMIT`。
2. Base 不是 Target 的祖先，无法形成确定性增量。
3. `SESSION_ROLE`、写入范围或强制 Reviewer 发生实质变化。
4. Contract Major、架构不变量、数据兼容性或安全边界发生变化。
5. Git 差异或证据 Hash 无法验证，继续执行会产生 P0/P1 风险。
6. 用户或 S1 明确要求独立全量审计。

文档仅有格式、状态、历史记录或无关角色内容变化，不构成 `FULL` 理由。

## 3. 唤醒字段

每个注册制唤醒信封必须增加：

```text
CONTEXT_MODE=<DELTA|FULL>
CONTEXT_BASE_COMMIT=<consumer-last-accepted-context-sha|none>
CONTEXT_TARGET_COMMIT=<exact-input-head>
CONTEXT_REQUIRED_READS=<comma-separated-repo-relative-paths>
```

`CONTEXT_REQUIRED_READS` 只列当前 Chain、Work Package、Registry 和直接 Handoff，
不能借此重新塞入整套仓库文档。

## 4. DELTA 算法

消费者按以下顺序执行：

```powershell
git merge-base --is-ancestor <context-base> <context-target>
git diff --name-status <context-base>..<context-target> -- `
  README.md STRUCTURE.md AGENTS.md docs/acceptance `
  docs/architecture docs/decisions docs/team/session-contracts
git diff --unified=20 <context-base>..<context-target> -- <changed-required-files>
```

1. 祖先校验失败：停止并请求 `FULL` 或新基线，不猜测。
2. 没有变化：不打开对应基线文件。
3. 有变化：先读变化片段；只有片段改变本角色决策前提时才读该文件全文。
4. ContractSet 仍单独复算 `content_digest`，无需全文读取所有 Schema。
5. 当前 Chain、Work Package、Registry 和 Handoff 各读取一次；同一 Attempt 恢复
   时如果 Git Blob 未变，可以完全跳过。

## 5. Token 与证据预算

- 不把命令日志、完整测试输出、历史 Handoff 或背景说明复制进唤醒消息。
- 不读取与当前写入范围、输入契约或风险无关的架构章节。
- Handoff 只记录 `CONTEXT_MODE`、Base/Target、实际读取的变化文件和是否触发
  `FULL`；不保存隐藏思考过程。
- S7 最终报告统计全量读取次数和重复读取次数；目标均为 0，除非命中第 2 节
  的明确例外。

## 6. 失败关闭

增量加载不是“相信聊天记忆”。所有跳过都必须由 Git 祖先、文件差异、Blob
或内容摘要支持。无法证明“未变化”时停止，而不是静默跳过安全或契约资料。

## 7. 子 Agent Context Capsule

领域主 Agent先完成 `DELTA/FULL`，再给子 Agent传递精确 Head、单一任务、读写范围、
相关接口、不变量、验收条件和必须读取的少量路径。子 Agent不得重新加载 README、
STRUCTURE、路线、全部 Handoff 或未变化架构文档；上下文不足时返回 `CONTEXT_GAP`。

Capsule、并发和退出规则以
[`PRINCIPAL_SUBAGENT_PROTOCOL.md`](./PRINCIPAL_SUBAGENT_PROTOCOL.md) 为准。
