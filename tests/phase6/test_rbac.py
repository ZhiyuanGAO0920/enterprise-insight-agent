"""Phase 6: RBAC 授权测试。

需要 PostgreSQL + Redis。Windows 上 TestClient 与 async 资源存在
事件循环兼容性问题，因此共享 TestClient 实例并 mock Redis。
"""
from unittest.mock import AsyncMock, patch

import pytest

from fastapi.testclient import TestClient
from app.api.main import app

_tc = TestClient(app)  # 模块级共享，避免事件循环被销毁
def _login(u):
    r = _tc.post("/api/auth/login", json={"username": u, "password": "admin123"})
    if r.status_code != 200:
        pytest.skip(f"Login failed: {u}")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.mark.db
class TestRoleBasedAccess:
    @pytest.fixture(autouse=True)
    def _mock_redis(self):
        """Mock 所有 Redis 调用，避免 Windows asyncio 兼容性问题。"""
        with patch("app.api.dependencies.is_token_blacklisted", new=AsyncMock(return_value=False)), \
             patch("app.api.dependencies.check_rate_limit", new=AsyncMock(return_value=(True, 99))):
            yield

    def test_admin(self):
        r = _tc.get("/api/analysis/history", headers=_login("admin"))
        assert r.status_code == 200

    def test_region(self):
        r = _tc.get("/api/analysis/history", headers=_login("zhangsan"))
        assert r.status_code == 200

    def test_store(self):
        r = _tc.get("/api/analysis/history", headers=_login("lisi"))
        assert r.status_code == 200
