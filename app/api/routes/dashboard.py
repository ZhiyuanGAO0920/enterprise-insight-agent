"""Dashboard 快报 API — V3 Mobile (P1-1).

提供移动端首页所需的今日经营快报数据，包括：
  - 昨日销售额
  - 活跃门店数（近 7 天有订单）
  - 近 7 天退款率
  - 总会员数
  - 近 24 小时订单数

数据按用户门店权限过滤，Redis 缓存 5 分钟。
V4.5: SQL 参数化 — 所有查询使用绑定参数替代字符串拼接。
"""

import hashlib
import json
import time

from fastapi import APIRouter, Depends

from app.api.dependencies import get_current_user, require_permission
from app.auth.rbac import get_user_store_ids
from app.database.redis import get_redis

router = APIRouter(prefix="/dashboard", tags=["经营快报"])

CACHE_TTL = 300  # 5 分钟


async def _get_cached(key: str) -> dict | None:
    """从 Redis 读取缓存。"""
    try:
        r = get_redis()
        data = await r.get(key)
        return json.loads(data) if data else None
    except Exception:
        return None


async def _set_cache(key: str, value: dict, ttl: int = CACHE_TTL) -> None:
    """写入 Redis 缓存。"""
    try:
        r = get_redis()
        await r.setex(key, ttl, json.dumps(value, ensure_ascii=False))
    except Exception:
        pass  # 缓存失败不影响主流程


# ── 参数化查询辅助函数 ──


def _build_store_params(store_ids: list[str] | None, column: str = "store_id") -> tuple[str, dict]:
    """构建参数化的门店过滤条件。

    Args:
        store_ids: 门店 ID 列表。None=无限制，[]=无门店。
        column: 用于过滤的列名（如 "store_id"、"o.store_id"、"s.id"）。

    Returns:
        (sql_fragment, params_dict) — 将 fragment 拼接到 WHERE 后，params 传给 execute()。
    """
    if store_ids is None:
        return "", {}  # 无限制
    if not store_ids:
        return "AND 1=0", {}  # 无门店访问权限
    return f"AND {column} = ANY(:store_ids)", {"store_ids": store_ids}


# ── 缓存层（统一处理问候语和用户名） ──


def _build_cache_key(prefix: str, user_id: int, store_ids: list[str] | None) -> str:
    store_key = 'all' if store_ids is None else (','.join(sorted(store_ids)) if store_ids else 'none')
    scope_key = hashlib.md5(f"{prefix}:{user_id}:{store_key}".encode()).hexdigest()[:12]
    return f"dashboard:{prefix}:{scope_key}"


def _enrich_response(response: dict, username: str) -> dict:
    response["greeting"] = _greeting()
    response["username"] = username
    return response


# ── 今日快报 ──


@router.get("/today-summary", summary="今日经营快报")
async def today_summary(
    user: dict = Depends(require_permission("analysis:create")),
):
    """返回今日经营快报数据，按用户门店权限过滤。"""
    store_ids = await get_user_store_ids(user["user_id"])
    username = user.get("username", user.get("sub", ""))

    cache_key = _build_cache_key("today", user["user_id"], store_ids)
    cached = await _get_cached(cache_key)
    if cached:
        return _enrich_response(cached, username)

    from app.tools.sql_runner import run_sql
    results = {}
    sf, sp = _build_store_params(store_ids, "store_id")  # orders.store_id
    sf_store, sp_store = _build_store_params(store_ids, "s.id")

    # V4.5: 并行执行无依赖的 SQL 查询
    import asyncio

    # Group A: orders 表独立聚合（使用 sf/sp）
    group_a = asyncio.gather(
        _safe_scalar(f"SELECT COALESCE(SUM(amount), 0) FROM orders WHERE create_time >= CURRENT_DATE AND create_time < CURRENT_DATE + INTERVAL '1 day' {sf}", sp),
        _safe_scalar(f"SELECT COALESCE(SUM(amount), 0) FROM orders WHERE create_time >= CURRENT_DATE - INTERVAL '1 day' AND create_time < CURRENT_DATE {sf}", sp),
        _safe_scalar(f"SELECT CASE WHEN SUM(amount) > 0 THEN ROUND(CAST(SUM(refund_amount)*100.0/SUM(amount) AS numeric),1) ELSE 0 END FROM orders WHERE create_time >= CURRENT_DATE - INTERVAL '7 days' {sf}", sp),
        _safe_scalar(f"SELECT COUNT(DISTINCT store_id) FROM orders WHERE create_time >= CURRENT_DATE - INTERVAL '7 days' {sf}", sp),
        _safe_scalar("SELECT COUNT(*) FROM member" if store_ids is None else "SELECT 0"),
        _safe_rows(f"SELECT TO_CHAR(create_time,'MM-DD') AS day, SUM(amount) AS daily FROM orders WHERE create_time >= CURRENT_DATE - INTERVAL '30 days' {sf} GROUP BY TO_CHAR(create_time,'MM-DD') ORDER BY MIN(create_time)", sp),
    )

    # Group B: 门店/区域维度查询（使用 sf_store/sp_store）
    group_b = asyncio.gather(
        _safe_rows(f"SELECT s.store_name, COALESCE(SUM(o.amount),0) AS sales FROM orders o JOIN store s ON o.store_id = s.id WHERE o.create_time >= CURRENT_DATE - INTERVAL '30 days' {sf_store} GROUP BY s.store_name ORDER BY sales DESC LIMIT 10", sp_store),
        _safe_rows(f"SELECT s.region, COALESCE(SUM(o.amount),0) AS sales FROM orders o JOIN store s ON o.store_id = s.id WHERE o.create_time >= CURRENT_DATE - INTERVAL '30 days' {sf_store} GROUP BY s.region ORDER BY sales DESC", sp_store),
        _safe_rows(f"SELECT s.store_name, CASE WHEN SUM(o.amount)>0 THEN ROUND(CAST(SUM(o.refund_amount)*100.0/SUM(o.amount) AS numeric),1) ELSE 0 END AS rate FROM orders o JOIN store s ON o.store_id=s.id WHERE o.create_time >= CURRENT_DATE - INTERVAL '30 days' {sf_store} GROUP BY s.store_name ORDER BY rate DESC LIMIT 10", sp_store),
    )

    # 等待所有查询完成
    (today_sales, yesterday_sales, week_refund_rate, active_stores, total_members, (trend_dates, trend_values)) = await group_a
    ((store_names, store_values), (region_names, region_values), (refund_names, refund_values)) = await group_b

    # 填充结果
    results["today_sales"] = today_sales
    results["yesterday_sales"] = yesterday_sales
    results["week_refund_rate"] = week_refund_rate
    results["active_stores"] = int(active_stores)
    results["total_members"] = int(total_members) if store_ids is None else 0
    results["trend_dates"] = trend_dates
    results["trend_values"] = [round(float(v or 0), 2) for v in trend_values]
    results["top_stores"] = store_names
    results["top_store_values"] = [round(float(v or 0), 2) for v in store_values]
    results["regions"] = region_names
    results["region_values"] = [round(float(v or 0), 2) for v in region_values]
    results["top_refund_stores"] = refund_names
    results["top_refund_values"] = [float(v or 0) for v in refund_values]
    response = {"greeting": _greeting(), "username": username, **results, "cached_at": time.time()}
    await _set_cache(cache_key, response)
    return response


# ── 经营概览看板 ──


@router.get("/overview", summary="经营概览看板")
async def dashboard_overview(
    user: dict = Depends(require_permission("analysis:create")),
):
    """返回经营概览看板数据：KPI 指标、30 天趋势、门店排名、区域占比。

    所有数据按用户门店权限过滤（参数化查询，Redis 缓存 5 分钟）。
    """
    store_ids = await get_user_store_ids(user["user_id"])
    username = user.get("username", user.get("sub", ""))

    cache_key = _build_cache_key("overview", user["user_id"], store_ids)
    cached = await _get_cached(cache_key)
    if cached:
        return _enrich_response(cached, username)

    from app.database.connection import get_session
    from sqlalchemy import text

    async def _safe_scalar(sql: str, params: dict | None = None, default=0.0):
        """执行标量查询，返回单个值。"""
        try:
            async with get_session() as session:
                r = await session.execute(text(sql), params or {})
                val = r.scalar_one()
                return round(float(val), 2) if val is not None else default
        except Exception:
            return default

    async def _safe_rows(sql: str, params: dict | None = None):
        """执行多行查询，返回 (col0_list, col1_list)。"""
        try:
            async with get_session() as session:
                r = await session.execute(text(sql), params or {})
                rows = r.fetchall()
                cols = [list(x) for x in zip(*rows)] if rows else [[], []]
                return cols[0] if len(cols) > 0 else [], cols[1] if len(cols) > 1 else []
        except Exception:
            return [], []

    results = {}
    sf, sp = _build_store_params(store_ids, "store_id")  # orders.store_id

    # --- 今日销售额 ---
    results["today_sales"] = await _safe_scalar(
        f"SELECT COALESCE(SUM(amount), 0) FROM orders "
        f"WHERE create_time >= CURRENT_DATE AND create_time < CURRENT_DATE + INTERVAL '1 day' {sf}",
        sp,
    )

    # --- 昨日销售额 ---
    results["yesterday_sales"] = await _safe_scalar(
        f"SELECT COALESCE(SUM(amount), 0) FROM orders "
        f"WHERE create_time >= CURRENT_DATE - INTERVAL '1 day' AND create_time < CURRENT_DATE {sf}",
        sp,
    )

    # --- 近 7 天退款率 ---
    results["week_refund_rate"] = await _safe_scalar(
        f"SELECT CASE WHEN SUM(amount) > 0 "
        f"THEN ROUND(CAST(SUM(refund_amount)*100.0/SUM(amount) AS numeric),1) "
        f"ELSE 0 END FROM orders "
        f"WHERE create_time >= CURRENT_DATE - INTERVAL '7 days' {sf}",
        sp,
    )

    # --- 活跃门店数 ---
    results["active_stores"] = int(await _safe_scalar(
        f"SELECT COUNT(DISTINCT store_id) FROM orders "
        f"WHERE create_time >= CURRENT_DATE - INTERVAL '7 days' {sf}",
        sp,
    ))

    # --- 总会员数（member 表不含 store_id，仅当无限制时查询，否则返回 0）---
    if store_ids is None:
        results["total_members"] = int(await _safe_scalar("SELECT COUNT(*) FROM member"))
    else:
        results["total_members"] = 0

    # --- 近 30 天每日销售额趋势 ---
    trend_dates, trend_values = await _safe_rows(
        f"SELECT TO_CHAR(create_time,'MM-DD') AS day, SUM(amount) AS daily "
        f"FROM orders WHERE create_time >= CURRENT_DATE - INTERVAL '30 days' {sf} "
        f"GROUP BY TO_CHAR(create_time,'MM-DD') ORDER BY MIN(create_time)",
        sp,
    )
    results["trend_dates"] = trend_dates
    results["trend_values"] = [round(float(v or 0), 2) for v in trend_values]

    # --- 门店销售额 Top 10（用 s.id 过滤） ---
    sf_store, sp_store = _build_store_params(store_ids, "s.id")
    store_names, store_values = await _safe_rows(
        f"SELECT s.store_name, COALESCE(SUM(o.amount),0) AS sales FROM orders o "
        f"JOIN store s ON o.store_id = s.id "
        f"WHERE o.create_time >= CURRENT_DATE - INTERVAL '30 days' {sf_store} "
        f"GROUP BY s.store_name ORDER BY sales DESC LIMIT 10",
        sp_store,
    )
    results["top_stores"] = store_names
    results["top_store_values"] = [round(float(v or 0), 2) for v in store_values]

    # --- 各区域销售占比 ---
    region_names, region_values = await _safe_rows(
        f"SELECT s.region, COALESCE(SUM(o.amount),0) AS sales FROM orders o "
        f"JOIN store s ON o.store_id = s.id "
        f"WHERE o.create_time >= CURRENT_DATE - INTERVAL '30 days' {sf_store} "
        f"GROUP BY s.region ORDER BY sales DESC",
        sp_store,
    )
    results["regions"] = region_names
    results["region_values"] = [round(float(v or 0), 2) for v in region_values]

    # --- V4.5: 门店退款率 Top 10 ---
    refund_names, refund_values = await _safe_rows(
        f"SELECT s.store_name, CASE WHEN SUM(o.amount)>0 THEN CAST(SUM(o.refund_amount)*100.0/NULLIF(SUM(o.amount),0) AS numeric(10,1)) ELSE 0 END AS rate "
        f"FROM orders o JOIN store s ON o.store_id=s.id "
        f"WHERE o.create_time >= CURRENT_DATE - INTERVAL '30 days' {sf_store} "
        f"GROUP BY s.store_name ORDER BY rate DESC LIMIT 10",
        sp_store,
    )
    results["top_refund_stores"] = refund_names
    results["top_refund_values"] = [float(v or 0) for v in refund_values]

    response = {"greeting": _greeting(), "username": username, **results, "cached_at": time.time()}
    await _set_cache(cache_key, response)
    return response


def _greeting() -> str:
    """根据当前小时生成问候语。"""
    import datetime
    hour = datetime.datetime.now().hour
    if 6 <= hour < 12:
        return "早上好"
    elif 12 <= hour < 14:
        return "中午好"
    elif 14 <= hour < 18:
        return "下午好"
    else:
        return "晚上好"


def _parse_single_value(sql_result: str, default=0) -> int | float:
    """从 run_sql 的管道分隔文本输出中提取单个数值。

    SQL 结果格式：
        header_name
        -----------
        value
    """
    if not sql_result or sql_result.startswith("[SQL_ERROR]") or sql_result == "(查询结果为空)":
        return default

    lines = sql_result.strip().split("\n")
    if len(lines) >= 3:
        value_str = lines[2].strip()
        try:
            if "." in value_str:
                return float(value_str)
            return int(value_str)
        except (ValueError, TypeError):
            return default
    return default
