"""SQL 安全检查器的测试。"""

import pytest

from app.tools.sql_checker import check_sql_safety


# ---------------------------------------------------------------------------
# 安全查询 —— 应通过检查
# ---------------------------------------------------------------------------

SAFE_QUERIES = [
    "SELECT * FROM orders",
    "SELECT id, name, amount FROM orders WHERE region = '华东'",
    "SELECT region, SUM(amount) AS total FROM orders GROUP BY region ORDER BY total DESC",
    "SELECT * FROM orders WHERE name LIKE '%DROP%'",  # 字面量，非关键字
    'SELECT * FROM orders WHERE status = "ACTIVE"',
    "SELECT o.id, c.name FROM orders o JOIN customers c ON o.customer_id = c.id",
    "SELECT * FROM orders LIMIT 100",
    "SELECT COUNT(*) FROM orders WHERE created_at >= '2024-01-01'",
]


@pytest.mark.parametrize("query", SAFE_QUERIES)
def test_safe_queries_pass(query: str):
    """所有安全查询都应通过安全检查。"""
    is_safe, message = check_sql_safety(query)
    assert is_safe, f"Safe query failed: {message}"


# ---------------------------------------------------------------------------
# 禁止的查询 —— 应被拦截
# ---------------------------------------------------------------------------

FORBIDDEN_QUERIES = [
    ("DROP TABLE orders", "DROP"),
    ("DELETE FROM orders WHERE id = 1", "DELETE"),
    ("UPDATE orders SET status = 'cancelled'", "UPDATE"),
    ("INSERT INTO orders VALUES (1, 'test', 100)", "INSERT"),
    ("ALTER TABLE orders ADD COLUMN new_col TEXT", "ALTER"),
    ("CREATE TABLE test (id INT)", "CREATE"),
    ("EXEC sp_dangerous", "EXEC"),
    ("TRUNCATE TABLE orders", "TRUNCATE"),
    ("SELECT * FROM orders; DROP TABLE orders", "多语句"),
]


@pytest.mark.parametrize("query,keyword", FORBIDDEN_QUERIES)
def test_forbidden_queries_blocked(query: str, keyword: str):
    """所有被禁止的查询都应该无法通过安全检查。"""
    is_safe, message = check_sql_safety(query)
    assert not is_safe, f"Query containing '{keyword}' should have been blocked"
    assert keyword.lower() in message.lower() or "multiple statements" in message.lower()


# ---------------------------------------------------------------------------
# 风险查询 —— 应被拦截
# ---------------------------------------------------------------------------

RISKY_QUERIES = [
    "SELECT * FROM orders LIMIT 50000",
    "SELECT * FROM a CROSS JOIN b",
]


@pytest.mark.parametrize("query", RISKY_QUERIES)
def test_risky_queries_blocked(query: str):
    """风险查询应该无法通过安全检查。"""
    is_safe, _ = check_sql_safety(query)
    assert not is_safe, f"Risky query should have been blocked: {query}"


# ---------------------------------------------------------------------------
# 边界情况
# ---------------------------------------------------------------------------

def test_empty_query():
    """空查询应该是安全的（虽然它是无效的 SQL）。"""
    is_safe, _ = check_sql_safety("")
    assert is_safe


def test_query_with_semicolons_in_literals():
    """字符串字面量中的分号不应触发多语句检查。"""
    is_safe, message = check_sql_safety("SELECT * FROM orders WHERE note = 'hello; world'")
    assert is_safe, f"Query with semicolon in literal failed: {message}"


def test_case_insensitivity():
    """检查应当大小写不敏感。"""
    is_safe, message = check_sql_safety("drop table orders")
    assert not is_safe
    assert "DROP" in message
