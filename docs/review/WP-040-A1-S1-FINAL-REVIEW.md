# WP-040-a1 S1 最终集成评审

## 裁决

```text
SESSION_ROLE=S1-ARCH
WORK_PACKAGE=WP-040
VERDICT=ACCEPT_M0_COMPOSITION
VALIDATED_HEAD=ffc90a53b158d37c5ae16bca8858e2c7e93c938c
CONTRACT_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
P0_P1_BLOCKERS=none
RELEASED=no
FROZEN=no
```

S1 接受 Core、Runtime 与 Data 的 M0 原子组合进入主分支。该裁决只证明当前九包候选可以组合、安装、测试和恢复，不代表 MCP Gateway、真实 Provider、LangGraph Studio、120/36 数据集、业务 E2E 或发布门禁完成。

## 输入身份

| 输入 | Head |
|---|---|
| S1 控制基线 | `6a16320a16fc76f2a5ffdedfc0ab893c87a636fa` |
| S2 Runtime | `c3da3118eac5ee7d57c6b333c2aac3a0f119d799` |
| S5 Core/Workspace | `315822de1c8a50f5ede304836686ce5e63f9ad1d` |
| S6 Data | `e41f0266e6e588417332043b68a3309b2d40bcf7` |
| S7 candidate | `4314766c0cfb57c3332a5fc0b0c27395e93cf879` |
| S7 final verifier | `09d1b38c3b8d6a0738ee23a66fe3138b5812646a` |

S1 使用私有 final worktree 将完整 S7 候选作为一次原子转换接入控制基线，没有把三个不完整输入 Head 逐个暴露为主分支中间态。

## S1 独立复现

| 门禁 | 结果 |
|---|---|
| S1 final composition verifier | PASS：42/42 |
| Core + Runtime + Data + Integration | PASS：159 |
| Contract Conformance | PASS：20 Schema、43 语义负例、52 Feature |
| Ruff | PASS |
| Mypy strict | PASS：57 source files |
| `git diff --check` | PASS |

S7 `WP-040-a1` 已对同一产品候选运行 RELEASE 档门禁：

- Candidate Manifest 36/36，`sha256:1e9140e267470a0b4404a34b07254569875c3d8c582517599cc328ba8b5dddb1`。
- 143 项 Core/Runtime/Data、10 项 S7 集成测试。
- 九个 Wheel 构建、全新环境安装与导入。
- 真实 Compose 五服务健康；Migration、PostgreSQL Adapter、RLS 与 Redis 丢失恢复通过。
- 专用 Compose 资源已清理。

S1 final 只增加控制面文档与经 S7 审查的 Verifier 修复；产品树、ContractSet、输入 Heads、`uv.lock` 和 Migration 对象未变化，因此按集成门禁分级复用 a1 RELEASE 证据，不重复运行完整 Compose。

## 保留项

| 级别 | 事项 | Owner | 处理 |
|---|---|---|---|
| P2 | Compose 尚未自动应用 `0002_checkpoint_sequence_cas` | S6 | M0 Compose 验收前建立独立小工作包 |
| P2 | `make test-security`、`make acceptance` 尚未实现 | S4/S5 | 共享入口工作包，不能据局部测试宣称发布验收 |
| P3 | S7/S5 使用的 uv 版本不同 | S5/S7 | 固定工具链版本；当前 Lock Hash 与 73 包闭包一致 |

这些事项不阻断 M0 组合，但阻断 `RELEASED`。

## 学习候选

```text
LEARNING_CANDIDATE=候选阶段规则不能直接复用于最终控制分支
MATURITY=IMPLEMENTED
TRIGGER=S7 candidate 36/36，但 S1 final 首次复算因 branch/delta scope 失败
MECHANISM=验证器混合了候选身份、S7 路径所有权和 S1 最终合并三个阶段
STRUCTURE=分离 S7_CANDIDATE/S1_FINAL；保护产品对象；按 FAST/STANDARD/RELEASE 分级
EVIDENCE=WP-040-a1/a2/a3 Handoff、42/42 final verifier、159 tests
RESIDUAL_RISK=新门禁 Profile 仍需在后续候选中验证缓存失效与工具链固定
TARGET=ENGINEERING_PLAYBOOK.md#4.12
```

## 下一阶段

1. S3/WP-020 从最终主基线启动 Platform 垂直切片。
2. S2/WP-012 以独立 Attempt 建设 LangGraph Studio 非黑箱入口；若依赖锁变化，先交给 S5。
3. S4/WP-030 逐步接入 Platform 与 Runtime 的跨组件黑盒验收。
4. S6 另行关闭 Migration 0002 自动接入，不回填 WP-021 历史 Attempt。
