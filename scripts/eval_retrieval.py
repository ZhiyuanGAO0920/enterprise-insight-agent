"""检索质量评估（V4.6.3，Phase 4 止损后仅保留语义召回）—— 零 LLM 成本。

把「BGE-M3 召回率 ~79%」这类拍脑袋数字变成可复测的实测指标：
1. 语义召回：对每条改写句检索相似历史（find_similar_analyses），
   检查原问题是否出现在 top-k 内（recall@k）—— 衡量向量检索质量

Phase 4 止损（T-10b, 2026-08-31）：RAG SQL 命中部分随 search_similar_sql 一起删除——
提取源（子结果文本）无 SQL，100 query 实测有效复用率 4%，修复后价值池仅 0.8%。

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

from app.database.connection import set_tenant_id
from app.tools.memory import find_similar_analyses  # noqa: E402

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


async def check_pair(original: str, paraphrase: str, _expected_tables: list[str], top_k: int, threshold: float) -> dict:
    """对一条改写句做语义召回检查（Phase 4 止损后仅保留召回）。"""
    norm_orig = _norm(original)

    # 语义召回
    hits = await find_similar_analyses(paraphrase, limit=top_k, threshold=threshold)
    recall = any(_norm(h["question"]) == norm_orig for h in hits)
    top1_sim = hits[0]["similarity"] if hits else None
    top_questions = [_norm(h["question"])[:20] for h in hits]

    return {
        "recall@k": recall,
        "top1_sim": top1_sim,
        "top_questions": top_questions,
    }


async def main():
    parser = argparse.ArgumentParser(description="检索质量评估：语义召回（Phase 4 止损后）")
    parser.add_argument("--top-k", type=int, default=5, help="recall@k 的 k（默认 5）")
    parser.add_argument("--threshold", type=float, default=0.3, help="最小余弦相似度（默认 0.3，放宽召回）")
    parser.add_argument("--domain", choices=["sales", "crm", "finance", "inventory", "supply_chain", "comprehensive"],
                        help="只看指定领域")
    args = parser.parse_args()

    set_tenant_id(1)  # T-02 租户隔离：无 tenant 上下文检索被拒，脚本显式指定默认租户

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
        sim = f"{r['top1_sim']:.3f}" if r["top1_sim"] is not None else "-"
        print(f"  {recall_mark} [{domain:12s}] 召回={sim}: {paraphrase[:40]}")

    recall_hits = sum(1 for _, _, _, r in results if r["recall@k"])
    sims = [r["top1_sim"] for _, _, _, r in results if r["top1_sim"] is not None]
    print("-" * 70)
    print(f"  语义召回率: {recall_hits}/{len(results)} = {recall_hits * 100.0 / len(results):.0f}%"
          f"（top-1 平均相似度 {sum(sims) / max(len(sims), 1):.3f}）")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
