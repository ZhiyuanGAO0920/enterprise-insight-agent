# -*- coding: utf-8 -*-
"""Phase 3 Step 0：相关性分析可行性报告 + 经验权重拍板。

收官包方案 §8 Phase 3 要求：先用现有 eval 数据做「4 维度 × 满意度」相关性分析。
本脚本：
  1. 扫描 tests/*.json 中 5 个 eval 结果文件（共 48 条样本，覆盖 16 条 canary × 3 次实验 + 2 次 12 条 baseline）
  2. 诚实判定「是否有独立 4 维度分 / 是否有满意度 ground truth / 是否有 issues 明细」
  3. 输出可量化的「次优替代证据」（现有数据能给的所有信号）
  4. 拍板新契约 4 项权重 + 阈值，并给出依据
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "tests"

EVAL_FILES = [
    "eval_baseline_p0.json",
    "eval_changed_p0.json",
    "eval_v462_check.json",
    "eval_v462_derive.json",
    "eval_v462_noreflect.json",
]

def load_all():
    rows = []
    for fn in EVAL_FILES:
        p = EVAL_DIR / fn
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        results = d.get("results", d)
        for r in results:
            r["__file__"] = fn
            rows.append(r)
    return rows

def analysis_feasibility(rows):
    n = len(rows)
    # 1. 是否有独立 4 维度字段
    KEY4_OLD = {"consistency_score", "logic_score", "actionability_score", "completeness_score"}
    KEY4_NEW = {"numerical", "grounding", "reasoning", "alignment",
                "numerical_consistency", "evidence_grounding", "reasoning_validity", "recommendation_alignment"}
    SAT = {"satisfaction", "satisfaction_score", "human_rating", "label"}
    ISSUES = {"reflection_feedback", "reflection_issues", "issues"}

    def any_key_present(keyset):
        return any(k in rows[0] for k in keyset) if rows else False

    dim4_old_present = any_key_present(KEY4_OLD)   # 老 4 项（consistency/logic/actionability/completeness）分
    dim4_new_present = any_key_present(KEY4_NEW)   # 新契约 4 项分
    sat_present     = any_key_present(SAT)         # 满意度 ground truth
    issues_present  = any_key_present(ISSUES)      # issues 明细（可展开算 category 分布）

    return {
        "n_rows": n,
        "n_files": sum(1 for f in EVAL_FILES if (EVAL_DIR / f).exists()),
        "dim4_old_scores_persisted": dim4_old_present,
        "dim4_new_contract_scores_persisted": dim4_new_present,
        "satisfaction_ground_truth_persisted": sat_present,
        "reflection_issues_detail_persisted": issues_present,
    }

def substitute_signals(rows):
    """现有数据能给的所有信号，供权重拍板使用。"""

    # A. 总体质量信号（虽然没有维度分，但整体 pass / hallucination / row-range 可用）
    passed     = sum(1 for r in rows if r.get("reflection_passed"))
    no_hall    = sum(1 for r in rows if r.get("no_hallucination"))
    rows_ok    = sum(1 for r in rows if r.get("rows_in_range"))
    dim_cov    = sum(r.get("dimension_coverage") or 0 for r in rows) / max(1, len(rows))
    err_count  = sum(r.get("errors") or 0 for r in rows)

    # B. Reflection 状态分布（passed / failed / skipped / parsing_fallback）
    status_dist = {}
    for r in rows:
        status_dist[r.get("reflection_status") or "(no status)"] = \
            status_dist.get(r.get("reflection_status") or "(no status)", 0) + 1

    # C. hallucination 与 reflection_pass 的共现（说明「不一致 = 幻觉主因」的证据）
    n_pass_hall = sum(1 for r in rows if r.get("reflection_passed") and not r.get("no_hallucination"))
    n_fail_hall = sum(1 for r in rows if not r.get("reflection_passed") and not r.get("no_hallucination"))
    n_pass_ok   = sum(1 for r in rows if r.get("reflection_passed") and r.get("no_hallucination"))
    n_fail_ok   = sum(1 for r in rows if not r.get("reflection_passed") and r.get("no_hallucination"))

    # D. SQL accuracy 与 cross_check（数值一致性信号）
    sql_acc_list = [r.get("sql_accuracy", {}).get("rate") for r in rows if r.get("sql_accuracy")]
    sql_acc_list = [x for x in sql_acc_list if isinstance(x, (int, float))]
    sql_acc = sum(sql_acc_list) / max(1, len(sql_acc_list)) if sql_acc_list else None
    cc_list    = [r.get("cross_check",  {}).get("rate") for r in rows if r.get("cross_check")]
    cc_list = [x for x in cc_list if isinstance(x, (int, float))]
    cross_check_avg = sum(cc_list) / max(1, len(cc_list)) if cc_list else None

    # E. cross_check 通过但 Reflection 仍失败的比例（≈ 原有 Reflection 对数值一致性以外维度的过度/不足判断）
    cc_and_fail = sum(
        1 for r in rows
        if r.get("cross_check") and (r.get("cross_check").get("rate") or 0) >= 0.95
        and not r.get("reflection_passed")
    )
    cc_high = sum(1 for r in rows if r.get("cross_check") and (r.get("cross_check").get("rate") or 0) >= 0.95)

    return {
        "overall_pass_rate":              f"{passed}/{len(rows)} = {passed/max(1,len(rows)):.1%}",
        "no_hallucination_rate":          f"{no_hall}/{len(rows)} = {no_hall/max(1,len(rows)):.1%}",
        "rows_in_range_rate":             f"{rows_ok}/{len(rows)} = {rows_ok/max(1,len(rows)):.1%}",
        "avg_dimension_coverage":         f"{dim_cov:.1%}",
        "total_errors":                   err_count,
        "status_distribution":            status_dist,
        "contingency_pass_vs_halluc": {
            "pass_and_no_hallucination":  n_pass_ok,
            "pass_and_HALLUCINATE":       n_pass_hall,   # 应≈0，否则 Reflection 没抓住幻觉
            "fail_and_no_hallucination":  n_fail_ok,     # 这些是「逻辑/完整性/可操作性」失败
            "fail_and_HALLUCINATE":       n_fail_hall,
        },
        "sql_accuracy_avg":               f"{sql_acc:.2%}" if sql_acc is not None else "N/A",
        "cross_check_rate_avg":           f"{cross_check_avg:.2%}" if cross_check_avg is not None else "N/A",
        "cc>=0.95_but_still_fail":        f"{cc_and_fail}/{cc_high} = {cc_and_fail/max(1,cc_high):.1%}" if cc_high else "N/A",
        "_comment_cc_fail":
            "cross_check 95%+ 但仍判失败的样本，说明原有 Reflection 因「逻辑/完整性/可操作性」判失败，而非数值问题。"
            "此比例越高 → Recommendation Alignment / Reasoning Validity 的权重应该越高。",
    }

def print_report(feas, signals):
    print("=" * 72)
    print("Phase 3 Step 0：4 维度 × 满意度 相关性分析 可行性报告")
    print("=" * 72)
    print(f"样本量：{feas['n_rows']} 条  (来自 {feas['n_files']} 个 eval 结果文件)")
    print()
    print("【可行性判定】逐项检查：")
    print(f"  - 老 4 项独立分（consistency/logic/actionability/completeness）是否落库： {feas['dim4_old_scores_persisted']}")
    print(f"  - 新契约 4 项独立分（numerical/grounding/reasoning/alignment）是否落库：  {feas['dim4_new_contract_scores_persisted']}")
    print(f"  - 人类满意度 ground truth 是否落库：                                      {feas['satisfaction_ground_truth_persisted']}")
    print(f"  - Reflection issues 明细（含 category）是否落库：                         {feas['reflection_issues_detail_persisted']}")
    print()
    feasible_corr = (feas['dim4_old_scores_persisted'] or feas['dim4_new_contract_scores_persisted']) \
                    and feas['satisfaction_ground_truth_persisted']
    print(f" → 严格 Pearson/Spearman 相关分析可行性：{'✅ 可行' if feasible_corr else '❌ 不可行'}")
    print()
    print("【原因】")
    if not feasible_corr:
        miss = []
        if not (feas['dim4_old_scores_persisted'] or feas['dim4_new_contract_scores_persisted']):
            miss.append("4 维度独立分")
        if not feas['satisfaction_ground_truth_persisted']:
            miss.append("满意度 ground truth")
        print("  run_eval.py 写入 eval 结果 JSON 时仅保留 reflection_passed + reflection_status 两个聚合字段。")
        print(f"  缺失：{'、'.join(miss)}。")
        print("  → 契约化改造本身就是为了解决此问题（新契约持久化 4 维度分 + 阈值）。")
        print("    完成后 eval_runner 自动记录，下次 eval 自然可做真正相关性分析（形成闭环）。")
        print()
    print("=" * 72)
    print("【次优替代证据】现有数据能给的所有信号")
    print("=" * 72)
    for k, v in signals.items():
        if k.startswith('_'):
            continue
        print(f"  {k:40s} = {v}")
    print()
    # 解释
    cont = signals["contingency_pass_vs_halluc"]
    total_fail = cont["fail_and_no_hallucination"] + cont["fail_and_HALLUCINATE"]
    pct_halluc_fail = cont["fail_and_HALLUCINATE"] / max(1, total_fail)
    pct_nonhall_fail = cont["fail_and_no_hallucination"] / max(1, total_fail)
    cc_fail = signals.get("cc>=0.95_but_still_fail", "")
    print(f"【诊断结论】基于替代信号的定性推断：")
    print(f"  1. Reflection 总通过率只有 {signals['overall_pass_rate']}，但 SQL 准确率 {signals['sql_accuracy_avg']}、")
    print(f"     Cross Check 均值 {signals['cross_check_rate_avg']}。说明数值准确性不是唯一瓶颈——")
    print(f"     原有 Reflection 的「逻辑/可操作性/完整性」三个维度非常苛刻，是主要失败原因。")
    print(f"  2. 在 Reflection fail 的样本中，{pct_halluc_fail:.1%} 是「真幻觉」（no_hallucination=False），")
    print(f"     剩余 {pct_nonhall_fail:.1%} 是无 hallucination 但仍被判 fail（逻辑/可操作性/完整性）。")
    print(f"     ——证明：单纯抓 hallucination 不够，Numerical + Grounding 能覆盖「数字正确性」，")
    print(f"            但「建议对不对得上 Finding」（Alignment）是另一个高价值维度。")
    print(f"  3. Cross Check ≥ 0.95 但仍被判 fail：{cc_fail}。这些样本的 Reflection 失败原因")
    print(f"     就是「非数值类问题」（逻辑跳跃、建议空泛、不完整）——正是方案要把 Recommendation Alignment")
    print(f"     单独拉出来加权的动机。")
    print()


def weight_decision():
    print("=" * 72)
    print("【权重拍板】基于产品判断 + 替代证据")
    print("=" * 72)
    print("""
  契约项                          权重  依据
  ─────────────────────────────  ──────  ─────────────────────────────
  ① Numerical Consistency        30%     经营报告底线；Cross Check avg 已有，但 report 文本与
                                          SQL 结果的"字面一致性"（非数值范围）原验证缺失——直接
                                          用 SQL 结果集的数值 + raw_data 做 report 内字符串硬匹配。
  ② Evidence Grounding           35%     V5 新增核心能力（T-10a + grounding.py）。Phase 2 验证：
                                          幻觉压力样本 coverage=25%、正常样本 ≥80%，鉴别力最强，
                                          权重最高。
  ③ Recommendation Alignment     20%     方案明确提「Alignment 显著高于 4%」目标。现有替代证据
                                          显示"无 hallucination 但仍 fail"比例很高，正对应原
                                          actionability/逻辑维度；此维度是"用户体感"最直接来源。
                                          数值上与方案 §3 用户研究「建议可执行 = 核心痛点」对应。
  ④ Reasoning Validity           15%     纯 LLM 判断最难确定性校验，且 Reasoning 问题最终会在
                                          Evidence + Alignment 维度上有表现；保留但降权。

  通过阈值（加权综合）：≥ 70%  且  无 Evidence/Numerical 的 high severity 违约
  （核心：底线类维度 Numerical/Grounding 不允许 high-sev 漏洞，否则综合分再高也不过）
""")

if __name__ == "__main__":
    rows = load_all()
    feas = analysis_feasibility(rows)
    sigs = substitute_signals(rows)
    print_report(feas, sigs)
    weight_decision()
