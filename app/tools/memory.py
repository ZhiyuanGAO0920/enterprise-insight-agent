"""长期记忆 —— 使用向量搜索保存和检索分析历史。

使用 pgvector 对 Ollama 嵌入向量进行余弦相似度搜索。
"""

import json
import math
from typing import Optional

from sqlalchemy import desc, select, text as sql_text

from app.database.connection import get_session, get_tenant_id
from app.database.models import AnalysisHistory
from app.tools.embedding import get_embedding


# ---------------------------------------------------------------------------
# 向量值检测：过滤 NaN / Inf 防止 PostgreSQL CAST 拒绝
# ---------------------------------------------------------------------------


def _sanitize_vector(embedding: list[float]) -> list[float]:
    """将 NaN 和 Infinity 替换为 0.0，确保 PostgreSQL vector 类型可接受。"""
    return [0.0 if math.isnan(x) or math.isinf(x) else x for x in embedding]


def _vec_to_str(embedding: list[float]) -> str:
    """将 embedding 列表格式化为 PostgreSQL vector 字面量（含 NaN/Inf 防护）。"""
    return "[" + ",".join(str(x) for x in _sanitize_vector(embedding)) + "]"


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
    input_tokens: int = 0,
    output_tokens: int = 0,
    llm_cost: float = 0.0,
    reflection_issues: list | None = None,
    followup_questions: list[str] | None = None,
    data_sources: list | None = None,
    _force_fq: bool = False,
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
        data_sources: V5 T-10a：证据链 [{id,agent,sql,row_count,raw_data,...}]，
            持久化后历史详情可回查，Grounding 校验器消费。

    Returns:
        新创建的历史记录 ID。
    """
    # V4.6.3: 嵌入「问题」而非「报告」——检索侧（find_similar_analyses）
    # 用问题文本做向量，存储侧必须同构；此前嵌入报告（长文+数字表格），
    # 与短查询语义错位，改写句召回率实测仅 25%。
    # Phase 4 止损（T-10b）：search_similar_sql 已删除，详见 TASKS.md T-10b。
    embedding = await get_embedding(question)
    # 格式化为 PG vector 字面量：[0.1,0.2,0.3,...]
    vec_str = _vec_to_str(embedding)

    async with get_session() as session:
        # 获取默认 tenant_id（关联用户或第一个租户）
        tenant_id = None
        if user_id:
            r2 = await session.execute(
                sql_text("SELECT tenant_id FROM users WHERE id = :uid"),
                {"uid": user_id},
            )
            row2 = r2.fetchone()
            if row2 and row2[0] is not None:
                tenant_id = row2[0]
        if tenant_id is None:
            r3 = await session.execute(
                sql_text("SELECT id FROM tenants ORDER BY id LIMIT 1"),
            )
            row3 = r3.fetchone()
            if row3:
                tenant_id = row3[0]

        # 强制转 JSON 存库（None/空列表→"[]"，非空→JSON）
        _fq_val = json.dumps(followup_questions, ensure_ascii=False) if followup_questions else "[]"
        _ds_val = json.dumps(data_sources, ensure_ascii=False) if isinstance(data_sources, list) and data_sources else "[]"
        result = await session.execute(
            sql_text(
                """
                INSERT INTO analysis_history
                    (question, report, sales_result, crm_result,
                     finance_result, inventory_result, supply_chain_result,
                     reflection_passed, reflection_issues, user_id, tenant_id, embedding,
                     input_tokens, output_tokens, llm_cost, followup_questions,
                     data_sources)
                VALUES
                    (:q, :r, :s, :c, :f, :inv, :sc, :rp, :ri, :uid, :tid, CAST(:e AS vector),
                     :it, :ot, :cost, :fq, CAST(:ds AS JSON))
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
                "ri": json.dumps(reflection_issues, ensure_ascii=False) if isinstance(reflection_issues, list) else "[]",
                "uid": user_id,
                "tid": tenant_id,
                "e": vec_str,
                "it": input_tokens,
                "ot": output_tokens,
                "cost": llm_cost,
                "fq": _fq_val,
                "ds": _ds_val,
            },
        )
        record_id = result.scalar_one()
        await session.commit()
        return record_id


async def find_similar_analyses(
    query: str,
    limit: int = 5,
    threshold: float = 0.7,
    user_id: int | None = None,
) -> list[dict]:
    """使用 pgvector 余弦相似度查找相似的历史分析。

    Args:
        query: 搜索查询文本。
        limit: 返回结果的最大数量。
        threshold: 最小余弦相似度（0.0 到 1.0）。
        user_id: 用户 ID（用于租户隔离，为 None 时不限制租户）。

    Returns:
        包含 id、question、report 预览、create_time、similarity 的字典列表。
    """
    embedding = await get_embedding(query)
    vec_str = _vec_to_str(embedding)

    async with get_session() as session:
        # 查询用户的 tenant_id 用于隔离
        tid = None
        if user_id is not None:
            r = await session.execute(
                sql_text("SELECT tenant_id FROM users WHERE id = :uid"),
                {"uid": user_id},
            )
            row = r.fetchone()
            if row and row[0] is not None:
                tid = row[0]
        # V5 T-02：无 user_id 或查不到 → contextvar 兜底；仍无 → 拒绝（不跨租户命中）
        if tid is None:
            tid = get_tenant_id()
        if tid is None:
            return []
        tid_filter = " AND tenant_id = :tid"
        result = await session.execute(
            sql_text(
                f"""
                SELECT id, question, report, create_time,
                       1 - (embedding <=> CAST(:e AS vector)) AS similarity
                FROM analysis_history
                WHERE embedding IS NOT NULL
                  AND (embedding <=> CAST(:e AS vector))::text <> 'NaN'
                  AND 1 - (embedding <=> CAST(:e AS vector)) > :t
                  {tid_filter}
                ORDER BY similarity DESC
                LIMIT :l
                """
            ),
            {"e": vec_str, "t": threshold, "l": limit, "tid": tid},
        )
        rows = result.fetchall()
        # 防御：过滤 NaN 相似度（全 0 向量余弦距离为 NaN）
        rows = [r for r in rows if not math.isnan(r.similarity)]
        return [
            {
                "id": row.id,
                # 清洗历史脏数据：旧记录曾把 [系统指令] ranking hint 存进 question，
                # 只取第一行（原始问题），不再向展示层泄漏系统指令
                "question": row.question.split("\n")[0].strip() if row.question else row.question,
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
            "data_sources": r.data_sources if isinstance(r.data_sources, list) else [],
        }
