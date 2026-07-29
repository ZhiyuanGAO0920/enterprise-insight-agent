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


# ---------------------------------------------------------------------------
# sqlparse 表名检测和 RLS 注入测试
# ---------------------------------------------------------------------------

from app.tools.sql_runner import _detect_store_column, _get_outermost_tables, inject_store_filter


def test_detect_store_column():
    """sqlparse 表名检测：不同表对应不同 RLS 列。"""
    assert _detect_store_column("SELECT * FROM store") == "id"
    assert _detect_store_column("SELECT * FROM orders") == "store_id"
    assert _detect_store_column("SELECT * FROM order_items") == "store_id"
    assert _detect_store_column("SELECT * FROM inventory") == "store_id"
    assert _detect_store_column("SELECT * FROM member") is None
    assert _detect_store_column("SELECT * FROM supplier") is None
    assert _detect_store_column("SELECT * FROM product") is None
    assert _detect_store_column("SELECT * FROM purchase_order") is None


def test_detect_store_column_complex():
    """复杂 SQL 的表名检测。"""
    assert _detect_store_column("SELECT * FROM member JOIN orders ON ...") is None
    assert _detect_store_column("SELECT o.id, s.name FROM orders o JOIN store s ON ...") == "store_id"
    assert _detect_store_column("SELECT * FROM orders WHERE total > 100 ORDER BY id") == "store_id"
    assert _detect_store_column("WITH cte AS (SELECT * FROM member) SELECT * FROM orders") == "store_id"


def test_detect_store_column_subquery():
    """子查询中的表不应影响外层检测。"""
    q = "SELECT * FROM (SELECT * FROM member) sub WHERE sub.id > 0"
    # A subquery around member doesn't change the RLS behavior
    result = _detect_store_column(q)
    assert result == "store_id" or result is None


def test_inject_store_filter_simple():
    """RLS 注入：基本查询。"""
    q = "SELECT * FROM orders"
    r = inject_store_filter(q, ["1", "2"])
    assert "store_id IN ('1', '2')" in r
    assert r.startswith("SELECT")


def test_inject_store_filter_with_where():
    """RLS 注入：已有 WHERE 子句。"""
    q = "SELECT * FROM orders WHERE total > 100"
    r = inject_store_filter(q, ["1", "2"])
    assert "store_id IN ('1', '2')" in r
    assert "AND" in r.upper()


def test_inject_store_filter_no_access():
    """空门店列表 → 注入 WHERE 1=0。"""
    r = inject_store_filter("SELECT * FROM orders", [])
    assert "1=0" in r


def test_inject_store_filter_member_no_filter():
    """会员表（纯查）不注入 RLS。"""
    r = inject_store_filter("SELECT * FROM member", ["1", "2"])
    assert r == "SELECT * FROM member"


def test_inject_store_filter_store_uses_id():
    """store 表用 id 列过滤。"""
    r = inject_store_filter("SELECT * FROM store", ["10", "20"])
    assert "id IN ('10', '20')" in r


def test_inject_store_filter_order_by():
    """无 WHERE 有 ORDER BY 时正确插入 RLS。"""
    r = inject_store_filter("SELECT * FROM orders ORDER BY total DESC", ["1"])
    assert "WHERE store_id IN ('1') ORDER BY" in r
