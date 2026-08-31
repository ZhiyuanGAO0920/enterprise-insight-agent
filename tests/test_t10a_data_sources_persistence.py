"""V5 T-10a：data_sources 落库 + 历史详情回查 端到端单测。

验证：save_analysis_history(data_sources=...) 持久化 → get_history_detail(record_id) 返回 data_sources，
历史分析可回查"结论当时依据什么数据"（方案 Phase 2 验收项 1）。

需要真实 PostgreSQL（使用用户表，tenant_id=1 兜底）。
"""
import pytest

from app.tools.memory import save_analysis_history, get_history_detail

pytestmark = pytest.mark.db

TEST_USER_ID = 1  # 默认 admin 用户（seed 后必存在）


@pytest.mark.asyncio
async def test_save_and_get_history_data_sources_persisted():
    """data_sources 持久化并在详情 API 正确回查。"""
    sample_ds = [
        {
            "id": 1,
            "agent": "sales",
            "sql": "SELECT store_name, SUM(amount) AS total FROM orders GROUP BY 1 ORDER BY 2 DESC LIMIT 10",
            "execution_time_ms": 42,
            "row_count": 10,
            "raw_data": "[('门店A', 125000.50), ('门店B', 98000.0), ('门店C', 75000.25)]",
        },
        {
            "id": 2,
            "agent": "crm",
            "sql": "SELECT level, COUNT(*) AS cnt FROM member GROUP BY level",
            "execution_time_ms": 15,
            "row_count": 4,
            "raw_data": "[('钻石', 300), ('黄金', 1200), ('白银', 2500), ('普通', 1000)]",
        },
    ]

    record_id = await save_analysis_history(
        question="T-10a 测试：各门店销售额和会员等级分布",
        report="门店A销售额最高(12.5万)。钻石会员300人，黄金1200人。",
        user_id=TEST_USER_ID,
        reflection_passed=True,
        sales_result="门店A=125000.5,门店B=98000",
        data_sources=sample_ds,
    )
    assert isinstance(record_id, int) and record_id > 0

    detail = await get_history_detail(record_id, user_id=TEST_USER_ID)
    assert detail is not None
    assert detail["id"] == record_id

    # data_sources 字段正确回查（非空，条数匹配，内容全量对比）
    ds = detail.get("data_sources", [])
    assert isinstance(ds, list), f"data_sources 应为 list，实际 {type(ds)}"
    assert len(ds) == len(sample_ds), f"应回 {len(sample_ds)} 条数据来源，实际 {len(ds)}"
    for i, expected in enumerate(sample_ds):
        for k in expected:
            assert ds[i][k] == expected[k], f"ds[{i}].{k} 不匹配: {ds[i].get(k)} vs {expected[k]}"


@pytest.mark.asyncio
async def test_save_empty_data_sources_returns_empty_list():
    """data_sources=None / 空列表 → 历史详情返回 []（归一化兜底）。"""
    record_id = await save_analysis_history(
        question="T-10a 空数据",
        report="无数据结论。",
        user_id=TEST_USER_ID,
        data_sources=None,
    )
    detail = await get_history_detail(record_id, user_id=TEST_USER_ID)
    assert detail.get("data_sources") == [], "None 应归一化为 []"

    record_id_2 = await save_analysis_history(
        question="T-10a 空列表",
        report="空。",
        user_id=TEST_USER_ID,
        data_sources=[],
    )
    detail_2 = await get_history_detail(record_id_2, user_id=TEST_USER_ID)
    assert detail_2.get("data_sources") == [], "[] 应返回 []"
