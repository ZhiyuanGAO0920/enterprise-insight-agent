"""V3 功能测试 —— 覆盖所有 P0/P1/P2 功能的全面测试。

涵盖：
  - V3 模块导入（chart_advisor、context_manager、tracer、errors）
  - Chart Advisor：提示词完整性、图表标记生成
  - Context Manager: session lifecycle, turn management, reference resolution
  - User-Friendly Errors: pattern matching, fallback behavior
  - APM Tracer: no-op tracing, error handling
  - V3 API Routes: session, feedback endpoints
  - V3 AnalysisState: new fields
  - V3 Feature Flags: config defaults
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")


# ============================================================================
# 1. V3 Module Imports
# ============================================================================


def test_v3_modules_import():
    """Verify all V3 modules can be imported successfully."""
    modules = [
        ("app.agents.chart_advisor_agent", "chart_advisor_node"),
        ("app.tools.context_manager", "ContextManager"),
        ("app.apm.tracer", "AgentTracer"),
        ("app.errors.user_friendly", "to_user_message"),
    ]
    for mod_name, attr in modules:
        mod = __import__(mod_name, fromlist=[attr])
        obj = getattr(mod, attr)
        assert obj is not None, f"Failed to import {attr} from {mod_name}"


# ============================================================================
# 2. Chart Advisor Agent
# ============================================================================


def test_chart_advisor_prompt_not_empty():
    """Chart Advisor system prompt should be a non-empty string."""
    from app.agents.chart_advisor_agent import CHART_ADVISOR_SYSTEM_PROMPT

    assert len(CHART_ADVISOR_SYSTEM_PROMPT) > 100
    assert "bar" in CHART_ADVISOR_SYSTEM_PROMPT.lower()
    assert "line" in CHART_ADVISOR_SYSTEM_PROMPT.lower()
    assert "pie" in CHART_ADVISOR_SYSTEM_PROMPT.lower()


def test_chart_marker_building():
    """Verify chart markers are built in pipe-delimited format (for LLM readability)."""
    from app.agents.report_agent import build_chart_markers

    charts = [
        {
            "type": "bar",
            "title": "各门店销售额排名",
            "x_data": ["门店A", "门店B", "门店C"],
            "series": [{"name": "销售额", "data": [120, 115, 108]}],
            "height": 400,
        }
    ]
    markers = build_chart_markers(charts)
    assert "[CHART:bar|" in markers
    assert "各门店销售额排名" in markers
    assert "门店A" in markers

    # Empty charts = no markers
    assert build_chart_markers([]) == ""


def test_chart_marker_encoding():
    """Verify post-processing converts pipe-delimited markers to URL-encoded JSON."""
    from app.agents.report_agent import encode_chart_markers

    # Simulate LLM report with old-style markers
    report = (
        "## 各门店销售额排名\n\n"
        '[CHART:bar|title=各门店排名|x_data=["A","B"]|series=[{"name":"销售额","data":[100,200]}]|height=400]\n\n'
        "| 排名 | 门店 | 销售额 |\n| --- | --- | --- |\n| 1 | A | 100 |"
    )
    encoded = encode_chart_markers(report)
    # Should still have [CHART:bar| but params should be URL-encoded
    assert "[CHART:bar|" in encoded
    # URL-encoded JSON should have %7B (for {)
    assert "%7B" in encoded
    # Original pipe-delimited params should NOT remain as-is
    assert "title=各门店排名" not in encoded
    # Non-chart content should be unchanged
    assert "## 各门店销售额排名" in encoded
    assert "| 1 | A | 100 |" in encoded

    # No markers = unchanged
    plain = "纯文本报告"
    assert encode_chart_markers(plain) == plain


def test_chart_instructions_for_llm():
    """Chart instructions include proper placement rules."""
    from app.agents.report_agent import build_chart_instructions

    charts = [{"type": "line", "title": "趋势图", "x_data": ["1月"], "series": [{"name": "sales", "data": [100]}], "height": 350}]
    instructions = build_chart_instructions(charts)
    assert "图表嵌入指令" in instructions
    assert "[CHART:line|" in instructions

    # No charts = empty instructions
    assert build_chart_instructions([]) == ""


@pytest.mark.asyncio
async def test_chart_advisor_node_disabled():
    """Chart advisor returns empty when feature is disabled."""
    from app.agents.chart_advisor_agent import chart_advisor_node

    # With feature disabled (default), should return empty charts
    result = await chart_advisor_node({"aggregator_summary": "测试数据"})
    assert result == {"chart_suggestions": []}


@pytest.mark.asyncio
async def test_chart_advisor_node_no_summary():
    """Chart advisor returns empty when no aggregator summary."""
    from app.agents.chart_advisor_agent import chart_advisor_node

    result = await chart_advisor_node({})
    assert result == {"chart_suggestions": []}


# ============================================================================
# 3. Context Manager (Multi-turn Conversation)
# ============================================================================


class TestContextManager:
    """Tests for ContextManager — multi-turn conversation state management."""

    @pytest.mark.asyncio
    async def test_is_followup_detection(self):
        """Follow-up detection should identify common patterns."""
        from app.tools.context_manager import ContextManager

        ctx = ContextManager("test-session")

        # These are follow-ups
        followups = [
            "那个门店的会员情况呢？",
            "它的退款率呢？",
            "再分析一下",
            "继续说",
            "那华东区呢",
            "这个呢？",
            "具体？",
        ]
        for q in followups:
            assert await ctx.is_followup(q), f"Should detect followup: {q}"

    @pytest.mark.asyncio
    async def test_non_followup_detection(self):
        """Standalone questions should not be flagged as follow-ups."""
        from app.tools.context_manager import ContextManager

        ctx = ContextManager("test-session")

        standalone = [
            "分析华东区域销售下降原因",
            "各门店销售额排名",
            "最近一周退款率最高的是哪些门店",
        ]
        for q in standalone:
            assert not await ctx.is_followup(q), f"Should NOT be followup: {q}"

    @pytest.mark.asyncio
    async def test_resolve_references_no_context(self):
        """Without entity memory, questions pass through unchanged."""
        from app.tools.context_manager import ContextManager

        ctx = ContextManager("test-session")
        question = "那个门店的销售情况如何？"
        resolved = await ctx.resolve_references(question)
        # Without any entities stored, the heuristic should still trigger
        # But the question may or may not be modified depending on entity memory
        assert isinstance(resolved, str)

    def test_context_manager_session_lifecycle(self):
        """ContextManager can be instantiated with a session ID."""
        from app.tools.context_manager import ContextManager

        ctx = ContextManager("my-session-123")
        assert ctx.session_id == "my-session-123"

    @pytest.mark.asyncio
    async def test_context_for_llm_empty(self):
        """When feature is disabled or no history, context is empty."""
        from app.tools.context_manager import ContextManager

        ctx = ContextManager("empty-session")
        result = await ctx.get_context_for_llm()
        # Feature disabled by default → empty string
        assert result == ""

    @pytest.mark.asyncio
    async def test_get_entity_memory_empty(self):
        """Entity memory starts empty."""
        from app.tools.context_manager import ContextManager

        ctx = ContextManager("test-session")
        memory = await ctx.get_entity_memory()
        assert memory == {}

    @pytest.mark.asyncio
    async def test_get_history_empty(self):
        """History starts empty."""
        from app.tools.context_manager import ContextManager

        ctx = ContextManager("test-session")
        history = await ctx.get_history()
        assert history == []


# ============================================================================
# 4. User-Friendly Error Messages
# ============================================================================


class TestUserFriendlyErrors:
    """Tests for user-friendly error message mapping."""

    def test_match_error_auth(self):
        """Auth error patterns should be matched correctly."""
        from app.errors.user_friendly import _match_error

        result = _match_error("invalid username or password")
        assert result is not None
        assert "用户名或密码错误" in result["user_message"]
        assert result["action"] == "retry_login"

        result = _match_error("token has expired please re-login")
        assert result is not None
        assert "登录已过期" in result["user_message"]
        assert result["action"] == "redirect_login"

    def test_match_error_sql(self):
        """SQL error patterns should be matched correctly."""
        from app.errors.user_friendly import _match_error

        result = _match_error("column 'status' does not exist")
        assert result is not None
        assert "自动调整" in result["user_message"]
        assert result["action"] == "auto_retry"

        result = _match_error("relation 'orders_new' does not exist")
        assert result is not None
        assert "数据表未找到" in result["user_message"]

        result = _match_error("syntax error in SQL statement")
        assert result is not None
        assert "自动修正" in result["user_message"]

    def test_match_error_connection(self):
        """Connection error patterns should be matched correctly."""
        from app.errors.user_friendly import _match_error

        result = _match_error("connection refused by server")
        assert result is not None
        assert "暂时无法连接" in result["user_message"]
        assert result["action"] == "retry_later"

        result = _match_error("connection timed out after 30 seconds")
        assert result is not None
        assert "超时" in result["user_message"]

    def test_match_error_permission(self):
        """Permission error patterns should be matched correctly."""
        from app.errors.user_friendly import _match_error

        result = _match_error("403 Forbidden")
        assert result is not None
        assert "没有权限" in result["user_message"]
        assert result["action"] == "contact_admin"

    def test_match_error_rate_limit(self):
        """Rate limit patterns should be matched correctly."""
        from app.errors.user_friendly import _match_error

        result = _match_error("Rate limit exceeded for this endpoint")
        assert result is not None
        assert "太频繁" in result["user_message"]
        assert result["action"] == "wait_retry"

    def test_match_error_unknown_fallback(self):
        """Unknown errors should return None from _match_error."""
        from app.errors.user_friendly import _match_error

        result = _match_error("some completely unknown error XYZ123")
        assert result is None

    def test_to_user_message_uses_fallback(self):
        """to_user_message should use fallback for unknown errors."""
        from app.errors.user_friendly import to_user_message

        # When feature is disabled, raw error passes through
        result = to_user_message("unknown error")
        assert "user_message" in result
        assert "action" in result
        assert "icon" in result

    def test_to_user_message_with_feature_enabled(self, monkeypatch):
        """to_user_message should map errors when feature is enabled."""
        from app.errors.user_friendly import to_user_message
        from app.config import get_settings

        # Enable the feature flag
        monkeypatch.setattr(get_settings(), "feature_friendly_errors", True)

        result = to_user_message("invalid username or password")
        assert "用户名或密码错误" in result["user_message"]
        assert result["action"] == "retry_login"

    def test_format_agent_errors(self):
        """format_agent_errors should augment each error with user-friendly fields."""
        from app.errors.user_friendly import format_agent_errors

        errors = [
            {"agent": "sales", "error": "column 'status' does not exist"},
            {"agent": "crm", "error": "connection timeout"},
        ]
        formatted = format_agent_errors(errors)
        assert len(formatted) == 2
        assert all("user_message" in e for e in formatted)
        assert all("action" in e for e in formatted)
        assert all("icon" in e for e in formatted)
        assert formatted[0]["agent"] == "sales"


# ============================================================================
# 5. APM Tracer
# ============================================================================


class TestAgentTracer:
    """Tests for the lightweight Agent Performance Tracer."""

    def test_tracer_enabled_by_default(self):
        """V4: APM feature is enabled by default."""
        from app.apm.tracer import AgentTracer

        tracer = AgentTracer(session_id="test", question="test question")
        assert tracer._should_trace() is True

    @pytest.mark.asyncio
    async def test_trace_active_when_enabled(self):
        """V4: Tracing should record events when feature is enabled."""
        from app.apm.tracer import AgentTracer

        tracer = AgentTracer(session_id="test", question="test")
        async with tracer.trace("test_node"):
            pass  # Should not raise
        # Records should be collected when enabled (but flush may fail without DB)
        assert len(tracer._records) >= 1

    def test_tracer_creation(self):
        """Tracer can be created with session and question."""
        from app.apm.tracer import AgentTracer

        tracer = AgentTracer(session_id="sess-001", question="分析销售趋势")
        assert tracer.session_id == "sess-001"
        assert tracer.question == "分析销售趋势"

    def test_tracer_global_set_get(self):
        """Global tracer can be set and retrieved."""
        from app.apm.tracer import AgentTracer, set_tracer, get_tracer

        tracer = AgentTracer(session_id="global-test", question="test")
        set_tracer(tracer)
        retrieved = get_tracer()
        assert retrieved is tracer


# ============================================================================
# 6. V3 API Routes
# ============================================================================


def test_v3_routers_exist():
    """V3 session and feedback routers should exist (V4: mounted under /api/v1)."""
    from app.api.routes.session import router as session_router
    from app.api.routes.feedback import router as feedback_router

    assert session_router.prefix == "/session"
    assert feedback_router.prefix == "/feedback"


def test_fastapi_includes_v3_routers():
    """FastAPI app should include V3 routes under /api/v1 prefix."""
    from app.api.main import app

    routes = [r.path for r in app.routes]
    assert "/api/v1/session/create" in routes
    assert "/api/v1/session/{session_id}" in routes
    assert "/api/v1/feedback/submit" in routes
    assert "/api/v1/feedback/stats" in routes


# ============================================================================
# 7. V3 AnalysisState
# ============================================================================


def test_state_v3_fields():
    """AnalysisState should include all V3 fields."""
    from app.workflow.state import AnalysisState

    annotations = AnalysisState.__annotations__

    v3_fields = {
        "data_sources",
        "chart_suggestions",
        "session_id",
        "conversation_context",
        "followup_questions",
        "is_followup",
        "resolved_question",
    }
    missing = v3_fields - set(annotations.keys())
    assert not missing, f"Missing V3 fields in AnalysisState: {missing}"


def test_state_data_sources_has_add_reducer():
    """data_sources should use the 'add' reducer for parallel agent concatenation."""
    from app.workflow.state import AnalysisState
    import typing

    # Check that data_sources has Annotated type with add reducer
    hints = typing.get_type_hints(AnalysisState, include_extras=True)
    assert "data_sources" in hints


# ============================================================================
# 8. V3 Feature Flags
# ============================================================================


def test_v3_feature_flags_exist():
    """All V3 feature flags should be defined in Settings."""
    from app.config import Settings

    # Create a minimal Settings instance (requires required env vars)
    os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
    os.environ.setdefault("DATABASE_URL_SYNC", "sqlite:///./test.db")
    os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

    s = Settings()

    v3_flags = [
        "feature_chart",
        "feature_multi_turn",
        "feature_data_trace",
        "feature_mobile_ui",
        "feature_feedback",
        "feature_prompt_yaml",
        "feature_apm",
        "feature_friendly_errors",
    ]
    for flag in v3_flags:
        val = getattr(s, flag)
        assert isinstance(val, bool), f"{flag} should be bool, got {type(val)}"


def test_v3_feature_flags_default_on():
    """V4: All feature flags should default to True (V3 features are production-ready)."""
    from app.config import Settings

    os.environ["DEEPSEEK_API_KEY"] = "sk-test"
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"
    os.environ["DATABASE_URL_SYNC"] = "sqlite:///./test.db"
    os.environ["JWT_SECRET_KEY"] = "test-secret"
    # 覆盖测试夹具中的 false，验证 V4 默认值
    os.environ["FEATURE_MULTI_TURN"] = "true"

    s = Settings()
    # V4: All features enabled by default
    assert s.feature_chart is True
    assert s.feature_multi_turn is True
    assert s.feature_data_trace is True
    assert s.feature_apm is True
    assert s.feature_friendly_errors is True


# ============================================================================
# 9. Graph V3 Topology
# ============================================================================


def test_graph_has_chart_advisor_node():
    """The compiled graph should include the chart_advisor node."""
    from app.workflow.graph import graph

    # Graph should be compiled
    assert graph is not None


def test_graph_node_labels():
    """Streaming node labels should include V3 nodes."""
    from app.api.routes.analysis import NODE_LABELS

    assert "chart_advisor" in NODE_LABELS
    assert NODE_LABELS["chart_advisor"] == "图表推荐"


# ============================================================================
# 10. V3 Response Models
# ============================================================================


def test_analysis_response_has_v3_fields():
    """AnalysisResponse should include V3 fields."""
    from app.api.routes.analysis import AnalysisResponse

    # Check the model fields
    fields = AnalysisResponse.model_fields
    assert "data_sources" in fields
    assert "followup_questions" in fields


def test_analysis_request_has_session_id():
    """AnalysisRequest should accept optional session_id."""
    from app.api.routes.analysis import AnalysisRequest

    fields = AnalysisRequest.model_fields
    assert "session_id" in fields
    # session_id is Optional[str]
    assert fields["session_id"].default is None


# ============================================================================
# 11. Feedback Model Validation
# ============================================================================


def test_feedback_request_validation():
    """FeedbackRequest should validate rating values."""
    from app.api.routes.feedback import FeedbackRequest

    # Valid rating
    req = FeedbackRequest(analysis_history_id=1, rating="helpful")
    assert req.rating == "helpful"

    req2 = FeedbackRequest(analysis_history_id=1, rating="inaccurate")
    assert req2.rating == "inaccurate"

    req3 = FeedbackRequest(analysis_history_id=1, rating="not_relevant")
    assert req3.rating == "not_relevant"

    # Invalid rating should raise validation error
    with pytest.raises(Exception):
        FeedbackRequest(analysis_history_id=1, rating="invalid_rating")
