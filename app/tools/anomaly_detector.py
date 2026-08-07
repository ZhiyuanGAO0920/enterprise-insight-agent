"""异常检测 —— 根据预警阈值检查业务指标。

由 n8n 定时任务触发。将当前指标值与定义的阈值进行比较，
当检测到异常时创建 Alert 记录。
"""

from typing import Optional

from sqlalchemy import select, text

from app.database.connection import get_session
from app.database.models import Alert, AlertRule
from datetime import datetime, timezone as _tz


# ---------------------------------------------------------------------------
# 各指标专用 SQL 查询（每条返回单个标量值）
# ---------------------------------------------------------------------------

# 指标键 → 中文名（推送/展示用，客户侧不暴露英文键）
METRIC_NAMES: dict[str, str] = {
    "refund_rate": "退款率",
    "sales_growth": "销售增长率",
    "member_churn": "会员流失率",
    "member_count": "会员数量",
    "total_revenue": "总营收",
}

METRIC_QUERIES: dict[str, str] = {
    "refund_rate": """
        SELECT
            COALESCE(
                COUNT(CASE WHEN refund_amount > 0 THEN 1 END) * 100.0
                / NULLIF(COUNT(*), 0),
                0
            ) AS value
        FROM orders
        WHERE create_time >= NOW() - INTERVAL '7 days'
    """,
    "sales_growth": """
        SELECT
            COALESCE(
                (SUM(CASE WHEN create_time >= NOW() - INTERVAL '7 days' THEN amount ELSE 0 END)
                 - SUM(CASE WHEN create_time >= NOW() - INTERVAL '14 days'
                            AND create_time < NOW() - INTERVAL '7 days'
                            THEN amount ELSE 0 END))
                * 100.0
                / NULLIF(SUM(CASE WHEN create_time >= NOW() - INTERVAL '14 days'
                                   AND create_time < NOW() - INTERVAL '7 days'
                                   THEN amount ELSE 0 END), 0),
                0
            ) AS value
        FROM orders
    """,
    "member_churn": """
        SELECT
            COALESCE(
                COUNT(CASE WHEN last_consume_date < NOW() - INTERVAL '30 days'
                           THEN 1 END)
                * 100.0 / NULLIF(COUNT(*), 0),
                0
            ) AS value
        FROM member
    """,
    "member_count": """
        SELECT COUNT(*)::float AS value FROM member
    """,
    "total_revenue": """
        SELECT COALESCE(SUM(amount - refund_amount), 0)::float AS value FROM orders
    """,
}


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


async def check_metric(metric: str, threshold: float, direction: str) -> Optional[dict]:
    """根据阈值检查单个指标。

    Args:
        metric: 指标键（例如 "refund_rate"）。
        threshold: 阈值。
        direction: "above"（当值 > 阈值时预警）或 "below"（当值 < 阈值时预警）。

    Returns:
        如果触发则返回预警详情字典，否则返回 None。
    """
    query = METRIC_QUERIES.get(metric)
    if not query:
        return None

    async with get_session() as session:
        result = await session.execute(text(query))
        row = result.fetchone()
        value = float(row[0]) if row and row[0] is not None else 0.0

        triggered = (
            (value > threshold)
            if direction == "above"
            else (value < threshold)
            if direction == "below"
            else False
        )

        if triggered:
            name = METRIC_NAMES.get(metric, metric)
            return {
                "metric": metric,
                "actual_value": round(value, 2),
                "threshold": threshold,
                "direction": direction,
                "detail": (
                    f"指标 {name} 当前值 {value:.2f}，"
                    f"{'超过' if direction == 'above' else '低于'}阈值 {threshold}，已触发预警。"
                ),
            }
    return None


async def run_alert_checks() -> list[dict]:
    """检查所有启用的预警规则，为触发的规则创建 Alert 记录。

    Returns:
        已创建的预警详情字典列表。
    """
    # 加载已启用的规则
    async with get_session() as session:
        stmt = select(AlertRule).where(AlertRule.enabled == True)
        result = await session.execute(stmt)
        rules = result.scalars().all()

    alerts_created: list[dict] = []

    for rule in rules:
        alert_data = await check_metric(rule.metric, rule.threshold, rule.direction)
        if alert_data:
            # 持久化预警记录
            async with get_session() as session:
                alert = Alert(
                    rule_id=rule.id,
                    metric=rule.metric,
                    actual_value=alert_data["actual_value"],
                    threshold=rule.threshold,
                    detail=alert_data["detail"],
                    created_at=datetime.now(_tz.utc).replace(tzinfo=None),
                )
                session.add(alert)
                await session.commit()
            alerts_created.append(alert_data)

    return alerts_created
