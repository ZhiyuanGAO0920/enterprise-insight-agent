"""Phase 1: 认证与基础设施端到端测试。"""
import pytest

def _c():
    from fastapi.testclient import TestClient
    from app.api.main import app
    return TestClient(app)


class TestHealthChecks:
    def test_health_check(self):
        r = _c().get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_readiness_check(self):
        r = _c().get("/health/ready")
        assert r.status_code == 200
        assert r.json()["status"] in ("就绪", "降级")


pytestmark = pytest.mark.db

class TestAuth:
    def test_login_success(self):
        r = _c().post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        assert r.status_code == 200
        assert "access_token" in r.json()

    def test_login_failure(self):
        r = _c().post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        assert r.status_code == 401

    def test_login_empty_fields(self):
        r = _c().post("/api/auth/login", json={"username": "", "password": ""})
        assert r.status_code == 422


class TestTokenValidation:
    def test_no_token(self):
        r = _c().post("/api/analysis/analyze", json={"question": "test"})
        assert r.status_code in (401, 403)

    def test_invalid_token(self):
        r = _c().post("/api/analysis/analyze", json={"question": "test"},
                          headers={"Authorization": "Bearer bad-token"})
        assert r.status_code in (401, 403)

    def test_valid_token(self):
        login = _c().post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        if login.status_code != 200:
            pytest.skip("Login failed")
        token = login.json()["access_token"]
        r = _c().post("/api/analysis/analyze", json={"question": "test"},
                          headers={"Authorization": f"Bearer {token}"})
        assert r.status_code not in (401, 403)
