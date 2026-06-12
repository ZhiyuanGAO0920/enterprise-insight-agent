"""端到端集成测试 —— 真实 PostgreSQL + DeepSeek LLM。

标记为 @pytest.mark.e2e 以跳过 conftest 中的 SQLite 覆盖。
"""
import os

import pytest

pytestmark = pytest.mark.e2e

os.environ["DATABASE_URL"] = "postgresql+asyncpg://admin:admin123@localhost:5432/enterprise_db"
os.environ["DATABASE_URL_SYNC"] = "postgresql+psycopg2://admin:admin123@localhost:5432/enterprise_db"
from app.config import get_settings
get_settings.cache_clear()


@pytest.mark.asyncio
async def test_schema_provider_with_real_db():
    """Verify schema_provider reads real PostgreSQL metadata."""
    from app.tools.schema_provider import get_table_schema
    tables = await get_table_schema()
    assert "orders" in tables
    assert "member" in tables
    print("[PASS] Schema provider: real tables detected")


@pytest.mark.asyncio
async def test_supervisor_routing():
    """Verify Supervisor activates correct agents for different questions."""
    from app.agents.supervisor_agent import supervisor_agent_node
    from app.workflow.state import AnalysisState

    # Finance-only
    s1 = await supervisor_agent_node(AnalysisState(question="退款率最高的门店是哪些"))  # type: ignore[arg-type]
    assert "finance" in s1.get("activated_agents", [])

    # Comprehensive
    s2 = await supervisor_agent_node(AnalysisState(question="分析最近整体经营情况"))  # type: ignore[arg-type]
    assert len(s2.get("activated_agents", [])) >= 2
    print("[PASS] Supervisor routing: finance={} comprehensive={}".format(
        s1.get("activated_agents"), s2.get("activated_agents")))


@pytest.mark.asyncio
async def test_graph_minimal():
    """Minimal graph test — single agent to verify pipeline works."""
    from app.workflow.graph import graph

    state = await graph.ainvoke({
        "question": "How many orders are there in the database? Answer in one sentence.",
        "user_id": None,
    })

    errors = state.get("agent_errors", [])
    # Filter out memory errors (embedding needs OpenAI key or Python 3.12 for BGE-M3)
    non_memory_errors = [e for e in errors if e.get("agent") != "memory"]
    summary = state.get("aggregator_summary", "")
    report = state.get("report", "")
    passed = state.get("reflection_passed")

    print("Errors:", len(errors), "(non-memory:", len(non_memory_errors), ")")
    print("Aggregator chars:", len(summary))
    print("Report chars:", len(report))
    print("Reflection passed:", passed)

    if errors:
        for e in errors:
            print("  [{}]: {}".format(e["agent"], e["error"][:80]))

    # Core pipeline MUST succeed
    assert len(non_memory_errors) == 0, "Core pipeline errors: {}".format(non_memory_errors)
    assert len(summary) > 0, "No aggregator output"
    assert len(report) > 0, "No report generated"
    print("[PASS] Full pipeline: supervisor -> agents -> aggregator -> report -> reflection")
