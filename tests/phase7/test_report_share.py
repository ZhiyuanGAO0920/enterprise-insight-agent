"""Phase 7: 报告分享功能测试（只读链接）。

注：使用同步 SQLAlchemy 引擎直接插入测试记录，避免 TestClient 与
pytest-asyncio 事件循环冲突（Windows Python 3.12 已知问题）。
"""
import pytest


_client = None


def _c():
    """TestClient 单例。"""
    global _client
    if _client is None:
        from fastapi.testclient import TestClient
        from app.api.main import app
        _client = TestClient(app)
    return _client


def _req(method, url, **kw):
    """发请求并在请求后丢弃引擎引用。

    Windows + TestClient + asyncpg 已知问题：每次 TestClient 请求用新的
    asyncio.run 循环，连接池跨请求复用会绑定已关闭循环 → Event loop is closed。
    每请求后清空引擎缓存，让旧连接随 GC 丢弃（conftest 的 _force_dispose_engine 做法）。
    """
    import app.database.connection as db_conn
    try:
        return getattr(_c(), method)(url, **kw)
    finally:
        db_conn._engine = None
        db_conn._factory = None


def _auth():
    r = _req("post","/api/auth/login", json={"username": "admin", "password": "admin123"})
    if r.status_code != 200:
        pytest.skip("Login failed")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()["user_id"]


def _insert_record(question="测试问题", report=None, user_id=None):
    """用同步引擎向 analysis_history 插入一条记录，返回 record_id。

    注意：必须与 HTTP 请求使用同一数据库。connection.py 在模块加载时
    快照了 settings（PG），而 get_settings() 会被测试 fixture 切到 SQLite，
    因此这里读 connection 模块级快照的 URL。
    """
    from sqlalchemy import create_engine, select, text
    from sqlalchemy.orm import Session
    from app.database.connection import settings as _db_settings
    from app.database.models import AnalysisHistory
    engine = create_engine(_db_settings.database_url_sync)
    try:
        with Session(engine) as s:
            # analysis_history.tenant_id 有 NOT NULL 约束（迁移 007）。
            # 与 memory.py save_analysis_history 一致：用户无租户时用第一个租户兜底。
            tenant_id = s.execute(text("SELECT tenant_id FROM users WHERE id = :uid"), {"uid": user_id}).scalar()
            if tenant_id is None:
                tenant_id = s.execute(text("SELECT id FROM tenants ORDER BY id LIMIT 1")).scalar()
            rec = AnalysisHistory(
                question=question,
                report=report or "## 测试报告\n\n结论：销售平稳。",
                user_id=user_id,
                tenant_id=tenant_id,
                reflection_passed=True,
            )
            s.add(rec)
            s.commit()
            return rec.id
    finally:
        engine.dispose()


class TestShareLink:
    def test_create_requires_auth(self):
        r = _req("post","/api/analysis/share", json={"record_id": 1})
        assert r.status_code in (401, 403)

    def test_create_and_view_public(self):
        headers, uid = _auth()
        rid = _insert_record(user_id=uid)
        # 登录生成分享链接
        r = _req("post","/api/analysis/share", json={"record_id": rid}, headers=headers)
        assert r.status_code == 200
        d = r.json()
        assert d["url"].startswith("/share/")
        token = d["token"]

        # 免登录通过 token 查看
        r2 = _req("get",f"/api/analysis/share/{token}")
        assert r2.status_code == 200
        v = r2.json()
        assert v["id"] == rid
        assert v["question"] == "测试问题"
        assert "测试报告" in v["report"]

        # 分享页路由返回 HTML
        r3 = _req("get",f"/share/{token}")
        assert r3.status_code == 200
        assert "text/html" in r3.headers.get("content-type", "")

    def test_unknown_token_404(self):
        assert _req("get","/api/analysis/share/not-a-real-token").status_code == 404

    def test_revoke_then_404(self):
        headers, uid = _auth()
        rid = _insert_record(user_id=uid)
        token = _req("post","/api/analysis/share", json={"record_id": rid}, headers=headers).json()["token"]
        # 取消分享
        r = _req("delete",f"/api/analysis/share?record_id={rid}", headers=headers)
        assert r.status_code == 200
        # 原链接立即失效
        assert _req("get",f"/api/analysis/share/{token}").status_code == 404

    def test_revoke_requires_auth(self):
        assert _req("delete","/api/analysis/share?record_id=1").status_code in (401, 403)

    def test_share_other_users_record_404(self):
        """不能分享不属于自己的记录。"""
        from sqlalchemy import create_engine, text
        from app.database.connection import settings as _db_settings
        headers, uid = _auth()
        engine = create_engine(_db_settings.database_url_sync)
        try:
            with engine.connect() as conn:
                other_id = conn.execute(text("SELECT id FROM users WHERE id != :uid ORDER BY id LIMIT 1"), {"uid": uid}).scalar()
        finally:
            engine.dispose()
        if other_id is None:
            pytest.skip("无其他用户，无法测试跨用户分享")
        rid = _insert_record(user_id=other_id)
        r = _req("post","/api/analysis/share", json={"record_id": rid}, headers=headers)
        assert r.status_code == 404
