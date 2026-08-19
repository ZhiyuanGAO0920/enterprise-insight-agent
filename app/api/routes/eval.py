"""评估闭环路由 —— 金丝雀每周跑分（应用内定时兜底 + n8n 双保险）+ 运行历史查询。

金丝雀设计（V4.7）：
  外部 LLM 模型漂移是"无通知、渐进式"的 —— 供应商推新版本后，Prompt 输出风格可能悄悄变差。
  eval_runs 表把每次评估结果（含 model_version）落库；每周跑固定子集（eval_set.json 中
  canary=true 的 16 条，每日 09:30 兜底检查、7 天幂等窗口）与上一次同模型基线对比，
  超阈值即 drift=true，推送告警。
  本端点通过子进程调用 tests/run_eval.py --canary --save-db（复用同一套评估引擎与指标口径），
  请求为阻塞式：耗时约 3-8 分钟，n8n 模板中 httpRequest 超时需放宽到 10 分钟。
"""
import asyncio
import hmac
import sys
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.api.dependencies import require_permission
from app.config import get_settings
from app.database.connection import get_session
from app.database.models import EvalRun
from app.scheduler import canary_ran_since

router = APIRouter(prefix="/eval", tags=["评估闭环"])

# tests/run_eval.py 位于仓库根下，端点从仓库根启动子进程（与 uvicorn 启动目录一致）
REPO_ROOT = Path(__file__).resolve().parents[3]
_run_lock = asyncio.Lock()  # 并发保护：同一时间只允许一次金丝雀评估


class CanaryResponse(BaseModel):
    run_id: int | None = None
    drift: bool = False
    summary: str = ""
    model_version: str = ""
    metrics: dict | None = None


def _row_to_dict(r: EvalRun) -> dict:
    return {
        "id": r.id,
        "run_at": r.run_at.isoformat() if r.run_at else None,
        "model_version": r.model_version,
        "canary": r.canary,
        "total": r.total,
        "passed": r.passed,
        "failed": r.failed,
        "pass_rate": r.pass_rate,
        "dimension_coverage": r.dimension_coverage,
        "cross_check_rate": r.cross_check_rate,
        "sql_accuracy": r.sql_accuracy,
        "reflection_strict_pass_rate": r.reflection_strict_pass_rate,
        "reflection_effective_pass_rate": r.reflection_effective_pass_rate,
        "avg_latency_ms": r.avg_latency_ms,
        "drift": r.drift,
        "drift_summary": r.drift_summary,
        "results_file": r.results_file,
    }


@router.post("/canary", response_model=CanaryResponse, summary="运行金丝雀评估（阻塞至完成；应用内定时/ n8n 触发，7 天幂等窗口）")
async def run_canary(
    request: Request,
    authorization: str | None = Header(None, description="Bearer <n8n_webhook_secret>"),
    settings=Depends(get_settings),
):
    """子进程跑 `tests/run_eval.py --canary --save-db --parallel 8`，落库后返回漂移信号。

    响应中的 drift=true 表示与上一次同模型基线相比有显著退化（通过率 -5% / 维度覆盖率 -10%
    / 延迟 +5s / Reflection 严格通过率 -8%），n8n 据此推送告警。

    认证与 /alerts/check、/weekly/generate 一致：n8n_webhook_secret（n8n 定时触发的
    服务端到端认证，不依赖会过期的 JWT）。
    """
    # 服务端到端认证：与 alerts/weekly 触发端点同一把 webhook secret，供 n8n 调用
    if not authorization or not hmac.compare_digest(
        authorization, f"Bearer {settings.n8n_webhook_secret}"
    ):
        raise HTTPException(status_code=401, detail="无效的 webhook secret")
    # 幂等：最近 canary_interval_days 天（默认 7=每周一次）已有金丝雀记录则跳过，
    # 直接返回最近一次的信号——与 app/scheduler.py 同判据，n8n 每日触发不再重复烧配额
    if await canary_ran_since(settings.canary_interval_days):
        session = get_session()
        try:
            res = await session.execute(
                select(EvalRun).where(EvalRun.canary.is_(True)).order_by(EvalRun.run_at.desc()).limit(1)
            )
            latest = res.scalar_one_or_none()
        finally:
            await session.close()
        if latest is not None:
            return CanaryResponse(
                run_id=latest.id,
                drift=bool(latest.drift),
                summary=latest.drift_summary or "",
                model_version=latest.model_version,
                metrics=latest.metrics_json,
            )
        # 理论不可达：无记录但幂等判 True（判据本身查 eval_runs）
    if _run_lock.locked():
        raise HTTPException(status_code=409, detail="上一次金丝雀评估仍在运行，请稍后再试")
    async with _run_lock:
        out_dir = REPO_ROOT / "results" / "canary"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_file = out_dir / f"canary_{stamp}.json"

        # 用请求自身的端口回环评估（8002 被异常占用等场景下服务可临时换端口，评估仍自洽）
        port = request.base_url.port or 8002
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "tests/run_eval.py", "--canary", "--save-db",
            "--parallel", "8", "--port", str(port), "--output", str(out_file),
            cwd=str(REPO_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=1800)
        except asyncio.TimeoutError:
            proc.kill()
            raise HTTPException(status_code=504, detail="金丝雀评估超时（>30 分钟），已终止")
        if proc.returncode != 0:
            tail = stdout.decode("utf-8", "ignore")[-1200:] if stdout else ""
            raise HTTPException(status_code=500, detail=f"金丝雀评估失败（exit {proc.returncode}）：{tail}")

        session = get_session()
        try:
            res = await session.execute(select(EvalRun).order_by(EvalRun.run_at.desc()).limit(1))
            run = res.scalar_one_or_none()
        finally:
            await session.close()
        if run is None:
            raise HTTPException(status_code=500, detail="评估完成但未找到落库记录（检查 run_eval --save-db 是否生效）")
        return CanaryResponse(
            run_id=run.id,
            drift=bool(run.drift),
            summary=run.drift_summary or "",
            model_version=run.model_version,
            metrics=run.metrics_json,
        )


@router.get("/runs", summary="最近评估运行记录（趋势查看）")
async def list_runs(limit: int = 30, _: dict = Depends(require_permission("alert:view"))):
    """返回最近的评估运行记录，可观察通过率/Reflection 通过率随时间的趋势。

    权限：alert:view（与 monitor 页其他端点一致）——金丝雀趋势是监控数据，
    不是用户管理数据；user:manage 过严会导致 React 版监控页可见角色
    （admin + regional_director）中 director 被 401 清态登出（T-11 排查修复）。
    """
    limit = min(max(limit, 1), 100)
    session = get_session()
    try:
        res = await session.execute(select(EvalRun).order_by(EvalRun.run_at.desc()).limit(limit))
        return {"runs": [_row_to_dict(r) for r in res.scalars().all()]}
    finally:
        await session.close()
