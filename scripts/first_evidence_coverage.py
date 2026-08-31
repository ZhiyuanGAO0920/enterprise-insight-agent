"""V5 Phase 2：首次 Evidence Coverage 出数（5 条合成样本，零 LLM 离线）。

模拟真实 query_type × 报告风格，验证 grounding 校验器有效性 + 输出核心指标。
"""
import sys
sys.path.insert(0, ".")

from app.tools.grounding import check_report_grounding

SAMPLES = [
    {
        "id": "Q1 查询型-门店销售排行",
        "type": "lookup",
        "report": (
            "## 门店销售额排名（前 10）\n\n"
            "| 排名 | 门店 | 销售额 |\n|---|---|---|\n"
            "| 1 | 门店A | 125,000.50 元 |\n| 2 | 门店B | 98,000 元 |\n| 3 | 门店C | 75,000 元 |\n\n"
            "前 3 门店合计销售 298,000.50 元，占全店销售比重 42.5%。"
        ),
        "sources": [
            {"id": 1, "raw_data": "[('门店A', Decimal('125000.50')), ('门店B', Decimal('98000')), "
                                 "('门店C', Decimal('75000')), ('门店D', Decimal('66000')), "
                                 "('门店E', Decimal('52000')), ('门店F', Decimal('48000')), "
                                 "('门店G', Decimal('41000')), ('门店H', Decimal('38000')), "
                                 "('门店I', Decimal('32000')), ('门店J', Decimal('28000'))]"},
        ],
    },
    {
        "id": "Q2 分析型-会员诊断",
        "type": "analysis",
        "report": (
            "## 会员活跃度诊断\n\n"
            "钻石会员共 300 人，占全体会员的 6.0%，但贡献销售 85 万元，占整体营收的 28%。"
            "黄金会员 1,200 人，消费频次 5.2 次/人，复购率 28.5%。\n\n"
            "**问题**：白银会员（2,500 人）的本月复购率仅 12%，低于行业基准 18%，"
            "建议对白银会员推送生日券 + 到店礼组合，预计可提升复购率 5 个百分点。"
        ),
        "sources": [
            {"id": 1, "raw_data": "[('钻石', 300, Decimal('850000.00')), ('黄金', 1200, Decimal('1200000')), "
                                 "('白银', 2500, Decimal('680000')), ('普通', 1000, Decimal('300000'))]"},
            {"id": 2, "raw_data": "[('钻石', 7.1, 0.35), ('黄金', 5.2, 0.285), ('白银', 3.0, 0.12), "
                                 "('普通', 1.2, 0.05)]"},
            {"id": 3, "raw_data": "[(Decimal('3030000.00'),)]"},
        ],
    },
    {
        "id": "Q3 查询型-日销售趋势",
        "type": "lookup",
        "report": (
            "## 近 7 天销售趋势\n\n"
            "| 日期 | 金额 |\n|---|---|\n"
            "| 08-25 | 4.2 万 |\n| 08-26 | 4.8 万 |\n| 08-27 | 5.1 万 |\n"
            "| 08-28 | 3.9 万 |\n| 08-29 | 5.5 万 |\n| 08-30 | 6.0 万 |\n| 08-31 | 6.2 万 |\n\n"
            "本周累计销售 35.7 万元，环比上周增长 15.2%。"
        ),
        "sources": [
            {"id": 1, "raw_data": "[('2026-08-25', 42000), ('2026-08-26', 48000), "
                                 "('2026-08-27', 51000), ('2026-08-28', 39000), "
                                 "('2026-08-29', 55000), ('2026-08-30', 60000), "
                                 "('2026-08-31', 62000)]"},
            {"id": 2, "raw_data": "[(Decimal('310000.0'),)]"},
        ],
    },
    {
        "id": "Q4 幻觉压力-含编造数字",
        "type": "analysis",
        "report": (
            "## 门店销售诊断\n\n"
            "门店A本周销售 125,000 元（真实）。\n"
            "全国门店 3,200 家，本季度新增门店 420 家，其中华东 158 家。\n"
            "虚构指标：门店A NPS 得分 78.2 分（数据源无此数据）。编造：门店B客单价 588.50 元（数据无）。"
        ),
        "sources": [
            {"id": 1, "raw_data": "[('门店A', Decimal('125000.00')), ('门店B', Decimal('98000.00')), "
                                 "('门店C', Decimal('75000.00'))]"},
        ],
    },
    {
        "id": "Q5 分析型-综合报告",
        "type": "analysis",
        "report": (
            "## 经营周度诊断\n\n"
            "**数据概览**：本周营收 35.7 万元，同比增长 18.5%，环比增长 15.2%。"
            "新增会员 120 人，会员总数 5,000 人。\n\n"
            "**根因诊断**：1. 门店A（12.5万元）贡献超额完成 125%；门店E仅 5.2 万，完成率 68%。"
            "2. 钻石会员客单价 2,833 元（85万/300人），明显高于白银 272 元（68万/2500人）。"
            "3. 周末（08-30/08-31）合计销售 12.2 万元，占整周 34.2%。\n\n"
            "**可执行建议**：门店E启动「到店礼+满减券」组合，预计带来 30% 客流增长，月度可增收约 2 万元。"
        ),
        "sources": [
            {"id": 1, "raw_data": "[('2026-08-25', 42000), ('2026-08-26', 48000), "
                                 "('2026-08-27', 51000), ('2026-08-28', 39000), "
                                 "('2026-08-29', 55000), ('2026-08-30', 60000), "
                                 "('2026-08-31', 62000)]"},
            {"id": 2, "raw_data": "[('门店A', Decimal('125000.00')), ('门店B', Decimal('98000.00')), "
                                 "('门店C', Decimal('75000.00')), ('门店D', Decimal('66000.00')), "
                                 "('门店E', Decimal('52000.00'))]"},
            {"id": 3, "raw_data": "[('钻石', 300, Decimal('850000.00')), ('黄金', 1200, Decimal('1200000')), "
                                 "('白银', 2500, Decimal('680000')), ('普通', 1000, Decimal('300000'))]"},
            {"id": 4, "raw_data": "[(5000, 120)]"},
            {"id": 5, "raw_data": "[(Decimal('301300'),)]"},
        ],
    },
]


def main():
    total_claims = 0
    total_grounded = 0
    per_sample = []
    for s in SAMPLES:
        gr = check_report_grounding(s["report"], s["sources"])
        total_claims += gr.total_claims
        total_grounded += gr.grounded_claims
        ungrounded = [d["claim"] for d in gr.details if not d["grounded"]]
        per_sample.append({
            "id": s["id"],
            "type": s["type"],
            "claims": gr.total_claims,
            "grounded": gr.grounded_claims,
            "coverage": gr.evidence_coverage,
            "ungrounded_sample": ungrounded[:2],
        })

    print("=== Evidence Coverage — 首次出数（5 条合成样本，零 LLM 离线）===")
    print(f"样例总数：{len(SAMPLES)}")
    print(f"关键结论（含数字陈述句）总条数：{total_claims}")
    print(f"有证据支撑的结论总数：{total_grounded}")
    agg = round(total_grounded / total_claims * 100, 2) if total_claims else 0
    print(f"Aggregated Evidence Coverage：{agg}%")
    avg = round(sum(p["coverage"] for p in per_sample) / max(len(per_sample), 1) * 100, 2)
    print(f"Arithmetic Avg Evidence Coverage：{avg}%")
    print()
    print("逐条明细：")
    for p in per_sample:
        cov = round(p["coverage"] * 100, 1)
        ty = p["type"].ljust(8)
        n = p["id"][:18].ljust(20)
        print(f"  [{ty}] {n} claims={p['claims']:2d} grounded={p['grounded']:2d} "
              f"coverage={cov:5.1f}%  未命中样例={p['ungrounded_sample']}")
    print()
    print("Q4 幻觉压力用例说明：故意注入编造数字，grounding 识别为未命中")


if __name__ == "__main__":
    main()
