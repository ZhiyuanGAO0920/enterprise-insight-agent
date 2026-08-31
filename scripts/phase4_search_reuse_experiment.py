# -*- coding: utf-8 -*-
"""Phase 4 止损实验 · Step 2：search_similar_sql 复用价值判定（只读）。

方案 Phase 4（T-10b）：100 个历史问题 → Top-K 相似检索 → 人工判定"真正有复用价值"比例。
决策规则：Top-5 有效复用率 < 20% → 砍掉（写止损记录）。

实验分两层证据：
  A. SQL 复用链路端到端命中率 —— 直接测 search_similar_sql 在真实历史数据上返回几条 SQL
     （探查已发现子结果文本为 LLM 回答，无 SQL，正则提取 0 命中）
  B. 向量相似召回质量 —— 批量算 100 query × 全库余弦相似度，输出 Top-5 相似问题
     与相似度分布（若召回差则"相似问题"也没价值；若召回好则语义检索有价值，但 SQL 复用仍不可行）

输出：
  - 控制台统计
  - scripts/phase4_reuse_judgment_samples.json —— 抽样 20 个 query 的 Top-1 相似问题，供人工判定
"""
from __future__ import annotations

import asyncio
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text as sql_text

from app.database.connection import get_session, set_tenant_id
from app.tools.embedding import get_embeddings
from app.tools.memory import search_similar_sql

N_QUERIES = 100
TOP_K = 5
THRESHOLD = 0.65
SAMPLE_FOR_JUDGE = 20


async def main() -> None:
    set_tenant_id(1)  # RLS：默认租户

    # ---- 取历史问题池（有 embedding 的，问题去重） ----
    async with get_session() as s:
        rows = (await s.execute(sql_text(
            "SELECT id, question, report FROM analysis_history "
            "WHERE embedding IS NOT NULL ORDER BY id DESC LIMIT 1200"
        ))).fetchall()

    seen: set[str] = set()
    pool: list[dict] = []
    for r in rows:
        q = (r.question or "").split("\n")[0].strip()
        if not q or q in seen:
            continue
        seen.add(q)
        pool.append({"id": r.id, "question": q, "report": (r.report or "")[:200]})
    if len(pool) > N_QUERIES:
        pool = pool[:N_QUERIES]
    print(f"问题池: {len(pool)} 条（去重后取前 {N_QUERIES}）")

    # ---- A. search_similar_sql 端到端命中率（生产代码原样调用） ----
    n_queries_with_sql = 0
    n_sql_returned = 0
    a_hits_detail = []
    for item in pool:
        hits = await search_similar_sql(item["question"], top_k=TOP_K, threshold=THRESHOLD)
        if hits:
            n_queries_with_sql += 1
            n_sql_returned += len(hits)
            a_hits_detail.append({
                "query": item["question"][:100],
                "hits": hits[:2],
            })
    print(f"\n[A] search_similar_sql 端到端（top_k={TOP_K}, threshold={THRESHOLD}）:")
    print(f"    有 SQL 返回的 query 数: {n_queries_with_sql}/{len(pool)} = {n_queries_with_sql / len(pool):.1%}")
    print(f"    返回 SQL 总条数: {n_sql_returned}")
    for d in a_hits_detail[:4]:
        print(f"    Q: {d['query']}")
        for h in d["hits"]:
            print(f"      ← 来自「{(h['question'] or '').split(chr(10))[0][:50]}」sim={h['similarity']}: {h['sql'][:120]}")

    # ---- B. 向量相似召回质量（批量算，绕开提取层看检索层本身） ----
    # 取全库 embedding
    async with get_session() as s:
        all_rows = (await s.execute(sql_text(
            "SELECT id, question FROM analysis_history WHERE embedding IS NOT NULL"
        ))).fetchall()
        all_ids = [r.id for r in all_rows]
        all_emb = []
        # 分块拉取 embedding（避免超长列表）
        for i in range(0, len(all_rows), 200):
            chunk = all_rows[i : i + 200]
            chunk_ids = [r.id for r in chunk]
            res = (await s.execute(sql_text(
                "SELECT id, embedding FROM analysis_history WHERE id = ANY(:ids) ORDER BY id"
            ).bindparams(ids=chunk_ids))).fetchall()
            # pgvector 无 asyncpg 适配器时返回字符串 "[1.2,3.4,...]" → json.loads 解析
            emb_map = {r.id: json.loads(r.embedding) for r in res}
            all_emb.extend([emb_map[c.id] for c in chunk])

    import numpy as np
    # 历史脏数据防护：过滤维度异常的 embedding（早期版本可能维度不同）
    from collections import Counter
    dims = Counter(len(e) for e in all_emb)
    print(f"\n    embedding 维度分布: {dict(dims)}")
    valid = [(r, e) for r, e in zip(all_rows, all_emb) if len(e) == dims.most_common(1)[0][0]]
    all_rows, all_emb = [r for r, _ in valid], [e for _, e in valid]
    emb_matrix = np.array(all_emb, dtype=np.float32)          # (N, dim)
    # 归一化（BGE-M3 已归一化？稳妥起见按行 L2 归一化）
    emb_matrix = emb_matrix / (np.linalg.norm(emb_matrix, axis=1, keepdims=True) + 1e-9)
    id_to_row = {r.id: i for i, r in enumerate(all_rows)}

    # query 向量
    qs = [q["question"] for q in pool]
    q_emb = await get_embeddings(qs)
    q_mat = np.array(q_emb, dtype=np.float32)
    q_mat = q_mat / (np.linalg.norm(q_mat, axis=1, keepdims=True) + 1e-9)

    sims = q_mat @ emb_matrix.T                      # (100, N) 余弦
    sims = np.where(np.isnan(sims), -1.0, sims)

    recall_stats = {"top1": [], "top5": [], "over_threshold": 0}
    for i, item in enumerate(pool):
        sim_row = sims[i]
        # 排除自身记录（query 来自历史记录本身）
        self_idx = id_to_row.get(item["id"])
        if self_idx is not None:
            sim_row = sim_row.copy()
            sim_row[self_idx] = -1.0
        order = np.argsort(-sim_row)[:TOP_K]
        top_scores = sim_row[order].tolist()
        recall_stats["top1"].append(top_scores[0] if top_scores else 0.0)
        recall_stats["top5"].append(max(top_scores, default=0.0))
        if any(x >= THRESHOLD for x in top_scores):
            recall_stats["over_threshold"] += 1

    top1 = np.array(recall_stats["top1"])
    top5 = np.array(recall_stats["top5"])
    print(f"\n[B] 向量相似召回质量（排除自身）:")
    print(f"    Top-1 相似度均值: {top1.mean():.4f}  中位: {np.median(top1):.4f}")
    print(f"    Top-5 最高相似度均值: {top5.mean():.4f}  中位: {np.median(top5):.4f}")
    print(f"    ≥ {THRESHOLD} 的 query 数: {recall_stats['over_threshold']}/{len(pool)} = {recall_stats['over_threshold'] / len(pool):.1%}")
    print(f"    Top-1 ≥ 0.65: {(top1 >= THRESHOLD).sum()}/{len(pool)} = {(top1 >= THRESHOLD).mean():.1%}")
    print(f"    Top-1 < 0.50（召回很弱）: {(top1 < 0.50).sum()}/{len(pool)} = {(top1 < 0.50).mean():.1%}")

    # ---- C. 抽样 20 个 query 的 Top-1 相似问题，供人工判定 ----
    random.seed(42)
    sample_idx = random.sample(range(len(pool)), min(SAMPLE_FOR_JUDGE, len(pool)))
    samples = []
    for i in sample_idx:
        item = pool[i]
        sim_row = sims[i]
        self_idx = id_to_row.get(item["id"])
        if self_idx is not None:
            sim_row = sim_row.copy()
            sim_row[self_idx] = -1.0
        j = int(np.argmax(sim_row))
        samples.append({
            "query_id": item["id"],
            "query": item["question"][:120],
            "top1_id": all_ids[j],
            "top1_question": (all_rows[j].question or "").split("\n")[0][:120],
            "top1_similarity": round(float(sim_row[j]), 4),
        })

    out = Path(__file__).resolve().parents[1] / "scripts" / "phase4_reuse_judgment_samples.json"
    out.write_text(json.dumps({
        "meta": {
            "n_queries": len(pool),
            "top_k": TOP_K,
            "threshold": THRESHOLD,
            "evidence_A_sql_hit_rate": f"{n_queries_with_sql}/{len(pool)}",
            "note": "A 层已证明 SQL 提取源为空；B 层供人工判定：Top-1 相似问题对生成新查询是否有复用价值",
        },
        "samples": samples,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[C] 人工判定样本已写入: {out}（{len(samples)} 条）")


if __name__ == "__main__":
    asyncio.run(main())
