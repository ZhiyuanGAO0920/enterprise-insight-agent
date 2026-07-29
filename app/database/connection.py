"""SQLAlchemy 异步引擎和会话工厂。

使用延迟初始化，以便在 PostgreSQL 或 asyncpg
不可用时不会导入失败（例如使用 SQLite 的开发/测试环境）。
"""

from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

settings = get_settings()

_engine: Optional[AsyncEngine] = None
_factory: Optional[async_sessionmaker[AsyncSession]] = None


def _get_engine():
    """延迟初始化异步引擎。"""
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            settings.database_url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            echo=False,
        )
    return _engine


def _get_factory() -> async_sessionmaker:
    """延迟初始化会话工厂。"""
    global _factory
    if _factory is None:
        _factory = async_sessionmaker(
            _get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _factory


def get_session() -> AsyncSession:
    """创建新的异步会话。用法：async with get_session() as session:"""
    return _get_factory()()


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖注入：生成一个异步数据库会话。"""
    session = get_session()
    try:
        yield session
    finally:
        await session.close()


async def dispose_engine():
    """关闭异步引擎并释放连接池（在测试清理或服务关闭时调用）。"""
    global _engine, _factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _factory = None
