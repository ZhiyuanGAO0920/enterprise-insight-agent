"""V4 多租户中间件。

从 JWT 中提取 tenant_id 并注入请求上下文。所有后续数据库查询
通过 tenant_id 进行数据隔离。

V4.1 修复：改用 FastAPI 原生 @app.middleware("http") 而非 BaseHTTPMiddleware，
避免 BaseHTTPMiddleware 吞掉路由异常、阻止 global_exception_handler 捕获的问题。
"""

from fastapi import Request
from starlette.responses import Response

from app.database.connection import set_tenant_id
from app.logging_config import bind_context, get_logger

logger = get_logger("eia.tenant")

# ⚠️ 不要放 "/" 进集合：startswith("/") 对一切路径为 True，会把所有请求跳过，
# 导致 request.state.tenant_id 恒为 None、审计日志 tenant_id 全空（V4.6.x 审计中间件
# 曾因同样问题全部缺失，此处沿用 audit.py 的 path == "/" 精确匹配修复）。
TENANT_SKIP_PATHS = {"/health", "/health/ready", "/static", "/favicon.ico", "/share", "/docs", "/openapi.json"}


async def tenant_middleware(request: Request, call_next):
    """FastAPI 原生 HTTP 中间件：从 JWT 提取 tenant_id 并绑定到日志上下文。

    在 main.py 中通过 app.middleware("http")(tenant_middleware) 注册。
    与审计中间件相同的注册方式，确保异常正确传播。
    """
    path = request.url.path
    if path == "/" or any(path.startswith(skip) for skip in TENANT_SKIP_PATHS):
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

    # V5 T-01 路径 B：写 contextvar，供 connection.py after_begin 事件读 + 注入 SET LOCAL
    # asyncio task 隔离保证 per-request 作用域，request 结束 task 结束 contextvar 自动失效
    set_tenant_id(tenant_id)

    # 绑定到结构化日志上下文
    if tenant_id is not None:
        bind_context(tenant_id=tenant_id)

    response = await call_next(request)
    return response
