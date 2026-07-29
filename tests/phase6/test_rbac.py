"""Phase 6: RBAC 授权测试。

需要 PostgreSQL + Redis。
"""
from unittest.mock import AsyncMock, patch

import pytest

def _c():
    from fastapi.testclient import TestClient
    from app.api.main import app
    return TestClient(app)


def _login(u):
    r = _c().post("/api/auth/login", json={"username": u, "password": "admin123"})
    if r.status_code != 200:
        pytest.skip(f"Login failed: {u}")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.mark.db
class TestRoleBasedAccess:
    @pytest.fixture(autouse=True)
    def _mock_redis(self):
        with patch("app.api.dependencies.is_token_blacklisted", new=AsyncMock(return_value=False)), \
             patch("app.api.dependencies.check_rate_limit", new=AsyncMock(return_value=(True, 99))):
            yield

    def test_admin(self):
        r = _c().get("/api/analysis/history", headers=_login("admin"))
        assert r.status_code == 200

    def test_region(self):
        r = _c().get("/api/analysis/history", headers=_login("zhangsan"))
        assert r.status_code == 200

    def test_store(self):
        r = _c().get("/api/analysis/history", headers=_login("lisi"))
        assert r.status_code == 200
