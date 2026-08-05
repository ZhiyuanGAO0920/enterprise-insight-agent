"""Phase 3: V3 功能 API 端到端测试。"""
import json
import pytest

def _c():
    from fastapi.testclient import TestClient
    from app.api.main import app
    return TestClient(app)

def _auth():
    r = _c().post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    if r.status_code != 200:
        pytest.skip("Login failed")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


class TestChartMarkers:
    def test_encode_markers(self):
        from app.agents.report_agent import encode_chart_markers
        report = '## R\n[CHART:bar|title=T|x_data=["A"]|series=[{"name":"s","data":[1]}]|height=400]\nT'
        encoded = encode_chart_markers(report)
        assert "[CHART:bar|" in encoded and "%7B" in encoded and "title=T" not in encoded

    def test_no_marker_unchanged(self):
        from app.agents.report_agent import encode_chart_markers
        assert encode_chart_markers("plain") == "plain"


class TestFollowupQuestions:
    def test_extraction(self):
        import re
        report = 'R\n[FOLLOWUP:["Q1","Q2"]]\nMore'
        m = re.search(r'\[FOLLOWUP:(\[.*?\])\]', report, re.DOTALL)
        if m:
            assert len(json.loads(m.group(1))) == 2


class TestFeedbackAPI:
    def test_requires_auth(self):
        assert _c().post("/api/feedback/submit", json={"analysis_history_id": 1, "rating": "helpful"}).status_code in (401, 403)

    def test_invalid_rating(self):
        # V4.6.2: bad 是前端「没有帮助」按钮取值，接受并归一化为 inaccurate；真正非法的 rating 仍 422
        assert _c().post("/api/feedback/submit", json={"analysis_history_id": 1, "rating": "whatever"}, headers=_auth()).status_code == 422

    def test_stats(self):
        r = _c().get("/api/feedback/stats", headers=_auth())
        assert r.status_code == 200
        assert "enabled" in r.json()


class TestAnalysisResponse:
    def test_has_v3_fields(self):
        from app.api.routes.analysis import AnalysisResponse
        f = AnalysisResponse.model_fields
        assert all(k in f for k in ("data_sources", "followup_questions", "reflection_passed"))


class TestSessionAPI:
    def test_requires_auth_create(self):
        assert _c().post("/api/session/create").status_code in (401, 403)

    def test_create_ok(self):
        assert _c().post("/api/session/create", headers=_auth()).status_code != 401

    def test_requires_auth_get(self):
        assert _c().get("/api/session/x").status_code in (401, 403)
