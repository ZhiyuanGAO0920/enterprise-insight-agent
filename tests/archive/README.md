# tests/archive —— 历史评估跑分快照

> 2026-09-02 归档：5 个「成绩单」类文件从 tests/ 根目录移入本目录。
> **题源唯一** = `tests/eval_set.json`（102 题）；**跑分入口** = `tests/run_eval.py`（只读 eval_set.json）。
> 归档文件不影响运行链，仅供回归对比 / 复盘复现用。

## 内容（均为 Q01–Q12 的 P0 子集，每条带逐题质检字段）

| 文件 | 是什么 | 对应时期 / 用途 |
|---|---|---|
| `eval_baseline_p0.json` | 改动前 12 题跑分 | 回归基线（`run_eval.py --compare` 可指） |
| `eval_changed_p0.json` | 改动后同 12 题跑分 | 与 baseline 成对对比 |
| `eval_v462_check.json` | Reflection 对照实验快照 | V4.6.2~4.6.3 实验存档（含 cross_check/sql_accuracy 字段） |
| `eval_v462_derive.json` | 同实验另一变量组 | 同上（变量语义未在代码标注） |
| `eval_v462_noreflect.json` | 跳过质检（ablation） | 量化质检价值（结论：质检与满意度几乎零相关 → 契约化改造动机） |

## 仍引用这些文件的代码

- `scripts/phase3_step0_correlation_analysis.py` —— 收官包复盘脚本，EVAL_DIR 已指向本目录

## 说明

- `tests/eval_canary_v5_contract_TEMPLATE.json` **未归档**：仍被 TASKS.md / docs / `scripts/phase3_step2_canary_synth.py`（生成器）引用，属现役金丝雀契约模板
- 若要恢复：`git mv tests/archive/*.json tests/` 并回滚 phase3_step0 的 EVAL_DIR 一行即可
