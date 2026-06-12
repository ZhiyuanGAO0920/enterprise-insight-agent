"""长期记忆 —— 使用向量搜索保存和检索分析历史。

使用 pgvector 对 Ollama 嵌入向量进行余弦相似度搜索。
"""

from typing import Optional

from sqlalchemy import desc, select, text as sql_text

from app.database.connection import get_session
from app.database.models import AnalysisHistory
from app.tools.embedding import get_embedding


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

async def save_analysis_history(
    question: str,
    report: str,
    sales_result: Optional[str] = None,
    crm_result: Optional[str] = None,
    finance_result: Optional[str] = None,
    inventory_result: Optional[str] = None,
    supply_chain_result: Optional[str] = None,
    reflection_passed: bool = False,
    user_id: Optional[int] = None,
) -> int:
    """将分析结果保存到历史记录表，同时保存向量嵌入。

    使用原始 SQL 配合 CAST(... AS vector) 来避免 asyncpg
    对 Vector 类型的序列化问题。

    Args:
        question: 用户的原始问题。
        report: 最终生成的报告。
        sales_result: 销售 Agent 的原始输出。
        crm_result: CRM Agent 的原始输出。
        finance_result: 财务 Agent 的原始输出。
        reflection_passed: 反思检查是否通过。
        user_id: 发起分析的用户 ID。

    Returns:
        新创建的历史记录 ID。
    """
    embedding = await get_embedding(report)
    # 格式化为 PG vector 字面量：[0.1,0.2,0.3,...]
    vec_str = "[" + ",".join(str(x) for x in embedding) + "]"

    # 获取默认 tenant_id（关联用户或第一个租户）
    tenant_id = None
    if user_id:
        async with get_session() as s2:
            r2 = await s2.execute(
                sql_text("SELECT tenant_id FROM users WHERE id = :uid"),
                {"uid": user_id},
            )
            row2 = r2.fetchone()
            if row2 and row2[0] is not None:
                tenant_id = row2[0]
    if tenant_id is None:
        async with get_session() as s3:
            r3 = await s3.execute(
                sql_text("SELECT id FROM tenants ORDER BY id LIMIT 1"),
            )
            row3 = r3.fetchone()
            if row3:
                tenant_id = row3[0]

    async with get_session() as session:
        result = await session.execute(
            sql_text(
                """
                INSERT INTO analysis_history
                    (question, report, sales_result, crm_result,
                     finance_result, inventory_result, supply_chain_result,
                     reflection_passed, user_id, tenant_id, embedding)
                VALUES
                    (:q, :r, :s, :c, :f, :inv, :sc, :rp, :uid, :tid, CAST(:e AS vector))
                RETURNING id
                """
            ),
            {
                "q": question,
                "r": report,
                "s": sales_result,
                "c": crm_result,
                "f": finance_result,
                "inv": inventory_result,
                "sc": supply_chain_result,
                "rp": reflection_passed,
                "uid": user_id,
                "tid": tenant_id,
                "e": vec_str,
            },
        )
        record_id = result.scalar_one()
        await session.commit()
        return record_id


async def find_similar_analyses(
    query: str,
    limit: int = 5,
    threshold: float = 0.7,
) -> list[dict]:
    """使用 pgvector 余弦相似度查找相似的历史分析。

    Args:
        query: 搜索查询文本。
        limit: 返回结果的最大数量。
        threshold: 最小余弦相似度（0.0 到 1.0）。

    Returns:
        包含 id、question、report 预览、create_time、similarity 的字典列表。
    """
    embedding = await get_embedding(query)
    vec_str = "[" + ",".join(str(x) for x in embedding) + "]"

    async with get_session() as session:
        result = await session.execute(
            sql_text(
                """
                SELECT id, question, report, create_time,
                       1 - (embedding <=> CAST(:e AS vector)) AS similarity
                FROM analysis_history
                WHERE embedding IS NOT NULL
                  AND 1 - (embedding <=> CAST(:e AS vector)) > :t
                ORDER BY similarity DESC
                LIMIT :l
                """
            ),
            {"e": vec_str, "t": threshold, "l": limit},
        )
        rows = result.fetchall()
        return [
            {
                "id": row.id,
                "question": row.question,
                "report_preview": (
                    row.report[:200] + "..." if len(row.report) > 200 else row.report
                ),
                "create_time": row.create_time.isoformat() if row.create_time else None,
                "similarity": round(row.similarity, 4),
            }
            for row in rows
        ]


async def get_history_by_user(
    user_id: int,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """获取指定用户的分析历史，按时间倒序排列。

    Args:
        user_id: 用户 ID。
        limit: 每页条数。
        offset: 分页偏移量。

    Returns:
        历史记录字典列表。
    """
    async with get_session() as session:
        stmt = (
            select(AnalysisHistory)
            .where(AnalysisHistory.user_id == user_id)
            .order_by(desc(AnalysisHistory.create_time))
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        records = result.scalars().all()
        return [
            {
                "id": r.id,
                "question": r.question,
                "summary": r.report[:200] if r.report else "",
                "reflection_passed": r.reflection_passed,
                "create_time": r.create_time.isoformat() if r.create_time else None,
            }
            for r in records
        ]


async def search_similar_sql(
    query_text: str,
    agent: str = "",
    top_k: int = 3,
    threshold: float = 0.65,
) -> list[dict]:
    """RAG 增强：检索历史上相似问题的已验证 SQL，供 Agent 作 Few-shot 参考。

    从 analysis_history 表中搜索与 query_text 语义相似的记录，
    并提取对应的 data_sources 中的 SQL 作为参考示例。

    Args:
        query_text: 当前用户问题文本。
        agent: 如果指定，只返回来自该 Agent 的 SQL（如 "sales"/"crm"/"finance"）。
        top_k: 返回的最大结果数。
        threshold: 最小余弦相似度。

    Returns:
        包含 question/sql/similarity 的字典列表。
    """
    from app.tools.embedding import get_embedding

    embedding = await get_embedding(query_text)
    vec_str = "[" + ",".join(str(x) for x in embedding) + "]"

    async with get_session() as session:
        result = await session.execute(
            sql_text(
                """
                SELECT id, question, report, create_time,
                       sales_result, crm_result, finance_result,
                       inventory_result, supply_chain_result,
                       1 - (embedding <=> CAST(:e AS vector)) AS similarity
                FROM analysis_history
                WHERE embedding IS NOT NULL
                  AND 1 - (embedding <=> CAST(:e AS vector)) > :t
                ORDER BY similarity DESC
                LIMIT :l
                """
            ),
            {"e": vec_str, "t": threshold, "l": top_k},
        )
        rows = result.fetchall()

        sql_results = []
        for row in rows:
            # 从主查询已经获取的子 Agent 结果中提取 SQL
            sales_text = row.sales_result or ""
            crm_text = row.crm_result or ""
            finance_text = row.finance_result or ""
            inventory_text = row.inventory_result or ""
            supply_chain_text = row.supply_chain_result or ""

            # 从子结果中简单提取 SQL（SQL 通常以 SELECT 开头）
            import re
            combined = f"{sales_text}\n{crm_text}\n{finance_text}\n{inventory_text}\n{supply_chain_text}"
            sql_matches = re.findall(r'(SELECT\s+.*?(?:;|$))', combined, re.IGNORECASE | re.DOTALL)

            for sql in sql_matches[:2]:  # 每条记录最多取 2 条 SQL
                sql_clean = sql.strip().replace("\n", " ")[:500]
                if sql_clean and len(sql_clean) > 20:
                    sql_results.append({
                        "question": row.question,
                        "sql": sql_clean,
                        "similarity": round(row.similarity, 4),
                    })

        return sql_results[:top_k]


async def get_history_detail(record_id: int, user_id: int | None = None) -> dict | None:
    """按 ID 获取单条历史记录的完整详情。

    返回前端重新渲染历史报告所需的所有字段，
    包括子 Agent 结果和数据来源。

    Args:
        record_id: 记录 ID。
        user_id: 如果提供，仅当记录属于该用户时才返回（数据隔离）。
    """
    async with get_session() as session:
        r = await session.get(AnalysisHistory, record_id)
        if r is None:
            return None
        # V4 数据隔离：验证记录所有权
        if user_id is not None and r.user_id is not None and r.user_id != user_id:
            return None
        return {
            "id": r.id,
            "question": r.question,
            "report": r.report or "",
            "sales_result": r.sales_result or "",
            "crm_result": r.crm_result or "",
            "finance_result": r.finance_result or "",
            "inventory_result": r.inventory_result or "",
            "supply_chain_result": r.supply_chain_result or "",
            "reflection_passed": r.reflection_passed,
            "create_time": r.create_time.isoformat() if r.create_time else None,
            "user_id": r.user_id,
        }
