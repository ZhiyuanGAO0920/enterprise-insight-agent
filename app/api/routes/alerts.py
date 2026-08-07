"""预警路由 — 异常检测与预警规则管理。

POST /api/alerts/check  — n8n 定时触发异常检测
GET  /api/alerts/rules  — 查看已配置的预警规则
"""

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.dependencies import require_permission
from app.config import get_settings
from app.database.connection import get_session
from app.database.models import AlertRule
from app.services.notification import send_notification
from app.tools.anomaly_detector import METRIC_NAMES, run_alert_checks

router = APIRouter(prefix="/alerts", tags=["预警管理"])


class AlertRuleItem(BaseModel):
    id: int = Field(description="规则 ID")
    name: str = Field(description="规则名称")
    metric: str = Field(description="监控指标（如 refund_rate）")
    threshold: float = Field(description="阈值")
    direction: str = Field(description="方向：above=高于阈值触发, below=低于阈值触发")
    enabled: bool = Field(description="是否启用")
    notify_channels: list = Field(description="通知渠道（如 feishu, email）")


class AlertCheckResponse(BaseModel):
    status: str = Field(description="状态")
    alerts_created: int = Field(description="本次触发的预警数量")
    alerts: list = Field(description="预警详情列表")


@router.post("/check", response_model=AlertCheckResponse, summary="执行异常检测")
async def check_alerts(
    authorization: str | None = Header(None, description="Bearer <n8n_webhook_secret>"),
    settings=Depends(get_settings),
):
    """运行所有已启用的预警规则，检测指标异常。

    由 n8n 定时调用（如每日早 8:00），需传入 Webhook 密钥。
    检测维度包括：退款率、销售增长率、会员流失率等。

    触发预警后通过配置的通知渠道推送（飞书/邮件）。
    """
    import hmac
    if not authorization or not hmac.compare_digest(authorization, f"Bearer {settings.n8n_webhook_secret}"):
        raise HTTPException(status_code=403, detail="Webhook 密钥无效")

    alerts = await run_alert_checks()

    # V4.1: 向已配置的 webhook 发送预警通知
    if alerts:
        alert_lines = "\n".join(
            f"- **{METRIC_NAMES.get(a['metric'], a['metric'])}**: {a['actual_value']:.2f} "
            f"({'超过' if a['direction'] == 'above' else '低于'}阈值 {a['threshold']})"
            for a in alerts
        )
        await send_notification(
            title=f"经营预警 — {len(alerts)} 项指标异常",
            content=f"## 预警详情\n{alert_lines}",
        )

    return {
        "status": "ok",
        "alerts_created": len(alerts),
        "alerts": alerts,
    }


@router.get("/rules", summary="获取预警规则列表")
async def get_alert_rules(
    user: dict = Depends(require_permission("alert:view")),
):
    """查看所有已配置的预警规则。需要 alert:view 权限。

    返回每条规则的名称、监控指标、阈值、通知渠道等信息。
    """
    async with get_session() as session:
        result = await session.execute(select(AlertRule))
        rules = result.scalars().all()
        return [
            {
                "id": r.id,
                "name": r.name,
                "metric": r.metric,
                "threshold": r.threshold,
                "direction": r.direction,
                "enabled": r.enabled,
                "notify_channels": r.notify_channels,
            }
            for r in rules
        ]
