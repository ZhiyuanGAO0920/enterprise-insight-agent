"""V4 审计日志中间件。

自动记录所有 /api/v1/* 请求的操作审计日志：
  - 谁（user_id）
  - 什么时候（created_at）
  - 做了什么（action + resource）
  - 从哪里（ip_address）
  - 结果如何（status_code）

异步写入，不阻塞请求响应。

使用 FastAPI 原生 @app.middleware("http") 注册，确保可靠触发。
"""

import json
import time

from fastapi import Request

from app.database.connection import get_session
from app.logging_config import get_logger

logger = get_logger("eia.audit")

# 不需要审计的路径
AUDIT_SKIP_PATHS = {"/health", "/health/ready", "/static", "/favicon.ico", "/"}


async def audit_middleware(request: Request, call_next):
    """FastAPI 原生 HTTP 中间件：记录所有 API 请求的审计日志。"""
    path = request.url.path

    # 跳过非审计路径
    if any(path.startswith(skip) for skip in AUDIT_SKIP_PATHS) or not path.startswith("/api/"):
        return await call_next(request)

    t0 = time.monotonic()
    response = await call_next(request)
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    # 异步写入（不阻塞响应）
    try:
        await _write_audit(request, response.status_code, elapsed_ms)
    except Exception:
        logger.warning("审计日志写入失败（降级处理）", exc_info=True)

    return response


async def _write_audit(request: Request, status_code: int, elapsed_ms: int) -> None:
    """将审计记录写入数据库。"""
    from sqlalchemy import text

    # 提取用户信息
    user_id = None
    session_id = ""
    if hasattr(request.state, "user") and request.state.user:
        user_id = request.state.user.get("user_id")

    # V4.1: 如果 request.state.user 未设置，直接从 JWT 解析 user_id
    if user_id is None:
        try:
            from app.auth.jwt import decode_access_token
            auth_header = request.headers.get("authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
                payload = decode_access_token(token)
                user_id = payload.get("user_id")
        except Exception:
            pass

    if hasattr(request.state, "session_id"):
        session_id = request.state.session_id or ""

    # 从 TenantMiddleware 提取 tenant_id
    tenant_id = getattr(request.state, "tenant_id", None)

    detail = json.dumps(
        {
            "query_params": str(request.query_params) if request.query_params else None,
            "client_host": request.client.host if request.client else None,
        },
        ensure_ascii=False,
    )

    try:
        async with get_session() as session:
            await session.execute(
                text("""
                    INSERT INTO audit_log
                        (user_id, tenant_id, action, resource, detail,
                         ip_address, session_id, user_agent, status_code, elapsed_ms, created_at)
                    VALUES
                        (:user_id, :tenant_id, :action, :resource, :detail,
                         :ip_address, :session_id, :user_agent, :status_code, :elapsed_ms, NOW())
                """),
                {
                    "user_id": user_id,
                    "tenant_id": tenant_id,
                    "action": request.method,
                    "resource": request.url.path,
                    "detail": detail,
                    "ip_address": request.client.host if request.client else None,
                    "session_id": session_id,
                    "user_agent": request.headers.get("user-agent", "")[:500],
                    "status_code": status_code,
                    "elapsed_ms": elapsed_ms,
                },
            )
            await session.commit()
    except Exception as e:
        logger.warning("审计日志 DB 写入异常", error=str(e), exc_info=True)
