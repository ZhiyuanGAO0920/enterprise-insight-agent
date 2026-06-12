"""Phase 2: 分析 API 端到端测试。"""
from unittest.mock import patch

import pytest

_tc = None

def _c():
    global _tc
    if _tc is None:
        from fastapi.testclient import TestClient
        from app.api.main import app
        _tc = TestClient(app)
    return _tc

def _auth():
    r = _c().post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    if r.status_code != 200:
        pytest.skip("Login failed")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


class TestAnalysisValidation:
    def test_empty_question(self):
        r = _c().post("/api/analysis/analyze", json={"question": ""}, headers=_auth())
        assert r.status_code == 422

    def test_missing_question(self):
        r = _c().post("/api/analysis/analyze", json={}, headers=_auth())
        assert r.status_code == 422

    def test_valid_question(self):
        with patch("app.workflow.graph.graph.ainvoke") as m:
            m.return_value = {"report": "Mock", "reflection_passed": True,
                              "agent_errors": [], "data_sources": [], "followup_questions": []}
            r = _c().post("/api/analysis/analyze", json={"question": "排名"}, headers=_auth())
            assert r.status_code == 200
            assert r.json()["report"] == "Mock"


class TestStreamingEndpoint:
    def test_stream(self):
        with patch("app.api.routes.analysis.graph.astream") as ms, \
             patch("app.api.routes.analysis.graph.ainvoke") as mi:
            async def mock_s(state, **kw):
                yield {"supervisor": {"activated_agents": ["sales"]}}
            ms.return_value = mock_s(state={})
            mi.return_value = {"report": "T", "reflection_passed": True,
                               "agent_errors": [], "data_sources": [], "followup_questions": []}
            r = _c().post("/api/analysis/analyze-stream", json={"question": "t"}, headers=_auth())
            assert r.status_code == 200
            assert "text/event-stream" in r.headers.get("content-type", "")


class TestHistoryEndpoint:
    def test_requires_auth(self):
        assert _c().get("/api/analysis/history").status_code in (401, 403)

    def test_paginated(self):
        r = _c().get("/api/analysis/history", headers=_auth())
        assert r.status_code == 200
        d = r.json()
        assert "records" in d and "page" in d
