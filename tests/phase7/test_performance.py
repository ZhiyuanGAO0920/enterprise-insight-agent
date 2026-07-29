"""Phase 7: 性能测试。"""
import time
from unittest.mock import patch

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


class TestGraphPerformance:
    def test_builds_quickly(self):
        t0 = time.perf_counter()
        from app.workflow.graph import graph  # noqa
        assert time.perf_counter() - t0 < 5.0

    def test_state_fast(self):
        from app.workflow.state import AnalysisState
        t0 = time.perf_counter()
        for _ in range(100):
            AnalysisState(question="t")
        assert time.perf_counter() - t0 < 1.0


class TestSSEStreamingPerformance:
    def test_sse(self):
        with patch("app.api.routes.analysis.graph.astream") as ms, \
             patch("app.api.routes.analysis.graph.ainvoke") as mi:
            async def mock_s(state, **kw):
                yield ("updates", {"supervisor": {"activated_agents": ["sales", "crm", "finance"]}})
            ms.return_value = mock_s(state={})
            mi.return_value = {"report": "R", "reflection_passed": True,
                               "agent_errors": [], "data_sources": [], "followup_questions": []}
            r = _c().post("/api/analysis/analyze-stream", json={"question": "t"}, headers=_auth())
            assert r.status_code == 200
            assert "text/event-stream" in r.headers.get("content-type", "")


class TestConcurrency:
    def test_independent_sessions(self):
        from app.tools.context_manager import ContextManager
        a, b = ContextManager("a"), ContextManager("b")
        assert a.session_id != b.session_id


class TestPromptLoaderPerformance:
    def test_singleton_cached(self):
        from app.tools.prompt_loader import get_prompt_loader
        t0 = time.perf_counter()
        for _ in range(1000):
            get_prompt_loader()
        assert time.perf_counter() - t0 < 1.0
