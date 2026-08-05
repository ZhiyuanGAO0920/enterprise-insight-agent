"""检索质量评估（V4.6.3）—— 语义召回 + RAG SQL 命中，零 LLM 成本。

把「BGE-M3 召回率 ~79%」这类拍脑袋数字变成可复测的实测指标：
1. 语义召回：对每条改写句检索相似历史（find_similar_analyses），
   检查原问题是否出现在 top-k 内（recall@k）—— 衡量向量检索质量
2. RAG SQL 命中：对每条改写句检索历史已验证 SQL（search_similar_sql），
   检查返回的 SQL 是否引用了该领域期望的表 —— 衡量 RAG 给 Agent 的参考质量

数据基础：analysis_history 中需存在原问题的历史记录
（每日投喂/评估集运行会自动积累）。

用法：
    python scripts/eval_retrieval.py               # 默认 recall@5，阈值 0.3
    python scripts/eval_retrieval.py --top-k 3     # 改 recall@3
    python scripts/eval_retrieval.py --domain sales # 只看销售域
"""

import argparse
import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.tools.memory import find_similar_analyses, search_similar_sql  # noqa: E402

# (domain, 原问题[须存在于历史], 改写句, 期望表)
# 期望表用于 RAG SQL 命中判定：返回的 SQL 引用任一期望表即算命中
CASES: list[tuple[str, str, str, list[str]]] = [
    ("sales", "各门店销售额排名", "按销售额给所有门店排个名次", ["store", "orders"]),
    ("sales", "华东区近30天销售额最高的门店是哪个", "华东最近30天哪个门店卖得最好", ["store", "orders"]),
    ("sales", "昨日销售额最高的 Top 10 门店", "昨天卖得最好的前十家门店是哪几家", ["store", "orders"]),
    ("crm", "会员复购率是多少", "咱们的会员回头购买的比例有多高", ["member"]),
    ("crm", "各等级会员人数分布", "不同会员等级各有多少人", ["member"]),
    ("crm", "各门店会员数量排名", "哪家门店的会员最多，排个名", ["member", "store"]),
    ("finance", "各门店毛利率排行", "按毛利率给门店从高到低排一下", ["store", "orders"]),
    ("finance", "近30天退款金额超过1000元的门店有哪些", "最近一个月退款超过一千块的门店名单", ["store", "orders"]),
    ("inventory", "哪些商品有缺货风险", "现在有哪些商品可能要断货", ["inventory", "product"]),
    ("inventory", "各品类库存总量排名", "各个品类的库存总量排个序", ["inventory", "product"]),
    ("supply_chain", "供应商准时交货率排名", "哪些供应商交货最准时，排个名", ["supplier", "purchase_order"]),
    ("supply_chain", "物流时效最差的5个供应商", "送货最慢的五个供应商", ["supplier", "purchase_order"]),
]

_NORM_RE = re.compile(r"[\s，。！？、,.!?;；:：“”‘’（）()【】\[\]]")


def _norm(q: str) -> str:
    return _NORM_RE.sub("", q or "")


async def check_pair(original: str, paraphrase: str, expected_tables: list[str], top_k: int, threshold: float) -> dict:
    """对一条改写句做召回 + SQL 命中检查。"""
    norm_orig = _norm(original)

    # 1. 语义召回
    hits = await find_similar_analyses(paraphrase, limit=top_k, threshold=threshold)
    recall = any(_norm(h["question"]) == norm_orig for h in hits)
    top1_sim = hits[0]["similarity"] if hits else None
    top_questions = [_norm(h["question"])[:20] for h in hits]

    # 2. RAG SQL 命中
    sqls = await search_similar_sql(paraphrase, top_k=3, threshold=threshold)
    sql_hit = False
    for s in sqls:
        sql_lower = s["sql"].lower()
        if any(t in sql_lower for t in expected_tables):
            sql_hit = True
            break
    return {
        "recall@k": recall,
        "top1_sim": top1_sim,
        "top_questions": top_questions,
        "sql_count": len(sqls),
        "sql_hit": sql_hit,
    }


async def main():
    parser = argparse.ArgumentParser(description="检索质量评估：语义召回 + RAG SQL 命中")
    parser.add_argument("--top-k", type=int, default=5, help="recall@k 的 k（默认 5）")
    parser.add_argument("--threshold", type=float, default=0.3, help="最小余弦相似度（默认 0.3，放宽召回）")
    parser.add_argument("--domain", choices=["sales", "crm", "finance", "inventory", "supply_chain", "comprehensive"],
                        help="只看指定领域")
    args = parser.parse_args()

    cases = [c for c in CASES if not args.domain or c[0] == args.domain]
    if not cases:
        print("无匹配用例")
        return

    print("=" * 70)
    print(f"  检索质量评估（recall@{args.top_k}，阈值 {args.threshold}，{len(cases)} 组改写句）")
    print("=" * 70)

    results = []
    for domain, original, paraphrase, tables in cases:
        r = await check_pair(original, paraphrase, tables, args.top_k, args.threshold)
        results.append((domain, original, paraphrase, r))
        recall_mark = "✅" if r["recall@k"] else "❌"
        sql_mark = "✅" if r["sql_hit"] else ("⚠️" if r["sql_count"] else "—")
        sim = f"{r['top1_sim']:.3f}" if r["top1_sim"] is not None else "-"
        print(f"  {recall_mark} [{domain:12s}] 召回={sim} SQL={sql_mark}（{r['sql_count']}条）: {paraphrase[:40]}")

    recall_hits = sum(1 for _, _, _, r in results if r["recall@k"])
    sql_hits = sum(1 for _, _, _, r in results if r["sql_hit"])
    sims = [r["top1_sim"] for _, _, _, r in results if r["top1_sim"] is not None]
    print("-" * 70)
    print(f"  语义召回率: {recall_hits}/{len(results)} = {recall_hits * 100.0 / len(results):.0f}%"
          f"（top-1 平均相似度 {sum(sims) / max(len(sims), 1):.3f}）")
    print(f"  RAG SQL 命中率: {sql_hits}/{len(results)} = {sql_hits * 100.0 / len(results):.0f}%"
          f"（返回 SQL 引用期望表）")
    if sql_hits == 0 and recall_hits > 0:
        print("  ⚠️ 注：召回正常但 SQL 命中 0，原因通常是「SQL 未随 Agent 结果落库」——"
              "analysis_history 只存最终回答（表格），不存工具调用的 SQL，"
              "search_similar_sql 的正则提取拿不到内容（存储设计缺口，非检索失败）。")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
