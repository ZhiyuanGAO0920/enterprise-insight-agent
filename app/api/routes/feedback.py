"""用户反馈路由 — V3 功能（P1-2：反馈闭环）。"""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.api.dependencies import get_current_user, require_permission
from app.config import get_settings
from app.database.connection import get_session

router = APIRouter(prefix="/feedback", tags=["用户反馈"])


class FeedbackRequest(BaseModel):
    analysis_history_id: int = Field(..., description="分析记录 ID（从 /api/analysis/analyze 的返回值获取）")
    rating: str = Field(..., pattern="^(helpful|inaccurate|not_relevant)$", description="评分：helpful=有帮助, inaccurate=不准确, not_relevant=不相关")
    reason: str = Field(default="", max_length=500, description="反馈原因（选填）")
    agent_issues: dict = Field(default={}, description="具体出错的 Agent 标记（选填）")


class FeedbackStatsResponse(BaseModel):
    enabled: bool = Field(description="反馈功能是否已启用")
    total: int = Field(default=0, description="反馈总数")
    helpful_rate: float = Field(default=0.0, description="好评率（0.0-1.0）")
    breakdown: dict = Field(default={}, description="各评分分类统计")


@router.post("/submit", summary="提交反馈")
async def submit_feedback(
    req: FeedbackRequest,
    user: dict = Depends(get_current_user),
):
    """对某次分析结果提交反馈。

    - 需要先通过 /api/analysis/analyze 获得 record_id
    - 每条分析记录仅需提交一次反馈
    - 反馈数据用于分析质量评估和 Prompt 持续优化
    """
    settings = get_settings()
    if not settings.feature_feedback:
        return {"status": "disabled", "message": "反馈功能未启用", "enabled": False}

    # 验证记录存在且属于当前用户
    async with get_session() as session:
        result = await session.execute(
            text("SELECT id FROM analysis_history WHERE id = :id AND user_id = :uid"),
            {"id": req.analysis_history_id, "uid": user["user_id"]},
        )
        if not result.fetchone():
            raise HTTPException(status_code=404, detail="分析记录未找到")

        await session.execute(
            text("""
                INSERT INTO user_feedback
                    (analysis_history_id, user_id, rating, reason, agent_issues)
                VALUES (:aid, :uid, :r, :reason, CAST(:issues AS jsonb))
            """),
            {
                "aid": req.analysis_history_id,
                "uid": user["user_id"],
                "r": req.rating,
                "reason": req.reason or None,
                "issues": json.dumps(req.agent_issues) if req.agent_issues else "{}",
            },
        )
        await session.commit()

    return {"status": "ok", "message": "反馈已提交，感谢您的参与！"}


@router.get("/stats", response_model=FeedbackStatsResponse, summary="获取反馈统计")
async def get_feedback_stats(
    user: dict = Depends(require_permission("alert:view")),
):
    """获取用户反馈汇总统计（管理员/区域经理权限）。

    返回总反馈数、好评率、各分类统计。
    """
    settings = get_settings()
    if not settings.feature_feedback:
        return {"enabled": False, "total": 0, "helpful_rate": 0.0, "breakdown": {}}

    async with get_session() as session:
        result = await session.execute(text("""
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN rating = 'helpful' THEN 1 END) as helpful,
                COUNT(CASE WHEN rating = 'inaccurate' THEN 1 END) as inaccurate,
                COUNT(CASE WHEN rating = 'not_relevant' THEN 1 END) as not_relevant
            FROM user_feedback
        """))
        row = result.fetchone()
        total = row[0] or 0
        return {
            "enabled": True,
            "total": total,
            "helpful_rate": round(row[1] / total, 2) if total > 0 else 0.0,
            "breakdown": {
                "有帮助": row[1] or 0,
                "不准确": row[2] or 0,
                "不相关": row[3] or 0,
            },
        }


@router.get("/analyze", summary="分析反馈数据 — 按 Agent 维度聚合")
async def analyze_feedback(
    days: int = 30,
    user: dict = Depends(require_permission("alert:view")),
):
    """返回最近 N 天按 Agent 维度聚合的反馈分析。

    用于驱动 Prompt 优化优先级排序：
    - 哪个 Agent 最常被投诉？
    - 最常见的投诉原因是什么？
    - 不准确率的变化趋势？

    Args:
        days: 统计最近多少天的数据（默认 30 天）。
    """
    settings = get_settings()
    if not settings.feature_feedback:
        return {"enabled": False, "message": "反馈功能未启用"}

    async with get_session() as session:
        # 按 Agent 聚合不准确率
        agent_stats = await session.execute(text("""
            SELECT
                COALESCE(aj.key, 'unknown') as agent,
                COUNT(*) as total_feedback,
                COUNT(CASE WHEN uf.rating = 'inaccurate' THEN 1 END) as inaccurate_count,
                ROUND(
                    COUNT(CASE WHEN uf.rating = 'inaccurate' THEN 1 END) * 100.0 / COUNT(*), 1
                ) as inaccurate_rate
            FROM user_feedback uf
            LEFT JOIN LATERAL jsonb_each(COALESCE(uf.agent_issues, '{}'::jsonb)) as aj ON true
            WHERE uf.created_at >= NOW() - (:days || ' days')::INTERVAL
            GROUP BY aj.key
            ORDER BY inaccurate_rate DESC
        """), {"days": str(days)})
        agents = [
            {
                "agent": row.agent,
                "total_feedback": row.total_feedback,
                "inaccurate_count": row.inaccurate_count,
                "inaccurate_rate": row.inaccurate_rate,
            }
            for row in agent_stats.fetchall()
        ]

        # 最常见的不准确原因
        reasons = await session.execute(text("""
            SELECT reason, COUNT(*) as cnt
            FROM user_feedback
            WHERE rating = 'inaccurate'
              AND reason IS NOT NULL
              AND reason != ''
              AND created_at >= NOW() - (:days || ' days')::INTERVAL
            GROUP BY reason
            ORDER BY cnt DESC
            LIMIT 10
        """), {"days": str(days)})
        top_reasons = [{"reason": row.reason, "count": row.cnt} for row in reasons.fetchall()]

        # 总体统计
        overall = await session.execute(text("""
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN rating = 'helpful' THEN 1 END) as helpful,
                ROUND(COUNT(CASE WHEN rating = 'helpful' THEN 1 END) * 100.0 / COUNT(*), 1) as helpful_pct
            FROM user_feedback
            WHERE created_at >= NOW() - (:days || ' days')::INTERVAL
        """), {"days": str(days)})
        o = overall.fetchone()

    return {
        "enabled": True,
        "period_days": days,
        "total_feedback": o.total,
        "helpful_rate": round(o.helpful_pct / 100, 2) if o.total > 0 else 0.0,
        "top_issue_agents": [
            {
                "agent": a["agent"],
                "inaccurate_rate": a["inaccurate_rate"],
                "priority": "🔴 高" if a["inaccurate_rate"] > 20 else "🟡 中" if a["inaccurate_rate"] > 10 else "🟢 低",
            }
            for a in agents[:5]
        ],
        "top_reasons": top_reasons[:5],
        "suggestion": (
            "建议优先优化 " + agents[0]["agent"] + " Agent 的 Prompt"
            if agents else "暂无足够反馈数据"
        ),
    }
