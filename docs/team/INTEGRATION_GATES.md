# FlowPilot 集成门禁分级

## 1. 目的

S7 的职责是证明组合候选可以复现，不是每次收到一个新消息就执行完整发布演练。门禁按变更风险分为 FAST、STANDARD 和 RELEASE；同一候选已经取得的高等级证据可以被更低等级复核引用，但必须绑定精确输入身份。

候选身份由以下元组共同确定：

```text
(input_heads,
 contract_content_digest,
 uv_lock_sha256,
 migration_hashes,
 compose_manifest_hash,
 gate_version,
 toolchain_version)
```

任一字段变化都使相关缓存失效。聊天顺序、会话声明或文件修改时间不能充当候选身份。

## 2. 三档门禁

| 档位 | 本地目标时间 | 运行内容 | 典型触发 |
|---|---:|---|---|
| FAST | 1～5 分钟 | Head/路径所有权/Handoff Hash、Contract/Lock/Migration 静态 Hash、受影响测试、Verifier 自测 | 文档、证据、Verifier、Handoff 或不改变产品树的控制面合并 |
| STANDARD | 5～15 分钟 | FAST + 全量 Python 测试、Ruff、Mypy、Contract Conformance、wheel 构建 | Runtime/API/Port/包依赖发生变化，但 Compose、迁移和安全边界未变 |
| RELEASE | 20～35 分钟 | STANDARD + 全新环境安装、依赖/Secret 扫描、真实 Compose、Migration、RLS、恢复、清理和证据 Manifest | Lock、Migration、Compose、RLS、授权、安全写路径变化；主候选或发布候选 |

时间是本地工程目标，不是降低验证强度的依据。超时需要记录最慢阶段和环境信息，不能把未完成步骤写成通过。

## 3. 选择规则

采用最高命中等级：

- `contracts/**`、授权、审批、租户、凭据、审计不变量变化：`RELEASE`。
- `migrations/**`、`infra/**`、`uv.lock` 或根级部署配置变化：`RELEASE`。
- 产品 Python 包、跨包 Port 或序列化映射变化：至少 `STANDARD`。
- S7 Verifier、报告模板、S1 文档或仅 Handoff 变化：`FAST`。
- 无法确定影响范围时：升级一级，不自行降级。

R3 不使用缓存。P0/P1 修复至少重跑触发失败的档位；如果修复改变候选身份，按新身份重新选择档位。

## 4. 并行和复用

同一候选内可以并行：

- Ruff、Mypy、Contract Conformance、Secret Scan。
- 各 Python 测试分组。
- wheel 构建与静态 Manifest 复算。

需要串行：

- Migration 升级/回滚与数据库恢复。
- RLS 角色和事务隔离验证。
- Redis 丢失、Lease/Fencing 和 `UNKNOWN` 对账。
- 使用同一 Compose project 或数据库卷的步骤。

高等级证据只有在候选身份元组完全一致、生成器版本一致、证据 Hash 可复算时才能复用。S1 最终合并如果只增加 S1 独占文档，并证明产品树、契约树、Lock 和 Migration 未变化，只运行 FAST final gate，不重复 RELEASE。

## 5. 工具链与输出

- 固定 `uv`、Python、Docker/Compose 和数据库主要版本；版本漂移作为证据字段，不只写在自由文本中。
- 报告必须列出每阶段耗时，至少区分 Bootstrap、Static、Tests、Build、Compose、Database/Recovery 和 Cleanup。
- 报告对外使用 `OUTCOME → EVIDENCE → RISKS → NEXT_ACTION`，不逐条转发无变化日志。
- FAST、STANDARD 和 RELEASE 都必须失败关闭；未安装依赖写 `ENV_BLOCKED`，不能冒充 PASS。

## 6. S7 约束

1. 候选阶段验证 S7 自身增量只包含 S7 独占路径。
2. S1 final 阶段验证 S7 Head 是待验 Head 的祖先，S1 增量只包含 S1 独占路径或工作包显式授权的共享文件。
3. final 阶段必须证明产品树、ContractSet、输入 Heads、Lock 和 Migration 没有被控制面合并改写。
4. S7 生成的报告不能自行批准主分支；最终裁决仍属于 S1。
5. 不因分支显示名不同而误判产品失败，也不取消分支和路径身份校验。
