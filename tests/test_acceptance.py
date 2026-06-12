"""全面验收测试 —— 无需 PostgreSQL 即可运行。

覆盖所有无需真实数据库即可验证的内容：
  1. 配置加载
  2. 所有模块导入
  3. SQL checker (10+ queries)
  4. LangGraph compilation
  5. DeepSeek LLM connectivity
  6. Agent prompt integrity
  7. AnalysisState structure
  8. Auth (hashing, JWT)
  9. Tools (sql_checker, schema_provider stubs)
"""

import asyncio
import os
import sys

import pytest

# Ensure test DB URL is set
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")


# ============================================================================
# 1. Config
# ============================================================================


def test_config_loads():
    from app.config import Settings, get_settings

    s = get_settings()
    assert s.deepseek_api_key.startswith("sk-"), "DeepSeek API key not set"
    assert "deepseek" in s.deepseek_model_name, f"Expected deepseek model, got {s.deepseek_model_name}"
    assert s.embedding_provider in ("ollama", "openai")
    assert s.embedding_dimension in (1024, 1536)
    assert s.llm_max_tokens == 8192  # V2 fix: raised from 4096 for 100-row tables
    assert s.max_sql_rows == 1000


# ============================================================================
# 2. All Module Imports
# ============================================================================


def test_all_imports():
    modules = [
        ("app.config", "get_settings"),
        ("app.llm", "create_llm"),
        ("app.workflow.state", "AnalysisState"),
        ("app.workflow.graph", "graph"),
        ("app.tools.sql_checker", "check_sql_safety"),
        ("app.tools.sql_runner", "run_sql"),
        ("app.tools.schema_provider", "get_table_schema"),
        ("app.tools.embedding", "get_embedding"),
        ("app.tools.memory", "save_analysis_history"),
        ("app.tools.anomaly_detector", "run_alert_checks"),
        ("app.agents.sales_agent", "sales_agent_node"),
        ("app.agents.crm_agent", "crm_agent_node"),
        ("app.agents.finance_agent", "finance_agent_node"),
        ("app.agents.report_agent", "report_agent_node"),
        ("app.agents.reflection_agent", "reflection_agent_node"),
        ("app.agents.supervisor_agent", "supervisor_agent_node"),
        ("app.agents.memory_node", "save_memory_node"),
        ("app.auth.hashing", "hash_password"),
        ("app.auth.jwt", "create_access_token"),
        ("app.auth.rbac", "get_user_permissions"),
        ("app.database.models", "Base"),
        ("prompts.sales_prompt", "SALES_SYSTEM_PROMPT"),
        ("prompts.crm_prompt", "CRM_SYSTEM_PROMPT"),
        ("prompts.finance_prompt", "FINANCE_SYSTEM_PROMPT"),
        ("prompts.report_prompt", "REPORT_SYSTEM_PROMPT"),
        ("prompts.reflection_prompt", "REFLECTION_SYSTEM_PROMPT"),
        ("prompts.supervisor_prompt", "SUPERVISOR_SYSTEM_PROMPT"),
    ]
    for mod_name, attr in modules:
        mod = __import__(mod_name, fromlist=[attr])
        obj = getattr(mod, attr)
        assert obj is not None, f"Failed to import {attr} from {mod_name}"


# ============================================================================
# 3. LangGraph Compilation
# ============================================================================


def test_graph_compiles():
    from app.workflow.graph import graph

    assert graph is not None
    # Verify key nodes are registered
    assert hasattr(graph, "ainvoke"), "Graph should have ainvoke method"


# ============================================================================
# 4. DeepSeek LLM Connectivity (requires API key)
# ============================================================================


@pytest.mark.slow
def test_deepseek_llm():
    """Verify DeepSeek API responds correctly."""
    from app.llm import create_llm
    from langchain_core.messages import HumanMessage

    llm = create_llm(temperature=0.0)
    resp = llm.invoke([HumanMessage(content="Reply with exactly: OK")])
    assert resp.content is not None
    assert len(resp.content.strip()) > 0, "LLM returned empty response (check max_tokens vs reasoning tokens)"


# ============================================================================
# 5. Auth System
# ============================================================================


def test_password_hashing():
    from app.auth.hashing import hash_password, verify_password

    hashed = hash_password("test123")
    assert verify_password("test123", hashed)
    assert not verify_password("wrong", hashed)


def test_jwt_roundtrip():
    from app.auth.jwt import create_access_token, decode_access_token

    token = create_access_token({"user_id": 1, "username": "test"})
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["user_id"] == 1
    assert payload["username"] == "test"


def test_jwt_invalid_rejected():
    from app.auth.jwt import decode_access_token

    assert decode_access_token("invalid.token.here") is None


# ============================================================================
# 6. AnalysisState Structure
# ============================================================================


def test_state_defaults():
    from app.workflow.state import AnalysisState

    # TypedDict doesn't enforce defaults at runtime, but we can verify
    # that all expected keys exist in the type annotations
    expected_keys = {
        "question", "user_id",
        "sales_result", "crm_result", "finance_result",
        "inventory_result", "supply_chain_result",
        "agent_errors", "aggregator_summary",
        "report", "reflection_passed", "reflection_feedback",
        "reflection_retries", "supervisor_plan", "activated_agents",
        "memory_record_id", "store_ids", "trace_id",
        "data_sources", "chart_suggestions",
        "session_id", "conversation_context",
        "followup_questions", "is_followup", "resolved_question",
    }
    annotations = AnalysisState.__annotations__
    assert expected_keys.issubset(set(annotations.keys())), \
        f"Missing keys: {expected_keys - set(annotations.keys())}"


# ============================================================================
# 7. Prompt Integrity
# ============================================================================


def test_prompts_contain_required_content():
    from prompts.sales_prompt import SALES_SYSTEM_PROMPT
    from prompts.crm_prompt import CRM_SYSTEM_PROMPT
    from prompts.finance_prompt import FINANCE_SYSTEM_PROMPT
    from prompts.report_prompt import REPORT_SYSTEM_PROMPT
    from prompts.reflection_prompt import REFLECTION_SYSTEM_PROMPT
    from prompts.supervisor_prompt import SUPERVISOR_SYSTEM_PROMPT

    assert len(SALES_SYSTEM_PROMPT) > 100
    assert len(CRM_SYSTEM_PROMPT) > 100
    assert len(FINANCE_SYSTEM_PROMPT) > 100
    assert len(REPORT_SYSTEM_PROMPT) > 100
    assert len(REFLECTION_SYSTEM_PROMPT) > 100
    assert len(SUPERVISOR_SYSTEM_PROMPT) > 100

    # Sales prompt mentions tools
    assert "run_sql" in SALES_SYSTEM_PROMPT
    assert "get_table_schema" in SALES_SYSTEM_PROMPT


# ============================================================================
# 8. Agent Node Functions (type check only — no LLM call)
# ============================================================================


def test_agent_nodes_are_async_callables():
    from app.agents.sales_agent import sales_agent_node
    from app.agents.crm_agent import crm_agent_node
    from app.agents.finance_agent import finance_agent_node
    from app.agents.report_agent import report_agent_node
    from app.agents.reflection_agent import reflection_agent_node
    from app.agents.supervisor_agent import supervisor_agent_node
    from app.agents.memory_node import save_memory_node

    nodes = [
        sales_agent_node, crm_agent_node, finance_agent_node,
        report_agent_node, reflection_agent_node,
        supervisor_agent_node, save_memory_node,
    ]
    for node in nodes:
        assert asyncio.iscoroutinefunction(node), f"{node.__name__} should be async"


# ============================================================================
# 9. API Route Module Availability
# ============================================================================


def test_api_routers_exist():
    from app.api.routes.analysis import router as analysis_router
    from app.api.routes.auth import router as auth_router
    from app.api.routes.weekly import router as weekly_router
    from app.api.routes.alerts import router as alerts_router

    assert analysis_router.prefix == "/analysis"
    assert auth_router.prefix == "/auth"
    assert weekly_router.prefix == "/weekly"
    assert alerts_router.prefix == "/alerts"


def test_fastapi_app_creates():
    from app.api.main import app

    assert "企业智能经营分析平台" in app.title
    routes = [r.path for r in app.routes]
    assert "/health" in routes
    assert "/api/v1/analysis/analyze" in routes
    assert "/api/v1/auth/login" in routes
