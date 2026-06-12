"""Phase 5: 错误恢复测试。"""

_tc = None
def _c():
    global _tc
    if _tc is None:
        from fastapi.testclient import TestClient
        from app.api.main import app
        _tc = TestClient(app)
    return _tc


class TestFriendlyErrorMessages:
    def test_auth(self):
        from app.errors.user_friendly import _match_error
        r = _match_error("invalid username or password")
        assert r and "用户名或密码" in r["user_message"] and r["action"] == "retry_login"

    def test_token(self):
        from app.errors.user_friendly import _match_error
        r = _match_error("token has expired please re-login")
        assert r and "登录已过期" in r["user_message"]

    def test_sql(self):
        from app.errors.user_friendly import _match_error
        r = _match_error("column 'status' does not exist")
        assert r and "自动调整" in r["user_message"]

    def test_table(self):
        from app.errors.user_friendly import _match_error
        r = _match_error("relation 'orders_new' does not exist")
        assert r and "数据表未找到" in r["user_message"]

    def test_syntax(self):
        from app.errors.user_friendly import _match_error
        r = _match_error("syntax error in SQL statement")
        assert r and "自动修正" in r["user_message"]

    def test_connection(self):
        from app.errors.user_friendly import _match_error
        r = _match_error("connection refused by server")
        assert r and "暂时无法连接" in r["user_message"]

    def test_timeout(self):
        from app.errors.user_friendly import _match_error
        r = _match_error("connection timed out after 30 seconds")
        assert r and "超时" in r["user_message"]

    def test_permission(self):
        from app.errors.user_friendly import _match_error
        r = _match_error("403 Forbidden")
        assert r and "没有权限" in r["user_message"]

    def test_rate_limit(self):
        from app.errors.user_friendly import _match_error
        r = _match_error("Rate limit exceeded for this endpoint")
        assert r and "太频繁" in r["user_message"]

    def test_unknown(self):
        from app.errors.user_friendly import _match_error
        assert _match_error("xyz unknown abc") is None

    def test_fallback(self):
        from app.errors.user_friendly import to_user_message
        r = to_user_message("err")
        assert "user_message" in r and "action" in r

    def test_format(self):
        from app.errors.user_friendly import format_agent_errors
        r = format_agent_errors([{"agent": "sales", "error": "column 'x' does not exist"}])
        assert len(r) == 1 and "user_message" in r[0]


class TestAgentErrorIsolation:
    def test_errors_field(self):
        from app.workflow.state import AnalysisState
        assert "agent_errors" in AnalysisState.__annotations__


class Test404Handling:
    def test_404(self):
        assert _c().get("/api/nonexistent").status_code == 404
