"""FastAPI 应用入口。

组装所有路由模块并提供 app 实例供 uvicorn 服务。
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.responses import Response
from fastapi.staticfiles import StaticFiles
from fastapi.routing import APIRouter

from app.config import get_settings
from app.errors.user_friendly import to_user_message
from app.logging_config import get_logger
from app.middleware.audit import audit_middleware
from app.middleware.tenant import tenant_middleware

settings = get_settings()
logger = get_logger("eia.api")

from app.api.routes.admin import router as admin_router
from app.api.routes.alerts import router as alerts_router
from app.api.routes.analysis import router as analysis_router
from app.api.routes.auth import router as auth_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.monitor import router as monitor_router
from app.api.routes.feedback import router as feedback_router
from app.api.routes.prompts import router as prompts_router
from app.api.routes.session import router as session_router
from app.api.routes.weekly import router as weekly_router

app = FastAPI(
    title="企业智能经营分析平台 V4",
    description="自然语言驱动的企业级 Multi-Agent 经营分析平台。V4：10 Agent 节点、5 业务域（销售/CRM/财务/库存/供应链）、ECharts 可视化、多轮对话、数据溯源、移动端适配、多租户、审计日志、PDF 报告、结构化日志。",
    version="4.0.0",
)

# CORS —— 从配置读取允许的来源。开发用 "*"，生产必须限制为具体域名。
_cors_origins_raw = settings.cors_origins.strip()
if _cors_origins_raw == "*":
    _cors_origins = ["*"]
else:
    _cors_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# V4: GZip 压缩（静态 JS/CSS 压缩，echarts.min.js ~1MB → ~280KB）
app.add_middleware(GZipMiddleware, minimum_size=1000)

# V4: 审计日志中间件（在 CORS 之后，异常处理之前）
app.middleware("http")(audit_middleware)

# V4: 多租户中间件（从 JWT 提取 tenant_id，注入请求上下文）
app.middleware("http")(tenant_middleware)

# ---------------------------------------------------------------------------
# 全局异常处理器 — 将技术错误转换为用户友好消息
# ---------------------------------------------------------------------------


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """捕获所有未处理的异常，返回用户友好错误消息。"""
    logger.exception("未处理异常 %s %s", request.method, request.url.path)
    friendly = to_user_message(str(exc))
    return JSONResponse(
        status_code=500,
        content={
            "detail": friendly["user_message"],
            "icon": friendly["icon"],
            "action": friendly["action"],
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTPException 统一输出格式。

    4xx 的 detail 是后端手写的业务文案（「用户名或密码错误」「账户已被禁用」
    「用户名已存在」等），必须原样透传——此前统一经过 to_user_message 友好映射，
    登录/创建用户等业务失败会被吞成通用兜底"系统遇到一个意外问题"，
    前端拿不到真实原因，表现为"没提示"。
    5xx 服务端错误同样透传原文（已知信息不被 fallback 覆盖）。
    """
    detail_str = str(exc.detail) if not isinstance(exc.detail, str) else exc.detail
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": detail_str},
    )


# ---------------------------------------------------------------------------
# API 版本化 — 所有业务路由挂载在 /api/v1 下
# ---------------------------------------------------------------------------

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(analysis_router)
v1_router.include_router(auth_router)
v1_router.include_router(weekly_router)
v1_router.include_router(alerts_router)
v1_router.include_router(dashboard_router)  # V3: Mobile dashboard snapshot
v1_router.include_router(session_router)    # V3: Multi-turn sessions
v1_router.include_router(feedback_router)   # V3: User feedback
v1_router.include_router(admin_router)      # V3: Admin — user management
v1_router.include_router(monitor_router)    # V3: AI quality dashboard
v1_router.include_router(prompts_router)    # V3: Prompt management

app.include_router(v1_router)


# --- API 版本响应头中间件 ---
@app.middleware("http")
async def add_api_version_header(request: Request, call_next):
    """为所有 /api/v1 响应添加版本和弃用提示头。"""
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["X-API-Version"] = "v1"
    return response


# --- 向后兼容：/api/xxx → /api/v1/xxx 重定向 ---
# 使用中间件而非 catch-all 路由，避免与 v1_router 路由匹配冲突
# 在 v4 或 v5 中移除
@app.middleware("http")
async def redirect_old_api(request: Request, call_next):
    """将旧版 /api/* 请求 308 重定向到 /api/v1/*。"""
    path = request.url.path
    if path.startswith("/api/") and not path.startswith("/api/v1/"):
        new_url = f"/api/v1/{path[5:]}"
        if request.url.query:
            new_url += f"?{request.url.query}"
        logger.warning("旧版 API 路径重定向: %s → %s", path, new_url)
        return RedirectResponse(
            url=new_url,
            status_code=308,
            headers={
                "X-API-Version": "v1",
                "X-Deprecation-Notice": "/api/* is deprecated. Use /api/v1/* instead.",
            },
        )
    return await call_next(request)


# 静态文件（Web 界面）
class _CachedStaticFiles(StaticFiles):
    """库文件设长缓存，app 文件设短缓存。"""
    _LIB_PATHS = {"echarts.min.js", "marked.min.js", "purify.min.js"}
    async def get_response(self, path: str, scope):
        resp: Response = await super().get_response(path, scope)
        if path in self._LIB_PATHS:
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            resp.headers["Cache-Control"] = "public, max-age=3600"
        return resp

_static_dir = Path(__file__).parent / "static"
try:
    _static_dir.mkdir(exist_ok=True)
except OSError:
    pass
app.mount("/static", _CachedStaticFiles(directory=str(_static_dir)), name="static")


@app.get("/")
async def root():
    """提供 Web 界面。"""
    from fastapi.responses import HTMLResponse
    html = (_static_dir / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html, headers={
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    })


@app.get("/share/{token}", include_in_schema=False)
async def share_page(token: str):
    """报告只读分享页（免登录）。token 由前端 JS 读取后调用 API 校验。"""
    from fastapi.responses import FileResponse
    page = _static_dir / "share.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="分享页不存在")
    return FileResponse(page, headers={
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    })


@app.get("/health", tags=["健康检查"], summary="存活检查")
async def health():
    """检查服务是否存活。返回服务版本号。"""
    return {"status": "ok", "version": "4.0.0"}


@app.get("/health/ready", tags=["健康检查"], summary="就绪检查")
async def readiness():
    """就绪检查 — 验证数据库和 Redis 连接是否正常。"""
    checks = {}
    try:
        from app.database.connection import get_session
        from sqlalchemy import text as _sql
        async with get_session() as s:
            await s.execute(_sql("SELECT 1"))
        checks["数据库"] = "正常"
    except Exception:
        checks["数据库"] = "异常（请检查 PostgreSQL 连接）"

    try:
        from app.database.redis import get_redis
        r = get_redis()
        await r.ping()
        checks["Redis"] = "正常"
    except Exception:
        checks["Redis"] = "异常（请检查 Redis 连接）"

    all_ok = all(v == "正常" for v in checks.values())
    return {
        "status": "就绪" if all_ok else "降级",
        "version": "4.0.0",
        "checks": checks,
    }


# ---------------------------------------------------------------------------
# 生命周期事件
# ---------------------------------------------------------------------------


@app.on_event("startup")
async def startup_event():
    """服务启动时初始化日志系统。"""
    from app.logging_config import setup_logging

    setup_logging()
    logger.info("EIA V4 服务启动 — 日志系统已初始化")


@app.on_event("shutdown")
async def shutdown_event():
    """服务关闭时清理资源（httpx 连接池等）。"""
    try:
        from app.llm import _http_client, _http_async_client
        _http_client.close()
        await _http_async_client.aclose()
    except Exception:
        pass
    try:
        from app.tools.embedding import _shutdown_http
        await _shutdown_http()
    except Exception:
        pass
    try:
        from app.middleware.audit import drain_audit_tasks
        await drain_audit_tasks()
    except Exception:
        pass
