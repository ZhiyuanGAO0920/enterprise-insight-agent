"""SQLAlchemy 异步引擎和会话工厂。

使用延迟初始化，以便在 PostgreSQL 或 asyncpg
不可用时不会导入失败（例如使用 SQLite 的开发/测试环境）。

V5 T-01 路径 B 真 PG RLS：
  - contextvar `_tenant_id_var` 持有当前请求的 tenant_id（由 tenant.py 中间件写入）
  - SQLAlchemy `after_begin` 事件在事务开始时注入 `SET LOCAL app.tenant_id = X`
  - PG RLS 策略 `current_setting('app.tenant_id')` 据此过滤 member 表
  - sql_runner.py 不动——它调 get_session()，自动获得注入后的 session
"""

import contextvars
from typing import AsyncGenerator, Optional

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session

from app.config import get_settings

settings = get_settings()

_engine: Optional[AsyncEngine] = None
_factory: Optional[async_sessionmaker[AsyncSession]] = None

# V5 T-01 路径 B：per-request tenant_id 上下文（HTTP 中间件写，after_begin 事件读）
_tenant_id_var: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "tenant_id", default=None
)


def set_tenant_id(tenant_id: Optional[int]) -> None:
    """由 tenant.py 中间件调用，设置当前请求的 tenant_id 到 contextvar。"""
    _tenant_id_var.set(tenant_id)


def get_tenant_id() -> Optional[int]:
    """读取当前 contextvar 的 tenant_id（测试 + 调试用）。"""
    return _tenant_id_var.get()


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


# V5 T-01 路径 B：事务开始时注入 SET LOCAL app.tenant_id 驱动 PG RLS
# 监听 sync Session 的 after_begin 事件（AsyncSession 内部用 sync Session，事件会触发）
@event.listens_for(Session, "after_begin")
def _set_tenant_id_on_begin(session, transaction, connection):
    """每个事务开始时，从 contextvar 读 tenant_id 并注入 SET LOCAL。

    - contextvar 有值 → SET LOCAL app.tenant_id = X，RLS 策略据此过滤
    - contextvar 无值（子进程/定时任务未设）→ 不注入，RLS 策略 current_setting 返回 NULL，
      member 表查询返回 0 行（安全失败：拒绝而非放行）
    - SQLite 测试环境不支持 SET LOCAL，跳过（RLS 策略本就不存在，不影响功能）
    """
    tenant_id = _tenant_id_var.get()
    if tenant_id is None:
        return
    try:
        if connection.dialect.name == "sqlite":
            return  # SQLite 测试环境跳过
        # int() 防 SQL 注入（tenant_id 从 JWT 解析，应为 int，兜底）
        connection.execute(text(f"SET LOCAL app.tenant_id = {int(tenant_id)}"))
    except Exception:
        pass  # SET LOCAL 不支持或执行失败，静默跳过
