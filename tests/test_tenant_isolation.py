"""V5 T-01/T-02 多租户隔离测试套件。

5 场景验证 PG RLS（路径 B）+ memory.py 检索前置校验。
需要真实 PostgreSQL（eia_app 用户，NOSUPERUSER+NOBYPASSRLS，RLS 生效）。

场景：
  1. Tenant A 查自己数据 → 返回数据（PASS）
  2. Tenant B 查 A 的数据 → 只看到 B 自己的数据（隔离）
  3. 无 tenant_id 查询 → 返回 0 行（安全失败：拒绝而非放行）
  4. SQL 注入样本复核（SET LOCAL 参数化 + int() 防注入）
  5. 跨租户向量检索隔离（memory.py 无 tenant_id → 拒绝）
"""
import pytest
import pytest_asyncio
from sqlalchemy import text

from app.database.connection import get_session, set_tenant_id

pytestmark = pytest.mark.db

TENANT_A = 1       # 现有默认租户（5000 member）
TENANT_B = 9999    # 临时测试租户（测试中创建，测试后清理）


@pytest_asyncio.fixture(autouse=True)
async def _reset_tenant_context():
    """每个测试前后清理 tenant_id contextvar，防泄漏。"""
    set_tenant_id(None)
    yield
    set_tenant_id(None)


@pytest_asyncio.fixture
async def tenant_b_data():
    """创建临时租户 B + member 数据，测试后清理。

    RLS 策略 FOR ALL（SELECT/INSERT/UPDATE/DELETE），
    eia_app 必须设置正确 tenant_id 才能插入/删除对应租户的数据。
    tenants 表无 RLS，直接操作。
    """
    # INSERT tenant（tenants 表无 RLS，不受约束）
    async with get_session() as session:
        await session.execute(text(
            "INSERT INTO tenants (id, name, slug) "
            "VALUES (:id, :name, :slug) ON CONFLICT (id) DO NOTHING"
        ), {"id": TENANT_B, "name": "Test Tenant B", "slug": "test-tenant-b"})
        await session.commit()

    # INSERT member（member 表有 RLS FOR ALL，需设 tenant_id 才能通过 WITH CHECK）
    set_tenant_id(TENANT_B)
    async with get_session() as session:
        for i in range(3):
            await session.execute(text(
                "INSERT INTO member (name, phone, tenant_id) "
                "VALUES (:name, :phone, :tid)"
            ), {"name": f"Test Member B-{i}", "phone": f"1390000000{i}", "tid": TENANT_B})
        await session.commit()
    set_tenant_id(None)

    yield

    # 清理：DELETE member（需设 tenant_id 才能通过 USING 过滤）+ tenant
    set_tenant_id(TENANT_B)
    async with get_session() as session:
        await session.execute(text("DELETE FROM member WHERE tenant_id = :tid"), {"tid": TENANT_B})
        await session.commit()
    set_tenant_id(None)

    async with get_session() as session:
        await session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": TENANT_B})
        await session.commit()


async def _count_member():
    """用当前 contextvar 的 tenant_id 查 member 数量（受 RLS 过滤）。"""
    async with get_session() as session:
        r = await session.execute(text("SELECT count(*) FROM member"))
        return r.scalar()


@pytest.mark.asyncio
async def test_scenario_1_tenant_a_sees_own_data():
    """场景 1：Tenant A 查自己数据 → 返回 5000 行（PASS）。"""
    set_tenant_id(TENANT_A)
    count = await _count_member()
    assert count == 5000, f"Tenant A 应看到 5000 条 member，实际 {count}"


@pytest.mark.asyncio
async def test_scenario_2_tenant_b_cannot_see_a_data(tenant_b_data):
    """场景 2：Tenant B 查 A 的数据 → 只看到 B 自己的 3 条（隔离）。"""
    set_tenant_id(TENANT_B)
    count = await _count_member()
    assert count == 3, f"Tenant B 应只看到自己的 3 条 member（不含 A 的 5000 条），实际 {count}"


@pytest.mark.asyncio
async def test_scenario_3_no_tenant_id_returns_zero():
    """场景 3：无 tenant_id 查询 → 返回 0 行（安全失败：拒绝而非放行）。"""
    set_tenant_id(None)
    count = await _count_member()
    assert count == 0, f"无 tenant_id 应返回 0 行（安全失败），实际 {count}"


@pytest.mark.asyncio
async def test_scenario_4_sql_injection_resistance():
    """场景 4：SQL 注入样本复核——int() 防注入，恶意值不执行。"""
    # 模拟恶意 tenant_id（SQL 注入尝试）
    set_tenant_id("1; DROP TABLE member")  # type: ignore[arg-type]
    # int() 抛 ValueError → after_begin except 捕获 → 不注入 SET LOCAL → 0 行
    count = await _count_member()
    assert count == 0, f"SQL 注入应被 int() 拦截，返回 0 行，实际 {count}"


@pytest.mark.asyncio
async def test_scenario_5_memory_search_tenant_isolation(monkeypatch):
    """场景 5：跨租户向量检索隔离——memory.py 无 tenant_id → 拒绝检索。"""
    from app.tools.memory import find_similar_analyses

    # mock get_embedding 避免依赖 Ollama（前置校验在 session 内，不执行向量查询）
    async def fake_embedding(_):
        return [0.0] * 1024
    monkeypatch.setattr("app.tools.memory.get_embedding", fake_embedding)

    # 无 user_id + 无 contextvar → 拒绝检索（返回空，不跨租户命中）
    set_tenant_id(None)
    results = await find_similar_analyses("测试查询", user_id=None)
    assert results == [], "无 tenant_id 应拒绝检索，不跨租户命中"
