"""V4 审计日志中间件。

自动记录所有 /api/v1/* 请求的操作审计日志：
  - 谁（user_id）
  - 什么时候（created_at）
  - 做了什么（action + resource）
  - 从哪里（ip_address）
  - 结果如何（status_code）

使用 asyncio.create_task 写入，不阻塞请求响应。
"""

import asyncio
import json
import time

from fastapi import Request

from app.database.connection import get_session
from app.logging_config import get_logger

logger = get_logger("eia.audit")

# 跟踪审计写入任务，确保关闭前 drain
_audit_tasks: set[asyncio.Task] = set()

# 不需要审计的路径
AUDIT_SKIP_PATHS = {"/health", "/health/ready", "/static", "/favicon.ico", "/", "/share"}


async def audit_middleware(request: Request, call_next):
    """FastAPI 原生 HTTP 中间件：记录所有 API 请求的审计日志。"""
    path = request.url.path

    # 跳过非审计路径
    if any(path.startswith(skip) for skip in AUDIT_SKIP_PATHS) or not path.startswith("/api/"):
        return await call_next(request)

    t0 = time.monotonic()
    response = await call_next(request)
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    # 提取请求元数据（在 create_task 前捕获，避免 request 对象回收）
    user_id = _get_user_id(request)
    session_id = getattr(request.state, "session_id", "") or ""
    tenant_id = getattr(request.state, "tenant_id", None)
    trace_id = _get_trace_id(request)
    client_host = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", "")[:500]
    detail = json.dumps(
        {"query_params": str(request.query_params) if request.query_params else None, "client_host": client_host},
        ensure_ascii=False,
    )

    # 后台写入审计日志，不阻塞响应
    # 跟踪 task 生命周期，确保关闭前完成写入
    _task = asyncio.create_task(
        _write_audit(
            user_id=user_id,
            tenant_id=tenant_id,
            trace_id=trace_id,
            method=request.method,
            path=path,
            detail=detail,
            client_host=client_host,
            session_id=session_id,
            user_agent=user_agent,
            status_code=response.status_code,
            elapsed_ms=elapsed_ms,
        )
    )
    _audit_tasks.add(_task)
    _task.add_done_callback(_audit_tasks.discard)

    return response


def _get_user_id(request: Request):
    """从 request.state 或 JWT 提取 user_id。"""
    if hasattr(request.state, "user") and request.state.user:
        return request.state.user.get("user_id")
    try:
        from app.auth.jwt import decode_access_token
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            payload = decode_access_token(auth_header[7:])
            return payload.get("user_id")
    except Exception:
        pass
    return None


def _get_trace_id(request: Request) -> str:
    """从请求状态或日志上下文提取 trace_id。"""
    tid = getattr(request.state, "trace_id", None) or ""
    if tid:
        return tid
    try:
        from app.logging_config import trace_id_ctx
        return trace_id_ctx.get() or ""
    except Exception:
        return ""


async def _write_audit(
    user_id, tenant_id, trace_id, method, path, detail, client_host, session_id, user_agent, status_code, elapsed_ms,
) -> None:
    """将审计记录写入数据库（后台任务，不阻塞响应）。"""
    from sqlalchemy import text

    try:
        async with get_session() as session:
            await session.execute(
                text("""
                    INSERT INTO audit_log
                        (user_id, tenant_id, trace_id, action, resource, detail,
                         ip_address, session_id, user_agent, status_code, elapsed_ms, created_at)
                    VALUES
                        (:user_id, :tenant_id, :trace_id, :action, :resource, :detail,
                         :ip_address, :session_id, :user_agent, :status_code, :elapsed_ms, NOW())
                """),
                {
                    "user_id": user_id,
                    "tenant_id": tenant_id,
                    "trace_id": trace_id,
                    "action": method,
                    "resource": path,
                    "detail": detail,
                    "ip_address": client_host,
                    "session_id": session_id,
                    "user_agent": user_agent,
                    "status_code": status_code,
                    "elapsed_ms": elapsed_ms,
                },
            )
            await session.commit()
    except Exception as e:
        logger.warning("审计日志 DB 写入异常", error=str(e), exc_info=True)


async def drain_audit_tasks(timeout: float = 3.0) -> None:
    """在服务关闭前等待所有未完成的审计写入任务完成。

    在 FastAPI shutdown 事件中调用，确保最近几秒的审计记录不丢失。
    """
    if not _audit_tasks:
        return
    logger.info("等待 %d 个审计日志写入任务完成 ...", len(_audit_tasks))
    tasks = list(_audit_tasks)
    done, pending = await asyncio.wait(tasks, timeout=timeout)
    if pending:
        logger.warning("%d 个审计任务未在 %.1fs 内完成，已放弃", len(pending), timeout)
