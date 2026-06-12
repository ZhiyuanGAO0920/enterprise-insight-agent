"""所有测试模块共享的 pytest 夹具。"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine, text


def _is_postgres_available() -> bool:
    """检测真实的 PostgreSQL 数据库是否可用。

    使用 pydantic-settings 从 .env 读取 DATABASE_URL_SYNC，
    而非 os.environ.get()（pydantic-settings 不会将配置写入环境变量）。
    """
    try:
        from app.config import get_settings
        db_url = get_settings().database_url_sync
        engine = create_engine(db_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


POSTGRES_AVAILABLE = _is_postgres_available()


@pytest.fixture(scope="session")
def event_loop():
    """创建会话级事件循环供异步测试使用。"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_openai_client():
    """Mock OpenAI 客户端，避免在测试中进行真实的 API 调用。"""
    with patch("openai.AsyncOpenAI") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.fixture
def mock_db_session():
    """提供模拟的异步数据库会话。"""
    session = AsyncMock()
    return session


@pytest.fixture(scope="session", autouse=True)
def _create_test_tables():
    """在 SQLite 测试数据库中创建所有表（会话级，仅执行一次）。"""
    from app.database.models import Base
    db_url = os.environ.get("DATABASE_URL_SYNC", "sqlite:///./test.db")
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def _use_test_db(request):
    """强制测试使用测试数据库 URL，除非标记为 'e2e' 或 'db'。"""
    if request.node.get_closest_marker("e2e"):
        return
    if request.node.get_closest_marker("db"):
        if not POSTGRES_AVAILABLE:
            pytest.skip("PostgreSQL 不可用 — 跳过需要数据库的测试")
        return
    os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL_TEST", "sqlite+aiosqlite:///./test.db")
    os.environ["DATABASE_URL_SYNC"] = os.environ.get("DATABASE_URL_TEST", "sqlite+aiosqlite:///./test.db").replace(
        "sqlite+aiosqlite:///", "sqlite:///"
    )
    # 测试环境禁用多轮对话，避免 Redis 异步事件循环清理问题
    os.environ["FEATURE_MULTI_TURN"] = "false"
    # 清除 pydantic-settings 缓存，确保环境变量修改对所有模块生效
    from app.config import get_settings
    get_settings.cache_clear()
