"""应用内金丝雀定时兜底（T-12）—— 每日 09:30 幂等触发离线评估。

背景：n8n 2.23 对 CLI 导入工作流的 cron 注册异常（每次操作只打
"Deregistered all crons for workflow"、从不打印注册成功），金丝雀每日调度
不可依赖 n8n。本调度器在服务启动时注册 asyncio 任务，每天定时检查
eval_runs 是否已有最近 canary_interval_days 天内的 canary 记录——没有则
子进程跑 run_eval --canary --save-db（复用 eval.py 同一套引擎），已有则跳过。

幂等设计：以"最近 N 天(UTC 日期)是否有 canary 记录"为判据（EvalRun.run_at 为
naive UTC，N=canary_interval_days，默认 7 = 每周一次）。与 n8n 触发天然不冲突：
无论哪条路径先跑完，另一条都会因"已有记录"而跳过（eval.py 侧另有
_run_lock 409 并发保护）。

失败策略：子进程失败只记日志不重试（避免失败风暴），次日 09:30 自动再试。
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
            "--parallel", "8", "--port", str(port), "--output", str(out_file),
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
