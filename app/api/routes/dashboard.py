"""Dashboard 快报 API — V3 Mobile (P1-1).

提供移动端首页所需的今日经营快报数据，包括：
  - 昨日销售额
  - 活跃门店数（近 7 天有订单）
  - 近 7 天退款率
  - 总会员数
  - 近 24 小时订单数

数据按用户门店权限过滤，Redis 缓存 5 分钟。
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


@router.get("/today-summary", summary="今日经营快报")
async def today_summary(
    user: dict = Depends(require_permission("analysis:create")),
):
    """返回今日经营快报数据，按用户门店权限过滤。

    返回字段：
      - greeting: 根据当前时间生成的问候语
      - yesterday_sales: 昨日销售额
      - active_stores: 近 7 天有订单的门店数
      - week_refund_rate: 近 7 天退款率（百分比）
      - total_members: 总会员数
      - recent_orders_24h: 近 24 小时订单数
      - username: 当前用户名
      - cached_at: 缓存时间戳
    """
    store_ids = await get_user_store_ids(user["user_id"])
    username = user.get("username", user.get("sub", ""))

    # 按用户 + 门店范围生成缓存键
    store_key = 'all' if store_ids is None else (','.join(sorted(store_ids)) if store_ids else 'none')
    scope_key = hashlib.md5(
        f"{user['user_id']}:{store_key}".encode()
    ).hexdigest()[:12]
    cache_key = f"dashboard:today:{scope_key}"

    # 尝试读取缓存
    cached = await _get_cached(cache_key)
    if cached:
        cached["greeting"] = _greeting()
        cached["username"] = username
        return cached

    # 执行查询
    from app.tools.sql_runner import run_sql

    results = {}

    # 昨日销售额
    result = await run_sql(
        "SELECT COALESCE(SUM(amount), 0) AS yesterday_sales "
        "FROM orders "
        "WHERE create_time >= CURRENT_DATE - INTERVAL '1 day' "
        "AND create_time < CURRENT_DATE",
        store_ids=store_ids,
    )
    results["yesterday_sales"] = _parse_single_value(result, 0)

    # 活跃门店数（近 7 天有订单）
    result = await run_sql(
        "SELECT COUNT(DISTINCT store_id) AS active_stores "
        "FROM orders "
        "WHERE create_time >= CURRENT_DATE - INTERVAL '7 days'",
        store_ids=store_ids,
    )
    results["active_stores"] = _parse_single_value(result, 0)

    # 近 7 天退款率
    result = await run_sql(
        "SELECT CASE WHEN SUM(amount) > 0 "
        "THEN ROUND(SUM(refund_amount) * 100.0 / SUM(amount), 1) "
        "ELSE 0 END AS refund_rate "
        "FROM orders "
        "WHERE create_time >= CURRENT_DATE - INTERVAL '7 days'",
        store_ids=store_ids,
    )
    results["week_refund_rate"] = _parse_single_value(result, 0)

    # 总会员数
    result = await run_sql(
        "SELECT COUNT(*) AS total_members FROM member",
        store_ids=store_ids,
    )
    results["total_members"] = _parse_single_value(result, 0)

    # 近 24 小时订单数
    result = await run_sql(
        "SELECT COUNT(*) AS recent_orders "
        "FROM orders "
        "WHERE create_time >= NOW() - INTERVAL '24 hours'",
        store_ids=store_ids,
    )
    results["recent_orders_24h"] = _parse_single_value(result, 0)

    response = {
        "greeting": _greeting(),
        "username": username,
        **results,
        "cached_at": time.time(),
    }

    # 写入缓存
    await _set_cache(cache_key, response)

    return response


@router.get("/overview", summary="经营概览看板")
async def dashboard_overview(
    user: dict = Depends(require_permission("analysis:create")),
):
    """返回经营概览看板数据：KPI 指标、30 天趋势、门店排名、区域占比。

    所有数据按用户门店权限过滤，Redis 缓存 5 分钟。
    """
    store_ids = await get_user_store_ids(user["user_id"])
    username = user.get("username", user.get("sub", ""))

    store_key = 'all' if store_ids is None else (','.join(sorted(store_ids)) if store_ids else 'none')
    scope_key = hashlib.md5(
        f"overview:{user['user_id']}:{store_key}".encode()
    ).hexdigest()[:12]
    cache_key = f"dashboard:overview:{scope_key}"

    cached = await _get_cached(cache_key)
    if cached:
        cached["greeting"] = _greeting()
        cached["username"] = username
        return cached

    from app.tools.sql_runner import inject_store_filter as _inject
    from app.database.connection import get_session
    from sqlalchemy import text

    # Helper: only inject store filter when store_ids is not None (admin = full access)
    def _filter(sql, ids):
        if ids is not None:
            return _inject(sql, ids)
        return sql

    async def _safe_scalar(sql: str, default=0.0):
        """Execute a scalar SQL query, returning default on any error."""
        try:
            async with get_session() as session:
                r = await session.execute(text(sql))
                val = r.scalar_one()
                return float(val) if val is not None else default
        except Exception:
            return default

    async def _safe_rows(sql: str):
        """Execute a multi-row SQL query, returning ([], []) on any error."""
        try:
            async with get_session() as session:
                r = await session.execute(text(sql))
                rows = r.fetchall()
                cols = [list(x) for x in zip(*rows)] if rows else [[], []]
                return cols[0] if len(cols) > 0 else [], cols[1] if len(cols) > 1 else []
        except Exception:
            return [], []

    results = {}

    # --- 今日销售额 ---
    results["today_sales"] = await _safe_scalar(_filter(
        "SELECT COALESCE(SUM(amount), 0) FROM orders "
        "WHERE create_time >= CURRENT_DATE AND create_time < CURRENT_DATE + INTERVAL '1 day'",
        store_ids,
    ))

    # --- 昨日销售额 ---
    results["yesterday_sales"] = await _safe_scalar(_filter(
        "SELECT COALESCE(SUM(amount), 0) FROM orders "
        "WHERE create_time >= CURRENT_DATE - INTERVAL '1 day' AND create_time < CURRENT_DATE",
        store_ids,
    ))

    # --- 近 7 天退款率 ---
    results["week_refund_rate"] = await _safe_scalar(_filter(
        "SELECT CASE WHEN SUM(amount) > 0 "
        "THEN ROUND(CAST(SUM(refund_amount)*100.0/SUM(amount) AS numeric),1) "
        "ELSE 0 END FROM orders "
        "WHERE create_time >= CURRENT_DATE - INTERVAL '7 days'",
        store_ids,
    ))

    # --- 活跃门店数 ---
    results["active_stores"] = int(await _safe_scalar(_filter(
        "SELECT COUNT(DISTINCT store_id) FROM orders "
        "WHERE create_time >= CURRENT_DATE - INTERVAL '7 days'",
        store_ids,
    )))

    # --- 总会员数 ---
    sql = _filter("SELECT COUNT(*) FROM member", store_ids)
    results["total_members"] = int(await _safe_scalar(sql)) if "1=0" not in sql else 0

    # --- 近 30 天每日销售额趋势 ---
    trend_dates, trend_values = await _safe_rows(_filter(
        "SELECT TO_CHAR(create_time,'MM-DD') AS day, SUM(amount) AS daily "
        "FROM orders WHERE create_time >= CURRENT_DATE - INTERVAL '30 days' "
        "GROUP BY TO_CHAR(create_time,'MM-DD') ORDER BY MIN(create_time)",
        store_ids,
    ))
    results["trend_dates"] = trend_dates
    results["trend_values"] = [float(v or 0) for v in trend_values]

    # --- 门店销售额 Top 10 ---
    store_names, store_values = await _safe_rows(_filter(
        "SELECT s.store_name, COALESCE(SUM(o.amount),0) AS sales FROM orders o "
        "JOIN store s ON o.store_id = s.id "
        "WHERE o.create_time >= CURRENT_DATE - INTERVAL '30 days' "
        "GROUP BY s.store_name ORDER BY sales DESC LIMIT 10",
        store_ids,
    ))
    results["top_stores"] = store_names
    results["top_store_values"] = [float(v or 0) for v in store_values]

    # --- 各区域销售占比 ---
    region_names, region_values = await _safe_rows(_filter(
        "SELECT s.region, COALESCE(SUM(o.amount),0) AS sales FROM orders o "
        "JOIN store s ON o.store_id = s.id "
        "WHERE o.create_time >= CURRENT_DATE - INTERVAL '30 days' "
        "GROUP BY s.region ORDER BY sales DESC",
        store_ids,
    ))
    results["regions"] = region_names
    results["region_values"] = [float(v or 0) for v in region_values]

    response = {
        "greeting": _greeting(),
        "username": username,
        **results,
        "cached_at": time.time(),
    }
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
