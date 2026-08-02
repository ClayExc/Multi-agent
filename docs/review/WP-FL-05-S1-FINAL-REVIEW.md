# WP-FL-05-S1-FINAL-REVIEW — M6 增量 C 聚合合并审查（evaluation-aggregator）

## 审查结论

```text
SNAPSHOT=M6_INCREMENTAL_C_AGGREGATED_MERGED
STATUS=APPROVED_FOR_MASTER
REVIEWER=S1-ARCH
REVIEW_DATE=2026-08-02
CANDIDATE_HEAD=7b16f0b（flow-lite/eval-agg）
PREVIOUS_MASTER=ecbf49b
MERGE_BASE=1b47059
```

## 背景（合并现场事故处置）

此前增量 C-1/C-2/C-3 三个目标从 M5 基线（1b47059）并行开发，同时写入
4 个聚合文件（dataset-card.yaml、manifest.json、incremental_c.py、
test_incremental_c_candidates.py），且 C-2 合并现场混入了 C-3 的
fault-profile 文件，导致 master 处于污染合并状态（MERGE_HEAD=f89c008）。

## 处置方式（用户决策）

1. `git merge --abort` 中止污染合并，清理未跟踪文件，master 回到 ecbf49b。
2. 保留 flow-lite/g1-3（C-1）、g2-3（C-2）、g3-3（C-3）三个干净分支为
   事实源（均从 1b47059 切出，case 文件互不重叠：C-1 ar/lh 16、
   C-2 pc 16、C-3 dlp 3 + 3 个新 fault-profile）。
3. 注册 `evaluation-aggregator` 身份（write_scope 限聚合文件），
   在独立 worktree（flow-lite/eval-agg）串行汇总：
   - case 文件分别检出（无冲突）
   - 4 个聚合文件由 aggregator 单写合并（CASE_SPECS 35 项、
     辅助函数并集、常量并集、EXPECTED_CATEGORY_COUNTS 聚合值、
     DATA_SOURCE/SECURITY_CLASS/GATE_DOMAIN/FEATURE 映射并集）
   - `write_cases` 重建 manifest（case_count=35）与 dataset-card
   - TRACEABILITY 补登记 19 行（16 pc + 3 dlp）

## 验证

| 检查 | 结果 |
|---|---|
| 全量测试 | **614 passed**（592→614，+22） |
| 契约一致性 | CONTRACT_CONFORMANCE_OK（35 cases / 52 features） |
| 生成一致性 | `generated_matches_committed=True`（manifest 哈希与磁盘文件一致） |
| 候选配额 | functional 104→120（16+16+16+8ar+8lh 口径确认）、safety 33→36（3 dlp） |
| 重复 case id | 无（35 个唯一） |
| master 门禁 | 未被移动（ecbf49b 保持） |
| 越权路径 | 聚合分支仅触碰 evals/packages.evaluation/tests.acceptance/TRACEABILITY（S4 与 S1 共享范围），无契约/凭据改动 |

## 已知后续（不阻断合并）

- 三个 C 分支保留留痕；`flow-lite/eval-agg` 为聚合事实分支。
- TRACEABILITY 顶部快照与旧表格不一致、Integration 的
  `codex/s1/*` 硬编码、FP-UI-001/M5-1 功能 ID 登记等 P2 项在
  M6 冻结阶段一并处理。
