"""应用内金丝雀定时兜底（T-12）—— 每日 13:05 幂等触发离线评估（时间读 config，见 canary_hour/canary_minute）。

背景：n8n 2.23 对 CLI 导入工作流的 cron 注册异常（每次操作只打
"Deregistered all crons for workflow"、从不打印注册成功），金丝雀每日调度
不可依赖 n8n。本调度器在服务启动时注册 asyncio 任务，每天定时检查
eval_runs 是否已有最近 canary_interval_days 天内的 canary 记录——没有则
子进程跑 run_eval --canary --save-db（复用 eval.py 同一套引擎），已有则跳过。

幂等设计：以"最近 N 天(UTC 日期)是否有 canary 记录"为判据（EvalRun.run_at 为
naive UTC，N=canary_interval_days，默认 7 = 每周一次）。与 n8n 触发天然不冲突：
无论哪条路径先跑完，另一条都会因"已有记录"而跳过（eval.py 侧另有
_run_lock 409 并发保护）。

失败策略：子进程失败只记日志不重试（避免失败风暴），次日同刻自动再试。
超时：30 分钟 kill（对齐 eval.py 的 1800s）。
"""

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

from app.config import get_settings
from app.database.connection import get_session
from app.database.models import EvalRun
from app.logging_config import get_logger

logger = get_logger("eia.scheduler")

# app/scheduler.py → parents[1] = 仓库根（app/ 是第 1 级）
REPO_ROOT = Path(__file__).resolve().parents[1]

_run_lock = asyncio.Lock()  # 运行中不重入（与 eval.py 的 _run_lock 同一思路）


async def canary_ran_since(days: int) -> bool:
    """最近 days 天（UTC 日期）是否已有金丝雀落库记录。"""
    since = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
    session = get_session()
    try:
        res = await session.execute(
            select(func.count())
            .select_from(EvalRun)
            .where(EvalRun.canary.is_(True), EvalRun.run_at >= since)
        )
        return res.scalar() > 0
    finally:
        await session.close()


async def run_canary_now() -> bool:
    """子进程跑金丝雀评估并落库。返回是否成功。"""
    if _run_lock.locked():
        logger.info("金丝雀评估已在运行，跳过本次触发")
        return False
    async with _run_lock:
        out_dir = REPO_ROOT / "results" / "canary"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_file = out_dir / f"canary_{stamp}.json"

        # 端口：run_eval 通过 HTTP 回调本服务跑评估，默认 8002（V4 标准端口）
        settings = get_settings()
        port = getattr(settings, "app_port", None) or 8002

        proc = await asyncio.create_subprocess_exec(
            sys.executable, "tests/run_eval.py", "--canary", "--save-db",
            # T-13: 并发 8→4 —— 与 eval.py 触发路径同一折中（8 路并行争抢致临界题超时假漂移）
            "--parallel", "4", "--port", str(port), "--output", str(out_file),
            cwd=str(REPO_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=1800)
        except asyncio.TimeoutError:
            proc.kill()
            logger.error("金丝雀评估超时（>30 分钟），已终止")
            return False
        if proc.returncode != 0:
            tail = stdout.decode("utf-8", "ignore")[-800:] if stdout else ""
            logger.error("金丝雀评估失败（exit %s）：%s", proc.returncode, tail)
            return False
        logger.info("金丝雀评估完成并落库")
        return True


async def canary_scheduler_loop() -> None:
    """每日 canary_hour:canary_minute 触发金丝雀评估（幂等：最近 N 天已跑过则跳过，N=canary_interval_days）。"""
    settings = get_settings()
    hour, minute = settings.canary_hour, settings.canary_minute
    interval = settings.canary_interval_days
    logger.info("金丝雀定时任务启动（每日 %02d:%02d 检查，最近 %d 天已跑则跳过）", hour, minute, interval)
    while True:
        now = datetime.now()
        next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        await asyncio.sleep(max((next_run - now).total_seconds(), 1))
        try:
            if await canary_ran_since(interval):
                logger.info("最近 %d 天已有金丝雀记录，跳过（幂等）", interval)
                continue
            await run_canary_now()
        except Exception as e:  # noqa: BLE001 —— 定时任务必须吞掉异常，否则循环死亡
            logger.error("金丝雀定时任务异常：%s", e)


# ---------------------------------------------------------------------------
# T-16 应用内告警兜底（2026-09-14）—— n8n 单点失效的第二例，与金丝雀兜底同构
# ---------------------------------------------------------------------------
# 背景：n8n「V4 异常检测与预警」工作流自 9/2 起停止触发（9/1 14:48 为最后一次调用），
# 13 天零检测、零推送且无人发现——告警链路当时单点依赖 n8n，n8n 停了没有任何机制报警。
# 兜底逻辑：每日定点检查 audit_log 有无最近 N 小时的 /alerts/check 调用记录（n8n 触发
# 或手工触发都会留痕）；有则跳过（n8n 正常，不重复通知）；无则应用自跑检测+推送，
# 并在首次发现 n8n 停摆时推送一条提示（n8n 恢复后状态重置，不重复打扰）。

# 进程内状态：是否已就 n8n 停摆发过提示（恢复后重置；重启丢失仅意味着可能多提示一次）
_n8n_down_notified = False


async def alert_check_ran_since(hours: int) -> bool:
    """最近 hours 小时内是否有 /alerts/check 调用记录（audit_log，n8n 或手工触发）。

    判据说明：不用 alerts 表是因为 0 告警时该表不写记录——无法区分"没跑过"与"跑过没异常"；
    审计日志是端点调用的完备记录（含 n8n 的每次触发），故以它为"检测已运行"的证据。
    """
    from sqlalchemy import text

    since = datetime.utcnow() - timedelta(hours=hours)
    session = get_session()
    try:
        res = await session.execute(
            text(
                "SELECT COUNT(*) FROM audit_log "
                "WHERE resource = '/api/v1/alerts/check' AND created_at >= :since"
            ),
            {"since": since},
        )
        return res.scalar() > 0
    finally:
        await session.close()


async def run_alert_check_now() -> bool:
    """应用内执行一次告警检测，有异常则推送，并写审计记录（供幂等判据识别）。

    审计记录是必要的：兜底直接调函数、不发 HTTP，若不落痕则下次检查判据仍为
    False → 每次检查都重跑、有告警时重复推送（判据与行为自洽的关键一环）。
    """
    from sqlalchemy import text

    from app.services.notification import send_alert_notification
    from app.tools.anomaly_detector import run_alert_checks

    alerts = await run_alert_checks()
    if alerts:
        results = await send_alert_notification(alerts)
        logger.info("告警兜底检测完成：%d 项异常，推送结果 %s", len(alerts), results)
    else:
        logger.info("告警兜底检测完成：无异常")

    try:
        session = get_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO audit_log "
                    "(action, resource, detail, user_agent, status_code, created_at) "
                    "VALUES ('POST', '/api/v1/alerts/check', :detail, "
                    "'eia-scheduler-fallback', 200, :now)"
                ),
                {"detail": '{"source": "scheduler_fallback"}', "now": datetime.utcnow()},
            )
            await session.commit()
        finally:
            await session.close()
    except Exception as e:  # noqa: BLE001 —— 落痕失败不阻断检测结果（仅日志）
        logger.warning("兜底审计记录写入失败：%s", e)
    return True


async def run_alert_check_cycle(stale_hours: int) -> str:
    """单次兜底周期。返回 'skipped'（n8n 正常，跳过）或 'fallback'（已接管检测）。

    抽成独立函数以便测试：loop 只是"定时 + 调它"。
    """
    global _n8n_down_notified

    if await alert_check_ran_since(stale_hours):
        _n8n_down_notified = False  # n8n 恢复，重置停摆提示状态
        return "skipped"

    if not _n8n_down_notified:
        from app.services.notification import send_notification

        await send_notification(
            title="告警链路提示 — n8n 定时触发停摆",
            content=(
                "## n8n 告警触发已停摆\n"
                f"最近 {stale_hours} 小时未收到 n8n 的告警检测请求"
                "（/alerts/check），应用内兜底已接管每日检测与推送。\n\n"
                "请检查 n8n 工作流「V4 异常检测与预警」的调度状态。"
            ),
        )
        _n8n_down_notified = True
        logger.warning("n8n 告警触发停摆，已推送提示并由应用内兜底接管")

    await run_alert_check_now()
    return "fallback"


async def alert_scheduler_loop() -> None:
    """每日 alert_check_hour:alert_check_minute 检查告警链路（幂等：最近 N 小时已跑过则跳过）。"""
    settings = get_settings()
    hour, minute = settings.alert_check_hour, settings.alert_check_minute
    stale_hours = settings.alert_check_stale_hours
    logger.info(
        "告警兜底任务启动（每日 %02d:%02d 检查，最近 %d 小时已有检测则跳过）",
        hour, minute, stale_hours,
    )
    while True:
        # 先检查后等待：服务启动即补一次（启动晚于定点时刻也能当天覆盖），
        # 幂等判据保证不会因频繁重启重复检测/重复推送
        try:
            outcome = await run_alert_check_cycle(stale_hours)
            if outcome == "skipped":
                logger.info("最近 %d 小时已有告警检测记录，跳过（幂等）", stale_hours)
        except Exception as e:  # noqa: BLE001 —— 定时任务必须吞掉异常，否则循环死亡
            logger.error("告警兜底任务异常：%s", e)
        now = datetime.now()
        next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        await asyncio.sleep(max((next_run - now).total_seconds(), 1))
