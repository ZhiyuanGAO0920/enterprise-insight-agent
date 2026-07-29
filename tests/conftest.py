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


def _force_dispose_engine():
    """清空引擎缓存，强制下次请求重新创建连接池。

    不尝试异步关闭旧连接（会触发事件循环冲突），而是直接丢掉引用让 Python GC 处理。
    在 Windows Python 3.12 上，TestClient 内部 httpx 使用 asyncio.run() 处理 async 端点，
    创建的 asyncpg 连接在测试间清理时引用已关闭的事件循环导致崩溃。
    丢引用比异步关闭更安全 —— 旧连接在后台被 GC 回收，不影响新测试。
    """
    try:
        import app.database.connection as db_conn
        db_conn._engine = None
        db_conn._factory = None
    except Exception:
        pass


@pytest.fixture(scope="session")
def event_loop():
    """创建会话级事件循环供异步测试使用。"""
    loop = asyncio.new_event_loop()
    yield loop
    # 清理异步 DB 连接池
    try:
        from app.database.connection import dispose_engine
        loop.run_until_complete(dispose_engine())
    except Exception:
        pass
    try:
        loop.run_until_complete(loop.shutdown_asyncgens())
    except Exception:
        pass
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
    """强制测试使用测试数据库 URL 并管理引擎生命周期。"""
    # 前向清理：释放上个测试残留的引擎连接
    _force_dispose_engine()

    if request.node.get_closest_marker("e2e"):
        yield
        _force_dispose_engine()
        return
    if request.node.get_closest_marker("db"):
        if not POSTGRES_AVAILABLE:
            pytest.skip("PostgreSQL 不可用 — 跳过需要数据库的测试")
        yield
        _force_dispose_engine()
        return

    # 非标记测试：强制使用 SQLite，避免 asyncpg 事件循环冲突
    os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL_TEST", "sqlite+aiosqlite:///./test.db")
    os.environ["DATABASE_URL_SYNC"] = os.environ.get("DATABASE_URL_TEST", "sqlite+aiosqlite:///./test.db").replace(
        "sqlite+aiosqlite:///", "sqlite:///"
    )
    # 测试环境禁用多轮对话，避免 Redis 异步事件循环清理问题
    os.environ["FEATURE_MULTI_TURN"] = "false"
    # 清除 pydantic-settings 缓存，确保环境变量修改对所有模块生效
    from app.config import get_settings
    get_settings.cache_clear()

    yield

    # 后向清理：释放本次测试创建但未正常关闭的引擎连接
    _force_dispose_engine()
