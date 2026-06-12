"""SQL 执行器 —— 执行已验证的 SQL 查询并返回格式化结果。

这是 Agent 生成的 SQL 到达数据库的唯一路径。
每条查询在执行前都经过 sql_checker 检查。

行级安全（RLS）：
  当提供 store_ids 时，系统会自动在 WHERE 子句中注入
  store_id IN (...) 过滤条件，以强制执行按用户的门店访问控制。

返回字符串（永不抛出异常），以便 Agent 在遇到 [SQL_ERROR] 时可以重试。
"""

import hashlib
import json
import re
from typing import Optional

from sqlalchemy import text

from app.config import get_settings
from app.database.connection import get_session
from app.database.redis import get_redis
from app.tools.sql_checker import check_sql_safety

settings = get_settings()


# ---------------------------------------------------------------------------
# RLS —— 门店过滤注入
# ---------------------------------------------------------------------------

def _detect_store_column(sql: str) -> Optional[str]:
    """根据 SQL 中的表名自动检测 RLS 应该用哪一列。

    - 查询 store 表本身 → 用 id
    - 查询 member 表 → 不注入（会员表通常没有 store_id）
    - 其他表（orders/inventory 等）→ 用 store_id
    """
    sql_upper = sql.upper()
    # 如果主 FROM 是 store 表（且不是 JOIN store），RLS 列用 id
    if re.search(r'\bFROM\s+STORE\b', sql_upper):
        return "id"
    # 如果是纯查 member 表，不应该注入 store_id（member 表没有这个列）
    if re.search(r'\bFROM\s+MEMBER\b', sql_upper) and not re.search(r'\bJOIN\b', sql_upper):
        return None  # 不注入
    # 同样，supplier/product/purchase_order 表没有 store_id
    # 注意：employee_performance 有 store_id 列，执行 RLS 过滤
    for t in ['MEMBER', 'SUPPLIER', 'PRODUCT', 'PURCHASE_ORDER']:
        if re.search(rf'\bFROM\s+{t}\b', sql_upper) and not re.search(r'\bJOIN\b', sql_upper):
            return None
    return "store_id"


def inject_store_filter(sql: str, store_ids: list[str], store_column: str = None) -> str:
    """向 SQL WHERE 子句注入 store_id IN (...) 过滤条件。

    如果查询已有 WHERE 子句，过滤条件以 AND 追加。
    否则，WHERE 子句插入到 GROUP BY/ORDER BY/LIMIT/HAVING 之前。

    Args:
        sql: 原始 SQL 查询。
        store_ids: 允许访问的门店 ID 列表。
        store_column: 用于过滤的列名（支持 "o.store_id" 形式的别名表）。

    Returns:
        注入了 RLS 过滤条件后的 SQL。
    """
    # 找到最外层 WHERE 的位置（使用括号深度追踪，跳过子查询内的 WHERE）
    where_matches = list(re.finditer(r'\bWHERE\b', sql, re.IGNORECASE))
    outer_where_pos = -1
    if where_matches:
        depth = 0
        depth_at_pos: dict[int, int] = {}
        for i, ch in enumerate(sql):
            if ch == '(': depth += 1
            elif ch == ')': depth -= 1
            depth_at_pos[i] = depth
        best_where = where_matches[0]
        best_depth = depth_at_pos.get(best_where.start(), 0)
        for wm in where_matches:
            d = depth_at_pos.get(wm.start(), 0)
            if d <= best_depth:
                best_depth = d
                best_where = wm
        outer_where_pos = best_where.start()

    if not store_ids:
        # 用户无门店访问权限 → 强制返回空结果，防止数据泄露
        if outer_where_pos >= 0:
            return sql[:outer_where_pos] + re.sub(
                r'\bWHERE\b', 'WHERE 1=0 AND ', sql[outer_where_pos:],
                count=1, flags=re.IGNORECASE,
            )
        for keyword in ['GROUP BY', 'ORDER BY', 'LIMIT', 'HAVING']:
            if re.search(rf'\b{keyword}\b', sql, re.IGNORECASE):
                return re.sub(rf'\b{keyword}\b', f'WHERE 1=0 {keyword}', sql, count=1, flags=re.IGNORECASE)
        return sql + ' WHERE 1=0'

    # 自动检测正确的 RLS 列
    if store_column is None:
        store_column = _detect_store_column(sql)
    if store_column is None:
        return sql

    ids_str = ", ".join(f"'{s.replace(chr(39), chr(39)+chr(39))}'" for s in store_ids)
    filter_clause = f"{store_column} IN ({ids_str})"

    # 情况 1：查询有最外层 WHERE —— 插入 RLS 过滤器
    if outer_where_pos >= 0:
        return (
            sql[:outer_where_pos]
            + re.sub(
                r'\bWHERE\b',
                f"WHERE {filter_clause} AND ",
                sql[outer_where_pos:],
                count=1,
                flags=re.IGNORECASE,
            )
        )

    # 情况 2：无 WHERE —— 插入到 GROUP BY / ORDER BY / LIMIT / HAVING 之前
    for keyword in ['GROUP BY', 'ORDER BY', 'LIMIT', 'HAVING']:
        pattern = rf'\b{keyword}\b'
        if re.search(pattern, sql, re.IGNORECASE):
            return re.sub(
                pattern,
                f"WHERE {filter_clause} {keyword}",
                sql,
                count=1,
                flags=re.IGNORECASE,
            )

    # 情况 3：简单查询，无任何子句 —— 在末尾追加 WHERE
    return f"{sql.rstrip(';').rstrip()} WHERE {filter_clause}"


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


async def run_sql(
    query: str,
    max_rows: Optional[int] = None,
    store_ids: Optional[list[str]] = None,
) -> str:
    """执行 SQL 查询并以管道分隔的文本表格返回结果。

    Args:
        query: 待执行的 SQL SELECT 查询。
        max_rows: 可选的行数限制覆盖（上限为 settings.max_sql_rows）。
        store_ids: 用户可访问的门店 ID 列表。
                   None = 无限制（管理员）。空列表 = 无门店。

    Returns:
        格式化的文本表格结果，或带 [SQL_ERROR] 前缀的错误消息，
        Agent 可据此进行重试。
    """
    # ---- 1. 注入 RLS 门店过滤 ----
    if store_ids is not None:
        query = inject_store_filter(query, store_ids)

    # ---- 2. 强制最小行数限制 ----
    # LLM 倾向于添加过度保守的 LIMIT（例如 LIMIT 10）。
    # 自动提升过小的 LIMIT 以确保用户获得完整结果。
    _limit_match = re.search(r'\bLIMIT\s+(\d+)', query, re.IGNORECASE)
    if _limit_match:
        _existing = int(_limit_match.group(1))
        _min_limit = max_rows or settings.max_sql_rows
        if _existing < _min_limit:
            query = re.sub(
                r'\bLIMIT\s+\d+',
                f'LIMIT {_min_limit}',
                query,
                count=1,
                flags=re.IGNORECASE,
            )

    # ---- 3. 安全检查 ----
    is_safe, message = check_sql_safety(query)
    if not is_safe:
        return f"[SQL_ERROR] Safety check failed: {message}"

    # ---- 4. 缓存检查 ----
    cache_key = f"sql:{hashlib.md5(query.encode()).hexdigest()[:16]}"
    try:
        redis = get_redis()
        cached = await redis.get(cache_key)
        if cached:
            return cached  # decode_responses=True 已返回 str
    except Exception:
        pass  # Redis 不可用时跳过缓存

    # ---- 5. 执行 ----
    try:
        async with get_session() as session:
            result = await session.execute(text(query))
            limit = max_rows or settings.max_sql_rows
            rows = result.fetchmany(limit)

            if not rows:
                return "(查询结果为空)"

            # 格式化为管道分隔的文本表格（LLM 可以可靠地解析此格式）
            columns = list(result.keys())
            header = " | ".join(columns)
            separator = "-" * len(header)
            lines = [header, separator]
            for row in rows:
                cells = [str(cell) if cell is not None else "NULL" for cell in row]
                lines.append(" | ".join(cells))

            result_text = "\n".join(lines)

            # 写入缓存（5 分钟 TTL）
            try:
                await redis.setex(cache_key, 300, result_text)
            except Exception:
                pass

            return result_text

    except Exception as e:
        return f"[SQL_ERROR] Execution failed: {str(e)}"
