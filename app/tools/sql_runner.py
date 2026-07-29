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

import sqlparse
from sqlparse.sql import Identifier, Where, Comparison
from sqlparse.tokens import Keyword, DML, Name, Number

from sqlalchemy import text

from app.config import get_settings
from app.database.connection import get_session
from app.database.redis import get_redis
from app.tools.sql_checker import check_sql_safety

settings = get_settings()


# ---------------------------------------------------------------------------
# RLS —— 门店过滤注入
# ---------------------------------------------------------------------------

def _get_outermost_tables(sql: str) -> list[str]:
    """使用 sqlparse 提取最外层 FROM 子句中的表名（跳过子查询/CTE）。"""
    parsed = sqlparse.parse(sql)[0]
    tables = []
    # 追踪括号深度以跳过子查询
    in_cte = False
    for token in parsed.tokens:
        # 跳过 CTE (WITH ... AS)
        if token.ttype in Keyword and token.value.upper() in ('WITH',):
            in_cte = True
            continue
        if in_cte:
            if token.ttype in Keyword and token.value.upper() in ('SELECT',):
                in_cte = False
            continue
        if isinstance(token, Where):
            break  # WHERE 之后的 FROM 不是外层 FROM
        # 查找 FROM 关键字
        if token.ttype in Keyword and token.value.upper() == 'FROM':
            # FROM 后面的标识符就是表名
            idx = token.parent.token_index(token) if token.parent else -1
            if idx >= 0:
                sibling = token.parent.token_next(idx)
                while sibling:
                    t = sibling[1]
                    if t.ttype in Name or isinstance(t, Identifier):
                        tables.append(t.get_real_name() or t.value)
                        break
                    elif t.ttype in Keyword:
                        break
                    sibling = token.parent.token_next(sibling[0])
    return tables


def _detect_store_column(sql: str) -> Optional[str]:
    """根据 SQL 中的表名自动检测 RLS 应该用哪一列。

    - 查询 store 表本身 → 用 id
    - 只有 member/supplier/product/purchase_order 表（无 JOIN）→ 不注入
    - 其他表（orders/inventory 等）→ 用 store_id
    """
    tables = _get_outermost_tables(sql)
    if not tables:
        # 兜底：纯正则
        sql_upper = sql.upper()
        if re.search(r'\bFROM\s+STORE\b', sql_upper):
            return "id"
        for t in ['MEMBER', 'SUPPLIER', 'PRODUCT', 'PURCHASE_ORDER']:
            if re.search(rf'\bFROM\s+{t}\b', sql_upper) and not re.search(r'\bJOIN\b', sql_upper):
                return None
        return "store_id"

    main_table = tables[0].upper().strip('"').strip("'")
    if main_table == 'STORE':
        return "id"
    if main_table in ('MEMBER', 'SUPPLIER', 'PRODUCT', 'PURCHASE_ORDER') and len(tables) == 1:
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
    # 找到最外层 WHERE 的位置（括号深度 + 字符串字面量感知）
    # 跳过子查询内的 WHERE 和字符串字面量中的 WHERE（防 RLS 绕过）
    where_matches = list(re.finditer(r'\bWHERE\b', sql, re.IGNORECASE))
    outer_where_pos = -1
    if where_matches:
        depth = 0
        in_string = False
        depth_at_pos: dict[int, int] = {}
        i = 0
        while i < len(sql):
            ch = sql[i]
            if ch == "'" and (i == 0 or sql[i-1] != '\\'):
                # SQL 中单引号转义用 ''，跳过连续两个单引号
                if i + 1 < len(sql) and sql[i+1] == "'":
                    i += 2
                    continue
                in_string = not in_string
            if not in_string:
                if ch == '(': depth += 1
                elif ch == ')': depth -= 1
            depth_at_pos[i] = depth
            i += 1
        best_where = where_matches[0]
        best_depth = depth_at_pos.get(best_where.start(), 0)
        for wm in where_matches:
            d = depth_at_pos.get(wm.start(), 0)
            # 只选择不在字符串内的 WHERE（depth_at_pos 可能标记为 in_string 区间）
            if d <= best_depth:
                best_depth = d
                best_where = wm
        outer_where_pos = best_where.start()

    # 辅助函数：找到 WHERE 子句的结束位置（在 GROUP BY / ORDER BY / LIMIT / HAVING 之前）
    def _where_clause_end(start_pos):
        end = len(sql)
        remaining = sql[start_pos:]
        for kw in ['GROUP BY', 'ORDER BY', 'LIMIT', 'HAVING', 'UNION', 'INTERSECT', 'EXCEPT']:
            m = re.search(rf'\b{kw}\b', remaining, re.IGNORECASE)
            if m:
                pos = start_pos + m.start()
                if pos < end:
                    end = pos
        return end

    if not store_ids:
        # 用户无门店访问权限 → 强制返回空结果，防止数据泄露
        if outer_where_pos >= 0:
            where_content_start = outer_where_pos + 6
            clause_end = _where_clause_end(where_content_start)
            original = sql[where_content_start:clause_end].strip()
            return (
                sql[:outer_where_pos]
                + f"WHERE (1=0) AND ({original})"
                + sql[clause_end:]
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

    # 情况 1：查询有最外层 WHERE —— 用括号包围原始条件，防止 AND/OR 优先级绕过 RLS
    if outer_where_pos >= 0:
        where_content_start = outer_where_pos + 6
        clause_end = _where_clause_end(where_content_start)
        original = sql[where_content_start:clause_end].strip()
        return (
            sql[:outer_where_pos]
            + f"WHERE ({filter_clause}) AND ({original})"
            + sql[clause_end:]
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
    # 使用 sqlparse 找到最外层的 LIMIT（跳过子查询内的）
    _min_limit = max_rows or settings.max_sql_rows
    _parsed = sqlparse.parse(query)[0]
    _limit_found = False
    _depth = 0
    for token in _parsed.flatten():
        if token.is_group:
            continue  # 只检查非分组 token
        if token.value == '(':
            _depth += 1
        elif token.value == ')':
            _depth -= 1
        if _depth == 0 and token.ttype == Keyword and token.value.upper() == 'LIMIT':
            # 找到最外层 LIMIT，获取其下一个 token（数字）
            idx = token.parent.token_index(token) if token.parent else -1
            if idx >= 0:
                sibling = token.parent.token_next(idx)
                if sibling and sibling[1].ttype in (Name, Number.Integer):
                    try:
                        _existing = int(sibling[1].value)
                        if _existing < _min_limit:
                            sibling[1].value = str(_min_limit)
                            _limit_found = True
                    except (ValueError, TypeError):
                        pass
            break
    if _limit_found:
        query = str(_parsed)

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
