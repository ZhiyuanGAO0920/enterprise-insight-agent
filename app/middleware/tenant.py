"""V4 多租户中间件。

从 JWT 中提取 tenant_id 并注入请求上下文。所有后续数据库查询
通过 tenant_id 进行数据隔离。
"""

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.logging_config import bind_context, get_logger

logger = get_logger("eia.tenant")

TENANT_SKIP_PATHS = {"/health", "/health/ready", "/static", "/favicon.ico", "/", "/docs", "/openapi.json"}


class TenantMiddleware(BaseHTTPMiddleware):
    """FastAPI 中间件：从 JWT 提取 tenant_id 并绑定到日志上下文。

    在 main.py 中通过 app.add_middleware(TenantMiddleware) 注册。
    应在认证中间件之后、业务路由之前执行。

    tenant_id 存储在 request.state.tenant_id 中，供下游使用。
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if any(path.startswith(skip) for skip in TENANT_SKIP_PATHS):
            return await call_next(request)

        # 从 JWT 直接解析 tenant_id（认证依赖当前不设置 request.state.user，
        # 因此主要路径是通过 JWT 解析；未来可通过依赖注入设置 request.state 后走主路径）
        tenant_id = None
        if hasattr(request.state, "user") and request.state.user:
            tenant_id = request.state.user.get("tenant_id")

        # JWT 直接解析（当前的主路径 + n8n webhook 等无 state 场景）
        if tenant_id is None:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                try:
                    from app.auth.jwt import decode_access_token
                    payload = decode_access_token(auth_header[7:])
                    if payload:
                        tenant_id = payload.get("tenant_id")
                except Exception:
                    pass

        # 注入请求 state
        request.state.tenant_id = tenant_id

        # 绑定到结构化日志上下文
        if tenant_id is not None:
            bind_context(tenant_id=tenant_id)

        response = await call_next(request)
        return response
