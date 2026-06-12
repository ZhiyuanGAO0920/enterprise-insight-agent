"""AI 质量监控仪表板 API — 聚合展示 Agent 表现趋势。

从 agent_trace_events、user_feedback、analysis_history 三张表中
提取 AI PM 最关心的 5 个核心指标，支持按时间范围筛选。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from app.api.dependencies import require_permission
from app.database.connection import get_session

router = APIRouter(prefix="/monitor", tags=["质量监控"])


@router.get("/errors", summary="Agent 错误日志")
async def error_log(
    days: int = Query(7, ge=1, le=30),
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(require_permission("alert:view")),
):
    """返回最近 Agent 执行错误的详细日志。"""
    async with get_session() as session:
        result = await session.execute(text("""
            SELECT node_name, error, elapsed_ms, created_at, session_id
            FROM agent_trace_events
            WHERE error IS NOT NULL
              AND created_at >= NOW() - (:d || ' days')::INTERVAL
            ORDER BY created_at DESC
            LIMIT :l
        """), {"d": str(days), "l": limit})
        errors = [
            {
                "time": row.created_at.isoformat() if row.created_at else "",
                "agent": row.node_name,
                "error": row.error[:300] if row.error else "",
                "elapsed_ms": row.elapsed_ms,
                "session": row.session_id or "",
            }
            for row in result.fetchall()
        ]
        # 按 Agent 聚合统计
        agg_result = await session.execute(text("""
            SELECT node_name, COUNT(*) as cnt
            FROM agent_trace_events
            WHERE error IS NOT NULL
              AND created_at >= NOW() - (:d || ' days')::INTERVAL
            GROUP BY node_name ORDER BY cnt DESC
        """), {"d": str(days)})
        by_agent = {row.node_name: row.cnt for row in agg_result.fetchall()}

    return {"period_days": days, "total_errors": len(errors), "by_agent": by_agent, "errors": errors}


@router.get("/overview", summary="AI 质量总览")
async def quality_overview(
    days: int = Query(30, ge=1, le=90, description="统计最近 N 天"),
    user: dict = Depends(require_permission("alert:view")),
):
    """返回 AI 产品质量核心指标。

    五大核心指标：
      - SQL 准确率：reflection_passed 的比例（近似衡量）
      - Reflection 通过率：质检 Agent 审核通过的比例
      - 各 Agent 错误率排行
      - P50/P95 延迟
      - 日均 LLM 调用成本（估算）
    """
    async with get_session() as session:
        # 1. Reflection 通过率 + 分析总量
        reflect = await session.execute(text("""
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN reflection_passed = true THEN 1 END) as passed,
                ROUND(COUNT(CASE WHEN reflection_passed = true THEN 1 END) * 100.0 / COUNT(*), 1) as pass_rate
            FROM analysis_history
            WHERE create_time >= NOW() - (:d || ' days')::INTERVAL
        """), {"d": str(days)})
        r = reflect.fetchone()

        # 2. 各 Agent 错误率排行
        agent_errors = await session.execute(text("""
            SELECT
                node_name as agent,
                COUNT(*) as total_runs,
                COUNT(CASE WHEN error IS NOT NULL THEN 1 END) as error_count,
                ROUND(COUNT(CASE WHEN error IS NOT NULL THEN 1 END) * 100.0 / COUNT(*), 1) as error_rate,
                ROUND(AVG(elapsed_ms)) as avg_ms,
                ROUND(MAX(elapsed_ms)) as max_ms
            FROM agent_trace_events
            WHERE created_at >= NOW() - (:d || ' days')::INTERVAL
            GROUP BY node_name
            ORDER BY error_rate DESC
        """), {"d": str(days)})
        agents = [
            {
                "agent": row.agent,
                "total_runs": row.total_runs,
                "error_count": row.error_count,
                "error_rate": row.error_rate,
                "avg_ms": row.avg_ms,
                "max_ms": row.max_ms,
            }
            for row in agent_errors.fetchall()
        ]

        # 3. P50/P95 延迟
        latency = await session.execute(text("""
            SELECT
                ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY elapsed_ms)) as p50,
                ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY elapsed_ms)) as p95
            FROM agent_trace_events
            WHERE created_at >= NOW() - (:d || ' days')::INTERVAL
        """), {"d": str(days)})
        lat = latency.fetchone()

        # 4. 反馈统计
        feedback = await session.execute(text("""
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN rating = 'helpful' THEN 1 END) as helpful,
                ROUND(COUNT(CASE WHEN rating = 'helpful' THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0), 1) as helpful_pct
            FROM user_feedback
            WHERE created_at >= NOW() - (:d || ' days')::INTERVAL
        """), {"d": str(days)})
        fb = feedback.fetchone()

        # 5. 日均分析量
        daily = await session.execute(text("""
            SELECT DATE(create_time) as dt, COUNT(*) as cnt
            FROM analysis_history
            WHERE create_time >= NOW() - (:d || ' days')::INTERVAL
            GROUP BY dt ORDER BY dt
        """), {"d": str(days)})
        daily_trend = [{"date": str(row.dt), "count": row.cnt} for row in daily.fetchall()]

        # 6. 成本估算（按每次分析约 ¥0.04）
        avg_cost_per_analysis = 0.04
        total_analyses = r.total

    return {
        "period_days": days,
        "total_analyses": total_analyses,
        "reflection_pass_rate": r.pass_rate if r.total > 0 else 0,
        "feedback_helpful_rate": fb.helpful_pct if fb.total > 0 else 0,
        "latency_p50_ms": lat.p50 or 0,
        "latency_p95_ms": lat.p95 or 0,
        "estimated_daily_cost": round(total_analyses * avg_cost_per_analysis / days, 2),
        "estimated_monthly_cost": round(total_analyses * avg_cost_per_analysis / days * 30, 2),
        "agents": agents,
        "daily_trend": daily_trend,
        "health": {
            "reflection": "✅" if (r.pass_rate or 0) >= 80 else "⚠️",
            "latency": "✅" if (lat.p95 or 0) < 60000 else "⚠️",
            "feedback": "✅" if (fb.helpful_pct or 0) >= 80 else "⚠️",
        },
    }
