"""SQL 安全检查 —— 在 SQL 执行前验证其安全性。

在任何查询触及数据库之前运行。两层检查：
  - 禁止（FORBIDDEN）：始终拦截（DROP、DELETE、UPDATE 等）
  - 风险（RISKY）：超过阈值时拦截（CROSS JOIN、LIMIT > 10000）

在匹配前先剥离字符串字面量，避免对
类似 WHERE name LIKE '%DROP%' 的查询产生误报。
"""

import re
from typing import Callable, Tuple, Union

# ---------------------------------------------------------------------------
# 始终拦截的模式
# ---------------------------------------------------------------------------
FORBIDDEN_PATTERNS: list[Tuple[str, str]] = [
    (r";", "Multiple statements are not allowed"),
    (r"\bDROP\b", "DROP statements are not allowed"),
    (r"\bTRUNCATE\b", "TRUNCATE statements are not allowed"),
    (r"\bDELETE\b", "DELETE statements are not allowed"),
    (r"\bUPDATE\b", "UPDATE statements are not allowed"),
    (r"\bINSERT\b", "INSERT statements are not allowed"),
    (r"\bALTER\b", "ALTER statements are not allowed"),
    (r"\bCREATE\b", "CREATE statements are not allowed"),
    (r"\bEXEC\b", "EXEC statements are not allowed"),
    (r"\bEXECUTE\b", "EXECUTE statements are not allowed"),
]

# ---------------------------------------------------------------------------
# 触发警告 / 软拦截的模式
# ---------------------------------------------------------------------------
RISKY_PATTERNS: list[Tuple[str, Union[Callable[[re.Match], bool], None], str]] = [
    (r"\bCROSS JOIN\b", None, "Cross join detected — may cause cartesian product"),
    (
        r"LIMIT\s*(\d+)",
        lambda m: int(m.group(1)) > 10000,
        "LIMIT exceeds 10000 rows",
    ),
]


def check_sql_safety(sql: str) -> Tuple[bool, str]:
    """验证 SQL 查询字符串。

    返回 (is_safe, message)。如果不安全，消息会说明原因。
    调用方可以用该消息要求 Agent 重试。

    Args:
        sql: 待验证的 SQL 查询字符串。

    Returns:
        (is_safe: bool, message: str) 元组。
    """
    # 第 1 步：剥离字符串字面量以防止误报
    # 例如 "WHERE name LIKE '%DROP%'" 不应匹配 DROP 检查
    # 先处理 PostgreSQL 风格的转义单引号 '' → 哨兵字符，再剥离字符串
    _SENTINEL = "\x00"
    prepared = re.sub(r"''", _SENTINEL, sql)
    stripped = re.sub(r"'[^']*'", "''", prepared)
    stripped = re.sub(r'"[^"]*"', '""', stripped)

    # 第 2 步：检查禁止模式
    for pattern, message in FORBIDDEN_PATTERNS:
        if re.search(pattern, stripped, re.IGNORECASE):
            return False, message

    # 第 3 步：检查风险模式
    for pattern, check_fn, message in RISKY_PATTERNS:
        m = re.search(pattern, stripped, re.IGNORECASE)
        if m:
            if check_fn is None or check_fn(m):
                return False, message

    return True, "SQL passed safety check"
