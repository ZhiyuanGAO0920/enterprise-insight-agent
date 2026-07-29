"""周报路由 — n8n 定时触发生成周报。"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from fastapi.responses import Response

from app.api.dependencies import require_permission
from app.config import get_settings
from app.database.connection import get_session
from app.database.models import WeeklyReport
from app.logging_config import get_logger
from app.services.notification import send_notification
from app.tools.memory import save_analysis_history
from app.workflow.graph import graph

router = APIRouter(prefix="/weekly", tags=["周报管理"])
logger = get_logger("eia.api.weekly")


class WeeklyReportItem(BaseModel):
    id: int = Field(description="周报记录 ID")
    week_start: str | None = Field(description="周起始日期")
    week_end: str | None = Field(description="周结束日期")
    summary: str = Field(description="周报摘要")
    created_at: str | None = Field(description="创建时间")


class GenerateReportResponse(BaseModel):
    status: str = Field(description="状态")
    record_id: int | None = Field(description="分析记录 ID")
    week_start: str = Field(description="周起始日期")
    week_end: str = Field(description="周结束日期")
    report_preview: str = Field(description="报告摘要预览")


@router.post("/generate", response_model=GenerateReportResponse, summary="生成周报")
async def generate_weekly_report(
    authorization: str | None = Header(None, description="Bearer <n8n_webhook_secret>"),
    settings=Depends(get_settings),
):
    """生成一周经营分析周报。

    由 n8n 定时调用（如每周一早 9:00），需传入 Webhook 密钥。
    报告涵盖销售、会员、财务三个维度的综合分析。
    """
    import hmac
    if not authorization or not hmac.compare_digest(authorization, f"Bearer {settings.n8n_webhook_secret}"):
        raise HTTPException(status_code=403, detail="Webhook 密钥无效")

    question = "生成本周经营分析周报，包含销售、会员和财务数据分析"
    system_uid = settings.system_user_id

    state = await graph.ainvoke({"question": question, "user_id": system_uid})

    report = state.get("report", "")

    if not report:
        raise HTTPException(status_code=500, detail="报告生成失败，无输出内容")

    # 使用图谱自带的 save_memory_node 生成的 record_id（避免重复保存）
    record_id = state.get("memory_record_id")
    # 兜底：save_memory 失败时直接保存
    if record_id is None:
        record_id = await save_analysis_history(
            question=question,
            report=report,
            user_id=system_uid,
            sales_result=state.get("sales_result"),
            crm_result=state.get("crm_result"),
            finance_result=state.get("finance_result"),
            reflection_passed=state.get("reflection_passed", False),
        )

    now = datetime.now(timezone.utc)  # 保留 tzinfo，确保跨时区兼容
    week_start = now - timedelta(days=now.weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)

    async with get_session() as session:
        wr = WeeklyReport(
            week_start=week_start,
            week_end=now,
            report_content=report,
            summary=report[:500] if report else "",
        )
        session.add(wr)
        await session.commit()

    # V4.1: 向已配置的 webhook 推送周报摘要
    summary_text = report[:800] if report else "本周暂无报告"
    await send_notification(
        title=f"经营周报 — {week_start.strftime('%m/%d')}-{now.strftime('%m/%d')}",
        content=f"## 本周经营周报\n\n{summary_text}\n\n> 完整报告请登录系统查看",
    )

    return {
        "status": "ok",
        "record_id": record_id,
        "week_start": week_start.isoformat(),
        "week_end": now.isoformat(),
        "report_preview": report[:300],
    }


@router.get("/reports", summary="获取历史周报列表")
async def get_weekly_reports(
    user: dict = Depends(require_permission("report:view")),
):
    """查询最近 20 条周报记录。需要 report:view 权限。"""
    async with get_session() as session:
        stmt = select(WeeklyReport).order_by(desc(WeeklyReport.created_at)).limit(20)
        result = await session.execute(stmt)
        reports = result.scalars().all()
        return [
            {
                "id": r.id,
                "week_start": r.week_start.isoformat() if r.week_start else None,
                "week_end": r.week_end.isoformat() if r.week_end else None,
                "summary": r.summary[:300] if r.summary else "",
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in reports
        ]


# ============================================================================
# V4: PDF 报告导出
# ============================================================================


class ExportRequest(BaseModel):
    report: str = Field(..., description="Markdown 格式的报告正文")
    title: str = Field("经营分析报告", description="报告标题")
    format: str = Field("pdf", description="导出格式：pdf")


@router.post("/export", summary="导出报告为 PDF")
async def export_report(
    req: ExportRequest,
    user: dict = Depends(require_permission("report:view")),
):
    """将分析报告导出为 PDF 文件。

    返回 PDF 字节流，Content-Type: application/pdf。
    需要 report:view 权限。
    """
    from app.services.pdf_exporter import export_pdf

    pdf_bytes = await export_pdf(req.report, req.title)
    if pdf_bytes is None:
        raise HTTPException(
            status_code=501,
            detail="PDF 导出功能不可用（weasyprint 未安装）。请安装: pip install -e '.[pdf]'",
        )

    # 清理文件名
    safe_title = "".join(c for c in req.title if c.isalnum() or c in "._- ")[:50]
    filename = f"{safe_title}.pdf"

    logger.info("PDF 导出成功", user_id=user["user_id"], title=req.title[:40])

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
