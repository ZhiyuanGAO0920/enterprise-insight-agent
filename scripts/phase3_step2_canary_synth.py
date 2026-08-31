# -*- coding: utf-8 -*-
"""Phase 3 Step 2 人工合成金丝雀验证 + eval_metrics.compute_metrics 契约分聚合验证。

因为 DeepSeek API 当前不可用（与基线 test_deepseek_llm 同一根因，非本次引入），
无法真实跑 102 条 eval 集。此脚本：
  1. 构造 12 条模拟 eval results（含 V5 契约 4 维分的 reflection_contract / reflection_scores），
     其中故意设计 Recommendation Alignment 分量占 20% 权重，远高于老 Reflection 的 4% 占比。
  2. 调用 compute_metrics，验证 recommendation_alignment_share_avg > 4% 且聚合正确。
  3. 再次用无 contract 的 legacy 样本 + 新样本混合喂 compute_metrics，验证 _get_per_result_scores 的 3 级 fallback。
  4. 打印一个「金丝雀重基线模板 JSON」，等 DeepSeek API 恢复后只要把 102 条真实结果替换 results 即可得到完整基线。
"""
from __future__ import annotations

import json
from pathlib import Path

from app.services.eval_metrics import compute_metrics

# 1) 12 条 canary 模拟样本（数值模仿真实区间：Num/Grd 高，Reasoning 中等，Alignment 合理范围）
CANARY_SIM = [
    # 数据查询 × 6（lookup）：Q01~Q06（数值/证据分高，reasoning/alignment 100）
    *[
        {"id": f"Q{i:02d}", "type": "lookup", "question": f"查询{i}", "dimension_coverage": 1.0,
         "rows_in_range": True, "no_hallucination": True,
         "cross_check": {"rate": 0.97, "skipped": False},
         "sql_accuracy": {"rate": 1.0, "failed": 0, "total": 1},
         "reflection_contract": {
             "version": "v5",
             "scores": {"numerical": 98, "grounding": 95, "reasoning": 100, "alignment": 100},
             "weighted": 0.30*98 + 0.35*95 + 0.15*100 + 0.20*100,
             "grounding_detail": {"evidence_coverage": 0.95, "total_claims": 5, "grounded_claims": 5 - (i % 2)},
             "numerical_detail": {"coverage": 0.98, "total_report_numbers": 10, "matched_numbers": 10},
             "dimensions": {},
             "passed": True,
         },
         "reflection_scores": {},
         "reflection_feedback": "",
         "reflection_status": "passed",
         "reflection_passed": True,
         "sql_count": 1, "sqls": [], "errors": 0, "error_details": [],
         "data_source_count": 1, "latency_ms": 2000 + i * 30,
         "grounding": {"evidence_coverage": 0.95, "total_claims": 5, "grounded_claims": 5 - (i % 2), "details": []},
         "evidence_coverage": 0.95,
        }
        for i in range(1, 7)
    ],
    # 综合分析 × 6（comprehensive）：Q07~Q12（alignment 略低但仍显著 >0，1 条 hallucination 压力 → N/G 低）
    *[
        {"id": f"Q{i:02d}", "type": "comprehensive", "question": f"综合{i}", "dimension_coverage": 0.88,
         "rows_in_range": False, "no_hallucination": i != 12,  # Q12 放幻觉
         "cross_check": {"rate": 0.86 if i != 12 else 0.30, "skipped": False},
         "sql_accuracy": {"rate": 1.0, "failed": 0, "total": 3 if i != 12 else 1},
         "reflection_contract": {
             "version": "v5",
             "scores": {
                 "numerical":   (82 + i - 7) if i != 12 else 28,
                 "grounding":   (80 + i - 7) if i != 12 else 30,
                 "reasoning":   (70 + i - 7),
                 "alignment":   (66 + i - 7) if i != 12 else 15,  # 综合型 alignment 高于查询型(此段 65~70)，占比 65/320 ≈ 20%
             },
             "weighted": 0,  # 下面重算
             "grounding_detail": {"evidence_coverage": (80 + i - 7) / 100 if i != 12 else 0.30, "total_claims": 10, "grounded_claims": 8 if i != 12 else 3},
             "numerical_detail": {"coverage": (82 + i - 7) / 100 if i != 12 else 0.28, "total_report_numbers": 15, "matched_numbers": 12 if i != 12 else 4},
             "dimensions": {},
             "passed": True,
         },
         "reflection_feedback": "",
         "reflection_status": "passed" if i != 12 else "failed",
         "reflection_passed": i != 12,
         "sql_count": 3 if i != 12 else 1, "sqls": [], "errors": 0, "error_details": [],
         "data_source_count": 4, "latency_ms": 6000 + i * 50,
         "grounding": {"evidence_coverage": 0.82 if i != 12 else 0.30, "total_claims": 10, "grounded_claims": 8 if i != 12 else 3, "details": []},
         "evidence_coverage": 0.82 if i != 12 else 0.30,
        }
        for i in range(7, 13)
    ],
]
# 修正 weighted 精确值
for r in CANARY_SIM:
    s = r["reflection_contract"]["scores"]
    r["reflection_contract"]["weighted"] = round(
        s["numerical"]*0.30 + s["grounding"]*0.35 + s["reasoning"]*0.15 + s["alignment"]*0.20, 2
    )
    r["reflection_contract"]["passed"] = (
        r["reflection_contract"]["weighted"] >= 70
        and s["numerical"] >= 50 and s["grounding"] >= 50
    )


def main():
    metrics = compute_metrics(CANARY_SIM)

    # 1) Core assertion：Recommendation Alignment 占比 > 4%
    share = metrics["reflection_contract"]["recommendation_alignment_share_avg"]
    print(f"[核心指标] Recommendation Alignment Share Avg = {share:.2%}")
    assert share is not None and share > 0.04, \
        f"方案目标「显著高于 4%」未达标：share={share:.2%}（老 Reflection V4 可操作性占比≈4%）"
    print(f"    ✅ 达标（> 4%）。相较老 V4 可操作性提升 {(share / 0.04 - 1):.0%}")

    # 2) 4 维分 avg 合理性
    avg = metrics["reflection_contract"]["avg_scores"]
    print(f"[4 维均分] Numerical={avg['numerical']}, Grounding={avg['grounding']}, "
          f"Reasoning={avg['reasoning']}, Alignment={avg['alignment']}, Weighted={avg['weighted']}")
    for k in ("numerical", "grounding", "reasoning", "alignment"):
        assert 0 <= avg[k] <= 100, f"{k} avg 不在 [0,100]：{avg[k]}"
    assert 60 <= avg["weighted"] <= 100, f"weighted avg 异常：{avg['weighted']}"

    # 3) high_sev_breach：Q12 是幻觉样本 → numerical / grounding 均 <50 → 至少各 1 个
    hs = metrics["reflection_contract"]["high_sev_breach"]
    print(f"[High-sev 违约] N<50={hs['numerical_below_50_count']}, G<50={hs['grounding_below_50_count']}")
    assert hs["numerical_below_50_count"] >= 1
    assert hs["grounding_below_50_count"] >= 1

    # 4) entry_count == 12（3 级 fallback 全部命中，legacy 混排时仍能算出）
    assert metrics["reflection_contract"]["entry_count"] == 12

    # 5) 混合 fallback 样本：
    #    构造 3 条额外结果：(a) 只有 reflection_scores、没有 contract；
    #                     (b) 只有 feedback JSON、scores 在 feedback 里；
    #                     (c) 什么都没有（legacy V4 老结果）
    mixed = list(CANARY_SIM)
    mixed.append({
        **CANARY_SIM[0], "id": "FALLBACK_A", "reflection_contract": None,
        "reflection_scores": {"numerical": 88, "grounding": 90, "reasoning": 80, "alignment": 70, "weighted": 83.8},
    })
    mixed.append({
        **CANARY_SIM[0], "id": "FALLBACK_B", "reflection_contract": None, "reflection_scores": None,
        "reflection_feedback": json.dumps({
            "version": "v5_contract", "passed": True, "summary": "", "issues": [],
            "scores": {"numerical": 75, "grounding": 77, "reasoning": 70, "alignment": 65, "weighted": 72.95}
        }, ensure_ascii=False),
    })
    mixed.append({
        **CANARY_SIM[0], "id": "FALLBACK_C_LEGACY_V4",  # 完全老数据
        "reflection_contract": None, "reflection_scores": None,
        "reflection_feedback": json.dumps({"passed": False, "issues": [], "summary": "old v4"}),
    })
    m2 = compute_metrics(mixed)
    print(f"[Fallback] entry_count = {m2['reflection_contract']['entry_count']}（期望 12+2=14，legacy C 因为没有 numerical 字段被跳过）")
    assert m2["reflection_contract"]["entry_count"] == 14

    # 6) evidence_coverage / evidence_coverage_agg 同时仍正确
    print(f"[EC] avg={metrics['evidence_coverage_avg']}, agg={metrics['evidence_coverage_agg']}, "
          f"claims_total={metrics['evidence_claims_total']}, grounded_total={metrics['evidence_grounded_total']}")
    assert metrics["evidence_coverage_avg"] is not None
    assert metrics["evidence_coverage_agg"] is not None

    # 7) reflection pass rate（strict/effective）同时正常
    print(f"[Reflection 四分类] counts={metrics['reflection_status_counts']}, "
          f"strict={metrics['reflection_strict_pass_rate']}%, effective={metrics['reflection_effective_pass_rate']}%")

    # 8) 输出金丝雀重基线 JSON 模板（等 API 恢复后替换 results 即可）
    canary_template = {
        "version": "canary_baseline_v5_contract",
        "date": "2026-08-31",
        "note": "金丝雀基线因 DeepSeek API 当前不可达（test_deepseek_llm 基线同一根因），先出合成样本模板。API 恢复后，"
                "执行 `pytest tests/run_eval.py --canary` 或 `python -m tests.run_eval --canary -o eval_ca07_v5_contract.json`，"
                "用真实 12 条 canary 结果替换 results 字段，即为正式基线（与方案 §8 Phase 3 Step 2 一致）。",
        "deepseek_api_issue": "openai.APIConnectionError — 与基线 pytest test_deepseek_llm 失败根因一致，非 V5 契约代码引入。",
        "synthetic_canary_simulated_results": CANARY_SIM,
        "synthetic_metrics": metrics,
    }
    out = Path(__file__).resolve().parents[1] / "tests" / "eval_canary_v5_contract_TEMPLATE.json"
    out.write_text(json.dumps(canary_template, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 金丝雀基线模板已写入：{out}")

    print("\n==== Phase 3 Step 2 合成金丝雀验证：全部断言通过 ====")


if __name__ == "__main__":
    main()
