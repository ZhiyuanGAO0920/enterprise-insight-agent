# -*- coding: utf-8 -*-
"""Phase 4 止损实验 · Step 1：探查 analysis_history 数据基础（只读）。

T-10b 实验前置：摸清检索链路的数据前提——
  1. 历史记录总量 / embedding 覆盖 / data_sources 落库率（T-10a 后新记录才有）
  2. 子 Agent 结果非空率（search_similar_sql 的 SQL 提取源）
  3. 正则 SQL 提取率（SELECT...; 模式在真实子结果里的命中情况）
  4. 抽样 3 条看 SQL 提取结果长相

零写入；RLS 经 set_tenant_id(1) 通过。
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text as sql_text

from app.database.connection import get_session, set_tenant_id

SQL_EXTRACT_RE = re.compile(r"(SELECT\s+.*?(?:;|$))", re.IGNORECASE | re.DOTALL)


async def main() -> None:
    set_tenant_id(1)  # RLS：默认租户
    async with get_session() as s:
        total = (await s.execute(sql_text("SELECT COUNT(*) FROM analysis_history"))).scalar_one()
        with_vec = (await s.execute(
            sql_text("SELECT COUNT(*) FROM analysis_history WHERE embedding IS NOT NULL")
        )).scalar_one()
        with_ds = (await s.execute(
            sql_text("SELECT COUNT(*) FROM analysis_history WHERE data_sources IS NOT NULL AND json_array_length(data_sources) > 0")
        )).scalar_one()
        with_sub = (await s.execute(
            sql_text("SELECT COUNT(*) FROM analysis_history WHERE sales_result IS NOT NULL OR crm_result IS NOT NULL OR finance_result IS NOT NULL OR inventory_result IS NOT NULL OR supply_chain_result IS NOT NULL")
        )).scalar_one()

        print(f"analysis_history 总数: {total}")
        print(f"  有 embedding  : {with_vec} ({with_vec / max(total, 1):.1%})")
        print(f"  有 data_sources: {with_ds} ({with_ds / max(total, 1):.1%})  <- T-10a 落库后新记录才有")
        print(f"  有子结果文本  : {with_sub} ({with_sub / max(total, 1):.1%})")

        # 子结果 SQL 提取率（search_similar_sql 的提取源）
        rows = (await s.execute(sql_text(
            "SELECT id, question, sales_result, crm_result, finance_result, inventory_result, supply_chain_result "
            "FROM analysis_history WHERE sales_result IS NOT NULL OR crm_result IS NOT NULL OR finance_result IS NOT NULL OR inventory_result IS NOT NULL OR supply_chain_result IS NOT NULL LIMIT 200"
        ))).fetchall()
        n_sql_hits = 0
        n_sql_clean = 0
        for r in rows:
            combined = "\n".join([x or "" for x in (r.sales_result, r.crm_result, r.finance_result, r.inventory_result, r.supply_chain_result)])
            matches = SQL_EXTRACT_RE.findall(combined)
            if matches:
                n_sql_hits += 1
                if any(len(m.strip().replace("\n", " ")) > 20 for m in matches[:2]):
                    n_sql_clean += 1
        print(f"\n子结果 SQL 提取率（抽样 {len(rows)} 条）:")
        print(f"  正则命中 ≥1 条 SQL : {n_sql_hits} ({n_sql_hits / max(len(rows), 1):.1%})")
        print(f"  有效 SQL（>20 字符）: {n_sql_clean} ({n_sql_clean / max(len(rows), 1):.1%})")

        # 抽样 3 条看提取结果长相
        print("\n===== 抽样 SQL 提取结果（3 条） =====")
        shown = 0
        for r in rows:
            combined = "\n".join([x or "" for x in (r.sales_result, r.crm_result, r.finance_result, r.inventory_result, r.supply_chain_result)])
            matches = SQL_EXTRACT_RE.findall(combined)
            clean = [m.strip().replace("\n", " ")[:300] for m in matches if len(m.strip().replace("\n", " ")) > 20]
            if clean:
                q = (r.question or "").split("\n")[0][:60]
                print(f"\n[id={r.id}] 问题: {q}")
                for c in clean[:2]:
                    print(f"  SQL: {c}")
                shown += 1
            if shown >= 3:
                break


if __name__ == "__main__":
    asyncio.run(main())
