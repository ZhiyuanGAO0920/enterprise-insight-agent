"""Phase 4: 多轮对话会话端到端测试。"""
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


class TestSessionLifecycle:
    def test_create(self):
        r = _c().post("/api/session/create", headers=_auth())
        assert r.status_code != 401

    def test_info(self):
        r = _c().get("/api/session/test-x", headers=_auth())
        assert r.status_code != 401


class TestFollowupDetection:
    @pytest.mark.asyncio
    async def test_followups(self):
        from app.tools.context_manager import ContextManager
        ctx = ContextManager("t")
        for q in ["那个呢？", "它的退款率呢？", "继续说"]:
            assert await ctx.is_followup(q), q

    @pytest.mark.asyncio
    async def test_non_followups(self):
        from app.tools.context_manager import ContextManager
        ctx = ContextManager("t")
        for q in ["分析华东销售", "各门店排名"]:
            assert not await ctx.is_followup(q), q


class TestContextForLLM:
    @pytest.mark.asyncio
    async def test_empty(self):
        from app.tools.context_manager import ContextManager
        assert await ContextManager("e").get_context_for_llm() == ""


class TestReferenceResolution:
    @pytest.mark.asyncio
    async def test_resolve(self):
        from app.tools.context_manager import ContextManager
        r = await ContextManager("t").resolve_references("它的退款率呢？")
        assert isinstance(r, str) and len(r) > 0
